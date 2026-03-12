"""
Runtime config module for DN-Studio.

This is a Python adaptation of the original notebook's 2b cell.
It reads `cfg/config.yaml` at import time and exposes the same
module-level constants that `diarization_pipeline.py` expects.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
YAML_PATH = PROJECT_ROOT / "cfg" / "config.yaml"

if not YAML_PATH.exists():
    raise FileNotFoundError(f"cfg/config.yaml not found at {YAML_PATH}")

with YAML_PATH.open(encoding="utf-8") as _f:
    _C: Dict[str, Any] = yaml.safe_load(_f)

# Project & Experiment
PROJECT_NAME = _C.get("project_name", "") or ""
EXPERIMENT_NAME = _C.get("experiment_name", "") or ""

# Audio
AUDIO_FORMAT = _C["audio"]["format"]
GDRIVE_AUDIO_URL = _C["audio"]["gdrive_url"]

# Meeting
MEETING_LABEL = _C["meeting"]["label"]
NUM_SPEAKERS = _C["meeting"]["num_speakers"]
COMPANY_ROSTER = _C["meeting"]["company_roster"]

# ASR
WHISPER_MODEL = _C["asr"]["whisper_model"]
BEAM_SIZE = _C["asr"]["beam_size"]
BEST_OF = _C["asr"]["best_of"]
VAD_FILTER = _C["asr"]["vad_filter"]
VAD_SILENCE_MS = _C["asr"]["vad_silence_ms"]
CONDITION_ON_PREV = _C["asr"]["condition_on_prev"]
NO_SPEECH_THRESH = _C["asr"]["no_speech_thresh"]
LOG_PROB_THRESH = _C["asr"]["log_prob_thresh"]
COMPRESS_THRESH = _C["asr"]["compress_thresh"]
REMOVE_FILLERS = _C["asr"]["remove_fillers"]
REMOVE_STUTTERS = _C["asr"]["remove_stutters"]
REMOVE_REPEATS = _C["asr"]["remove_repeats"]

# Diarization
MAX_SPEAKERS = _C["diarization"]["max_speakers"]
SMOOTH_WINDOW = _C["diarization"]["smooth_window"]
MIN_SEG_DUR = _C["diarization"]["min_seg_dur"]
PCA_VARIANCE = _C["diarization"]["pca_variance"]
LINKAGE = _C["diarization"]["linkage"]
METRIC = _C["diarization"]["metric"]
USE_UTTERANCE_EMBEDDINGS = _C["diarization"]["use_utterance_embeddings"]

# Seed
SEED = _C["seed"]

# Paths (interpreted relative to project root)
_paths = _C["paths"]
SCRIPTS_DIR = PROJECT_ROOT / _paths["scripts_dir"]
OUTPUTS_ROOT = PROJECT_ROOT / _paths["outputs_root"]
_audio_raw = Path(_paths["audio"])
AUDIO_FILE = _audio_raw if _audio_raw.is_absolute() else PROJECT_ROOT / _audio_raw
_LABEL = MEETING_LABEL.strip().replace(" ", "_")[:24]
OUTPUT_DIR = OUTPUTS_ROOT / "diarization"
SEGMENTS_JSON = str(PROJECT_ROOT / _paths["diarization"]["transcript_json"])

# Device from env (set by environment / launcher)
DEVICE = os.environ.get("DN_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("DN_COMPUTE", "int8")

# Ensure package is importable from scripts
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


