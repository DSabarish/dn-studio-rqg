"""
BRD LLM Generator — Stages 1-3 consolidated.

Stage 1: Convert diarization transcript.json → user prompt with context/speaker_map
Stage 2: Call Gemini via LangChain to generate structured BRD JSON
Stage 3: Enrich trace objects with transcript text
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT_PATH = PROJECT_ROOT / "prompts" / "brd_system_prompt.json"


def _load_llm_config() -> Dict[str, Any]:
    import yaml
    cfg_path = PROJECT_ROOT / "cfg" / "config.yaml"
    with cfg_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("llm", {})


def _build_user_prompt(transcript: List[Dict], context: str) -> Dict[str, Any]:
    unique_speakers = sorted(set(u.get("speaker_id", u.get("speaker_name", "UNKNOWN")) for u in transcript))
    speaker_map = {sid: sid for sid in unique_speakers}
    return {
        "context": context or "Requirements-gathering meeting.",
        "speaker_map": speaker_map,
        "transcript": transcript,
    }


ENFORCEMENT_CHECKLIST = """
=== FINAL ENFORCEMENT CHECKLIST ===
Before outputting JSON, verify every item below is addressed:

[HEADER]
  ✓ Version = '1.0 Draft'
  ✓ Date = today's date
  ✓ Document Status = 'Draft'
  ✓ Project Type = classified type (NOT the project name)

[DOCUMENT REVISIONS]
  ✓ items = [{Version,Date,Author,Description}] — NOT empty

[STAKEHOLDER APPROVALS]
  ✓ items includes any named stakeholders with Status='Pending Approval'

[SUCCESS CRITERIA]
  ✓ Minimum 5 binary pass/fail test statements — NOT feature descriptions

[OBJECTIVES]
  ✓ Primary = Phase 1 goals ONLY
  ✓ Secondary = Phase 2+ goals
  ✓ NEVER output ['description','format','value'] as array content

[BUSINESS DRIVERS]
  ✓ Minimum 4 specific noun phrases — NOT generic one-liners

[RISKS]
  ✓ Minimum 3 Risk/Mitigation pairs as flat array: [{Risk,Mitigation},...]

[KPIs]
  ✓ Minimum 4 Metric/Target pairs as flat array: [{Metric,Target},...]

[FUNCTIONAL REQUIREMENTS]
  ✓ Populate all module sections with requirements from the transcript
  ✓ Use placeholder 'TBD' for modules not discussed

[NFR]
  ✓ 7.2 Availability: minimum 2 items
  ✓ 7.4 Security: minimum 3 items

[DATA GOVERNANCE — NEVER LEAVE BLANK]
  ✓ 8.1 Data Classification: object mapping data assets to sensitivity levels
  ✓ 8.2 Privacy Checklist: minimum 5 items

[ARCHITECTURE]
  ✓ 9.2 Flow: array of 'ComponentA → ComponentB' strings

[APPENDICES]
  ✓ 10.1 Glossary: object with at least 5 term definitions
  ✓ 10.2 Acronyms: array with relevant acronyms
  ✓ 10.3 Related Documents: array with at least 1 entry
  ✓ 10.4 Sign-Off: items = [{Name,Role,Date,Signature}] — NOT empty

[OUTPUT FORMAT]
  ✓ Start with { end with }. Zero prose. Zero markdown fences.
  ✓ All items arrays = flat [{key:val},...] NOT {key:{value:val}}
  ✓ Complete the ENTIRE JSON — do NOT truncate.
=== END CHECKLIST ===
"""


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


def _flatten_items(obj: Any) -> Any:
    if isinstance(obj, dict):
        if list(obj.keys()) == ["value"]:
            return obj["value"]
        if "value" in obj and "description" in obj and len(obj) == 2:
            return obj["value"]
        return {k: _flatten_items(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_flatten_items(i) for i in obj]
    return obj


def _normalize_trace_list(trace_data: Any) -> List[Dict]:
    if trace_data is None:
        return []
    if isinstance(trace_data, list):
        return trace_data
    if isinstance(trace_data, dict):
        return [trace_data]
    return []


def _enrich_traces(brd: Dict, transcript: List[Dict]) -> Dict:
    lookup = {}
    for u in transcript:
        uid = u.get("utterance_id")
        if uid is not None:
            lookup[uid] = {
                "text": u.get("text", ""),
                "speaker": u.get("speaker_name", u.get("speaker_id", "")),
                "start": u.get("start", 0),
                "end": u.get("end", 0),
            }

    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            if "trace" in obj and obj["trace"] is not None:
                trace_list = _normalize_trace_list(obj["trace"])
                for t in trace_list:
                    uid = t.get("utterance_id")
                    if uid is not None and uid in lookup:
                        t["text"] = lookup[uid]["text"]
                        t["start"] = lookup[uid]["start"]
                        t["end"] = lookup[uid]["end"]
                if isinstance(obj["trace"], list):
                    obj["trace"] = trace_list
                elif isinstance(obj["trace"], dict) and trace_list:
                    obj["trace"] = trace_list[0]
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
        return obj

    return _walk(brd)


def _brd_to_markdown(brd: Dict) -> str:
    lines = ["# Business Requirements Document\n"]

    def _val(obj, *keys):
        cur = obj
        for k in keys:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(k, {})
        if isinstance(cur, dict):
            return cur.get("value")
        return cur

    def _items_list(obj, key):
        section = obj.get(key, {})
        if isinstance(section, dict):
            return section.get("items", [])
        return []

    header = brd.get("Header", {})
    lines.append(f"**Project:** {_val(header, 'Project Name') or 'TBD'}")
    lines.append(f"**Version:** {_val(header, 'Version') or 'TBD'}")
    lines.append(f"**Date:** {_val(header, 'Date') or 'TBD'}")
    lines.append(f"**Status:** {_val(header, 'Document Status') or 'Draft'}\n")

    pd = brd.get("0. Project Details", {})
    overview = _val(pd, "Project Overview")
    if overview:
        lines.append("## Project Overview\n")
        lines.append(f"{overview}\n")

    need = _val(pd, "Business Need")
    if need:
        lines.append("## Business Need\n")
        lines.append(f"{need}\n")

    sc = _val(pd, "Success Criteria")
    if isinstance(sc, list) and sc:
        lines.append("## Success Criteria\n")
        for c in sc:
            lines.append(f"- {c}")
        lines.append("")

    intro = brd.get("1. Introduction", {})
    summary = _val(intro, "1.1 Project Summary")
    if summary:
        lines.append("## 1.1 Project Summary\n")
        lines.append(f"{summary}\n")

    obj_items = intro.get("1.2 Objectives", {}).get("items", {})
    primary = _val(obj_items, "Primary") or []
    secondary = _val(obj_items, "Secondary") or []
    if primary or secondary:
        lines.append("## 1.2 Objectives\n")
        if primary:
            lines.append("### Primary")
            for o in (primary if isinstance(primary, list) else [primary]):
                lines.append(f"- {o}")
        if secondary:
            lines.append("\n### Secondary")
            for o in (secondary if isinstance(secondary, list) else [secondary]):
                lines.append(f"- {o}")
        lines.append("")

    scope = brd.get("2. Project Scope", {})
    in_scope = _val(scope, "2.1 In-Scope Functionality")
    if isinstance(in_scope, list) and in_scope:
        lines.append("## 2.1 In-Scope\n")
        for s in in_scope:
            lines.append(f"- {s}")
        lines.append("")

    out_scope = _val(scope, "2.2 Out-of-Scope Functionality")
    if isinstance(out_scope, list) and out_scope:
        lines.append("## 2.2 Out-of-Scope\n")
        for s in out_scope:
            lines.append(f"- {s}")
        lines.append("")

    fr = brd.get("6. Functional Requirements", {})
    fr_found = False
    for key in sorted(k for k in fr if k.startswith("6.")):
        reqs = _val(fr, key)
        if isinstance(reqs, list) and reqs:
            if not fr_found:
                lines.append("## 6. Functional Requirements\n")
                fr_found = True
            lines.append(f"### {key}\n")
            for i, r in enumerate(reqs, 1):
                lines.append(f"{i}. {r}")
            lines.append("")

    nfr = brd.get("7. Non-Functional Requirements", {})
    nfr_found = False
    for key in sorted(nfr.keys()):
        val = _val(nfr, key)
        if isinstance(val, list) and val:
            if not nfr_found:
                lines.append("## 7. Non-Functional Requirements\n")
                nfr_found = True
            lines.append(f"### {key}\n")
            for item in val:
                lines.append(f"- {item}")
            lines.append("")

    return "\n".join(lines)


def generate_brd(
    transcript_path: str,
    output_dir: str,
    context: str = "",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full BRD generation pipeline:
    1. Load transcript + system prompt
    2. Call Gemini LLM
    3. Parse + flatten JSON response
    4. Enrich traces with transcript text
    5. Save response_brd.json + response_brd_trace.json

    Returns dict with keys: ok, brd_json_path, brd_trace_path, error
    """
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import SystemMessage, HumanMessage

    llm_cfg = _load_llm_config()
    model = llm_cfg.get("model", "models/gemini-2.5-flash")
    if model.startswith("models/"):
        model = model[len("models/"):]
    temperature = llm_cfg.get("temperature", 0)
    max_tokens = llm_cfg.get("max_output_tokens", 65536)

    transcript = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
    if not transcript:
        return {"ok": False, "error": "Transcript is empty"}

    system_prompt_text = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    user_prompt = _build_user_prompt(transcript, context)

    user_content = (
        "TRANSCRIPT:\n"
        + json.dumps(user_prompt, ensure_ascii=False)
        + "\n\n"
        + ENFORCEMENT_CHECKLIST
    )

    messages = [
        SystemMessage(content=system_prompt_text),
        HumanMessage(content=user_content),
    ]

    log.info("[BRD-LLM] Calling %s (temp=%s, max_tokens=%s)", model, temperature, max_tokens)

    kwargs = {}
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
    log.info("[BRD-LLM] Got response (%d chars)", len(full_response))

    cleaned = _extract_json(full_response)
    try:
        brd_response = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.warning("[BRD-LLM] JSON parse error: %s — attempting recovery", e)
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
            brd_response = json.loads(recovered)
            log.info("[BRD-LLM] Recovered %d sections from truncated JSON", len(brd_response))
        else:
            return {"ok": False, "error": f"JSON parse failed: {e}"}

    brd_response = _flatten_items(brd_response)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Save the raw BRD JSON emitted by the LLM
    brd_json_path = out / "response_brd.json"
    brd_json_path.write_text(
        json.dumps(brd_response, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("[BRD-LLM] Saved → %s", brd_json_path)

    # Enrich trace objects with transcript text and save a trace JSON
    enriched = _enrich_traces(brd_response, transcript)
    brd_trace_path = out / "response_brd_trace.json"
    brd_trace_path.write_text(
        json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("[BRD-LLM] Saved → %s", brd_trace_path)

    # Derive a lightweight markdown BRD for the dashboard editor / exports
    # without persisting markdown files. The structured JSON remains the
    # source of truth on disk.
    brd_md = _brd_to_markdown(enriched)

    return {
        "ok": True,
        "brd_json_path": str(brd_json_path),
        "brd_trace_path": str(brd_trace_path),
        "brd_md": brd_md,
        "brd_md_path": "",
    }
