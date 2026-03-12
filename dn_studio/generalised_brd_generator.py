#!/usr/bin/env python3
"""
generalised_brd_generator.py (FIXED v2)
-----------------------------------------
Root-cause fixes vs previous versions:

1. Objectives (Primary/Secondary) were EMPTY:
   The JSON structure for "1.2 Objectives" uses an "items" key (not "value").
   Fix: extract obj_items = I["1.2 Objectives"].get("items", {})
        then vlist(obj_items, "Primary") and vlist(obj_items, "Secondary").

2. Phasing Plan table was EMPTY:
   Same pattern — "2.3 Phasing Plan" uses "items" not "value".
   Fix: raw_phases = S["2.3 Phasing Plan"].get("items", {})

3. Document Revisions were EMPTY:
   "0. Document Revisions" uses "items" list not a top-level array.
   Fix: raw_revisions = DR.get("items", [])

4. Stakeholder Approvals were EMPTY:
   Same — "0. Stakeholder Approvals" uses "items" list.
   Fix: raw_approvals = SA.get("items", [])

5. KPIs were EMPTY:
   "5. KPI & Success Metrics" uses "items" list.
   Fix: raw_kpis = KP.get("items", [])

6. Risks were EMPTY:
   "3.3 Risks" uses "items" list.
   Fix: raw_risks = SP["3.3 Risks"].get("items", [])

7. Sign-Off:
   "10.4 Document Sign-Off" value is a plain dict array (no .value wrapper
   on Name/Role/Date/Signature).
   Fix: s.get("Name") not v(s, "Name").

8. All body() and bullet() paragraphs now use AlignmentType.JUSTIFIED.

9. Section 9.2 replaced with a grey placeholder box.

10. Empty page between sections 7 and 8:
    removed the trailing sp(80) after the last NFR sub-section before the PageBreak.
"""

import json
import sys
import subprocess
import argparse
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def v(obj, *keys, default="TBD"):
    """Traverse nested dict by keys and return the innermost .value, or default."""
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, {})
    if isinstance(cur, dict):
        val = cur.get("value", None)
    else:
        val = cur
    if val is None or val == "" or val == []:
        return default
    return val


def vlist(obj, *keys, default=None):
    """Like v() but always returns a list."""
    result = v(obj, *keys, default=default if default is not None else [])
    if isinstance(result, list):
        return result
    if result == "TBD":
        return []
    return [str(result)]


def vdict(obj, *keys, default=None):
    """Like v() but always returns a dict."""
    result = v(obj, *keys, default=default if default is not None else {})
    if isinstance(result, dict):
        return result
    return {}


def safe_str(val, default="TBD"):
    if val is None or val == "" or (isinstance(val, list) and len(val) == 0):
        return default
    if isinstance(val, list):
        return "; ".join(str(x) for x in val)
    return str(val)


def js_str(s):
    if s is None:
        s = "TBD"
    s = str(s)
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("\n", " ")
    s = s.replace("\r", "")
    return s


# ---------------------------------------------------------------------------
# Parse JSON
# ---------------------------------------------------------------------------
def parse_brd(data: dict) -> dict:
    H  = data.get("Header", {})
    P  = data.get("0. Project Details", {})
    DR = data.get("0. Document Revisions", {})
    SA = data.get("0. Stakeholder Approvals", {})
    I  = data.get("1. Introduction", {})
    S  = data.get("2. Project Scope", {})
    SP = data.get("3. System Perspective", {})
    BP = data.get("4. Business Process Overview", {})
    KP = data.get("5. KPI & Success Metrics", {})
    FR = data.get("6. Functional Requirements", {})
    NF = data.get("7. Non-Functional Requirements", {})
    DG = data.get("8. Data Governance & Privacy", {})
    TA = data.get("9. Technology Stack & Architecture", {})
    AP = data.get("10. Appendices", {})

    ctx = {}

    # ── Header ─────────────────────────────────────────────────────────────
    ctx["project_name"]  = safe_str(v(H, "Project Name"))
    ctx["version"]       = safe_str(v(H, "Version"))
    ctx["date"]          = safe_str(v(H, "Date"))
    ctx["business_unit"] = safe_str(v(H, "Business Unit"))
    ctx["project_type"]  = safe_str(v(H, "Project Type"))
    ctx["deployment"]    = safe_str(v(H, "Deployment Model"))
    ctx["data_store"]    = safe_str(v(H, "Primary Data Store"))
    ctx["compute"]       = safe_str(v(H, "Compute Engine"))
    ctx["infrastructure"]= safe_str(v(H, "Infrastructure"))
    ctx["doc_status"]    = safe_str(v(H, "Document Status"))

    # ── Project Details ─────────────────────────────────────────────────────
    ctx["overview"]          = safe_str(v(P, "Project Overview"))
    ctx["business_need"]     = safe_str(v(P, "Business Need"))
    ctx["success_criteria"]  = vlist(P, "Success Criteria")

    # ── Document Revisions (FIX 3) ──────────────────────────────────────────
    raw_revisions = DR.get("items", [])
    ctx["revisions"] = []
    for r in raw_revisions:
        if isinstance(r, dict):
            ctx["revisions"].append({
                "version": safe_str(v(r, "Version")),
                "date":    safe_str(v(r, "Date")),
                "author":  safe_str(v(r, "Author")),
                "desc":    safe_str(v(r, "Description")),
            })

    # ── Stakeholder Approvals (FIX 4) ───────────────────────────────────────
    raw_approvals = SA.get("items", [])
    ctx["approvals"] = []
    for a in raw_approvals:
        if isinstance(a, dict):
            ctx["approvals"].append({
                "name":   safe_str(v(a, "Name")),
                "role":   safe_str(v(a, "Role")),
                "status": safe_str(v(a, "Status")),
            })

    # ── Introduction ────────────────────────────────────────────────────────
    ctx["project_summary"] = safe_str(v(I, "1.1 Project Summary"))

    # FIX 1: "1.2 Objectives" has "items" dict with Primary/Secondary inside
    obj_items = I.get("1.2 Objectives", {}).get("items", {})
    ctx["obj_primary"]   = vlist(obj_items, "Primary")
    ctx["obj_secondary"] = vlist(obj_items, "Secondary")

    ctx["background"]       = safe_str(v(I, "1.3 Background & Business Context"))
    ctx["business_drivers"]  = vlist(I, "1.4 Business Drivers")

    # ── Scope ───────────────────────────────────────────────────────────────
    ctx["in_scope"]  = vlist(S, "2.1 In-Scope Functionality")
    ctx["out_scope"] = vlist(S, "2.2 Out-of-Scope Functionality")

    # FIX 2: "2.3 Phasing Plan" has "items" dict
    raw_phases = S.get("2.3 Phasing Plan", {}).get("items", {})
    ctx["phases"] = []
    for phase_key in sorted(raw_phases.keys()):
        phase_obj = raw_phases[phase_key]
        phase_val = safe_str(phase_obj.get("value", "TBD")) if isinstance(phase_obj, dict) else safe_str(phase_obj)
        focus = phase_val.split("Module")[0].strip().split("of the ")[-1].strip() if "Module" in phase_val else phase_key
        ctx["phases"].append([phase_key, focus, phase_val])

    # ── System Perspective ──────────────────────────────────────────────────
    ctx["assumptions"] = vlist(SP, "3.1 Assumptions")
    ctx["constraints"] = vlist(SP, "3.2 Constraints")

    # FIX 6: "3.3 Risks" has "items" list
    raw_risks = SP.get("3.3 Risks", {}).get("items", [])
    ctx["risks"] = []
    for r in raw_risks:
        if isinstance(r, dict):
            ctx["risks"].append([
                safe_str(v(r, "Risk")),
                safe_str(v(r, "Mitigation")),
            ])

    # ── Business Process ────────────────────────────────────────────────────
    ctx["as_is"] = vlist(BP, "4.1 Current Process (As-Is)")
    ctx["to_be"] = vlist(BP, "4.2 Proposed Process (To-Be)")

    # ── KPIs (FIX 5) ───────────────────────────────────────────────────────
    raw_kpis = KP.get("items", [])
    ctx["kpis"] = []
    for k in raw_kpis:
        if isinstance(k, dict):
            ctx["kpis"].append([
                safe_str(v(k, "Metric")),
                safe_str(v(k, "Target")),
            ])

    # ── Functional Requirements ─────────────────────────────────────────────
    ctx["fr_sections"] = []
    for sec_key in sorted(fr_key for fr_key in FR.keys() if fr_key.startswith("6.")):
        sec_obj = FR[sec_key]
        reqs = []
        raw_reqs = v(sec_obj, default=[])
        if isinstance(raw_reqs, list):
            for idx, req in enumerate(raw_reqs, 1):
                sec_num = sec_key.split(".")[1] if "." in sec_key else "X"
                prefix_map = {"1": "STU", "2": "PAR", "3": "TCH", "4": "ADM", "5": "MGT", "6": "GEN"}
                prefix = prefix_map.get(sec_num, "REQ")
                req_id = f"{prefix}-{idx:03d}"
                req_str = str(req)
                priority = "P1"
                for tag in ["P1", "P2", "P3"]:
                    if f"({tag}" in req_str:
                        priority = tag
                        break
                clean = req_str.replace(f" ({priority})", "").replace(f"({priority})", "").strip()
                clean = clean.rstrip(".")
                reqs.append([req_id, clean, priority])
        ctx["fr_sections"].append({
            "title": sec_key,
            "key": sec_key,
            "reqs": reqs,
        })

    # ── Non-Functional Requirements ─────────────────────────────────────────
    ctx["nfr_perf"]       = vlist(NF, "7.1 Performance & Scalability")
    ctx["nfr_avail"]      = vlist(NF, "7.2 Availability & Reliability")
    ctx["nfr_usab"]       = vlist(NF, "7.3 Usability & Accessibility")
    ctx["nfr_sec"]        = vlist(NF, "7.4 Security & Access Control")
    ctx["nfr_compliance"] = vlist(NF, "7.5 Compliance & Regulatory")

    # ── Data Governance ─────────────────────────────────────────────────────
    raw_dc = vdict(DG, "8.1 Data Classification")
    ctx["data_classification"] = [[k, safe_str(vv)] for k, vv in raw_dc.items()] if raw_dc else []
    ctx["privacy_checklist"] = vlist(DG, "8.2 Data Privacy Checklist")

    # ── Tech Stack ──────────────────────────────────────────────────────────
    raw_ts = vdict(TA, "9.1 Proposed Technology Stack")
    ctx["tech_stack"] = [[k, safe_str(vv)] for k, vv in raw_ts.items()] if raw_ts else []

    # ── Appendices ──────────────────────────────────────────────────────────
    raw_glossary = vdict(AP, "10.1 Glossary of Terms")
    ctx["glossary"] = sorted([[k, safe_str(vv)] for k, vv in raw_glossary.items()]) if raw_glossary else []
    ctx["acronyms"] = vlist(AP, "10.2 List of Acronyms")
    ctx["related_docs"] = vlist(AP, "10.3 Related Documents")

    # FIX 7: "10.4 Document Sign-Off" is plain dicts (no .value wrapper)
    raw_signoff = AP.get("10.4 Document Sign-Off", {}).get("value", [])
    ctx["signoff"] = []
    for s in raw_signoff:
        if isinstance(s, dict):
            ctx["signoff"].append([
                safe_str(s.get("Name")),
                safe_str(s.get("Role")),
                safe_str(s.get("Date") or "________________"),
                safe_str(s.get("Signature") or "________________"),
            ])

    return ctx


# ---------------------------------------------------------------------------
# Build Node.js generator script
# ---------------------------------------------------------------------------
def build_js(ctx: dict) -> str:
    def jsa(lst):
        items = [f'"{js_str(x)}"' for x in lst]
        return "[" + ", ".join(items) + "]"

    def jsa2(lst):
        items = [f'["{js_str(r[0])}", "{js_str(r[1])}"]' for r in lst]
        return "[" + ", ".join(items) + "]"

    def jsa3(lst):
        items = [f'["{js_str(r[0])}", "{js_str(r[1])}", "{js_str(r[2])}"]' for r in lst]
        return "[" + ", ".join(items) + "]"

    def jsa4(lst):
        items = [f'["{js_str(r[0])}", "{js_str(r[1])}", "{js_str(r[2])}", "{js_str(r[3])}"]' for r in lst]
        return "[" + ", ".join(items) + "]"

    fr_js_parts = []
    for sec in ctx["fr_sections"]:
        title_js = js_str(sec["key"])
        reqs_js  = jsa3(sec["reqs"])
        fr_js_parts.append(f'{{ title: "{title_js}", reqs: {reqs_js} }}')
    fr_sections_js = "[" + ",\n".join(fr_js_parts) + "]"

    rev_items = [f'["{js_str(r["version"])}", "{js_str(r["date"])}", "{js_str(r["author"])}", "{js_str(r["desc"])}"]' for r in ctx["revisions"]]
    revisions_js = "[" + ", ".join(rev_items) + "]"

    appr_items = [f'["{js_str(a["name"])}", "{js_str(a["role"])}", "{js_str(a["status"])}"]' for a in ctx["approvals"]]
    approvals_js = "[" + ", ".join(appr_items) + "]"

    script = f"""
const {{ Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, PageNumber, PageBreak, LevelFormat, TableOfContents,
  TabStopType, TabStopPosition }} = require('docx');
const fs = require('fs');

const D = {{
  projectName: "{js_str(ctx['project_name'])}",
  version: "{js_str(ctx['version'])}",
  date: "{js_str(ctx['date'])}",
  businessUnit: "{js_str(ctx['business_unit'])}",
  projectType: "{js_str(ctx['project_type'])}",
  deployment: "{js_str(ctx['deployment'])}",
  dataStore: "{js_str(ctx['data_store'])}",
  compute: "{js_str(ctx['compute'])}",
  infrastructure: "{js_str(ctx['infrastructure'])}",
  docStatus: "{js_str(ctx['doc_status'])}",
  overview: "{js_str(ctx['overview'])}",
  businessNeed: "{js_str(ctx['business_need'])}",
  successCriteria: {jsa(ctx['success_criteria'])},
  revisions: {revisions_js},
  approvals: {approvals_js},
  projectSummary: "{js_str(ctx['project_summary'])}",
  objPrimary: {jsa(ctx['obj_primary'])},
  objSecondary: {jsa(ctx['obj_secondary'])},
  background: "{js_str(ctx['background'])}",
  businessDrivers: {jsa(ctx['business_drivers'])},
  inScope: {jsa(ctx['in_scope'])},
  outScope: {jsa(ctx['out_scope'])},
  phases: {jsa3(ctx['phases'])},
  assumptions: {jsa(ctx['assumptions'])},
  constraints: {jsa(ctx['constraints'])},
  risks: {jsa2(ctx['risks'])},
  asIs: {jsa(ctx['as_is'])},
  toBe: {jsa(ctx['to_be'])},
  kpis: {jsa2(ctx['kpis'])},
  frSections: {fr_sections_js},
  nfrPerf: {jsa(ctx['nfr_perf'])},
  nfrAvail: {jsa(ctx['nfr_avail'])},
  nfrUsab: {jsa(ctx['nfr_usab'])},
  nfrSec: {jsa(ctx['nfr_sec'])},
  nfrCompliance: {jsa(ctx['nfr_compliance'])},
  dataClassification: {jsa2(ctx['data_classification'])},
  privacyChecklist: {jsa(ctx['privacy_checklist'])},
  techStack: {jsa2(ctx['tech_stack'])},
  glossary: {jsa2(ctx['glossary'])},
  acronyms: {jsa(ctx['acronyms'])},
  relatedDocs: {jsa(ctx['related_docs'])},
  signoff: {jsa4(ctx['signoff'])},
}};

const C = {{
  primary: "003366", accent: "0070C0", lightBlue: "D6E4F0",
  dark: "404040", mid: "666666", border: "CCCCCC",
  white: "FFFFFF", placeholder: "DDDDDD",
}};
const PW = 9360;

const bd = (c=C.border) => ({{ style: BorderStyle.SINGLE, size: 1, color: c }});
const bds = (c=C.border) => ({{ top:bd(c), bottom:bd(c), left:bd(c), right:bd(c) }});

function sp(n=100) {{
  return new Paragraph({{ spacing:{{before:n, after:0}}, children:[new TextRun("")] }});
}}

function divider(color=C.accent) {{
  return new Paragraph({{
    border: {{ bottom: {{ style:BorderStyle.SINGLE, size:12, color, space:1 }} }},
    spacing: {{ before:0, after:200 }},
    children: [new TextRun("")]
  }});
}}

function h1(text, pageBreak=true) {{
  return new Paragraph({{
    heading: HeadingLevel.HEADING_1, pageBreakBefore: pageBreak,
    children: [new TextRun({{ text, bold:true, color:C.primary }})],
    spacing: {{ before:200, after:120 }}
  }});
}}

function h2(text) {{
  return new Paragraph({{
    heading: HeadingLevel.HEADING_2,
    children: [new TextRun({{ text, bold:true, color:C.accent }})],
    spacing: {{ before:280, after:100 }}
  }});
}}

function h3(text) {{
  return new Paragraph({{
    heading: HeadingLevel.HEADING_3,
    children: [new TextRun({{ text, bold:true, color:C.dark, size:22 }})],
    spacing: {{ before:200, after:80 }}
  }});
}}

function body(text, {{bold=false, italic=false, color=C.dark, size=22}}={{}}) {{
  return new Paragraph({{
    alignment: AlignmentType.JUSTIFIED,
    children: [new TextRun({{ text, bold, italic, color, size, font:"Arial" }})],
    spacing: {{ before:60, after:60 }}
  }});
}}

function bullet(text, ref) {{
  return new Paragraph({{
    numbering: {{ reference: ref || "b0", level:0 }},
    alignment: AlignmentType.JUSTIFIED,
    children: [new TextRun({{ text, size:22, color:C.dark, font:"Arial" }})],
    spacing: {{ before:40, after:40 }}
  }});
}}

function tbl(headers, rows, colWidths) {{
  const total = colWidths.reduce((a,b)=>a+b, 0);
  const hrow = new TableRow({{
    children: headers.map((h,i) => new TableCell({{
      borders: bds(), width: {{ size:colWidths[i], type:WidthType.DXA }},
      shading: {{ fill:C.primary, type:ShadingType.CLEAR }},
      margins: {{ top:100, bottom:100, left:150, right:150 }},
      children:[new Paragraph({{ children:[new TextRun({{text:h, bold:true, size:20, color:C.white, font:"Arial"}})] }})]
    }}))
  }});
  const drows = rows.map(row => new TableRow({{
    children: row.map((cell,i) => new TableCell({{
      borders: bds(), width: {{ size:colWidths[i], type:WidthType.DXA }},
      margins: {{ top:80, bottom:80, left:150, right:150 }},
      children:[new Paragraph({{ alignment: AlignmentType.JUSTIFIED,
        children:[new TextRun({{text:cell||"—", size:20, color:C.dark, font:"Arial"}})] }})]
    }}))
  }}));
  return new Table({{ width:{{size:total, type:WidthType.DXA}}, columnWidths:colWidths, rows:[hrow,...drows] }});
}}

function kvTable(data) {{
  const rows = data.map(([k,val]) => new TableRow({{
    children:[
      new TableCell({{ borders:bds(), width:{{size:2400, type:WidthType.DXA}},
        shading:{{fill:C.lightBlue, type:ShadingType.CLEAR}},
        margins:{{top:100, bottom:100, left:150, right:150}},
        children:[new Paragraph({{children:[new TextRun({{text:k, bold:true, size:20, color:C.primary, font:"Arial"}})]}})]
      }}),
      new TableCell({{ borders:bds(), width:{{size:6960, type:WidthType.DXA}},
        margins:{{top:100, bottom:100, left:150, right:150}},
        children:[new Paragraph({{children:[new TextRun({{text:val, size:20, color:C.dark, font:"Arial"}})]}})]
      }}),
    ]
  }}));
  return new Table({{ width:{{size:PW, type:WidthType.DXA}}, columnWidths:[2400,6960], rows }});
}}

function archPlaceholder() {{
  const cell = new TableCell({{
    borders: bds(C.placeholder), width: {{ size:PW, type:WidthType.DXA }},
    shading: {{ fill:C.placeholder, type:ShadingType.CLEAR }},
    margins: {{ top:800, bottom:800, left:300, right:300 }},
    children:[
      new Paragraph({{ alignment: AlignmentType.CENTER, spacing: {{ before:0, after:160 }},
        children:[new TextRun({{text:"[ Attach Architecture Data Flow Diagram ]", bold:true, size:24, color:"888888", font:"Arial", italics:true}})]
      }}),
      new Paragraph({{ alignment: AlignmentType.CENTER,
        children:[new TextRun({{text:"Replace this placeholder with the finalised diagram before distributing this document.", size:18, color:"999999", font:"Arial", italics:true}})]
      }})
    ]
  }});
  return new Table({{ width:{{size:PW, type:WidthType.DXA}}, columnWidths:[PW], rows:[new TableRow({{children:[cell]}})] }});
}}

const bulletRefs = ["b0","b1","b2","b3","b4","b5","b6","b7","b8","b9",
  "b10","b11","b12","b13","b14","b15","b16","b17","b18","b19"];
const numberingConfig = bulletRefs.map(ref => ({{
  reference: ref,
  levels:[{{ level:0, format:LevelFormat.BULLET, text:"\\u2022", alignment:AlignmentType.LEFT,
    style:{{ paragraph:{{ indent:{{ left:540, hanging:300 }} }} }}
  }}]
}}));

const ch = [];

// COVER
ch.push(new Paragraph({{ spacing:{{before:1800,after:0}}, children:[new TextRun("")] }}));
ch.push(new Paragraph({{ alignment:AlignmentType.CENTER,
  children:[new TextRun({{text:"BUSINESS REQUIREMENTS DOCUMENT", bold:true, size:52, color:C.primary, font:"Arial"}})]
}}));
ch.push(sp(200));
ch.push(new Paragraph({{ alignment:AlignmentType.CENTER,
  children:[new TextRun({{text:D.projectName, bold:true, size:40, color:C.accent, font:"Arial"}})]
}}));
ch.push(sp(300));
ch.push(new Paragraph({{ alignment:AlignmentType.CENTER,
  border:{{bottom:{{style:BorderStyle.SINGLE,size:6,color:C.accent,space:1}}}},
  children:[new TextRun("")]
}}));
ch.push(sp(200));
[["Prepared for",D.businessUnit],["Version",D.version],["Date",D.date],["Document Status",D.docStatus]].forEach(([k,val])=>{{
  ch.push(new Paragraph({{ alignment:AlignmentType.CENTER, spacing:{{before:80,after:80}},
    children:[new TextRun({{text:k+": ",bold:true,size:22,color:C.mid,font:"Arial"}}),new TextRun({{text:val,size:22,color:C.dark,font:"Arial"}})]
  }}));
}});
ch.push(new Paragraph({{children:[new PageBreak()]}}));

// TOC
ch.push(h1("Table of Contents", false));
ch.push(divider());
ch.push(new TableOfContents("Table of Contents", {{hyperlink:true, headingStyleRange:"1-3"}}));
ch.push(new Paragraph({{children:[new PageBreak()]}}));

// DOCUMENT CONTROL
ch.push(h1("Document Control", false));
ch.push(divider());
ch.push(h3("Document Information"));
ch.push(sp(60));
ch.push(kvTable([
  ["Project Name",D.projectName],["Version",D.version],["Date",D.date],
  ["Business Unit",D.businessUnit],["Project Type",D.projectType],
  ["Deployment",D.deployment],["Data Store",D.dataStore],
  ["Compute Engine",D.compute],["Infrastructure",D.infrastructure],["Document Status",D.docStatus],
]));
ch.push(sp(200));
ch.push(h3("Document Revisions"));
ch.push(sp(60));
if (D.revisions.length > 0) {{
  ch.push(tbl(["Version","Date","Author","Description"], D.revisions, [900,1500,1800,5160]));
}} else {{
  ch.push(body("No revisions recorded.", {{italic:true, color:C.mid}}));
}}
ch.push(sp(200));
ch.push(h3("Stakeholder Approvals"));
ch.push(sp(60));
if (D.approvals.length > 0) {{
  ch.push(tbl(["Name","Role","Status"], D.approvals, [2400,4560,2400]));
}} else {{
  ch.push(body("No stakeholder approvals recorded.", {{italic:true, color:C.mid}}));
}}

// SECTION 1
ch.push(h1("1. Introduction"));
ch.push(divider());
ch.push(h2("1.1 Project Summary"));
ch.push(body(D.projectSummary));
ch.push(sp(120));
ch.push(h2("1.2 Objectives"));
ch.push(body("Primary Objectives", {{bold:true, color:C.primary}}));
if (D.objPrimary.length > 0) {{ D.objPrimary.forEach(x => ch.push(bullet(x, "b0"))); }}
else {{ ch.push(body("To be defined.", {{italic:true, color:C.mid}})); }}
ch.push(sp(80));
ch.push(body("Secondary Objectives", {{bold:true, color:C.accent}}));
if (D.objSecondary.length > 0) {{ D.objSecondary.forEach(x => ch.push(bullet(x, "b1"))); }}
else {{ ch.push(body("To be defined.", {{italic:true, color:C.mid}})); }}
ch.push(sp(120));
ch.push(h2("1.3 Background & Business Context"));
ch.push(body(D.background));
ch.push(sp(120));
ch.push(h2("1.4 Business Drivers"));
if (D.businessDrivers.length > 0) {{ D.businessDrivers.forEach(x => ch.push(bullet(x, "b2"))); }}
else {{ ch.push(body("To be defined.", {{italic:true, color:C.mid}})); }}

// SECTION 2
ch.push(h1("2. Project Scope"));
ch.push(divider());
ch.push(h2("2.1 In-Scope Functionality"));
if (D.inScope.length > 0) {{ D.inScope.forEach(x => ch.push(bullet(x,"b3"))); }}
else {{ ch.push(body("To be defined.", {{italic:true,color:C.mid}})); }}
ch.push(sp(120));
ch.push(h2("2.2 Out-of-Scope Functionality"));
if (D.outScope.length > 0) {{ D.outScope.forEach(x => ch.push(bullet(x,"b4"))); }}
else {{ ch.push(body("To be defined.", {{italic:true,color:C.mid}})); }}
ch.push(sp(120));
ch.push(h2("2.3 Phasing Plan"));
ch.push(sp(60));
if (D.phases.length > 0) {{
  ch.push(tbl(["Phase","Focus Area","Scope Description"], D.phases, [1000,1900,6460]));
}} else {{
  ch.push(body("Phasing plan to be defined.", {{italic:true, color:C.mid}}));
}}

// SECTION 3
ch.push(h1("3. System Perspective"));
ch.push(divider());
ch.push(h2("3.1 Assumptions"));
if (D.assumptions.length > 0) {{ D.assumptions.forEach(x => ch.push(bullet(x,"b5"))); }}
else {{ ch.push(body("To be defined.",{{italic:true,color:C.mid}})); }}
ch.push(sp(120));
ch.push(h2("3.2 Constraints"));
if (D.constraints.length > 0) {{ D.constraints.forEach(x => ch.push(bullet(x,"b6"))); }}
else {{ ch.push(body("To be defined.",{{italic:true,color:C.mid}})); }}
ch.push(sp(120));
ch.push(h2("3.3 Risks & Mitigations"));
ch.push(sp(60));
if (D.risks.length > 0) {{
  ch.push(tbl(["Risk","Mitigation"], D.risks, [4680,4680]));
}} else {{
  ch.push(body("No risks recorded.",{{italic:true,color:C.mid}}));
}}

// SECTION 4
ch.push(h1("4. Business Process Overview"));
ch.push(divider());
ch.push(h2("4.1 Current Process (As-Is)"));
if (D.asIs.length > 0) {{ D.asIs.forEach(x => ch.push(bullet(x,"b7"))); }}
else {{ ch.push(body("To be defined.",{{italic:true,color:C.mid}})); }}
ch.push(sp(120));
ch.push(h2("4.2 Proposed Process (To-Be)"));
if (D.toBe.length > 0) {{ D.toBe.forEach(x => ch.push(bullet(x,"b8"))); }}
else {{ ch.push(body("To be defined.",{{italic:true,color:C.mid}})); }}

// SECTION 5
ch.push(h1("5. KPI & Success Metrics"));
ch.push(divider());
ch.push(body("The following quantitative performance targets will be used to evaluate whether the system is operating successfully in production."));
ch.push(sp(80));
if (D.kpis.length > 0) {{
  ch.push(tbl(["Metric","Target"], D.kpis, [7200,2160]));
}} else {{
  ch.push(body("KPIs to be defined.",{{italic:true,color:C.mid}}));
}}

// SECTION 6
ch.push(h1("6. Functional Requirements"));
ch.push(divider());
ch.push(h3("Priority Rating Scale"));
ch.push(sp(60));
ch.push(tbl(["Priority","Definition"],[
  ["P1 — Must Have", "Project is not complete without this. Blocking requirements — if not delivered, the project fails UAT."],
  ["P2 — Should Have", "Strongly desired and planned, but project can launch without it if necessary. Deferral requires explicit stakeholder agreement."],
  ["P3 — Nice to Have", "Valuable enhancement but not planned for current phase. Included for visibility and future planning only."],
],[2200,7160]));
ch.push(sp(120));
D.frSections.forEach((sec) => {{
  ch.push(h2(sec.title));
  if (sec.reqs && sec.reqs.length > 0) {{
    ch.push(sp(60));
    ch.push(tbl(["ID","Requirement","Priority"], sec.reqs, [900,7460,1000]));
  }} else {{
    ch.push(body("Requirements for this module to be defined in a future planning session.", {{italic:true, color:C.mid}}));
  }}
  ch.push(sp(120));
}});

// SECTION 7
ch.push(h1("7. Non-Functional Requirements"));
ch.push(divider());
const nfrSections = [
  ["7.1 Performance & Scalability", D.nfrPerf, "b11"],
  ["7.2 Availability & Reliability", D.nfrAvail, "b12"],
  ["7.3 Usability & Accessibility", D.nfrUsab, "b13"],
  ["7.4 Security & Access Control", D.nfrSec, "b14"],
  ["7.5 Compliance & Regulatory", D.nfrCompliance, "b15"],
];
nfrSections.forEach(([title, items, ref], idx) => {{
  ch.push(h2(title));
  if (items && items.length > 0) {{
    items.forEach(x => ch.push(bullet(x, ref)));
  }} else {{
    ch.push(body("To be defined in consultation with relevant stakeholders.", {{italic:true, color:C.mid}}));
  }}
  if (idx < nfrSections.length - 1) ch.push(sp(80));
}});

// SECTION 8
ch.push(h1("8. Data Governance & Privacy"));
ch.push(divider());
ch.push(h2("8.1 Data Classification"));
ch.push(sp(60));
if (D.dataClassification.length > 0) {{
  ch.push(tbl(["Data Asset","Classification Level"], D.dataClassification, [5760,3600]));
}} else {{
  ch.push(body("Data classification to be defined.",{{italic:true,color:C.mid}}));
}}
ch.push(sp(160));
ch.push(h2("8.2 Data Privacy Checklist"));
if (D.privacyChecklist.length > 0) {{
  D.privacyChecklist.forEach(x => ch.push(bullet(x,"b16")));
}} else {{
  ch.push(body("Privacy checklist to be defined.",{{italic:true,color:C.mid}}));
}}

// SECTION 9
ch.push(h1("9. Technology Stack & Architecture"));
ch.push(divider());
ch.push(h2("9.1 Proposed Technology Stack"));
ch.push(body("The development team has been granted autonomy to select the most feasible technology stack. The following table captures confirmed and provisional technology decisions."));
ch.push(sp(60));
if (D.techStack.length > 0) {{
  ch.push(tbl(["Architectural Layer","Selected Technology"], D.techStack, [3200,6160]));
}} else {{
  ch.push(body("Technology stack to be defined.",{{italic:true,color:C.mid}}));
}}
ch.push(sp(200));
ch.push(h2("9.2 Architecture Data Flow"));
ch.push(body("The architecture data flow diagram is to be attached below. Replace the placeholder with the finalised diagram before distributing this document."));
ch.push(sp(80));
ch.push(archPlaceholder());

// SECTION 10
ch.push(h1("10. Appendices"));
ch.push(divider());
ch.push(h2("10.1 Glossary of Terms"));
ch.push(sp(60));
if (D.glossary.length > 0) {{
  ch.push(tbl(["Term","Definition"], D.glossary, [1800,7560]));
}} else {{
  ch.push(body("Glossary to be defined.",{{italic:true,color:C.mid}}));
}}
ch.push(sp(140));
ch.push(h2("10.2 List of Acronyms"));
if (D.acronyms.length > 0) {{ D.acronyms.forEach(x => ch.push(bullet(x,"b17"))); }}
else {{ ch.push(body("To be defined.",{{italic:true,color:C.mid}})); }}
ch.push(sp(120));
ch.push(h2("10.3 Related Documents"));
if (D.relatedDocs.length > 0) {{ D.relatedDocs.forEach(x => ch.push(bullet(x,"b18"))); }}
else {{ ch.push(body("To be defined.",{{italic:true,color:C.mid}})); }}
ch.push(sp(140));
ch.push(h2("10.4 Document Sign-Off"));
ch.push(sp(60));
const signoffRows = D.signoff.length ? D.signoff : [["________________","________________","________________","________________"]];
ch.push(tbl(["Name","Role","Date","Signature"], signoffRows, [2200,3500,1800,1860]));

const doc = new Document({{
  numbering: {{ config: numberingConfig }},
  styles: {{
    default: {{ document: {{ run: {{ font:"Arial", size:22, color:C.dark }} }} }},
    paragraphStyles: [
      {{ id:"Heading1", name:"Heading 1", basedOn:"Normal", next:"Normal", quickFormat:true,
        run:{{size:36, bold:true, font:"Arial", color:C.primary}},
        paragraph:{{spacing:{{before:480, after:160}}, outlineLevel:0}} }},
      {{ id:"Heading2", name:"Heading 2", basedOn:"Normal", next:"Normal", quickFormat:true,
        run:{{size:28, bold:true, font:"Arial", color:C.accent}},
        paragraph:{{spacing:{{before:320, after:120}}, outlineLevel:1}} }},
      {{ id:"Heading3", name:"Heading 3", basedOn:"Normal", next:"Normal", quickFormat:true,
        run:{{size:24, bold:true, font:"Arial", color:C.dark}},
        paragraph:{{spacing:{{before:240, after:80}}, outlineLevel:2}} }},
    ]
  }},
  sections: [{{
    properties: {{
      page: {{ size:{{width:12240, height:15840}}, margin:{{top:1440, right:1440, bottom:1440, left:1440}} }}
    }},
    headers: {{
      default: new Header({{
        children:[
          new Paragraph({{
            children:[
              new TextRun({{text:"CONFIDENTIAL DRAFT | "+D.projectName+" | "+D.businessUnit, size:16, color:C.mid, font:"Arial"}}),
              new TextRun({{text:"\\t", size:16}}),
              new TextRun({{children:["Page ", PageNumber.CURRENT, " of ", PageNumber.TOTAL_PAGES], size:16, color:C.mid, font:"Arial"}}),
            ],
            tabStops:[{{type:TabStopType.RIGHT, position:TabStopPosition.MAX}}],
            border:{{ bottom:{{style:BorderStyle.SINGLE, size:4, color:C.accent, space:4}} }}
          }})
        ]
      }})
    }},
    footers: {{
      default: new Footer({{
        children:[
          new Paragraph({{
            children:[new TextRun({{text:"Version "+D.version+" | "+D.date+" | "+D.businessUnit, size:16, color:C.mid, font:"Arial"}})],
            border:{{ top:{{style:BorderStyle.SINGLE, size:4, color:C.accent, space:4}} }}
          }})
        ]
      }})
    }},
    children: ch
  }}]
}});

Packer.toBuffer(doc).then(buf => {{
  fs.writeFileSync(process.argv[2], buf);
  console.log("SUCCESS: " + process.argv[2]);
}}).catch(err => {{
  console.error("ERROR: " + err.message);
  process.exit(1);
}});
"""
    return script


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def ensure_docx_package(script_dir: Path):
    node_modules = script_dir / "node_modules" / "docx"
    if node_modules.exists():
        return
    print("First run: installing 'docx' npm package locally (~10 seconds)...")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    result = subprocess.run(
        [npm_cmd, "install", "docx", "--prefix", str(script_dir)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("ERROR: Failed to install 'docx' npm package.", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    print("  'docx' installed successfully.\n")


def main():
    parser = argparse.ArgumentParser(
        description="Generate a McKinsey-style BRD Word document from a structured JSON file."
    )
    parser.add_argument("input_json", help="Path to the BRD JSON file")
    parser.add_argument("output_docx", nargs="?", help="Path for the output .docx (default: <input_stem>_BRD.docx)")
    args = parser.parse_args()

    input_path = Path(args.input_json).resolve()
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path = (
        Path(args.output_docx).resolve()
        if args.output_docx
        else input_path.with_name(input_path.stem + "_BRD.docx")
    )

    script_dir = Path(__file__).resolve().parent
    ensure_docx_package(script_dir)

    print(f"Reading JSON: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("Parsing BRD data...")
    ctx = parse_brd(data)
    print(f"  Project : {ctx['project_name']}")
    print(f"  Phases  : {len(ctx['phases'])}")
    print(f"  Obj Primary : {len(ctx['obj_primary'])}")
    print(f"  Obj Secondary: {len(ctx['obj_secondary'])}")
    print(f"  Revisions : {len(ctx['revisions'])}")
    print(f"  KPIs    : {len(ctx['kpis'])}")
    print(f"  Risks   : {len(ctx['risks'])}")
    print(f"  FR sections : {len(ctx['fr_sections'])}")

    js_code = build_js(ctx)
    tmp_js_path = script_dir / "_brd_tmp_gen.js"
    tmp_js_path.write_text(js_code, encoding="utf-8")

    print(f"Generating document: {output_path}")
    node_cmd = "node.exe" if sys.platform == "win32" else "node"
    result = subprocess.run(
        [node_cmd, str(tmp_js_path), str(output_path)],
        capture_output=True, text=True, cwd=str(script_dir),
    )

    try:
        tmp_js_path.unlink()
    except Exception:
        pass

    if result.returncode != 0 or "ERROR" in result.stdout:
        print("Node.js error:", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    print(result.stdout.strip())
    if output_path.exists():
        print(f"\nDone! Output: {output_path} ({output_path.stat().st_size/1024:.1f} KB)")
    else:
        print("ERROR: Output file was not created.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
