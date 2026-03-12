"""
MoM LLM Generator — transcript.json → structured Minutes of Meeting.

Pipeline:
1. Load diarization transcript.json
2. Build a user prompt object (context + speaker_map + transcript)
3. Call Gemini via LangChain using prompts/mom_system_prompt.json
4. Parse JSON response and attach trace objects using source_utterance_ids
5. Save response_mom.json + response_mom_trace.json into the run directory
6. Derive a compact MoM doc JSON for the markdown/DOCX generator
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOM_SYSTEM_PROMPT_PATH = PROJECT_ROOT / "prompts" / "mom_system_prompt.json"


def _load_llm_config() -> Dict[str, Any]:
    import yaml

    cfg_path = PROJECT_ROOT / "cfg" / "config.yaml"
    with cfg_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("llm", {})


def _build_user_prompt(transcript: List[Dict[str, Any]], context: str) -> Dict[str, Any]:
    unique_speakers = sorted(
        {u.get("speaker_id", u.get("speaker_name", "UNKNOWN")) for u in transcript}
    )
    speaker_map = {sid: sid for sid in unique_speakers}
    return {
        "context": context or "Minutes of a meeting.",
        "speaker_map": speaker_map,
        "transcript": transcript,
    }


def _extract_json(text: str) -> str:
    text = text.strip()
    if "```" in text:
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text.strip())
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _enrich_traces_mom(mom: Dict[str, Any], transcript: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach full utterance info for any node that has source_utterance_ids."""

    lookup: Dict[int, Dict[str, Any]] = {}
    for u in transcript:
        uid = u.get("utterance_id")
        if uid is None:
            continue
        lookup[uid] = {
            "utterance_id": uid,
            "text": u.get("text", ""),
            "speaker": u.get("speaker_name", u.get("speaker_id", "")),
            "start": u.get("start", 0.0),
            "end": u.get("end", 0.0),
        }

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            # If this node has explicit source_utterance_ids, derive a trace list
            if "source_utterance_ids" in node and "trace" not in node:
                ids = node.get("source_utterance_ids") or []
                traces: List[Dict[str, Any]] = []
                for uid in ids:
                    if isinstance(uid, int) and uid in lookup:
                        traces.append(lookup[uid].copy())
                if traces:
                    node["trace"] = traces
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
        return node

    return _walk(mom)


def _safe_val(obj: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = obj
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, {})
    if isinstance(cur, dict) and "value" in cur:
        return cur.get("value", default)
    return cur if cur not in (None, "") else default


def _build_mom_doc_json(mom: Dict[str, Any]) -> Dict[str, Any]:
    """Map rich MoM JSON into the simpler schema expected by generalised_mom_generator."""

    ctx = mom.get("meeting_context", {}) or {}
    participants = mom.get("participants", []) or []
    entities = mom.get("entities", []) or []

    # Basic meeting metadata
    title = _safe_val(ctx, "title", default="Minutes of Meeting")
    project_name = _safe_val(ctx, "project", "name", default="—")
    meeting_type = _safe_val(ctx, "meeting_type", default="other")
    date = _safe_val(ctx, "date", default="")
    time_start = _safe_val(ctx, "time_start", default="")
    time_end = _safe_val(ctx, "time_end", default="")
    duration_seconds = _safe_val(ctx, "duration_seconds", default=None)
    duration_minutes = round(float(duration_seconds) / 60.0, 1) if duration_seconds else None

    # Attendees / absent
    attendee_names: List[str] = []
    for p in participants:
        name = _safe_val(p, "name")
        if name:
            attendee_names.append(str(name))

    # Simple derived executive summary pieces from entities
    decisions: List[str] = []
    top_actions: List[Dict[str, Any]] = []
    blockers: List[str] = []

    for ent in entities:
        etype = ent.get("type")
        statement = ent.get("statement") or ""
        if not statement:
            continue
        if etype == "decision":
            decisions.append(statement)
        elif etype == "action_item":
            top_actions.append(
                {
                    "action": statement,
                    "owner": ent.get("owner", "unassigned"),
                    "due": ent.get("due", "tbd"),
                }
            )
        elif etype in {"risk", "blocker"}:
            blockers.append(statement)

    primary_outcome = ""
    if decisions:
        primary_outcome = decisions[0]
    elif top_actions:
        primary_outcome = top_actions[0]["action"]

    doc: Dict[str, Any] = {
        "meeting_title": title,
        "project": project_name,
        "meeting_type": meeting_type,
        "date_time": f"{date} {time_start}–{time_end}".strip() if date or time_start or time_end else "",
        "duration_minutes": duration_minutes,
        "classification": "Internal",
        "facilitated_by": "",
        "prepared_by": "DN-Studio AI",
        "attendees": attendee_names,
        "absent": [],
        "executive_summary": {
            "primary_outcome": primary_outcome,
            "critical_decisions": decisions,
            "top_actions": top_actions,
            "blockers": blockers,
        },
    }

    return doc


def generate_mom(
    transcript_path: str,
    output_dir: str,
    context: str = "",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full MoM generation pipeline:
    1. Load transcript + mom_system_prompt.json
    2. Call Gemini LLM to get structured MoM JSON
    3. Attach trace objects using source_utterance_ids
    4. Save response_mom.json + response_mom_trace.json
    5. Derive a compact MoM doc JSON and MoM.md for export

    Returns dict with keys: ok, mom_md, mom_json_path, mom_trace_path, error
    """

    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import SystemMessage, HumanMessage
    from .generalised_mom_generator import build_markdown

    llm_cfg = _load_llm_config()
    model = llm_cfg.get("model", "models/gemini-2.5-flash")
    if model.startswith("models/"):
        model = model[len("models/") :]
    temperature = llm_cfg.get("temperature", 0)
    max_tokens = llm_cfg.get("max_output_tokens", 65536)

    transcript = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
    if not transcript:
        return {"ok": False, "error": "Transcript is empty"}

    mom_prompt = json.loads(MOM_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"))
    system_prompt_text = mom_prompt.get("system_prompt", "")
    schema_template = mom_prompt.get("schema_template", {})

    user_prompt = _build_user_prompt(transcript, context)
    user_payload = {
        "schema_template": schema_template,
        "transcript": user_prompt,
    }
    user_content = json.dumps(user_payload, ensure_ascii=False)

    messages = [
        SystemMessage(content=system_prompt_text),
        HumanMessage(content=user_content),
    ]

    log.info("[MOM-LLM] Calling %s (temp=%s, max_tokens=%s)", model, temperature, max_tokens)

    kwargs: Dict[str, Any] = {}
    if api_key:
        kwargs["google_api_key"] = api_key

    llm = ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        max_output_tokens=max_tokens,
        **kwargs,
    )

    ai_message = llm.invoke(messages)
    full_response = ai_message.content
    log.info("[MOM-LLM] Got response (%d chars)", len(full_response))

    cleaned = _extract_json(full_response)
    try:
        mom_response = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.warning("[MOM-LLM] JSON parse error: %s — attempting recovery", e)
        depth = 0
        last_safe = 0
        in_string = False
        escape_next = False
        for idx_c, ch in enumerate(cleaned):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 1:
                    last_safe = idx_c
        if last_safe > 0:
            recovered = cleaned[: last_safe + 1] + "\n}"
            mom_response = json.loads(recovered)
            log.info("[MOM-LLM] Recovered %d top-level keys from truncated JSON", len(mom_response))
        else:
            return {"ok": False, "error": f"JSON parse failed: {e}"}

    # Attach trace objects based on source_utterance_ids
    enriched = _enrich_traces_mom(mom_response, transcript)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    mom_json_path = out / "response_mom.json"
    mom_json_path.write_text(json.dumps(mom_response, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("[MOM-LLM] Saved → %s", mom_json_path)

    mom_trace_path = out / "response_mom_trace.json"
    mom_trace_path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("[MOM-LLM] Saved → %s", mom_trace_path)

    # Derive compact doc JSON for the MoM view / exports.
    # We keep JSON on disk as the single source of truth and avoid
    # persisting markdown files – the frontend can always render
    # a view from this JSON when needed.
    doc_json = _build_mom_doc_json(enriched)
    minutes_dir = out / "minutes"
    minutes_dir.mkdir(parents=True, exist_ok=True)

    mom_doc_json_path = minutes_dir / "MoM.json"
    mom_doc_json_path.write_text(json.dumps(doc_json, indent=2, ensure_ascii=False), encoding="utf-8")

    mom_md = build_markdown(doc_json)

    return {
        "ok": True,
        "mom_md": mom_md,
        "mom_json_path": str(mom_json_path),
        "mom_trace_path": str(mom_trace_path),
        "mom_doc_path": str(mom_doc_json_path),
    }

