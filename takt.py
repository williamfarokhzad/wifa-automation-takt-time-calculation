"""Calculate demand pace and a fixed-cycle planning screen for one line."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


@dataclass(frozen=True)
class Window:
    name: str
    scheduled_min: int
    demand: int
    exclusions_min: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class Result:
    name: str
    available_s: int
    demand: int
    capacity: int

    @property
    def takt(self) -> Fraction | None:
        return Fraction(self.available_s, self.demand) if self.demand else None

    @property
    def margin(self) -> int:
        return self.capacity - self.demand


def fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"{label} needs exactly: {', '.join(expected)}")
    return value


def integer(value, label, minimum):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be a whole number >= {minimum}")
    return value


def load_plan(data) -> tuple[int, tuple[Window, ...]]:
    plan = fields(data, ("cycle_s", "windows"), "plan")
    cycle = integer(plan["cycle_s"], "cycle_s", 1)
    if not isinstance(plan["windows"], list) or not plan["windows"]:
        raise ValueError("windows must be a nonempty list")
    windows = []
    names = set()
    for i, raw in enumerate(plan["windows"], 1):
        label = f"window {i}"
        w = fields(raw, ("name", "scheduled_min", "demand", "exclusions_min"), label)
        name = w["name"]
        if not isinstance(name, str) or not name.strip() or not name.isprintable():
            raise ValueError(f"{label} needs a printable, nonblank name")
        if name in names:
            raise ValueError(f"duplicate window name: {name}")
        names.add(name)
        scheduled = integer(w["scheduled_min"], f"{label} scheduled_min", 1)
        demand = integer(w["demand"], f"{label} demand", 0)
        if not isinstance(w["exclusions_min"], list):
            raise ValueError(f"{label} exclusions_min must be a list")
        stops = []
        for interval in w["exclusions_min"]:
            if not isinstance(interval, list) or len(interval) != 2:
                raise ValueError(f"{label}: exclusion needs two minute offsets")
            start = integer(interval[0], f"{label} exclusion start", 0)
            end = integer(interval[1], f"{label} exclusion end", 1)
            if not start < end <= scheduled:
                raise ValueError(f"{label}: require 0 <= start < end <= scheduled_min")
            stops.append((start, end))
        windows.append(Window(name, scheduled, demand, tuple(stops)))
    return cycle, tuple(windows)


def production_blocks(window: Window) -> tuple[int, ...]:
    """Return continuous production durations in seconds after merging stops."""
    cursor = 0
    blocks = []
    for start, end in sorted(window.exclusions_min):
        if start > cursor:
            blocks.append((start - cursor) * 60)
        cursor = max(cursor, end)
    if cursor < window.scheduled_min:
        blocks.append((window.scheduled_min - cursor) * 60)
    return tuple(blocks)


def evaluate(cycle_s: int, windows: tuple[Window, ...]) -> tuple[tuple[Result, ...], Result]:
    rows = []
    for window in windows:
        blocks = production_blocks(window)
        rows.append(Result(window.name, sum(blocks), window.demand,
                           sum(block // cycle_s for block in blocks)))
    total = Result("Pooled", sum(r.available_s for r in rows),
                   sum(r.demand for r in rows), sum(r.capacity for r in rows))
    return tuple(rows), total


def decimal_2(value: Fraction) -> str:
    # Values here are nonnegative. Round half up only for display.
    cents, rem = divmod(100 * value.numerator, value.denominator)
    cents += 2 * rem >= value.denominator
    return f"{cents // 100}.{cents % 100:02d}"


def line(row: Result, cycle_s: int) -> str:
    takt = row.takt
    if takt is None:
        pace = "n/a (no demand)"
        screen = "no demand"
    else:
        pace = f"{decimal_2(takt)} s/unit"
        if cycle_s > takt:
            screen = "cycle slower than takt"
        elif row.margin < 0:
            screen = "cycle meets takt; blocks fall short"
        else:
            screen = "fits modeled blocks"
    return (f"{row.name}: net {row.available_s} s | demand {row.demand} | takt {pace} | "
            f"capacity {row.capacity} | margin {row.margin:+d} | {screen}")


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="JSON plan; minute offsets from each window's start")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.plan.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        cycle, windows = load_plan(data)
        rows, total = evaluate(cycle, windows)
    except (OSError, ValueError) as error:
        print(f"Input error: {error}", file=sys.stderr)
        return 2
    print(f"Fixed output cycle: {cycle} s/unit (planning assumption)")
    for row in (*rows, total):
        print(line(row, cycle))
    short = [r.name for r in rows if r.margin < 0]
    print("Local shortages: " + (", ".join(short) if short else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
