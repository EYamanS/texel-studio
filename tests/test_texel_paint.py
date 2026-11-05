"""
Tests for texel_paint (standard library only):   python -m unittest discover -s tests -v
Every test runs against a throw-away TEXEL_HOME, never against your real database.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_HOME = tempfile.mkdtemp(prefix="texel_test_")
os.environ["TEXEL_HOME"] = _HOME                      # must be set before texel_paint is imported

from texel_paint import batch, store                  # noqa: E402
from texel_paint.lint import lint                     # noqa: E402
from texel_paint.painter import apply_ops, op_reference  # noqa: E402
from texel_paint.script import parse_ops, preprocess  # noqa: E402
from texel_paint.stamps import list_stamps            # noqa: E402


def paint(canvas, text):
    errors, notes = apply_ops(canvas, parse_ops(text))
    return errors, notes


class ScriptTests(unittest.TestCase):
    def test_text_and_json_syntax_agree(self):
        self.assertEqual(parse_ops("rect 0 0 3 3 1"), parse_ops('[["rect",0,0,3,3,1]]'))

    def test_comments_and_dicts(self):
        ops = parse_ops("stamp s 1 2 0 x 1 {#ff0000:#00ff00} // note")
        self.assertEqual(ops[0][:3], ["stamp", "s", 1])
        self.assertEqual(ops[0][-1], {"#ff0000": "#00ff00"})

    def test_loop_and_expression(self):
        lines = preprocess("for i 0 2\n px ${$i*2} 1 3\nendfor").splitlines()
        self.assertEqual([l.strip() for l in lines], ["px 0 1 3", "px 2 1 3", "px 4 1 3"])

    def test_macro_is_stored_and_reusable(self):
        preprocess("macro dot $x $y\n px $x $y 1\nendmacro")
        self.assertEqual(preprocess("use dot 3 4").strip(), "px 3 4 1")

    def test_unsafe_expression_rejected(self):
        with self.assertRaises(ValueError):
            preprocess("px ${__import__('os')} 1 1")


class PaintTests(unittest.TestCase):
    def new(self, size=16, colors=None, **kw):
        gid = store.create("test", size, "item", colors if colors is not None else ["#000000", "#ffffff"], **kw)
        return gid, store.load(gid)

    def test_rect_and_save_roundtrip(self):
        gid, canvas = self.new()
        errors, _ = paint(canvas, "rect 2 2 5 5 1")
        self.assertEqual(errors, [])
        store.save(gid, canvas, "t")
        self.assertEqual(store.load(gid).pixels[3][3], 1)
        self.assertTrue((store.OUTPUT / f"gen_{gid}_16x16.png").exists())

    def test_unknown_hex_color_is_appended_and_reported(self):
        gid, canvas = self.new(colors=[])
        errors, notes = paint(canvas, "px 1 1 #12ab34")
        self.assertEqual(errors, [])
        self.assertEqual(canvas.palette, ["#12ab34"])
        self.assertEqual(notes, ["#12ab34=0"])

    def test_rectangular_canvas_discards_outside(self):
        gid, canvas = self.new(size=20, colors=["#000000"], width=10, height=20)
        paint(canvas, "rect 0 0 19 19 0")
        store.save(gid, canvas)
        saved = store.load(gid)
        self.assertEqual((saved.width, saved.height), (10, 20))
        self.assertEqual(saved.pixels[5][15], -1)
        self.assertEqual(saved.to_image().size, (10, 20))

    def test_alpha_palette_color(self):
        gid, canvas = self.new(colors=["#ff000080"])
        paint(canvas, "px 0 0 0")
        self.assertEqual(canvas.to_image().getpixel((0, 0)), (255, 0, 0, 128))

    def test_float_arguments_cannot_hang_line_ops(self):
        gid, canvas = self.new()
        errors, _ = paint(canvas, "line 0 0 7.6 7.4 1\npline 0 0 5.5 3.2 1")
        self.assertEqual(errors, [])

    def test_absurd_numbers_are_rejected(self):
        gid, canvas = self.new()
        errors, _ = paint(canvas, "rect 0 0 99999999 5 1")
        self.assertEqual(len(errors), 1)

    def test_unknown_op_is_reported_not_fatal(self):
        gid, canvas = self.new()
        errors, _ = paint(canvas, "nope 1 2\nrect 0 0 1 1 1")
        self.assertEqual(len(errors), 1)
        self.assertEqual(canvas.pixels[0][0], 1)

    def test_shapes_are_symmetric_around_pixel_edge(self):
        canvas = store.PaintCanvas(32, ["#000000"])
        paint(canvas, "disc 16 16 9 0")
        for row in canvas.pixels:
            self.assertEqual(row, row[::-1])        # centre on the edge between pixels 15|16 -> mirror symmetric

    def test_bevel_gradient_rim_autoline_run(self):
        gid, canvas = self.new(size=24, colors=["#222222", "#888888", "#eeeeee"])
        errors, _ = paint(canvas, "rect 4 4 19 19 1\nbevel [rect,4,4,19,19] 2 0\ngradient [rect,6,6,17,17] [0,1,2] 90\n"
                                  "rim [rect,4,4,19,19]\nautoline\npolish")
        self.assertEqual(errors, [])

    def test_stamp_library(self):
        gid, canvas = self.new(colors=["#ff0000", "#0000ff"])
        paint(canvas, "rect 1 1 2 2 0\ngrab testmark [rect,1,1,2,2]\nstamp testmark 8 8 0 x 1 {#ff0000:#00ff00}")
        self.assertIn("testmark", list_stamps())
        self.assertIn("#00ff00", [c.lower() for c in canvas.palette])
        self.assertNotEqual(canvas.pixels[8][8], -1)

    def test_card_frame_part_and_lint(self):
        gid, canvas = self.new(size=72, colors=[], width=52, height=72)
        errors, _ = paint(canvas, "card_frame 0 0 51 71 rare")
        self.assertEqual(errors, [])
        summary, warnings = lint(canvas)
        self.assertEqual(warnings, [])
        self.assertIn("52x72", summary)

    def test_every_op_has_a_docstring(self):
        names = [n for n, _ in op_reference()]
        for expected in ("rect", "bevel", "gradient", "heart", "stamp", "card_frame", "autoline", "pline"):
            self.assertIn(expected, names)


class BatchTests(unittest.TestCase):
    SPEC = """@design batch_a size=16
rect 2 2 13 13 #223344
autoline
@design batch_b size=24x32
card_frame 0 0 23 31 common
"""

    def test_batch_builds_checks_and_overwrites(self):
        lines, sheet = batch.run_batch(self.SPEC)
        self.assertTrue(any(l.startswith("batch_a") for l in lines))
        self.assertTrue(sheet.exists())
        first = store.find_by_name("batch_a", 16)
        batch.run_batch(self.SPEC)
        self.assertEqual(store.find_by_name("batch_a", 16), first)       # reused, not duplicated

    def test_batch_reports_script_errors_and_continues(self):
        lines, _ = batch.run_batch("@design bad_one size=8\nfor i 0 2\n@design good_one size=8\nrect 0 0 3 3 #fff\n")
        self.assertTrue(any("ERROR" in l and l.startswith("bad_one") for l in lines))
        self.assertTrue(any(l.startswith("good_one") and "ERROR" not in l for l in lines))

    def test_ship_backs_up_existing_file(self):
        gid = store.create("shipme", 8, "item", ["#ff0000"])
        canvas = store.load(gid)
        paint(canvas, "rect 0 0 7 7 0")
        store.save(gid, canvas)
        target = Path(_HOME) / "game" / "sprite.png"
        batch.ship(gid, str(target))
        batch.ship(gid, str(target))
        self.assertTrue(target.exists())
        self.assertTrue(list((store.WORK / "ship_backup").glob("sprite_*.png")))

    def test_variant_recolours_palette_only(self):
        gid = store.create("orig", 8, "item", ["#ff0000", "#00ff00"])
        canvas = store.load(gid)
        paint(canvas, "px 1 1 0")
        store.save(gid, canvas)
        new_id = batch.variant(gid, "orig_blue", {"#ff0000": "#0000ff"})
        copy = store.load(new_id)
        self.assertEqual(copy.palette[0], "#0000ff")
        self.assertEqual(copy.pixels[1][1], 0)


class MigrationTests(unittest.TestCase):
    def test_old_database_gets_width_and_height_columns(self):
        path = Path(tempfile.mkdtemp()) / "old.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE generations (id INTEGER PRIMARY KEY AUTOINCREMENT, prompt TEXT NOT NULL, size INTEGER NOT NULL)")
        conn.commit()
        store.ensure_schema(conn)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(generations)")}
        self.assertTrue({"width", "height", "colors", "sprite_type", "reference_id"} <= columns)


if __name__ == "__main__":
    unittest.main()
