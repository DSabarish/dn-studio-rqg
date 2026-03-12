"""
timeline_renderer.py – Speaker Diarization Visualization

Generates a self-contained interactive HTML file from a segments JSON.
Ported from the original notebook to a standalone module.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np


def load_segments(json_path: str) -> List[Dict[str, Any]]:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_stats(segments: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    spk_data: Dict[str, Dict[str, Any]] = {}
    for seg in segments:
        spk = seg.get("speaker_id", "UNKNOWN")
        dur = max(0.0, seg["end"] - seg["start"])
        wc = len(seg["text"].split())
        if spk not in spk_data:
            spk_data[spk] = {
                "total_sec": 0.0,
                "utterances": 0,
                "words": 0,
                "durations": [],
            }
        spk_data[spk]["total_sec"] += dur
        spk_data[spk]["utterances"] += 1
        spk_data[spk]["words"] += wc
        spk_data[spk]["durations"].append(dur)
    for spk, d in spk_data.items():
        durs = np.array(d["durations"])
        d["avg_dur"] = float(durs.mean())
        d["median_dur"] = float(np.median(durs))
        d["max_dur"] = float(durs.max())
    return spk_data


def build_density(
    segments: List[Dict[str, Any]], total: float, bucket: float = 10.0
) -> List[Dict[str, Any]]:
    n_buckets = int(np.ceil(total / bucket))
    counts = [0] * n_buckets
    spk_map: Dict[int, set] = {}
    for seg in segments:
        b0 = int(seg["start"] // bucket)
        b1 = int(seg["end"] // bucket)
        for b in range(max(0, b0), min(n_buckets, b1 + 1)):
            counts[b] += 1
            spk_map.setdefault(b, set()).add(seg["speaker_id"])
    return [
        {"t": b * bucket, "count": counts[b], "speakers": list(spk_map.get(b, set()))}
        for b in range(n_buckets)
    ]


PALETTE = [
    {"bg": "#3b82f6", "light": "#93c5fd", "track": "#1e3a5f"},
    {"bg": "#10b981", "light": "#6ee7b7", "track": "#064e3b"},
    {"bg": "#f59e0b", "light": "#fcd34d", "track": "#451a03"},
    {"bg": "#ec4899", "light": "#f9a8d4", "track": "#500724"},
    {"bg": "#8b5cf6", "light": "#c4b5fd", "track": "#2e1065"},
    {"bg": "#06b6d4", "light": "#67e8f9", "track": "#083344"},
]


def _color_map(speakers: List[str]) -> Dict[str, Dict[str, str]]:
    return {spk: PALETTE[i % len(PALETTE)] for i, spk in enumerate(sorted(speakers))}


def render_html(json_path: str, out_path: str | None = None) -> str:
    segments = load_segments(json_path)
    if not segments:
        raise ValueError("No segments found in JSON.")

    total = max(seg["end"] for seg in segments)
    stats = compute_stats(segments)
    density = build_density(segments, total)
    speakers = sorted(stats.keys())
    cmap = _color_map(speakers)

    if out_path is None:
        out_path = str(Path(json_path).with_suffix(".html"))

    js_segments = json.dumps(segments, ensure_ascii=False)
    js_stats = json.dumps(
        {spk: {**d, "durations": d["durations"]} for spk, d in stats.items()},
        ensure_ascii=False,
    )
    js_density = json.dumps(density, ensure_ascii=False)
    js_cmap = json.dumps(
        {
            spk: {"bg": c["bg"], "light": c["light"], "track": c["track"]}
            for spk, c in cmap.items()
        },
        ensure_ascii=False,
    )
    js_speakers = json.dumps(speakers, ensure_ascii=False)
    js_total = json.dumps(float(total))

    # Use placeholder tokens then simple string replaces to avoid
    # f-string + template-literal escaping issues.
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Diarization Report</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#09090e;color:#e2e8f0;font-family:monospace;padding:24px}}
  h1{{font-size:1.3rem;margin-bottom:16px;color:#60a5fa}}
  .lane-row{{display:flex;align-items:center;margin-bottom:6px}}
  .lane-label{{width:100px;font-size:0.65rem;text-align:right;padding-right:10px;flex-shrink:0}}
  .lane-track{{flex:1;height:24px;background:#111827;border-radius:4px;position:relative;overflow:hidden}}
  .seg-block{{position:absolute;top:2px;height:20px;border-radius:3px;cursor:pointer;opacity:0.8}}
  .seg-block:hover{{opacity:1}}
  .utt-row{{display:flex;gap:10px;padding:7px 14px;border-bottom:1px solid #111827;cursor:pointer}}
  .utt-row:hover{{background:#111827}}
  .utt-time{{font-size:0.6rem;color:#334155;min-width:40px}}
  .utt-spk{{font-size:0.62rem;min-width:80px}}
  .utt-text{{font-size:0.72rem;color:#94a3b8;line-height:1.5}}
  ::-webkit-scrollbar{{width:4px}}
  ::-webkit-scrollbar-thumb{{background:#333;border-radius:2px}}
</style>
</head>
<body>
<h1>Voice Timeline</h1>
<div id="lanes" style="margin-bottom:20px"></div>
<div style="max-height:400px;overflow-y:auto;background:#0c0c14;border:1px solid #1e293b;border-radius:8px" id="log"></div>
<script>
const SEGMENTS=__JS_SEGMENTS__;
const STATS=__JS_STATS__;
const CMAP=__JS_CMAP__;
const SPEAKERS=__JS_SPEAKERS__;
const TOTAL=__JS_TOTAL__;
const fmt=t=>`${{Math.floor(t/60)}}:${{String(Math.floor(t%60)).padStart(2,'0')}}`;
const lanes=document.getElementById('lanes');
const log=document.getElementById('log');
SPEAKERS.forEach(spk=>{
  const c=CMAP[spk];
  const row=document.createElement('div');
  row.className='lane-row';
  row.innerHTML=`<div class="lane-label" style="color:${{c.light}}">${{spk}}</div><div class="lane-track" id="t-${{spk}}"></div>`;
  lanes.appendChild(row);
  const track=row.querySelector('.lane-track');
  SEGMENTS.filter(s=>s.speaker_id===spk).forEach(seg=>{
    const left=(seg.start/TOTAL)*100;
    const width=Math.max(0.2,((seg.end-seg.start)/TOTAL)*100);
    const b=document.createElement('div');
    b.className='seg-block';
    b.style.cssText=`left:${{left}}%;width:${{width}}%;background:${{c.bg}}`;
    b.title=`${{fmt(seg.start)}}–${{fmt(seg.end)}}: ${{seg.text.slice(0,80)}}`;
    track.appendChild(b);
  });
});
SEGMENTS.forEach(seg=>{
  const c=CMAP[seg.speaker_id]||{bg:'#6366f1',light:'#a5b4fc'};
  const row=document.createElement('div');
  row.className='utt-row';
  row.innerHTML=`<div class="utt-time">${{fmt(seg.start)}}</div><div class="utt-spk" style="color:${{c.light}}">${{seg.speaker_id}}</div><div class="utt-text">${{seg.text}}</div>`;
  log.appendChild(row);
});
</script>
</body>
</html>"""

    html = (
        html.replace("__JS_SEGMENTS__", js_segments)
        .replace("__JS_STATS__", js_stats)
        .replace("__JS_CMAP__", js_cmap)
        .replace("__JS_SPEAKERS__", js_speakers)
        .replace("__JS_TOTAL__", js_total)
    )

    Path(out_path).write_text(html, encoding="utf-8")
    print(f"[VIZ] Interactive chart saved → {out_path}")
    return out_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("json_path")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    path = render_html(args.json_path, args.out)
    print(f"Open in browser: file://{Path(path).resolve()}")


