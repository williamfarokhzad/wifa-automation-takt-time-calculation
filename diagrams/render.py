"""Render original diagrams from the included plans (Python + Inkscape + ImageMagick)."""
from html import escape
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from takt import evaluate, load_plan  # noqa: E402

BG, INK, MUTED = "#f7f9fc", "#102a43", "#465b72"
BLUE, TEAL, AMBER = "#21528e", "#10736a", "#a44512"


def rect(x, y, w, h, fill, radius=0, stroke=None):
    outline = f' stroke="{stroke}" stroke-width="2"' if stroke else ""
    return f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{radius}" fill="{fill}"{outline}/>'


def text(x, y, label, size=23, color=INK, bold=False, align="start"):
    return (f'<text x="{x:g}" y="{y:g}" fill="{color}" text-anchor="{align}" '
            f'font-size="{size}" font-weight="{700 if bold else 400}">{escape(label)}</text>')


def plan(filename):
    return load_plan(json.loads((ROOT / "examples" / filename).read_text()))


def timeline():
    _, (window,) = plan("overlapping-stops.json")
    def x(minute):
        return 46 + 748 * minute / window.scheduled_min
    stops = sorted(window.exclusions_min)
    merged = []
    for start, end in stops:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    excluded = sum(end - start for start, end in merged)
    items = [text(46, 56, "Overlapping stops count once", 35, bold=True),
             text(46, 94, "480 scheduled minutes • offsets from shift start", 24, MUTED),
             rect(46, 136, 748, 46, "#dbe9f8", 8),
             text(46, 226, "Planned exclusions merged", 25, color=AMBER, bold=True)]
    for i, (start, end) in enumerate(merged):
        middle = (x(start) + x(end)) / 2
        items.extend([rect(x(start), 136, x(end) - x(start), 46, AMBER),
                      rect(middle - 1, 182, 2, 13, AMBER),
                      text(middle, 263, f"{start} to {end}", 26, AMBER, bold=True, align="middle")])
    items.extend([text(46, 326, f"{excluded} min excluded", 27, AMBER, bold=True),
                  text(794, 326, f"{window.scheduled_min - excluded} min available", 27, BLUE, bold=True, align="end")])
    return 360, items


def shift_chart():
    cycle, windows = plan("shift-surge.json")
    rows, total = evaluate(cycle, windows)
    def bar_width(units):
        return 470 * units / max(v for row in rows for v in (row.capacity, row.demand))
    items = [text(46, 56, "A daily surplus can hide a late shortage", 32, bold=True),
             text(46, 95, "Demand and modeled capacity, in whole units", 23, MUTED),
             rect(46, 121, 20, 20, BLUE, 3), text(75, 140, "Demand", 23),
             rect(220, 121, 20, 20, TEAL, 3), text(250, 140, "Capacity", 23)]
    for i, row in enumerate(rows):
        y = 174 + 98 * i
        items.extend([text(46, y + 40, row.name, 27, bold=True),
                      rect(155, y, bar_width(row.demand), 28, BLUE, 4),
                      rect(155, y + 34, bar_width(row.capacity), 28, TEAL, 4),
                      text(170 + bar_width(row.demand), y + 23, str(row.demand), 23, BLUE, bold=True),
                      text(170 + bar_width(row.capacity), y + 57, str(row.capacity), 23, TEAL, bold=True),
                      text(793, y + 39, f"{row.margin:+d}", 27,
                           AMBER if row.margin < 0 else TEAL, bold=True, align="end")])
    items.extend([rect(46, 358, 748, 52, "#e8effa", 7),
                  text(64, 392, f"Pooled margin: {total.margin:+d}  |  Late margin: {rows[1].margin:+d}", 26, bold=True)])
    return 435, items


for name, builder in (("takt-time-calendar", timeline), ("takt-time-shift-demand", shift_chart)):
    height, elements = builder()
    svg = ROOT / "diagrams" / f"{name}.svg"
    svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="840" height="{height}" '
                   f'viewBox="0 0 840 {height}" font-family="DejaVu Sans">\n'
                   + rect(0, 0, 840, height, BG) + "\n" + "\n".join(elements) + "\n</svg>\n",
                   encoding="utf-8")
    png = subprocess.check_output(["inkscape", str(svg), "--export-type=png", "--export-filename=-"])
    subprocess.run(["convert", "png:-", "-strip", "-quality", "88",
                    str(svg.with_suffix(".webp"))], input=png, check=True)
