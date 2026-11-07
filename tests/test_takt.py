import itertools
import json
from fractions import Fraction
from pathlib import Path
import subprocess
import sys
import unittest

from takt import Result, Window, evaluate, line, load_plan, production_blocks

ROOT = Path(__file__).resolve().parents[1]


def sample(filename):
    return evaluate(*load_plan(json.loads((ROOT / "examples" / filename).read_text())))


class TaktTests(unittest.TestCase):
    def test_calendar_matches_independent_minute_enumeration(self):
        # Exhaustive ordered pairs on a five-minute grid, including containment
        # and adjacency. The oracle scans individual minutes, not intervals.
        intervals = tuple(itertools.combinations(range(6), 2))
        for pair in itertools.product(intervals, repeat=2):
            allowed = [not any(a <= m < b for a, b in pair) for m in range(5)]
            reference = tuple(60 * sum(1 for _ in group)
                              for available, group in itertools.groupby(allowed) if available)
            self.assertEqual(production_blocks(Window("A", 5, 1, pair)), reference)

    def test_overlap_example_agrees_with_hand_calculation(self):
        (row,), total = sample("overlapping-stops.json")
        self.assertEqual((row.available_s, row.capacity, row.margin), (25500, 462, 12))
        self.assertEqual(row.takt, Fraction(170, 3))
        self.assertEqual(total.takt, row.takt)

    def test_pooled_screen_does_not_erase_a_local_shortage(self):
        (early, late), total = sample("shift-surge.json")
        self.assertEqual((early.takt, late.takt, total.takt),
                         (Fraction(75), Fraction(675, 13), Fraction(675, 11)))
        self.assertEqual((early.margin, late.margin, total.margin), (45, -35, 10))

    def test_partial_cycles_do_not_cross_a_stop_or_window_boundary(self):
        (row,), _ = sample("short-blocks.json")
        self.assertEqual((row.available_s, row.takt, row.capacity, row.margin), (180, 90, 0, -2))
        windows = (Window("A", 1, 1, ()), Window("B", 1, 0, ()))
        rows, total = evaluate(90, windows)
        self.assertEqual([r.capacity for r in rows], [0, 0])
        self.assertEqual(total.capacity, 0)

    def test_completely_excluded_window_preserves_unmet_demand(self):
        (row,), _ = evaluate(50, (Window("Closed", 5, 2, ((0, 5),)),))
        self.assertEqual((row.takt, row.capacity, row.margin), (0, 0, -2))
        self.assertIn("cycle slower than takt", line(row, 50))

    def test_no_orders_has_no_finite_takt(self):
        (row,), total = sample("no-orders.json")
        self.assertIsNone(row.takt)
        self.assertIsNone(total.takt)
        self.assertEqual(row.capacity, 80)

    def test_screen_uses_exact_fraction_not_rounded_display(self):
        row = Result("Near threshold", 599, 300, 299)
        output = line(row, 2)
        self.assertIn("takt 2.00 s/unit", output)
        self.assertIn("cycle slower than takt", output)

    def test_rejects_invalid_numbers_bounds_and_duplicate_names(self):
        good = {"name": "A", "scheduled_min": 5, "demand": 1, "exclusions_min": []}
        bad = [
            {"cycle_s": True, "windows": [good]},
            {"cycle_s": 0, "windows": [good]},
            {"cycle_s": 1, "windows": []},
            {"cycle_s": 1, "windows": [good, good]},
            {"cycle_s": 1, "windows": [dict(good, demand=-1)]},
            {"cycle_s": 1, "windows": [dict(good, exclusions_min=[[1, 1]])]},
            {"cycle_s": 1, "windows": [dict(good, exclusions_min=[[1, 6]])]},
            {"cycle_s": 1, "windows": [dict(good, exclusions_min=[[-1, 1]])]},
        ]
        for plan in bad:
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                load_plan(plan)

    def test_cli_distinguishes_a_shortage_from_invalid_input(self):
        for filename, status, output in (
            ("shift-surge.json", 0, "Local shortages: Late"),
            ("invalid-interval.json", 2, "0 <= start < end <= scheduled_min"),
        ):
            result = subprocess.run([sys.executable, "takt.py", f"examples/{filename}"],
                                    cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, status)
            self.assertIn(output, result.stdout if status == 0 else result.stderr)
