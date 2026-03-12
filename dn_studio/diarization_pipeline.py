"""
DN-Studio Speaker Diarization Core

Port of the notebook's `diarization_pipeline.py` into a reusable module.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import librosa
import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel
from scipy.ndimage import median_filter
from sklearn.cluster import AgglomerativeClustering, SpectralClustering
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize

from .config import (
    AUDIO_FILE,
    BEAM_SIZE,
    BEST_OF,
    COMPRESS_THRESH,
    COMPUTE_TYPE,
    DEVICE,
    GDRIVE_AUDIO_URL,
    LINKAGE,
    LOG_PROB_THRESH,
    MAX_SPEAKERS,
    METRIC,
    MIN_SEG_DUR,
    NO_SPEECH_THRESH,
    NUM_SPEAKERS,
    OUTPUT_DIR,
    PCA_VARIANCE,
    REMOVE_FILLERS,
    REMOVE_REPEATS,
    REMOVE_STUTTERS,
    SEED,
    SMOOTH_WINDOW,
    USE_UTTERANCE_EMBEDDINGS,
    VAD_FILTER,
    VAD_SILENCE_MS,
    WHISPER_MODEL,
)
from .timeline_renderer import render_html

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("diarization_pipeline")


@dataclass
class ASRSegment:
    start: float
    end: float
    text: str
    speaker: Optional[str] = None
    utterance_id: Optional[int] = None
    confidence: float = 1.0


@dataclass
class SpeakerSegment:
    start: float
    end: float
    speaker: str


_FILLERS = re.compile(
    r"\b(um+|uh+|er+|ah+|hmm+|mhm|uh-huh|you know|i mean"
    r"|like,?\s+(?=\w)|sort of|kind of|basically|literally|actually,?\s+)\b",
    re.IGNORECASE,
)
_STUTTER = re.compile(r"\b(\w+)[–-]\s+\1", re.IGNORECASE)
_REPEATED = re.compile(r"\b(\w{2,})\s+\1\b", re.IGNORECASE)
_MULTI_SP = re.compile(r"\s{2,}")
_LEAD_PCT = re.compile(r"^[,\.;\s]+")


def clean_text(
    raw: str,
    remove_fillers: bool = True,
    remove_stutters: bool = True,
    remove_repeats: bool = True,
) -> str:
    t = raw.strip()
    if remove_stutters:
        t = _STUTTER.sub(r"\1", t)
    if remove_repeats:
        t = _REPEATED.sub(r"\1", t)
    if remove_fillers:
        t = _FILLERS.sub(" ", t)
    t = _LEAD_PCT.sub("", _MULTI_SP.sub(" ", t))
    return (t[0].upper() + t[1:]).strip() if t else t


def transcribe(
    audio_path: str,
    model_size: str = WHISPER_MODEL,
    device: str = DEVICE,
    compute_type: str = COMPUTE_TYPE,
    beam_size: int = BEAM_SIZE,
    best_of: int = BEST_OF,
    vad_filter: bool = VAD_FILTER,
    vad_silence_ms: int = VAD_SILENCE_MS,
    condition_on_prev: bool = True,
    no_speech_thresh: float = NO_SPEECH_THRESH,
    log_prob_thresh: float = LOG_PROB_THRESH,
    compression_thresh: float = COMPRESS_THRESH,
    remove_fillers: bool = REMOVE_FILLERS,
    remove_stutters: bool = REMOVE_STUTTERS,
    remove_repeats: bool = REMOVE_REPEATS,
) -> List[ASRSegment]:
    log.info(
        "[ASR] Loading model='%s'  device=%s  compute=%s",
        model_size,
        device,
        compute_type,
    )
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    segs, _info = model.transcribe(
        audio_path,
        language="en",
        beam_size=beam_size,
        best_of=best_of,
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        compression_ratio_threshold=compression_thresh,
        log_prob_threshold=log_prob_thresh,
        no_speech_threshold=no_speech_thresh,
        condition_on_previous_text=condition_on_prev,
        vad_filter=vad_filter,
        vad_parameters=dict(min_silence_duration_ms=vad_silence_ms),
        word_timestamps=False,
    )

    out: List[ASRSegment] = []
    for s in segs:
        t = clean_text(s.text, remove_fillers, remove_stutters, remove_repeats)
        if not t:
            continue
        conf = float(np.clip(np.exp(s.avg_logprob), 0.0, 1.0))
        out.append(ASRSegment(float(s.start), float(s.end), t, confidence=conf))

    log.info("[ASR] %d segments produced.", len(out))
    return out


def load_audio_mono(path: str, sr: int = 16_000) -> np.ndarray:
    y, _ = librosa.load(path, sr=sr, mono=True)
    return y


def get_segment_embedding(
    encoder,
    y: np.ndarray,
    sr: int,
    start: float,
    end: float,
    min_dur: float = 0.5,
) -> Optional[np.ndarray]:
    s, e = int(start * sr), int(end * sr)
    chunk = y[s:e]
    if len(chunk) < int(min_dur * sr):
        return None
    try:
        from resemblyzer import preprocess_wav

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, chunk, sr)
            wav = preprocess_wav(tmp.name)
        os.unlink(tmp.name)
        return encoder.embed_utterance(wav)
    except Exception as ex:  # pragma: no cover
        log.debug("[EMB] Skipping [%.1f–%.1f]s: %s", start, end, ex)
        return None


def extract_embeddings_for_segments(
    audio_path: str,
    asr_segments: List[ASRSegment],
    sr: int = 16_000,
) -> Tuple[List[int], np.ndarray]:
    from resemblyzer import VoiceEncoder

    log.info("[EMB] Loading VoiceEncoder (resemblyzer d-vector)…")
    encoder = VoiceEncoder("cpu")
    log.info("[EMB] Embedding %d ASR segments…", len(asr_segments))
    y = load_audio_mono(audio_path, sr)

    valid_idx: List[int] = []
    embeddings: List[np.ndarray] = []
    for i, seg in enumerate(asr_segments):
        emb = get_segment_embedding(encoder, y, sr, seg.start, seg.end)
        if emb is not None:
            valid_idx.append(i)
            embeddings.append(emb)
    emb_arr = np.array(embeddings, dtype=np.float32)
    log.info("[EMB] %d embeddings extracted  (dim=%d).", len(valid_idx), emb_arr.shape[1])
    return valid_idx, emb_arr


def best_num_speakers(X: np.ndarray, max_n: int = MAX_SPEAKERS) -> int:
    Xn = normalize(X)
    best_n, best_score = 2, -1.0
    log.info("[DIAR] Silhouette search for num_speakers (max=%d)…", max_n)
    for n in range(2, min(max_n + 1, len(X))):
        try:
            _Xn = normalize(Xn)
            _aff = np.clip(_Xn @ _Xn.T, 0.0, 1.0)
            np.fill_diagonal(_aff, 1.0)
            labels = SpectralClustering(
                n_clusters=n,
                affinity="precomputed",
                random_state=SEED,
                assign_labels="discretize",
                n_init=20,
            ).fit_predict(_aff)
            if len(np.unique(labels)) < n:
                raise ValueError("collapsed")
            score = silhouette_score(Xn, labels, metric="cosine")
            log.info("  n=%d  silhouette=%.4f", n, score)
            if score > best_score:
                best_score, best_n = score, n
        except Exception as ex:  # pragma: no cover
            log.warning("  n=%d  failed: %s", n, ex)
    log.info("[DIAR] Best n_speakers=%d  (silhouette=%.4f)", best_n, best_score)
    return best_n


def smooth_labels(labels: np.ndarray, window: int = 5) -> np.ndarray:
    return np.round(median_filter(labels.astype(float), size=window)).astype(int)


def diarize_utterances(
    asr_segments: List[ASRSegment],
    valid_idx: List[int],
    embeddings: np.ndarray,
    num_speakers: Optional[int],
    max_speakers: int,
    smooth_window: int,
    pca_variance: float,
) -> List[ASRSegment]:
    embeddings = np.nan_to_num(embeddings, nan=0.0, posinf=0.0, neginf=0.0)
    _norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = np.where(
        _norms > 1e-8,
        embeddings,
        np.random.default_rng(SEED).normal(0, 1e-4, embeddings.shape),
    )
    Xn = normalize(embeddings)

    if pca_variance < 1.0 and Xn.shape[1] > 10:
        pca = PCA(n_components=pca_variance, svd_solver="full")
        Xn = pca.fit_transform(Xn)

    if num_speakers is None:
        num_speakers = best_num_speakers(Xn, max_speakers)
    else:
        log.info("[DIAR] Using num_speakers=%d", num_speakers)

    log.info("[DIAR] Clustering %d utterances → %d speakers…", len(Xn), num_speakers)
    try:
        _Xn = normalize(Xn)
        _aff = np.clip(_Xn @ _Xn.T, 0.0, 1.0)
        np.fill_diagonal(_aff, 1.0)
        labels = SpectralClustering(
            n_clusters=num_speakers,
            affinity="precomputed",
            random_state=SEED,
            assign_labels="discretize",
            n_init=50,
        ).fit_predict(_aff)
        if len(np.unique(labels)) < num_speakers:
            log.warning(
                "[DIAR] discretize collapsed to %d clusters, retrying with kmeans",
                len(np.unique(labels)),
            )
            labels = SpectralClustering(
                n_clusters=num_speakers,
                affinity="precomputed",
                random_state=SEED + 1,
                assign_labels="kmeans",
                n_init=50,
            ).fit_predict(_aff)
        if len(np.unique(labels)) < num_speakers:
            raise ValueError("Spectral collapsed")
        log.info("[DIAR] Spectral produced %d clusters ✅", len(np.unique(labels)))
    except Exception as ex:  # pragma: no cover
        log.warning(
            "[DIAR] Spectral failed (%s) — falling back to Agglomerative", ex
        )
        labels = AgglomerativeClustering(
            n_clusters=num_speakers,
            metric="euclidean",
            linkage="ward",
        ).fit_predict(normalize(Xn))
        log.info(
            "[DIAR] Agglomerative (ward) produced %d clusters",
            len(np.unique(labels)),
        )

    labels = smooth_labels(np.array(labels), smooth_window)

    for rank, seg_idx in enumerate(valid_idx):
        asr_segments[seg_idx].speaker = f"SPEAKER_{labels[rank]}"
        asr_segments[seg_idx].utterance_id = seg_idx

    for i, seg in enumerate(asr_segments):
        if seg.speaker is None:
            nearest = min(valid_idx, key=lambda j: abs(j - i), default=None)
            seg.speaker = (
                asr_segments[nearest].speaker if nearest else "SPEAKER_UNKNOWN"
            )
            seg.utterance_id = i
    return asr_segments


def to_json(asr: List[ASRSegment]) -> List[Dict[str, Any]]:
    return [
        {
            "start": round(s.start, 3),
            "end": round(s.end, 3),
            "utterance_id": s.utterance_id,
            "speaker_id": s.speaker,
            "speaker_name": s.speaker,
            "confidence": round(s.confidence, 3),
            "text": s.text,
        }
        for s in asr
    ]


def speaker_summary(asr: List[ASRSegment]) -> Dict[str, Any]:
    spk: Dict[str, Dict[str, Any]] = {}
    for s in asr:
        k = s.speaker or "SPEAKER_UNKNOWN"
        spk.setdefault(
            k,
            {
                "speaker_name": k,
                "total_time_sec": 0.0,
                "utterances": 0,
                "word_count": 0,
            },
        )
        spk[k]["total_time_sec"] += max(0.0, s.end - s.start)
        spk[k]["utterances"] += 1
        spk[k]["word_count"] += len(s.text.split())
    return {"total_segments": len(asr), "speakers": spk}


def to_markdown(asr: List[ASRSegment], summary: Dict[str, Any]) -> str:
    lines = ["# Meeting Transcript\n", "## Speaker Summary\n"]
    for spk, st in sorted(summary["speakers"].items()):
        display = st.get("speaker_name", spk)
        lines.append(
            f"- **{display}**: {st['utterances']} utterances | "
            f"{st['total_time_sec']:.0f}s | {st['word_count']} words"
        )
    lines.append("\n## Transcript\n")
    prev = None
    for s in asr:
        if s.speaker != prev:
            display = summary["speakers"].get(s.speaker, {}).get(
                "speaker_name", s.speaker
            )
            lines.append(f"\n**{display}** _{s.start:.1f}s_")
            prev = s.speaker
        lines.append(f"> {s.text}")
    return "\n".join(lines)


def _compute_clusters(
    seg_path: str,
    audio_path: str,
    out_path: str,
) -> Optional[str]:
    """Compute PCA / t-SNE projections of utterance embeddings for the clusters tab."""
    try:
        from resemblyzer import VoiceEncoder, preprocess_wav  # type: ignore[import]

        segs = json.loads(Path(seg_path).read_text(encoding="utf-8"))
        if not segs:
            return None

        y, _ = librosa.load(audio_path, sr=16_000, mono=True)
        enc = VoiceEncoder("cpu")

        embs: List[np.ndarray] = []
        meta: List[Dict[str, Any]] = []
        for s in segs:
            dur = s["end"] - s["start"]
            if dur < 0.4:
                continue
            s0 = int(s["start"] * 16_000)
            e0 = int(s["end"] * 16_000)
            chunk = y[s0:e0]
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    sf.write(tmp.name, chunk, 16_000)
                    wav = preprocess_wav(tmp.name)
                os.unlink(tmp.name)
                embs.append(enc.embed_utterance(wav))
                meta.append(
                    {
                        "spk": s.get("speaker_name") or s.get("speaker_id", "UNKNOWN"),
                        "start": round(s["start"], 2),
                        "end": round(s["end"], 2),
                        "text": (s.get("text") or "")[:100],
                    }
                )
            except Exception:
                continue

        if len(embs) < 4:
            return None

        arr = np.array(embs, dtype="float32")
        Xn = normalize(arr)

        # PCA 2D
        pca_xy = PCA(n_components=2, random_state=0).fit_transform(Xn)

        # t-SNE 2D and 3D (with small perplexity for few points)
        perp = max(5, min(30, len(Xn) // 4))
        tsne2_xy = TSNE(
            n_components=2,
            perplexity=perp,
            n_iter=1000,
            metric="cosine",
            random_state=0,
            init="pca",
        ).fit_transform(Xn)
        tsne3_xyz = TSNE(
            n_components=3,
            perplexity=perp,
            n_iter=1000,
            metric="cosine",
            random_state=1,
            init="pca",
        ).fit_transform(Xn)

        def _pts(coords: np.ndarray) -> List[Dict[str, Any]]:
            return [
                {
                    "x": float(coords[i, 0]),
                    "y": float(coords[i, 1]),
                    "z": float(coords[i, 2]) if coords.shape[1] > 2 else 0.0,
                    "spk": meta[i]["spk"],
                    "start": meta[i]["start"],
                    "end": meta[i]["end"],
                    "text": meta[i]["text"],
                }
                for i in range(len(meta))
            ]

        clusters = {
            "pca": _pts(pca_xy),
            "tsne": _pts(tsne2_xy),
            "tsne3d": _pts(tsne3_xyz),
        }
        Path(out_path).write_text(
            json.dumps(clusters, ensure_ascii=False), encoding="utf-8"
        )
        log.info("[CLUSTER] Saved cluster embeddings → %s", out_path)
        return out_path
    except Exception as exc:
        log.warning("[CLUSTER] Cluster embedding generation failed: %s", exc)
        return None


def run_pipeline(
    audio_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    num_speakers_override: Optional[int] = None,
    asr_overrides: Optional[Dict[str, Any]] = None,
    diar_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Optional[str]]:
    if audio_path is None:
        audio_path = str(AUDIO_FILE)
    if output_dir is None:
        output_dir = str(OUTPUT_DIR)
    if asr_overrides is None:
        asr_overrides = {}
    if diar_overrides is None:
        diar_overrides = {}

    if not os.path.exists(audio_path):
        log.info("[GDWN] Downloading audio from Google Drive…")
        _fid_match = re.search(
            r"(?:id=|/d/)([A-Za-z0-9_-]{25,})", GDRIVE_AUDIO_URL
        )
        if _fid_match:
            _clean_url = (
                f"https://drive.google.com/uc?id={_fid_match.group(1)}"
            )
        else:
            _clean_url = GDRIVE_AUDIO_URL
        _dest = audio_path
        log.info("[GDWN] URL  : %s", _clean_url)
        log.info("[GDWN] Dest : %s", _dest)
        _dl_result = subprocess.run(
            ["gdown", "-O", _dest, _clean_url],
            capture_output=False,
        )
        if _dl_result.returncode != 0:
            raise RuntimeError(
                f"[GDWN] gdown failed (exit {_dl_result.returncode}).\n"
                "Make sure the file is publicly shared."
            )

    _MIN_AUDIO_BYTES = 100_000
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"AUDIO file not found: {audio_path}")
    _audio_size = os.path.getsize(audio_path)
    if _audio_size < _MIN_AUDIO_BYTES:
        os.remove(audio_path)
        raise ValueError(
            f"Downloaded file too small ({_audio_size:,} bytes). "
            "Google Drive link may be private or invalid."
        )
    log.info(
        "[AUDIO] ✅ %s  (%.1f MB)",
        os.path.basename(audio_path),
        _audio_size / 1_048_576,
    )

    os.makedirs(output_dir, exist_ok=True)
    seg_path = os.path.join(output_dir, "transcript.json")
    sum_path = os.path.join(output_dir, "summary.json")
    md_path = os.path.join(output_dir, "transcript.md")

    print("\n" + "=" * 60)
    print("  STEP 0 — EMBEDDING-BASED SPEAKER DIARIZATION")
    print("=" * 60)

    _a = asr_overrides
    asr = transcribe(
        audio_path,
        model_size=_a.get("whisper_model", WHISPER_MODEL),
        beam_size=int(_a.get("beam_size", BEAM_SIZE)),
        best_of=int(_a.get("best_of", BEST_OF)),
        vad_filter=bool(_a.get("vad_filter", VAD_FILTER)),
        vad_silence_ms=int(_a.get("vad_silence_ms", VAD_SILENCE_MS)),
        no_speech_thresh=float(_a.get("no_speech_thresh", NO_SPEECH_THRESH)),
        log_prob_thresh=float(_a.get("log_prob_thresh", LOG_PROB_THRESH)),
        compression_thresh=float(_a.get("compress_thresh", COMPRESS_THRESH)),
        remove_fillers=bool(_a.get("remove_fillers", REMOVE_FILLERS)),
        remove_stutters=bool(_a.get("remove_stutters", REMOVE_STUTTERS)),
        remove_repeats=bool(_a.get("remove_repeats", REMOVE_REPEATS)),
    )
    valid_idx, embeddings = extract_embeddings_for_segments(audio_path, asr)

    _d = diar_overrides
    n_speakers = num_speakers_override if num_speakers_override is not None else NUM_SPEAKERS
    asr = diarize_utterances(
        asr,
        valid_idx,
        embeddings,
        n_speakers,
        int(_d.get("max_speakers", MAX_SPEAKERS)),
        int(_d.get("smooth_window", SMOOTH_WINDOW)),
        float(_d.get("pca_variance", PCA_VARIANCE)),
    )

    result = to_json(asr)
    summ = speaker_summary(asr)
    md = to_markdown(asr, summ)

    with open(seg_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    with open(sum_path, "w", encoding="utf-8") as f:
        json.dump(summ, f, indent=2, ensure_ascii=False)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    viz_path = os.path.join(output_dir, "viz.html")
    try:
        render_html(seg_path, viz_path)
        log.info("[VIZ] Timeline saved → %s", viz_path)
    except Exception as e:  # pragma: no cover
        log.warning("[VIZ] Skipped (%s)", e)

    # ── optional: compute cluster embeddings for console cluster tab ────────
    clusters_path = os.path.join(output_dir, "clusters.json")
    clusters_path_or_none = _compute_clusters(seg_path, audio_path, clusters_path)

    print("\n[OUT] Outputs saved to:", output_dir)
    for p in [seg_path, sum_path, md_path, viz_path, clusters_path_or_none]:
        if p and os.path.exists(p):
            print(f"  {os.path.basename(p):<30} {os.path.getsize(p):>8,} bytes")
    print("=" * 60)

    return {
        "segments": seg_path,
        "summary": sum_path,
        "markdown": md_path,
        "viz_html": viz_path if os.path.exists(viz_path) else None,
        "clusters": clusters_path_or_none,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="DN-Studio Speaker Diarization"
    )
    parser.add_argument(
        "--audio", default=None, help="Path to audio file (default from config)"
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory (default cfg.paths.diarization)",
    )
    parser.add_argument(
        "--speakers",
        type=int,
        default=None,
        help="Known speaker count (None = auto from config / silhouette search)",
    )
    args = parser.parse_args()
    run_pipeline(
        audio_path=args.audio,
        output_dir=args.out,
        num_speakers_override=args.speakers,
    )


