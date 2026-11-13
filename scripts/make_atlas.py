#!/usr/bin/env python3
"""Build data/glyphs.json: Manrope outlines, advances and kerning for the
characters the profile cards use. Run once, locally, when the character set
or the weights change:

    pip install fonttools uharfbuzz
    python3 scripts/make_atlas.py path/to/Manrope[wght].ttf

build.py then needs nothing but the Python standard library, so the daily
GitHub Action has no dependencies to install.

Manrope is (c) The Manrope Project Authors, SIL Open Font License 1.1
(see assets/OFL.txt).
"""
import json
import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
import uharfbuzz as hb

WEIGHTS = (500, 600, 800)
CHARS = "".join(chr(c) for c in range(32, 127)) + "·—–→↗°’“”…×"


def main(src: str) -> None:
    out = {"unitsPerEm": None, "weights": {}}
    blob = hb.Blob.from_file_path(src)
    face = hb.Face(blob)
    for w in WEIGHTS:
        font = instancer.instantiateVariableFont(TTFont(src), {"wght": w})
        upm = font["head"].unitsPerEm
        out["unitsPerEm"] = upm
        cmap = font.getBestCmap()
        glyphs = font.getGlyphSet()
        have = [c for c in CHARS if ord(c) in cmap]
        missing = [c for c in CHARS if ord(c) not in cmap]
        if missing:
            print(f"wght {w}: not in the font, skipped: {' '.join(missing)}")

        hbfont = hb.Font(face)
        hbfont.set_variations({"wght": w})

        def advance(text: str) -> int:
            buf = hb.Buffer()
            buf.add_str(text)
            buf.guess_segment_properties()
            hb.shape(hbfont, buf, {"kern": True, "liga": False, "calt": False})
            return sum(p.x_advance for p in buf.glyph_positions)

        adv, paths = {}, {}
        for c in have:
            pen = SVGPathPen(glyphs, ntos=lambda v: str(int(round(v))))
            glyphs[cmap[ord(c)]].draw(pen)
            paths[c] = pen.getCommands()
            adv[c] = advance(c)
        kern = {}
        for a in have:
            for b in have:
                d = advance(a + b) - adv[a] - adv[b]
                if d:
                    kern[a + b] = d
        out["weights"][str(w)] = {
            "ascender": font["hhea"].ascent,
            "descender": font["hhea"].descent,
            "capHeight": getattr(font["OS/2"], "sCapHeight", 0),
            "xHeight": getattr(font["OS/2"], "sxHeight", 0),
            "advance": adv,
            "kern": kern,
            "path": paths,
        }
        print(f"wght {w}: {len(have)} glyphs, {len(kern)} kerning pairs")
    dest = Path(__file__).resolve().parent.parent / "data" / "glyphs.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"{dest} — {dest.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(sys.argv[1])
