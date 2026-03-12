"""
DN-Studio Project Console — Flask backend
"""

import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template_string, request, send_from_directory

BASE_DIR   = Path(__file__).parent.absolute()
GCS_DIR    = BASE_DIR / "gcs"
CFG_DIR    = BASE_DIR / "cfg"
# For consistency with Colab runs and the dn_studio server, treat
# inputs/ as the canonical location for uploaded audio.
AUDIO_DIR  = BASE_DIR / "inputs"
TMPL_PATH  = BASE_DIR / "dashboard.html"*** End Patch```} ***!

GCS_DIR.mkdir(exist_ok=True)
CFG_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)

def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def _new_project_id() -> str:
    return f"proj_{_ts()}"

def _new_run_id() -> str:
    return f"run_{_ts()}"

def _global_cfg() -> dict:
    p = CFG_DIR / "config.yaml"
    if p.exists():
        return yaml.safe_load(p.read_text()) or {}
    return {}

def _load_cfg(path: Path) -> dict:
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}

def _save_cfg(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))

def _list_projects() -> list[dict]:
    projects = []
    if not GCS_DIR.exists():
        return projects
    for proj_dir in sorted(GCS_DIR.iterdir(), reverse=True):
        if not proj_dir.is_dir():
            continue
        cfg = _load_cfg(proj_dir / "config.yaml")
        runs_dir = proj_dir / "runs"
        runs = []
        if runs_dir.exists():
            for run_dir in sorted(runs_dir.iterdir(), reverse=True):
                if not run_dir.is_dir():
                    continue
                rcfg = _load_cfg(run_dir / "config.yaml")
                runs.append({
                    "id":           run_dir.name,
                    "project_id":   proj_dir.name,
                    "project_name": cfg.get("project_name", proj_dir.name),
                    "label":        f"{cfg.get('project_name', proj_dir.name)} / {run_dir.name}",
                    "config":       rcfg,
                    "has_diarization": (run_dir / "diarization.json").exists(),
                    "has_transcript":  (run_dir / "transcript.json").exists(),
                    "has_clusters":    (run_dir / "clusters.json").exists(),
                    "has_mom":         (run_dir / "mom.md").exists(),
                    "has_brd":         (run_dir / "brd.md").exists(),
                })
        projects.append({
            "id":    proj_dir.name,
            "name":  cfg.get("project_name", proj_dir.name),
            "path":  str(proj_dir),
            "config": cfg,
            "runs":  runs,
        })
    return projects

def _active_project_and_run():
    projects = _list_projects()
    if not projects:
        pid = _new_project_id()
        proj_dir = GCS_DIR / pid
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "runs").mkdir(exist_ok=True)
        _save_cfg(proj_dir / "config.yaml", {})
        return proj_dir, None
    proj = projects[0]
    proj_dir = GCS_DIR / proj["id"]
    if proj["runs"]:
        run_dir = proj_dir / "runs" / proj["runs"][0]["id"]
        return proj_dir, run_dir
    return proj_dir, None

def _run_dir_for_id(run_id: str) -> Path | None:
    for proj_dir in GCS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        candidate = proj_dir / "runs" / run_id
        if candidate.exists():
            return candidate
    return None

def _build_runs_json() -> list[dict]:
    import base64
    def _b64(path: Path) -> str | None:
        if path and path.exists():
            return base64.b64encode(path.read_bytes()).decode()
        return None
    runs = []
    projects = _list_projects()
    if not projects:
        runs.append({"id": "current","label": "Current (latest)","project_id": "","project_name": "","diarization_b64": None,"clusters_b64": None,"transcript_b64": None,"mom_md_b64": None,"brd_md_b64": None,"audio_path": None,})
        return runs
    for proj in projects:
        proj_dir = GCS_DIR / proj["id"]
        for run in proj["runs"]:
            run_dir = proj_dir / "runs" / run["id"]
            cfg = run["config"]
            runs.append({"id": run["id"],"label": run["label"],"project_id": proj["id"],"project_name": proj["name"],"has_diarization": run.get("has_diarization", False),"has_transcript": run.get("has_transcript", False),"has_clusters": run.get("has_clusters", False),"has_mom": run.get("has_mom", False),"has_brd": run.get("has_brd", False),"diarization_b64": _b64(run_dir / "diarization.json"),"clusters_b64": _b64(run_dir / "clusters.json"),"transcript_b64": _b64(run_dir / "transcript.json"),"mom_md_b64": _b64(run_dir / "mom.md"),"brd_md_b64": _b64(run_dir / "brd.md"),"audio_path": cfg.get("audio_path"),"num_speakers": cfg.get("num_speakers"),"context": cfg.get("context", ""),})
        if not proj["runs"]:
            runs.append({"id": "current","label": f"{proj['name'] or proj['id']} -- no runs yet","project_id": proj["id"],"project_name": proj["name"],"diarization_b64": None,"clusters_b64": None,"transcript_b64": None,"mom_md_b64": None,"brd_md_b64": None,"audio_path": None,})
    if not runs:
        runs.append({"id": "current", "label": "Current (latest)","project_id": "", "project_name": "","diarization_b64": None, "clusters_b64": None,"transcript_b64": None, "mom_md_b64": None,"brd_md_b64": None, "audio_path": None,})
    return runs

app = Flask(__name__)

@app.route("/")
def index():
    tmpl = TMPL_PATH.read_text(encoding="utf-8")
    runs = _build_runs_json()
    default_run = 0
    roster = []
    clusters = None
    for r in runs:
        if r.get("clusters_b64"):
            import base64
            try:
                clusters = json.loads(base64.b64decode(r["clusters_b64"]))
            except Exception:
                pass
            break
    tmpl = tmpl.replace("__RUNS_JSON__",    json.dumps(runs))
    tmpl = tmpl.replace("__DEFAULT_RUN__",  str(default_run))
    tmpl = tmpl.replace("__ROSTER_JSON__",  json.dumps(roster))
    tmpl = tmpl.replace("__CLUSTERS_JSON__", json.dumps(clusters))
    return tmpl

@app.route("/api/config")
def api_config():
    run_id = request.args.get("run_id", "current")
    if run_id and run_id != "current":
        run_dir = _run_dir_for_id(run_id)
        if run_dir:
            cfg_path = run_dir / "config.yaml"
            cfg = _load_cfg(cfg_path)
            yaml_raw = cfg_path.read_text() if cfg_path.exists() else ""
            return jsonify({"ok": True, **cfg, "yaml_raw": yaml_raw})
    proj_dir, run_dir = _active_project_and_run()
    if run_dir and (run_dir / "config.yaml").exists():
        cfg_path = run_dir / "config.yaml"
    elif proj_dir and (proj_dir / "config.yaml").exists():
        cfg_path = proj_dir / "config.yaml"
    else:
        cfg_path = CFG_DIR / "config.yaml"
    cfg = _load_cfg(cfg_path)
    yaml_raw = cfg_path.read_text() if cfg_path.exists() else ""
    return jsonify({"ok": True, **cfg, "yaml_raw": yaml_raw})

@app.route("/api/save_config", methods=["POST"])
def api_save_config():
    data = request.get_json(force=True)
    run_id = data.get("run_id")
    if run_id and run_id != "current":
        run_dir = _run_dir_for_id(run_id)
        if run_dir:
            cfg_path = run_dir / "config.yaml"
        else:
            proj_dir, _ = _active_project_and_run()
            cfg_path = proj_dir / "config.yaml"
    else:
        proj_dir, run_dir = _active_project_and_run()
        cfg_path = (run_dir / "config.yaml") if run_dir else (proj_dir / "config.yaml")
    existing = _load_cfg(cfg_path)
    existing.update({k: v for k, v in {"project_name": data.get("project_name"),"context": data.get("context"),"num_speakers": int(data["num_speakers"]) if data.get("num_speakers") else None,}.items() if v is not None})
    _save_cfg(cfg_path, existing)
    return jsonify({"ok": True})

@app.route("/api/new_project", methods=["POST"])
def api_new_project():
    pid = _new_project_id()
    proj_dir = GCS_DIR / pid
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "runs").mkdir(exist_ok=True)
    data = request.get_json(force=True, silent=True) or {}
    initial_cfg = {}
    if data.get("project_name"):
        initial_cfg["project_name"] = data["project_name"]
    _save_cfg(proj_dir / "config.yaml", initial_cfg)
    return jsonify({"ok": True, "project_id": pid})

@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(force=True, silent=True) or {}
    proj_id = data.get("project_id")
    if proj_id:
        proj_dir = GCS_DIR / proj_id
        if not proj_dir.exists():
            return jsonify({"ok": False, "error": f"Project {proj_id} not found"})
    else:
        proj_dir, _ = _active_project_and_run()
    proj_cfg = _load_cfg(proj_dir / "config.yaml")
    run_id  = _new_run_id()
    run_dir = proj_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _save_cfg(run_dir / "config.yaml", proj_cfg)
    try:
        result = _run_diarization(proj_cfg, run_dir)
        if not result["ok"]:
            return jsonify({"ok": False, "error": result.get("error", "Diarization failed")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    return jsonify({"ok": True, "run_id": run_id, "project_id": proj_dir.name})

def _run_diarization(cfg: dict, run_dir: Path) -> dict:
    import subprocess
    script = BASE_DIR / "run_diarization.py"
    if not script.exists():
        (run_dir / "diarization.json").write_text(json.dumps({"segments": []}))
        (run_dir / "transcript.json").write_text(json.dumps({"utterances": []}))
        (run_dir / "clusters.json").write_text(json.dumps({}))
        return {"ok": True}
    res = subprocess.run(["python", str(script), "--run-dir", str(run_dir)],capture_output=True, text=True, timeout=3600)
    if res.returncode != 0:
        return {"ok": False, "error": res.stderr[-500:]}
    return {"ok": True}

@app.route("/api/upload_audio", methods=["POST"])
def api_upload_audio():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file in request"})
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "Empty filename"})
    safe_name = Path(f.filename).name
    dest = AUDIO_DIR / safe_name
    f.save(dest)
    proj_dir, run_dir = _active_project_and_run()
    cfg_path = (run_dir / "config.yaml") if run_dir else (proj_dir / "config.yaml")
    cfg = _load_cfg(cfg_path)
    cfg["audio_path"] = str(dest)
    _save_cfg(cfg_path, cfg)
    return jsonify({"ok": True, "filename": safe_name, "path": str(dest)})

@app.route("/api/set_audio_path", methods=["POST"])
def api_set_audio_path():
    data = request.get_json(silent=True) or {}
    audio_path = data.get("audio_path", "").strip()
    if not audio_path:
        return jsonify({"ok": False, "error": "No audio_path provided"}), 400
    p = Path(audio_path)
    if not p.exists() or not p.is_file():
        return jsonify({"ok": False, "error": f"File not found: {audio_path}"}), 404
    proj_dir, run_dir = _active_project_and_run()
    cfg_path = (run_dir / "config.yaml") if run_dir else (proj_dir / "config.yaml")
    cfg = _load_cfg(cfg_path)
    cfg["audio_path"] = audio_path
    _save_cfg(cfg_path, cfg)
    return jsonify({"ok": True, "audio_path": audio_path})

@app.route("/audio/<path:filename>")
def serve_audio(filename):
    return send_from_directory(AUDIO_DIR, filename)

@app.route("/api/save_names", methods=["POST"])
def api_save_names():
    data = request.get_json(force=True)
    run_id  = data.get("run_id")
    mapping = data.get("mapping", {})
    run_dir = _run_dir_for_id(run_id) if (run_id and run_id != "current") else None
    if run_dir is None:
        _, run_dir = _active_project_and_run()
    if run_dir is None:
        return jsonify({"ok": False, "error": "No active run"})
    for fname in ["diarization.json", "transcript.json"]:
        p = run_dir / fname
        if p.exists():
            d = json.loads(p.read_text())
            d["speaker_names"] = mapping
            p.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    return jsonify({"ok": True})

@app.route("/api/save_mom", methods=["POST"])
def api_save_mom():
    data    = request.get_json(force=True)
    run_id  = data.get("run_id")
    content = data.get("content", "")
    run_dir = _run_dir_for_id(run_id) if (run_id and run_id != "current") else None
    if run_dir is None:
        _, run_dir = _active_project_and_run()
    if run_dir is None:
        return jsonify({"ok": False, "error": "No active run"})
    (run_dir / "mom.md").write_text(content, encoding="utf-8")
    return jsonify({"ok": True})

@app.route("/api/save_brd", methods=["POST"])
def api_save_brd():
    data    = request.get_json(force=True)
    run_id  = data.get("run_id")
    content = data.get("content", "")
    run_dir = _run_dir_for_id(run_id) if (run_id and run_id != "current") else None
    if run_dir is None:
        _, run_dir = _active_project_and_run()
    if run_dir is None:
        return jsonify({"ok": False, "error": "No active run"})
    (run_dir / "brd.md").write_text(content, encoding="utf-8")
    return jsonify({"ok": True})

@app.route("/api/generate_mom", methods=["POST"])
def api_generate_mom():
    data   = request.get_json(force=True)
    run_id = data.get("run_id")
    ctx    = data.get("context", "")
    run_dir = _run_dir_for_id(run_id) if (run_id and run_id != "current") else None
    if run_dir is None:
        _, run_dir = _active_project_and_run()
    if run_dir is None:
        return jsonify({"ok": False, "error": "No active run"})
    transcript_path = run_dir / "transcript.json"
    if not transcript_path.exists():
        return jsonify({"ok": False, "error": "No transcript for this run"})
    # Use the same MoM LLM pipeline as the dn_studio dashboard
    try:
        from dn_studio.mom_llm import generate_mom
    except Exception as exc:
        return jsonify({"ok": False, "error": f"MoM LLM integration not available: {exc}"}), 500

    result = generate_mom(
        transcript_path=str(transcript_path),
        output_dir=str(run_dir),
        context=ctx or "",
    )

    if not result.get("ok"):
        return jsonify({"ok": False, "error": result.get("error", "MoM generation failed")}), 500

    mom_md = result.get("mom_md", "")
    # Keep a flat mom.md copy for the legacy export endpoint
    if mom_md:
        (run_dir / "mom.md").write_text(mom_md, encoding="utf-8")

    return jsonify({
        "ok": True,
        "mom_md": mom_md,
        "mom_json_path": result.get("mom_json_path", ""),
        "mom_trace_path": result.get("mom_trace_path", ""),
        "mom_doc_path": result.get("mom_doc_path", ""),
    })

@app.route("/api/generate_brd", methods=["POST"])
def api_generate_brd():
    data   = request.get_json(force=True)
    run_id = data.get("run_id")
    ctx    = data.get("context", "")
    run_dir = _run_dir_for_id(run_id) if (run_id and run_id != "current") else None
    if run_dir is None:
        _, run_dir = _active_project_and_run()
    if run_dir is None:
        return jsonify({"ok": False, "error": "No active run"})
    transcript_path = run_dir / "transcript.json"
    if not transcript_path.exists():
        return jsonify({"ok": False, "error": "No transcript for this run"})
    # Use the same BRD LLM pipeline as the dn_studio dashboard
    try:
        from dn_studio.brd_llm import generate_brd
    except Exception as exc:
        return jsonify({"ok": False, "error": f"BRD LLM integration not available: {exc}"}), 500

    result = generate_brd(
        transcript_path=str(transcript_path),
        output_dir=str(run_dir),
        context=ctx or "",
    )

    if not result.get("ok"):
        return jsonify({"ok": False, "error": result.get("error", "BRD generation failed")}), 500

    brd_md = result.get("brd_md", "")
    # Keep a flat brd.md copy for the legacy export endpoint
    if brd_md:
        (run_dir / "brd.md").write_text(brd_md, encoding="utf-8")

    return jsonify({
        "ok": True,
        "brd_md": brd_md,
        "brd_json_path": result.get("brd_json_path", ""),
        "brd_trace_path": result.get("brd_trace_path", ""),
    })

def _generate_doc(transcript_path: Path, doc_type: str, context: str) -> str:
    # Legacy stub kept only so older code paths don't crash if still referenced.
    return f"# {doc_type.upper()} -- auto-generated\n\n_Please run via the MoM/BRD LLM endpoints instead._\n"

@app.route("/api/export", methods=["POST"])
def api_export():
    data     = request.get_json(force=True)
    run_id   = data.get("run_id")
    doc_type = data.get("doc_type", "transcript")
    fmt      = data.get("format", "txt")
    run_dir = _run_dir_for_id(run_id) if (run_id and run_id != "current") else None
    if run_dir is None:
        _, run_dir = _active_project_and_run()
    if run_dir is None:
        return jsonify({"ok": False, "error": "No active run"})
    export_dir = run_dir / "exports"
    export_dir.mkdir(exist_ok=True)
    src_map = {"transcript": run_dir / "transcript.json","mom": run_dir / "mom.md","brd": run_dir / "brd.md",}
    src = src_map.get(doc_type)
    if not src or not src.exists():
        return jsonify({"ok": False, "error": f"No {doc_type} to export"})
    out_name = f"{doc_type}_{_ts()}.{fmt}"
    out_path = export_dir / out_name
    shutil.copy(src, out_path)
    return jsonify({"ok": True, "filename": out_name, "path": str(out_path)})

@app.route("/api/projects")
def api_projects():
    projects = _list_projects()
    return jsonify({"ok": True, "projects": projects})

if __name__ == "__main__":
    if not any(GCS_DIR.iterdir()) if GCS_DIR.exists() else True:
        pid = _new_project_id()
        proj_dir = GCS_DIR / pid
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "runs").mkdir(exist_ok=True)
        _save_cfg(proj_dir / "config.yaml", {})
    app.run(debug=True, port=5000)

