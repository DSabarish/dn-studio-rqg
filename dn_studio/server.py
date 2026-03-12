"""
DN-Studio Flask dashboard server
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request
from flask_cors import CORS

from datetime import datetime
import shutil

import yaml as _yaml

from . import config
from .diarization_pipeline import run_pipeline

app = Flask(__name__)
CORS(app)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = config.OUTPUT_DIR  # outputs/diarization
DASHBOARD_TEMPLATE = PROJECT_ROOT / "dn_studio" / "dashboard.html"

GCS_ROOT = PROJECT_ROOT / "gcs"
GCS_ROOT.mkdir(parents=True, exist_ok=True)


def _slugify(s: str) -> str:
    return ("".join(c if c.isalnum() or c in "-_" else "-" for c in (s or "")).strip("-_") or "default")


def _latest_run_subdir(exp_dir: Path) -> Optional[Path]:
    """Return the most-recently-created run subdir that has transcript.json, or None."""
    if not exp_dir.exists():
        return None
    subdirs = sorted(
        [d for d in exp_dir.iterdir() if d.is_dir() and (d / "transcript.json").exists()],
        reverse=True,
    )
    return subdirs[0] if subdirs else None


def _gcs_folder_for_current() -> str:
    manifest_path = Path(OUTPUT_DIR) / "run_manifest.json"
    if manifest_path.exists():
        try:
            mf = json.loads(manifest_path.read_text(encoding="utf-8"))
            proj = mf.get("project_name", "") or ""
            exp  = mf.get("experiment_name", "") or ""
            if proj or exp:
                exp_dir = GCS_ROOT / _slugify(proj) / _slugify(exp)
                latest  = _latest_run_subdir(exp_dir)
                return str(latest) if latest else str(exp_dir)
        except Exception:
            pass
    return str(Path(OUTPUT_DIR))


def _find_current_yaml() -> Optional[Path]:
    manifest_path = Path(OUTPUT_DIR) / "run_manifest.json"
    if manifest_path.exists():
        try:
            mf = json.loads(manifest_path.read_text(encoding="utf-8"))
            proj = mf.get("project_name", "") or ""
            exp  = mf.get("experiment_name", "") or ""
            if proj or exp:
                candidate = GCS_ROOT / _slugify(proj) / _slugify(exp) / "config.yaml"
                if candidate.exists():
                    return candidate
        except Exception:
            pass
    fallback = PROJECT_ROOT / "cfg" / "config.yaml"
    return fallback if fallback.exists() else None


def _safe_audio_path(raw: Any) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        default = getattr(config, "AUDIO_FILE", None)
        if default is None:
            return ""
        s = str(default).strip()
        return "" if s == "None" else s
    s = str(raw).strip()
    return "" if s == "None" else s


def _b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("utf-8")


def _run_dir(run_id: str) -> Path:
    if not run_id or run_id.strip().lower() == "current":
        return Path(OUTPUT_DIR)
    return GCS_ROOT / run_id.strip()


def _build_run_payload(
    dir_path: Path,
    run_id: str,
    label: str,
    audio_path_override: Optional[str] = None,
) -> Dict[str, Any]:
    dir_exists = dir_path is not None and dir_path.exists()
    payload: Dict[str, Any] = {
        "id": run_id,
        "label": label,
        "segments_b64": "",
        "clusters_b64": "",
        "speaker_map": {},
        "audio_b64": "",
        "audio_mime": "audio/mpeg",
        "audio_name": "",
        "mom_md_b64": "",
        "mom_json_b64": "",
        "brd_md_b64": "",
        "has_diarization": False,
        "has_clusters": False,
        "has_mom": False,
        "has_brd": False,
    }
    if not dir_exists:
        return payload

    try:
        payload["has_clusters"] = (dir_path / "clusters.json").exists()
        payload["has_mom"] = any((dir_path / "minutes").glob("MoM*.md")) if (dir_path / "minutes").exists() else False
        payload["has_brd"] = any((dir_path / "brd").glob("BRD*.md")) if (dir_path / "brd").exists() else False
    except Exception:
        pass

    seg_path = dir_path / "transcript.json"
    if seg_path.exists():
        try:
            seg_text = seg_path.read_text(encoding="utf-8")
            seg_data = json.loads(seg_text)
            if isinstance(seg_data, list) and len(seg_data) > 0:
                payload["has_diarization"] = True
                payload["segments_b64"] = _b64(seg_text)
            elif isinstance(seg_data, dict) and seg_data.get("segments"):
                payload["has_diarization"] = True
                payload["segments_b64"] = _b64(seg_text)
        except Exception:
            pass

    clusters_path = dir_path / "clusters.json"
    if clusters_path.exists():
        try:
            payload["clusters_b64"] = _b64(clusters_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    manifest_path = dir_path / "run_manifest.json"
    if manifest_path.exists():
        try:
            mf = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["speaker_map"] = mf.get("speaker_map", {}) or {}
        except Exception:
            pass

    raw_audio = audio_path_override or getattr(config, "AUDIO_FILE", None)
    audio_path = _safe_audio_path(raw_audio)
    try:
        if audio_path and audio_path != "None":
            audio_file = Path(audio_path)
            if audio_file.exists() and audio_file.is_file() and audio_file.stat().st_size < 20 * 1024 * 1024:
                payload["audio_b64"] = base64.b64encode(audio_file.read_bytes()).decode("utf-8")
                payload["audio_name"] = audio_file.name
                ext = audio_file.suffix.lower()
                payload["audio_mime"] = {
                    ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".mp3": "audio/mpeg",
                    ".wav": "audio/wav", ".ogg": "audio/ogg", ".webm": "audio/webm",
                }.get(ext, "audio/mpeg")
    except Exception:
        pass

    minutes_dir = dir_path / "minutes"
    if minutes_dir.exists():
        for p in minutes_dir.glob("MoM*.md"):
            payload["mom_md_b64"] = _b64(p.read_text(encoding="utf-8"))
            break
        for p in minutes_dir.glob("MoM*.json"):
            payload["mom_json_b64"] = _b64(p.read_text(encoding="utf-8"))
            break

    brd_dir = dir_path / "brd"
    if brd_dir.exists():
        for p in brd_dir.glob("BRD*.md"):
            payload["brd_md_b64"] = _b64(p.read_text(encoding="utf-8"))
            break

    return payload


@app.route("/")
def index() -> str:
    if not DASHBOARD_TEMPLATE.exists():
        return "<h2>dashboard.html not found</h2>"

    runs: List[Dict[str, Any]] = []
    output_dir = Path(OUTPUT_DIR)
    manifest_path = output_dir / "run_manifest.json"
    audio_path = _safe_audio_path(getattr(config, "AUDIO_FILE", None))

    _cur_proj = ""
    _cur_exp  = ""
    if manifest_path.exists():
        try:
            _mf = json.loads(manifest_path.read_text(encoding="utf-8"))
            _cur_proj  = _mf.get("project_name", "") or ""
            _cur_exp   = _mf.get("experiment_name", "") or ""
            audio_path = _safe_audio_path(_mf.get("audio_path") or audio_path)
        except Exception:
            pass

    _cur_label = "Current (latest)"
    if _cur_proj or _cur_exp:
        _cur_label = f"Current (latest) -- {_cur_proj or _cur_exp}"

    _data_dir = output_dir
    if _cur_proj or _cur_exp:
        _exp_dir = GCS_ROOT / _slugify(_cur_proj) / _slugify(_cur_exp)
        _latest = _latest_run_subdir(_exp_dir)
        if _latest:
            _data_dir = _latest
        else:
            _data_dir = _exp_dir

    current = _build_run_payload(_data_dir, run_id="current", label=_cur_label, audio_path_override=audio_path)
    current["label"]           = _cur_label
    current["project_name"]    = _cur_proj
    current["experiment_name"] = _cur_exp

    if _cur_proj or _cur_exp:
        _exp_dir = GCS_ROOT / _slugify(_cur_proj) / _slugify(_cur_exp)
        _latest  = _latest_run_subdir(_exp_dir)
        current["experiment_folder"] = str(_latest) if _latest else str(_exp_dir)
    else:
        current["experiment_folder"] = _gcs_folder_for_current()

    current["experiment_dir"] = (
        str(GCS_ROOT / _slugify(_cur_proj) / _slugify(_cur_exp))
        if (_cur_proj or _cur_exp) else str(output_dir)
    )

    runs.append(current)

    if GCS_ROOT.exists():
        for proj_dir in sorted(GCS_ROOT.iterdir(), reverse=True):
            if not proj_dir.is_dir():
                continue
            for exp_dir in sorted(proj_dir.iterdir(), reverse=True):
                if not exp_dir.is_dir():
                    continue
                for run_dir in sorted(exp_dir.iterdir(), reverse=True):
                    if not run_dir.is_dir() or not (run_dir / "transcript.json").exists():
                        continue
                    run_id = f"{proj_dir.name}/{exp_dir.name}/{run_dir.name}"
                    label  = f"{proj_dir.name} / {exp_dir.name} / {run_dir.name}"
                    cfg_path = exp_dir / "config.yaml"
                    audio_override = None
                    if cfg_path.exists():
                        try:
                            cfg = _yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                            proj_label = cfg.get("project_name") or proj_dir.name
                            exp_label  = cfg.get("experiment_name") or (cfg.get("experiment") or {}).get("name") or exp_dir.name
                            label = f"{proj_label} / {exp_label} / {run_dir.name}"
                            p = (cfg.get("paths") or {}).get("audio")
                            if p and Path(p).exists():
                                audio_override = p
                        except Exception:
                            pass
                    payload = _build_run_payload(run_dir, run_id=run_id, label=label, audio_path_override=audio_override)
                    payload["experiment_folder"] = str(run_dir)
                    payload["experiment_dir"]    = str(exp_dir)
                    runs.append(payload)

    html = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    chips_fix = """<script>
(function() {
  var DIAR_TABS = ['diarization', 'timeline'];
  function _syncChips(tabName) {
    var el = document.getElementById('spk-chips');
    if (!el) return;
    el.style.display = DIAR_TABS.indexOf(tabName) !== -1 ? '' : 'none';
  }
  function _init() {
    var orig = window.switchTab;
    if (typeof orig === 'function') {
      window.switchTab = function(name) { orig(name); _syncChips(name); };
    }
    _syncChips('config');
    document.addEventListener('click', function(e) {
      var btn = e.target && e.target.closest && e.target.closest('[data-tab]');
      if (btn) _syncChips(btn.getAttribute('data-tab'));
    }, true);
  }
  function _onRunLoaded(run) {
    if (!run) return;
    var folderEl = document.getElementById('exp-folder-path')
                || document.querySelector('[data-field="experiment_folder"]')
                || document.querySelector('.exp-folder-val');
    if (folderEl && run.experiment_folder) {
      folderEl.textContent = run.experiment_folder;
    }
    var hasDiar = !!(run.has_diarization && run.segments_b64);
    var artifactSections = [
      document.getElementById('swimlane-section') || document.getElementById('swimlane-wrap'),
      document.getElementById('utterances-section') || document.getElementById('utt-log'),
      document.getElementById('tsne-section') || document.querySelector('[data-section="tsne"]'),
      document.getElementById('clusters-section'),
    ];
    artifactSections.forEach(function(el) {
      if (!el) return;
      var wrap = el.closest('.card') || el;
      if (!hasDiar) {
        wrap.style.opacity = '0.3';
        wrap.style.pointerEvents = 'none';
        if (!wrap.querySelector('._no-data-overlay')) {
          var overlay = document.createElement('div');
          overlay.className = '_no-data-overlay';
          overlay.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:.7rem;color:#475569;pointer-events:none;z-index:10';
          overlay.textContent = 'No diarization data -- run diarization first';
          wrap.style.position = 'relative';
          wrap.appendChild(overlay);
        }
      } else {
        wrap.style.opacity = '';
        wrap.style.pointerEvents = '';
        var ov = wrap.querySelector('._no-data-overlay');
        if (ov) ov.remove();
      }
    });
  }
  function _patchExpFolder() {
    var origLoad = window.loadRun;
    if (typeof origLoad === 'function') {
      window.loadRun = function(idx) {
        origLoad(idx);
        var runs = window.RUNS || [];
        _onRunLoaded(runs[idx]);
      };
    }
    var runs = window.RUNS || [];
    var defIdx = window.DEFAULT_RUN || 0;
    if (runs[defIdx]) _onRunLoaded(runs[defIdx]);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { _init(); _patchExpFolder(); });
  } else {
    _init();
    _patchExpFolder();
  }
})();
</script>"""
    html = (
        html.replace("__RUNS_JSON__", json.dumps(runs, ensure_ascii=False))
        .replace("__DEFAULT_RUN__", "0")
        .replace("__ROSTER_JSON__", json.dumps(getattr(config, "COMPANY_ROSTER", []), ensure_ascii=False))
        .replace("__CLUSTERS_JSON__", json.dumps({}))
        .replace("</body>", chips_fix + "</body>", 1)
    )
    return html


@app.route("/api/run", methods=["POST"])
def api_run() -> Any:
    try:
        manifest_path = Path(OUTPUT_DIR) / "run_manifest.json"
        audio_path = _safe_audio_path(getattr(config, "AUDIO_FILE", None))
        num_speakers_override: Optional[int] = None
        project_name = ""
        experiment_name = ""
        context = ""
        asr_overrides: Optional[Dict[str, Any]] = None
        diar_overrides: Optional[Dict[str, Any]] = None
        if manifest_path.exists():
            try:
                mf = json.loads(manifest_path.read_text(encoding="utf-8"))
                audio_path = _safe_audio_path(mf.get("audio_path") or audio_path)
                ns = mf.get("num_speakers")
                if isinstance(ns, int) and ns > 0:
                    num_speakers_override = ns
                project_name    = mf.get("project_name", "") or ""
                experiment_name = mf.get("experiment_name", "") or ""
                context         = mf.get("context", "") or ""
                if isinstance(mf.get("asr"), dict):
                    asr_overrides = mf["asr"]
                if isinstance(mf.get("diarization"), dict):
                    diar_overrides = mf["diarization"]
            except Exception:
                pass

        if not audio_path:
            return jsonify({"ok": False, "error": "No audio path configured."}), 400

        result = run_pipeline(
            audio_path=audio_path,
            output_dir=str(OUTPUT_DIR),
            num_speakers_override=num_speakers_override,
            asr_overrides=asr_overrides,
            diar_overrides=diar_overrides,
        )

        proj_slug = _slugify(project_name)
        exp_slug  = _slugify(experiment_name)
        ts        = datetime.now().strftime("%y%m%d_%H%M")
        run_key   = f"{ts}-run"

        proj_dir  = GCS_ROOT / proj_slug
        exp_base  = proj_dir / exp_slug
        exp_dir   = exp_base / run_key

        base_cfg_path = PROJECT_ROOT / "cfg" / "config.yaml"
        cfg_yaml_path = exp_base / "config.yaml"
        try:
            cfg = {}
            if base_cfg_path.exists():
                cfg = json.loads(json.dumps(_yaml.safe_load(base_cfg_path.read_text(encoding="utf-8"))))
            cfg["project_name"]    = project_name
            cfg["experiment_name"] = experiment_name
            if "meeting" in cfg:
                if project_name:
                    cfg["meeting"]["label"] = project_name.replace(" ", "_")[:24]
                if num_speakers_override is not None:
                    cfg["meeting"]["num_speakers"] = num_speakers_override
            if "paths" in cfg:
                cfg["paths"]["audio"] = audio_path
            cfg.setdefault("experiment", {})
            cfg["experiment"]["name"]    = experiment_name or exp_slug
            cfg["experiment"]["context"] = context
            cfg_yaml_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_yaml_path.write_text(_yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
        except Exception:
            pass

        exp_dir.mkdir(parents=True, exist_ok=True)

        # ── FIX: guard against None paths before calling Path(p).exists() ────
        for key in ("segments", "summary", "markdown", "viz_html", "clusters"):
            p = result.get(key)
            if not p:          # skip None / empty string — this was the crash
                continue
            src = Path(p)
            try:
                if src.exists():
                    shutil.copy2(src, exp_dir / src.name)
            except Exception:
                continue
        # ─────────────────────────────────────────────────────────────────────

        if audio_path and audio_path != "None":
            try:
                audio_src = Path(audio_path)
                if audio_src.exists() and audio_src.is_file():
                    shutil.copy2(audio_src, exp_dir / audio_src.name)
            except Exception:
                pass

        if manifest_path.exists():
            try:
                shutil.copy2(manifest_path, exp_dir / "run_manifest.json")
            except Exception:
                pass

        for subdir, name in (("minutes", "minutes"), ("brd", "brd")):
            src_dir = Path(OUTPUT_DIR) / subdir
            if src_dir.exists():
                dst_dir = exp_dir / name
                dst_dir.mkdir(parents=True, exist_ok=True)
                for f in src_dir.iterdir():
                    if f.is_file():
                        try:
                            shutil.copy2(f, dst_dir / f.name)
                        except Exception:
                            continue

        exported_files = [f.name for f in exp_dir.iterdir() if f.is_file()]

        # ── Build a human-readable save summary ──────────────────────────────
        save_path = str(exp_dir)
        save_summary = (
            f"Artifacts saved to: {save_path}\n"
            f"Files: {', '.join(exported_files) if exported_files else 'none'}"
        )
        # ─────────────────────────────────────────────────────────────────────

        return jsonify({
            "ok": True,
            "result": result,
            "exported": exported_files,
            "save_path": save_path,           # <-- new: full GCS path
            "save_summary": save_summary,     # <-- new: human-readable summary
            "experiment": {
                "project":    proj_slug,
                "experiment": exp_slug,
                "run":        run_key,
                "path":       save_path,
            },
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/new_project", methods=["POST"])
def api_new_project() -> Any:
    try:
        output_dir = Path(OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        for p in [output_dir / n for n in ("transcript.json", "transcript.md", "summary.json", "viz.html", "clusters.json")]:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        for subdir_name in ("minutes", "brd"):
            subdir = output_dir / subdir_name
            if subdir.exists():
                try:
                    for f in subdir.iterdir():
                        if f.is_file():
                            f.unlink()
                except Exception:
                    pass
        manifest: Dict[str, Any] = {
            "project_name": "", "experiment_name": "", "context": "",
            "audio_path": _safe_audio_path(getattr(config, "AUDIO_FILE", None)),
            "speaker_map": {},
        }
        (output_dir / "run_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return jsonify({"ok": True, "message": "New project created."})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/health")
def api_health() -> Any:
    return jsonify({"ok": True})


@app.route("/api/save_names", methods=["POST"])
def api_save_names() -> Any:
    data    = request.get_json(force=True)
    run_id  = (data.get("run_id") or "").strip() or "current"
    mapping = data.get("mapping") or {}
    if not isinstance(mapping, dict):
        return jsonify({"ok": False, "error": "mapping must be an object"}), 400
    root = _run_dir(run_id)
    if not root.exists():
        return jsonify({"ok": False, "error": f"run not found: {run_id}"}), 404
    seg_path = root / "transcript.json"
    if not seg_path.exists():
        return jsonify({"ok": False, "error": "transcript.json not found"}), 404
    segs = json.loads(seg_path.read_text(encoding="utf-8"))
    for seg in segs:
        sid = seg.get("speaker_id")
        if not sid:
            continue
        seg["speaker_name"] = mapping.get(sid, seg.get("speaker_name", sid))
    seg_path.write_text(json.dumps(segs, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest_path = root / "run_manifest.json"
    manifest: Dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    manifest["speaker_map"] = mapping
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return jsonify({"ok": True, "files_updated": 2})


@app.route("/api/save_mom", methods=["POST"])
def api_save_mom() -> Any:
    data    = request.get_json(force=True)
    run_id  = (data.get("run_id") or "").strip() or "current"
    content = data.get("content", "")
    root    = _run_dir(run_id)
    root.mkdir(parents=True, exist_ok=True)
    minutes_dir = root / "minutes"
    minutes_dir.mkdir(parents=True, exist_ok=True)
    existing = list(minutes_dir.glob("MoM*.md"))
    out_path = existing[0] if existing else minutes_dir / "MoM.md"
    out_path.write_text(content, encoding="utf-8")
    return jsonify({"ok": True, "path": str(out_path)})


@app.route("/api/save_brd", methods=["POST"])
def api_save_brd() -> Any:
    data    = request.get_json(force=True)
    run_id  = (data.get("run_id") or "").strip() or "current"
    content = data.get("content", "")
    root    = _run_dir(run_id)
    root.mkdir(parents=True, exist_ok=True)
    brd_dir = root / "brd"
    brd_dir.mkdir(parents=True, exist_ok=True)
    existing = list(brd_dir.glob("BRD*.md"))
    out_path = existing[0] if existing else brd_dir / "BRD.md"
    out_path.write_text(content, encoding="utf-8")
    return jsonify({"ok": True, "path": str(out_path)})


def _config_for_run(run_id: Optional[str]) -> Dict[str, Any]:
    project_name    = ""
    experiment_name = ""
    context         = ""
    num_speakers: Optional[int] = None
    audio_path = _safe_audio_path(getattr(config, "AUDIO_FILE", None))
    yaml_raw   = ""

    is_current = not run_id or run_id.strip().lower() == "current"

    if is_current:
        dir_path      = Path(OUTPUT_DIR)
        manifest_path = dir_path / "run_manifest.json"
        yaml_path     = _find_current_yaml()
    else:
        run_id        = run_id.strip()
        dir_path      = GCS_ROOT / run_id
        manifest_path = dir_path / "run_manifest.json"
        yaml_path     = dir_path.parent / "config.yaml"
        if not yaml_path.exists():
            yaml_path = dir_path / "config.yaml"

    if manifest_path.exists():
        try:
            mf = json.loads(manifest_path.read_text(encoding="utf-8"))
            project_name    = mf.get("project_name", "") or ""
            experiment_name = mf.get("experiment_name", "") or ""
            context         = mf.get("context", "") or ""
            ns = mf.get("num_speakers")
            if isinstance(ns, int) and ns > 0:
                num_speakers = ns
            audio_path = _safe_audio_path(mf.get("audio_path") or audio_path)
        except Exception:
            pass

    if yaml_path and yaml_path.exists():
        try:
            yaml_raw = yaml_path.read_text(encoding="utf-8")
        except Exception:
            yaml_raw = ""

    if is_current and not yaml_raw:
        base_yaml = PROJECT_ROOT / "cfg" / "config.yaml"
        if base_yaml.exists():
            try:
                yaml_raw = base_yaml.read_text(encoding="utf-8")
            except Exception:
                pass

    # ── FIX: build gcs_path directly from proj/exp already read above ────────
    if is_current:
        if project_name or experiment_name:
            exp_dir  = GCS_ROOT / _slugify(project_name) / _slugify(experiment_name)
            latest   = _latest_run_subdir(exp_dir)
            gcs_path = str(latest) if latest else str(exp_dir)
        else:
            gcs_path = str(Path(OUTPUT_DIR))
    else:
        parts = [p for p in run_id.strip().replace("\\", "/").split("/") if p]
        candidate = GCS_ROOT
        for part in parts:
            candidate = candidate / part
        if len(parts) == 2:
            latest = _latest_run_subdir(candidate)
            if latest:
                candidate = latest
        gcs_path = str(candidate)
    # ─────────────────────────────────────────────────────────────────────────

    yaml_display = f"# experiment_folder: {gcs_path}\n" + (yaml_raw or "")

    asr_params: Dict[str, Any] = {}
    diar_params: Dict[str, Any] = {}
    try:
        parsed = _yaml.safe_load(yaml_raw) if yaml_raw else {}
        if isinstance(parsed, dict):
            asr_params = parsed.get("asr", {}) or {}
            diar_params = parsed.get("diarization", {}) or {}
    except Exception:
        pass

    return {
        "ok":               True,
        "project_name":     project_name,
        "experiment_name":  experiment_name,
        "context":          context,
        "num_speakers":     num_speakers,
        "audio_path":       audio_path,
        "yaml_raw":         yaml_display,
        "gcs_path":         gcs_path,
        "asr":              asr_params,
        "diarization":      diar_params,
    }


@app.route("/api/config", methods=["GET"])
def api_get_config() -> Any:
    run_id = request.args.get("run_id")
    return jsonify(_config_for_run(run_id))


@app.route("/api/save_config", methods=["POST"])
def api_save_config() -> Any:
    try:
        data            = request.get_json(force=True)
        project_name    = data.get("project_name", "") or ""
        experiment_name = data.get("experiment_name", "") or ""
        context         = data.get("context", "") or ""
        num_speakers    = data.get("num_speakers")
        audio_path      = _safe_audio_path(data.get("audio_path") or getattr(config, "AUDIO_FILE", None))
        asr_overrides   = data.get("asr")
        diar_overrides  = data.get("diarization")

        if num_speakers is not None:
            try:
                ns_int = int(num_speakers)
                num_speakers = ns_int if ns_int > 0 else None
            except (ValueError, TypeError):
                num_speakers = None

        manifest_path = Path(OUTPUT_DIR) / "run_manifest.json"
        manifest: Dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}

        if project_name:
            manifest["project_name"] = project_name
        if experiment_name:
            manifest["experiment_name"] = experiment_name
        if context:
            manifest["context"] = context
        if num_speakers is not None:
            manifest["num_speakers"] = num_speakers
        else:
            manifest.pop("num_speakers", None)
        if audio_path:
            manifest["audio_path"] = audio_path
        if isinstance(asr_overrides, dict):
            manifest["asr"] = asr_overrides
        if isinstance(diar_overrides, dict):
            manifest["diarization"] = diar_overrides

        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        proj_slug = _slugify(manifest.get("project_name", "") or project_name)
        exp_slug  = _slugify(manifest.get("experiment_name", "") or experiment_name)
        exp_dir   = GCS_ROOT / proj_slug / exp_slug
        exp_dir.mkdir(parents=True, exist_ok=True)
        yaml_raw = ""
        base_cfg_path = PROJECT_ROOT / "cfg" / "config.yaml"
        try:
            cfg: Dict[str, Any] = {}
            if base_cfg_path.exists():
                cfg = json.loads(json.dumps(_yaml.safe_load(base_cfg_path.read_text(encoding="utf-8"))))
            p_name = manifest.get("project_name", "") or project_name
            e_name = manifest.get("experiment_name", "") or experiment_name
            if p_name:
                cfg["project_name"] = p_name
            if e_name:
                cfg["experiment_name"] = e_name
            if "meeting" in cfg:
                if p_name:
                    cfg["meeting"]["label"] = p_name.replace(" ", "_")[:24]
                if num_speakers is not None:
                    cfg["meeting"]["num_speakers"] = num_speakers
            if "paths" in cfg and audio_path:
                cfg["paths"]["audio"] = audio_path
            cfg.setdefault("experiment", {})
            cfg["experiment"]["name"]    = e_name or exp_slug
            if context:
                cfg["experiment"]["context"] = context
            if isinstance(asr_overrides, dict):
                cfg.setdefault("asr", {})
                cfg["asr"].update(asr_overrides)
            if isinstance(diar_overrides, dict):
                cfg.setdefault("diarization", {})
                cfg["diarization"].update(diar_overrides)
            yaml_raw = _yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)
            (exp_dir / "config.yaml").write_text(yaml_raw, encoding="utf-8")
            base_cfg_path.write_text(yaml_raw, encoding="utf-8")
        except Exception:
            pass

        return jsonify({"ok": True, "yaml_raw": yaml_raw, "gcs_path": str(exp_dir)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/upload_audio", methods=["POST"])
def api_upload_audio() -> Any:
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file field in request"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400
    ext = Path(f.filename).suffix.lower()
    allowed = {".mp3", ".m4a", ".wav", ".ogg", ".webm", ".mp4"}
    if ext not in allowed:
        return jsonify({"ok": False, "error": f"Unsupported audio type: {ext}"}), 400
    audio_dir = Path(OUTPUT_DIR)
    audio_dir.mkdir(parents=True, exist_ok=True)
    dest = audio_dir / f"uploaded_audio{ext}"
    f.save(str(dest))
    manifest_path = audio_dir / "run_manifest.json"
    manifest: Dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    manifest["audio_path"] = str(dest)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return jsonify({"ok": True, "audio_path": str(dest), "filename": f.filename})


@app.route("/api/generate_mom", methods=["POST"])
def api_generate_mom() -> Any:
    return jsonify({"ok": False, "error": "MoM LLM generation not configured."}), 501


@app.route("/api/generate_brd", methods=["POST"])
def api_generate_brd() -> Any:
    return jsonify({"ok": False, "error": "BRD LLM generation not configured."}), 501


def _export_pdf(md_text: str, out_path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate
    doc = SimpleDocTemplate(str(out_path), pagesize=A4)
    styles = getSampleStyleSheet()
    story = [Paragraph(md_text.replace("\n", "<br/>"), styles["Normal"])]
    doc.build(story)


def _export_docx(md_text: str, out_path: Path) -> None:
    from docx import Document
    doc = Document()
    for line in md_text.splitlines():
        doc.add_paragraph(line)
    doc.save(str(out_path))


@app.route("/api/export", methods=["POST"])
def api_export() -> Any:
    data     = request.get_json(force=True)
    run_id   = (data.get("run_id") or "").strip() or "current"
    doc_type = data.get("doc_type", "mom")
    fmt      = data.get("format", "pdf")
    if doc_type not in {"mom", "brd"} or fmt not in {"pdf", "docx"}:
        return jsonify({"ok": False, "error": "Unsupported doc_type or format"}), 400
    root = _run_dir(run_id)
    if not root.exists():
        return jsonify({"ok": False, "error": f"run not found: {run_id}"}), 404
    base_dir = root / ("minutes" if doc_type == "mom" else "brd")
    pattern  = "MoM*.md" if doc_type == "mom" else "BRD*.md"
    src = next(base_dir.glob(pattern), None) if base_dir.exists() else None
    if not src:
        return jsonify({"ok": False, "error": f"{doc_type.upper()}.md not found"}), 404
    md_text  = src.read_text(encoding="utf-8")
    out_dir  = root / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{doc_type.upper()}.{fmt}"
    try:
        if fmt == "pdf":
            _export_pdf(md_text, out_path)
        else:
            _export_docx(md_text, out_path)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    if not out_path.exists():
        return jsonify({"ok": False, "error": "Export file was not created"}), 500
    return jsonify({"ok": True, "path": str(out_path), "size": out_path.stat().st_size})


def main() -> None:
    port = int(os.environ.get("DN_SERVER_PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()

