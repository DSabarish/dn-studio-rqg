#!/usr/bin/env python3
"""
MOM Documentation Generator

Standalone version of the notebook's generalised MoM generator:
reads a structured MoM JSON and emits Markdown/PDF/DOCX.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict


def load_json(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def v(node: Any) -> Any:
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


def build_markdown(data: Dict[str, Any]) -> str:
    # Truncated version of the rich markdown builder from the notebook.
    # Keeps the core structure while staying maintainable.
    lines: list[str] = []

    title = v(data.get("meeting_title", "Minutes of Meeting"))
    project = v(data.get("project")) or "—"
    mtype = v(data.get("meeting_type")) or "—"
    date = v(data.get("date_time")) or "—"
    duration = v(data.get("duration_minutes"))
    classification = v(data.get("classification")) or "Internal"
    facilitated_by = v(data.get("facilitated_by")) or "—"
    prepared_by = v(data.get("prepared_by")) or "—"
    attendees = ", ".join(v(data.get("attendees", []))) or "—"
    absent = ", ".join(v(data.get("absent", []))) or "—"

    lines += [
        "# Minutes of Meeting",
        f"## {title}",
        "",
        "---",
        "",
        "| Field | Details |",
        "|---|---|",
        f"| **Project** | {project} |",
        f"| **Meeting Type** | {mtype} |",
        f"| **Date/Time** | {date} |",
        f"| **Duration** | {duration} minutes |" if duration else "| **Duration** | — |",
        f"| **Classification** | {classification} |",
        f"| **Facilitated By** | {facilitated_by} |",
        f"| **Prepared By** | {prepared_by} |",
        f"| **Attendees** | {attendees} |",
        f"| **Absent** | {absent} |",
        "",
        "---",
        "",
    ]

    es = data.get("executive_summary", {})
    primary = v(es.get("primary_outcome", "")) if es else ""
    crit_decisions = v(es.get("critical_decisions", [])) if es else []
    top_actions = v(es.get("top_actions", [])) if es else []
    blockers = v(es.get("blockers", [])) if es else []

    lines += ["## Executive Summary", ""]
    if primary:
        lines += [f"**Primary Outcome:** {primary}", ""]
    if crit_decisions:
        lines += ["### Critical Decisions", ""]
        for d in crit_decisions:
            lines.append(f"- {d}")
        lines.append("")
    if top_actions:
        lines += ["### Top Action Items", "", "| Action | Owner | Due |", "|---|---|---|"]
        for a in top_actions:
            lines.append(
                f"| {a.get('action','')} | {a.get('owner','—')} | {a.get('due','—')} |"
            )
        lines.append("")
    lines += [
        f"**Blockers:** {'None' if not blockers else '; '.join(blockers)}",
        "",
        "---",
        "",
    ]

    prepared_by = prepared_by or "DN-Studio AI"
    lines.append(f"*Prepared by {prepared_by} | Classification: {classification}*")
    return "\n".join(lines)


def build_pdf(data: Dict[str, Any], output_path: str) -> None:
    # Import lazily so the CLI can still run without reportlab installed
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    doc = SimpleDocTemplate(output_path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [Paragraph(build_markdown(data).replace("\n", "<br/>"), styles["Normal"])]
    doc.build(story)
    print(f"  PDF saved → {output_path}")


def build_docx(data: Dict[str, Any], output_path: str) -> None:
    from docx import Document  # type: ignore[import]

    doc = Document()
    md = build_markdown(data)
    for line in md.splitlines():
        doc.add_paragraph(line)
    doc.save(output_path)
    print(f"  DOCX saved → {output_path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate Minutes of Meeting artifacts from structured JSON."
    )
    parser.add_argument(
        "input", help="Path to MoM JSON produced by the LLM pipeline"
    )
    parser.add_argument(
        "--output-dir", "-o", default="outputs/gcs/mom", help="Output directory"
    )
    parser.add_argument(
        "--formats",
        default="md,pdf,docx",
        help="Comma-separated list of formats: md,pdf,docx",
    )
    args = parser.parse_args(argv)

    input_path = args.input
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    formats = {f.strip().lower() for f in args.formats.split(",")}
    valid = {"pdf", "docx", "md"}
    unknown = formats - valid
    if unknown:
        parser.error(
            f"Unknown format(s): {', '.join(sorted(unknown))}. "
            f"Choose from: {', '.join(sorted(valid))}"
        )

    print(f"\nLoading: {input_path}")
    data = load_json(input_path)

    if "md" in formats:
        md_path = out / "minutes_of_meeting.md"
        md_content = build_markdown(data)
        md_path.write_text(md_content, encoding="utf-8")
        print(f"  MD   saved → {md_path}")

    if "pdf" in formats:
        pdf_path = str(out / "minutes_of_meeting.pdf")
        build_pdf(data, pdf_path)

    if "docx" in formats:
        docx_path = str(out / "minutes_of_meeting.docx")
        build_docx(data, docx_path)

    print(f"\nAll files written to: {out.resolve()}\n")


if __name__ == "__main__":
    main()


