#!/usr/bin/env python3
"""Renders every image used on the profile page into assets/.

    python3 scripts/build.py            # redraw from the data already in data/
    python3 scripts/build.py --live     # first refresh data/pulse.json:
                                        #   the contribution calendar (needs GH_TOKEN)
                                        #   and a check that the site answers

Standard library only: the daily GitHub Action runs this file as is.
Text is drawn from glyph outlines in data/glyphs.json (see make_atlas.py), so the
cards look the same on every device and need no web font.

What to edit:
    data/profile.json   texts, links, numbers on the cards
    THEMES below        colours
"""
import argparse
import datetime as dt
import json
import math
import os
import random
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
ATLAS = json.loads((ROOT / "data" / "glyphs.json").read_text())
PROFILE = json.loads((ROOT / "data" / "profile.json").read_text())
PULSE_FILE = ROOT / "data" / "pulse.json"
UPM = ATLAS["unitsPerEm"]

THEMES = {
    "light": dict(
        surface="#FAF8F3", border="#E7E2D6", hair="#E6E1D5",
        ink="#14181A", ink2="#4B5559", muted="#687276",
        teal="#0F6E74", teal_soft="#DFECEA", accent="#D9812A",
        btn="#0F6E74", on_btn="#FFFFFF",
        bar="#008F95", bar_soft="#A9D6D6",
        ridge=("#DCE9E6", "#B3D3CF", "#0F6E74"), crest="#0B5D62",
        glow=0.20, topo=0.20,
    ),
    "dark": dict(
        surface="#0B1517", border="#1E2E31", hair="#1C2B2E",
        ink="#F3F0E9", ink2="#B5BFC0", muted="#819092",
        teal="#3CBDB1", teal_soft="#12292B", accent="#F4B04E",
        btn="#3CBDB1", on_btn="#062124",
        bar="#2AA79D", bar_soft="#1B4F4D",
        ridge=("#0F2529", "#143337", "#1A4549"), crest="#2A6A6E",
        glow=0.30, topo=0.22,
    ),
}
MARK = "#0F6E74"  # the Z mark keeps one colour in both themes

EASE = "cubic-bezier(.23,1,.32,1)"
CSS = f"""
@keyframes up{{from{{opacity:0;transform:translateY(14px)}}}}
@keyframes fade{{from{{opacity:0}}}}
@keyframes draw{{from{{stroke-dashoffset:1}}to{{stroke-dashoffset:0}}}}
@keyframes grow{{from{{transform:scaleY(0)}}}}
@keyframes rise{{from{{opacity:0;transform:translateY(34px)}}}}
@keyframes ping{{0%{{transform:scale(1);opacity:.55}}70%,100%{{transform:scale(2.6);opacity:0}}}}
@keyframes twinkle{{0%,100%{{opacity:.25}}50%{{opacity:.95}}}}
@keyframes nudge{{0%,60%,100%{{transform:none}}80%{{transform:translate(3px,-3px)}}}}
.up{{animation:up .9s {EASE} both}}
.fade{{animation:fade 1.2s ease both}}
.rise{{animation:rise 1.6s {EASE} both}}
.draw{{stroke-dasharray:1;animation:draw 2.2s {EASE} both}}
.grow{{transform-box:fill-box;transform-origin:50% 100%;animation:grow .8s {EASE} both}}
.ping{{transform-box:fill-box;transform-origin:center;animation:ping 2.4s ease-out infinite}}
.twinkle{{animation:twinkle 3.6s ease-in-out infinite}}
.nudge{{transform-box:fill-box;animation:nudge 3.2s ease-in-out infinite}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}.motion{{display:none}}}}
""".strip()


def n(v: float) -> str:
    """A short number for SVG attributes."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def measure(s: str, size: float, weight: int = 500, track: float = 0) -> float:
    w = ATLAS["weights"][str(weight)]
    units = 0
    for i, ch in enumerate(s):
        if ch not in w["advance"]:
            raise KeyError(f"no glyph for {ch!r}: add it to CHARS in make_atlas.py")
        units += w["advance"][ch]
        if i + 1 < len(s):
            units += w["kern"].get(ch + s[i + 1], 0)
    return units * size / UPM + track * max(len(s) - 1, 0)


class Svg:
    def __init__(self, w: int, h: int, theme: str, title: str, static: bool = False):
        self.w, self.h, self.t = w, h, THEMES[theme]
        self.theme, self.title, self.static = theme, title, static
        self.body, self.defs, self.glyphs = [], [], {}

    def add(self, s: str) -> None:
        self.body.append(s)

    def anim(self, cls: str, delay: float = 0) -> str:
        """class/style attributes for an entrance animation (nothing in static mode)."""
        if self.static:
            return ""
        d = f' style="animation-delay:{n(delay)}s"' if delay else ""
        return f' class="{cls}"{d}'

    def text(self, x, y, s, size, weight=500, fill=None, anchor="start", track=0,
             attrs="") -> float:
        """Draws s with its baseline at y. Returns the width in px."""
        width = measure(s, size, weight, track)
        if anchor == "end":
            x -= width
        elif anchor == "middle":
            x -= width / 2
        wt = ATLAS["weights"][str(weight)]
        k = size / UPM
        pen, uses = 0.0, []
        for i, ch in enumerate(s):
            if wt["path"][ch]:
                gid = f"g{weight // 100}{ord(ch):x}"
                self.glyphs[gid] = wt["path"][ch]
                uses.append(f'<use href="#{gid}" x="{n(pen)}"/>')
            pen += wt["advance"][ch] + track / k
            if i + 1 < len(s):
                pen += wt["kern"].get(ch + s[i + 1], 0)
        g = (f'<g transform="translate({n(x)} {n(y)}) scale({k:.5f} {-k:.5f})" '
             f'fill="{fill or self.t["ink"]}">{"".join(uses)}</g>')
        # animation attributes go on a wrapper: a CSS transform would replace the attribute above
        self.add(f"<g{attrs}>{g}</g>" if attrs else g)
        return width

    def runs(self, x, y, parts, size, attrs="") -> float:
        """Several (text, weight, fill) runs on one baseline."""
        if attrs:
            self.add(f"<g{attrs}>")
        start = x
        for s, weight, fill in parts:
            x += self.text(x, y, s, size, weight, fill)
        if attrs:
            self.add("</g>")
        return x - start

    def frame(self, r: float = 28) -> None:
        t = self.t
        self.defs.append(f'<clipPath id="clip"><rect width="{self.w}" height="{self.h}" rx="{r}"/></clipPath>')
        self.add(f'<rect x=".5" y=".5" width="{self.w - 1}" height="{self.h - 1}" rx="{n(r - .5)}" '
                 f'fill="{t["surface"]}" stroke="{t["border"]}"/>')

    def render(self) -> str:
        glyphs = "".join(f'<path id="{g}" d="{d}"/>' for g, d in sorted(self.glyphs.items()))
        style = "" if self.static else f"<style>{CSS}</style>"
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
                f'width="{self.w}" height="{self.h}" role="img" aria-label="{escape(self.title, {chr(34): "&quot;"})}">'
                f"<title>{escape(self.title)}</title>{style}"
                f'<defs>{"".join(self.defs)}{glyphs}</defs>{"".join(self.body)}</svg>\n')


# ---------------------------------------------------------------- shared pieces

def smooth(points, closed=False) -> str:
    """A Catmull-Rom spline through points, as cubic Béziers."""
    p = list(points)
    m = len(p)
    get = (lambda i: p[i % m]) if closed else (lambda i: p[min(max(i, 0), m - 1)])
    d = [f"M{n(p[0][0])} {n(p[0][1])}"]
    for i in range(m if closed else m - 1):
        p0, p1, p2, p3 = get(i - 1), get(i), get(i + 1), get(i + 2)
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d.append(f"C{n(c1[0])} {n(c1[1])} {n(c2[0])} {n(c2[1])} {n(p2[0])} {n(p2[1])}")
    return "".join(d) + ("Z" if closed else "")


def topo(svg: Svg, cx, cy, rings=6, r0=26, dr=22, seed=1, delay=0.0) -> None:
    """Map contour lines: the texture every card shares."""
    rng = random.Random(seed)
    ph = [rng.uniform(0, math.tau) for _ in range(4)]
    out = []
    for i in range(rings):
        radius = r0 + i * dr
        drift = i * 0.16
        pts = []
        for k in range(14):
            th = math.tau * k / 14
            r = radius * (1 + 0.13 * math.sin(2 * th + ph[0] + drift)
                          + 0.08 * math.sin(3 * th + ph[1] - drift)
                          + 0.04 * math.sin(5 * th + ph[2]))
            pts.append((cx + r * math.cos(th), cy + r * math.sin(th) * 0.82))
        out.append(f'<path d="{smooth(pts, closed=True)}"/>')
    svg.add(f'<g clip-path="url(#clip)"><g fill="none" stroke="{svg.t["teal"]}" stroke-width="1.5" '
            f'opacity="{svg.t["topo"]}"{svg.anim("fade", delay)}>{"".join(out)}</g></g>')


def zmark(svg: Svg, x, y, s=56, attrs="") -> None:
    """The personal mark: a Z drawn as a trail with a waypoint at the end."""
    k = s / 56
    svg.add(f'<g{attrs}><g transform="translate({n(x)} {n(y)}) scale({n(k)})">'
            f'<rect width="56" height="56" rx="16" fill="{MARK}"/>'
            f'<path d="M17 18H39L17 38H31" fill="none" stroke="#fff" stroke-width="5.5" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
            f'<circle cx="39.5" cy="38" r="4.6" fill="#F4B04E"/></g></g>')


def arrow(x, y, s, color, width=2.6) -> str:
    """An up-right arrow in an s×s box whose top-left corner is (x, y)."""
    return (f'<path transform="translate({n(x)} {n(y)})" d="M0 {n(s)}L{n(s)} 0M{n(s * .28)} 0H{n(s)}V{n(s * .72)}" '
            f'fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>')


# ------------------------------------------------------------------------- hero

def jag(points, rng, levels=2, rough=0.20):
    """Midpoint displacement: turns a few peaks into a ridge line."""
    for _ in range(levels):
        out = [points[0]]
        for a, b in zip(points, points[1:]):
            span = b[0] - a[0]
            out.append(((a[0] + b[0]) / 2 + rng.uniform(-.18, .18) * span,
                        (a[1] + b[1]) / 2 + rng.uniform(-1, 1) * rough * span * .5))
            out.append(b)
        points, rough = out, rough * .55
    return points


def hero(theme: str, static: bool) -> str:
    W, H = 1000, 440
    p = PROFILE["hero"]
    svg = Svg(W, H, theme, p["alt"], static)
    t = svg.t
    svg.frame()

    sun = (876, 150)
    svg.defs.append(
        f'<radialGradient id="glow" cx="{sun[0]}" cy="{sun[1]}" r="330" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{t["accent"]}" stop-opacity="{t["glow"]}"/>'
        f'<stop offset="1" stop-color="{t["accent"]}" stop-opacity="0"/></radialGradient>')
    svg.add('<g clip-path="url(#clip)">')
    svg.add(f'<rect width="{W}" height="{H}" fill="url(#glow)"{svg.anim("fade", .2)}/>')

    if theme == "dark":
        rng = random.Random(7)
        stars = []
        for _ in range(34):
            x, y = rng.uniform(560, 985), rng.uniform(22, 150)
            if math.hypot(x - sun[0], y - sun[1]) < 78 or (x < 800 and y > 96):
                continue
            tw = "" if static else f' class="twinkle" style="animation-delay:{n(rng.uniform(0, 3.6))}s"'
            stars.append(f'<circle cx="{n(x)}" cy="{n(y)}" r="{n(rng.uniform(.8, 1.7))}"{tw}/>')
        svg.add(f'<g fill="{t["ink"]}" opacity=".8">{"".join(stars)}</g>')

    svg.add(f'<g{svg.anim("rise", .25)}><circle cx="{sun[0]}" cy="{sun[1]}" r="62" fill="{t["accent"]}" opacity=".16"/>'
            f'<circle cx="{sun[0]}" cy="{sun[1]}" r="42" fill="{t["accent"]}"/></g>')

    ridges = [
        [(540, 392), (620, 352), (668, 368), (744, 300), (800, 330), (880, 222), (936, 286), (1000, 256)],
        [(330, 414), (430, 388), (500, 400), (590, 352), (650, 372), (748, 312), (812, 344), (902, 276), (952, 316), (1000, 300)],
        [(0, 424), (130, 410), (250, 420), (390, 392), (500, 410), (620, 368), (700, 388), (846, 330), (930, 366), (1000, 352)],
    ]
    for i, key in enumerate(ridges):
        pts = jag(key, random.Random(11 + i), levels=2, rough=(.26, .22, .16)[i])
        d = "M" + "L".join(f"{n(x)} {n(y)}" for x, y in pts) + f"L{W} {H}L{n(key[0][0])} {H}Z"
        svg.add(f'<path d="{d}" fill="{t["ridge"][i]}"{svg.anim("rise", .35 + i * .18)}/>')
        if i == 2:
            crest = "M" + "L".join(f"{n(x)} {n(y)}" for x, y in pts)
            svg.add(f'<path d="{crest}" fill="none" stroke="{t["crest"]}" stroke-width="1.5"{svg.anim("fade", 1.1)}/>')

    # the trail: follows the near ridge and ends at a waypoint on its highest pass
    near = ridges[2]
    peak = min(near, key=lambda q: q[1])
    trail_pts = [(-10, 436)] + [(x, y + 20) for x, y in near if x < peak[0]] + [(peak[0] - 26, peak[1] + 30), (peak[0], peak[1] + 14)]
    trail = smooth(trail_pts)
    on_ridge = "#fff" if theme == "light" else t["accent"]
    svg.add(f'<path d="{trail}" fill="none" stroke="{on_ridge}" stroke-width="2.4" stroke-linecap="round" '
            f'stroke-dasharray="1 9" opacity=".9"{svg.anim("fade", 1.3)}/>')
    end = trail_pts[-1]
    if not static:
        svg.add(f'<circle class="ping motion" cx="{n(end[0])}" cy="{n(end[1])}" r="8" fill="{t["accent"]}"/>')
    svg.add(f'<circle cx="{n(end[0])}" cy="{n(end[1])}" r="7.5" fill="{t["accent"]}" stroke="{t["ridge"][2]}" stroke-width="2.5"/>')
    if static:
        mid = trail_pts[5]
        svg.add(f'<circle cx="{n(mid[0])}" cy="{n(mid[1])}" r="6" fill="#fff" stroke="{t["accent"]}" stroke-width="3"/>')
    else:
        svg.add(f'<circle class="motion" r="6" fill="#fff" stroke="{t["accent"]}" stroke-width="3">'
                f'<animateMotion dur="16s" repeatCount="indefinite" calcMode="linear" keyPoints="0;1;1" '
                f'keyTimes="0;.86;1" path="{trail}"/></circle>')
    svg.add("</g>")

    # the words
    zmark(svg, 56, 50, 54, svg.anim("up", 0))
    svg.text(128, 86, p["eyebrow"], 22, 800, t["teal"], track=3.4, attrs=svg.anim("up", .08))
    name, dot = p["name"][:-1], p["name"][-1]
    svg.runs(52, 216, [(name, 800, t["ink"]), (dot, 800, t["accent"])], 112, svg.anim("up", .16))
    for i, line in enumerate(p["tagline"]):
        parts = [(s, 800 if strong else 500, t["ink"] if strong else t["ink2"]) for s, strong in line]
        svg.runs(56, 272 + i * 44, parts, 33, svg.anim("up", .28 + i * .08))
    return svg.render()


# ---------------------------------------------------------------------- buttons

def button(theme: str, static: bool, label: str, primary: bool) -> str:
    H, size, pad, icon, gap = 76, 27, 34, 15, 14
    tw = measure(label, size, 800)
    W = int(round(tw + pad * 2 + gap + icon))
    svg = Svg(W, H, theme, label, static)
    t = svg.t
    if primary:
        svg.add(f'<rect width="{W}" height="{H}" rx="{H / 2}" fill="{t["btn"]}"/>')
        fg = t["on_btn"]
    else:
        svg.add(f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="{H / 2 - 1}" fill="{t["surface"]}" '
                f'stroke="{t["border"]}" stroke-width="2"/>')
        fg = t["ink"]
    svg.text(pad, 47.5, label, size, 800, fg)
    nudge = "" if static else ' class="nudge"'
    svg.add(f'<g{nudge}>{arrow(pad + tw + gap, 31, icon, fg, 3)}</g>')
    return svg.render()


# ------------------------------------------------------------------------ tiles

TW, TH = 490, 232


def door(theme: str, static: bool, index: int, item: dict) -> str:
    """A link into the live product."""
    svg = Svg(TW, TH, theme, f'{item["title"]}. {item["sub"]}', static)
    t = svg.t
    svg.frame(24)
    topo(svg, TW - 64, 46, rings=6, r0=24, dr=20, seed=20 + index, delay=.1)
    svg.text(32, 60, f"{index:02d}", 21, 800, t["teal"], track=2.2, attrs=svg.anim("up", 0))
    nudge = "" if static else ' class="nudge"'
    svg.add(f'<circle cx="{TW - 56}" cy="54" r="24" fill="{t["btn"]}"/>'
            f'<g{nudge}>{arrow(TW - 63.5, 46.5, 15, t["on_btn"], 3)}</g>')
    svg.text(32, 158, item["title"], 42, 800, t["ink"], attrs=svg.anim("up", .08))
    svg.text(32, 196, item["sub"], 24, 500, t["ink2"], attrs=svg.anim("up", .16))
    return svg.render()


def stat(theme: str, static: bool, index: int, item: dict) -> str:
    """A number about the build."""
    label = " ".join(item["label"])
    svg = Svg(TW, TH, theme, f'{item["value"]} {item.get("unit", "")} {label}'.replace("  ", " "), static)
    t = svg.t
    svg.frame(24)
    topo(svg, TW - 40, TH - 24, rings=5, r0=30, dr=24, seed=40 + index, delay=.1)
    svg.add(f'<g{svg.anim("up", 0)}>')
    x = 30 + svg.text(30, 116, item["value"], 96, 800, t["ink"])
    if item.get("unit"):
        svg.text(x + 12, 116, item["unit"], 34, 800, t["teal"])
    svg.add("</g>")
    for i, line in enumerate(item["label"]):
        svg.text(32, 164 + i * 32, line, 24, 500, t["ink2"], attrs=svg.anim("up", .1 + i * .06))
    return svg.render()


# ------------------------------------------------------------------------ pulse

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def day(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def nice_date(d: dt.date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def nice_step(top: float) -> int:
    for step in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
        if top / step <= 4:
            return step
    return 10000


def pulse(theme: str, static: bool, data: dict) -> str:
    W, H = 1000, 474
    days = sorted(data["days"].items())
    today = day(data["updated"])
    last30 = sum(c for d, c in days if 0 <= (today - day(d)).days < 30)
    year = sum(c for d, c in days if 0 <= (today - day(d)).days < 365)

    # weeks start on Sunday, as on the GitHub calendar
    weeks = {}
    for d, c in days:
        dd = day(d)
        start = dd - dt.timedelta(days=(dd.weekday() + 1) % 7)
        weeks[start] = weeks.get(start, 0) + c
    this_week = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    shown = [(this_week - dt.timedelta(weeks=i)) for i in range(25, -1, -1)]
    values = [weeks.get(w, 0) for w in shown]

    svg = Svg(W, H, theme,
              f"Shipping pulse: {last30} contributions in the last 30 days, {year} in the last 12 months. "
              f"Weekly bars for the last 26 weeks, busiest week {max(values)}. Updated {nice_date(today)}.", static)
    t = svg.t
    svg.frame()

    # header
    if not static:
        svg.add(f'<circle class="ping motion" cx="64" cy="55" r="6" fill="{t["teal"]}"/>')
    svg.add(f'<circle cx="64" cy="55" r="6" fill="{t["teal"]}"/>')
    svg.text(84, 62, "SHIPPING PULSE", 20, 800, t["teal"], track=3.2)
    svg.text(W - 56, 62, f"Updated {nice_date(today)}", 20, 500, t["muted"], anchor="end")

    w30 = svg.text(52, 160, f"{last30:,}", 100, 800, t["ink"], attrs=svg.anim("up", .05))
    svg.text(52 + w30 + 22, 124, "contributions", 27, 500, t["ink2"], attrs=svg.anim("up", .12))
    svg.text(52 + w30 + 22, 158, "in the last 30 days", 27, 500, t["ink2"], attrs=svg.anim("up", .12))
    svg.text(W - 56, 124, f"{year:,}", 46, 800, t["ink"], anchor="end", attrs=svg.anim("up", .18))
    svg.text(W - 56, 158, "in the last 12 months", 22, 500, t["ink2"], anchor="end", attrs=svg.anim("up", .18))

    # plot
    x0, x1, top, base = 104, W - 56, 232, 366
    svg.text(56, top - 24, "Contributions per week", 19, 500, t["muted"])
    step = nice_step(max(values) or 1)
    ymax = max(step * math.ceil((max(values) or 1) / step), step)
    y = lambda v: base - (base - top) * v / ymax
    for k in range(0, int(ymax / step) + 1):
        v = k * step
        svg.add(f'<path d="M{x0} {n(y(v))}H{x1}" stroke="{t["hair"]}" stroke-width="1"/>')
        svg.text(x0 - 14, y(v) + 6.5, str(v), 18, 500, t["muted"], anchor="end")
    band = (x1 - x0) / len(shown)
    bw = min(22, band - 2)
    peak = max(range(len(values)), key=lambda i: values[i])
    for i, (wk, v) in enumerate(zip(shown, values)):
        cx = x0 + band * (i + .5)
        if v:
            h = max(base - y(v), 3)
            r = min(4, h)
            fill = t["bar_soft"] if wk == this_week else t["bar"]
            d = (f"M{n(cx - bw / 2)} {base}V{n(base - h + r)}Q{n(cx - bw / 2)} {n(base - h)} {n(cx - bw / 2 + r)} {n(base - h)}"
                 f"H{n(cx + bw / 2 - r)}Q{n(cx + bw / 2)} {n(base - h)} {n(cx + bw / 2)} {n(base - h + r)}V{base}Z")
            svg.add(f'<path d="{d}" fill="{fill}"{svg.anim("grow", .25 + i * .028)}/>')
        if i == peak and v:
            lw = measure(str(v), 20, 800)
            svg.add(f'<g{svg.anim("fade", 1.1)}><rect x="{n(cx - lw / 2 - 5)}" y="{n(y(v) - 29)}" width="{n(lw + 10)}" '
                    f'height="22" fill="{t["surface"]}"/>')
            svg.text(cx, y(v) - 11, str(v), 20, 800, t["ink"], anchor="middle")
            svg.add("</g>")
        if wk.day <= 7:  # first week of a month
            svg.text(cx - bw / 2, base + 30, MONTHS[wk.month - 1], 19, 500, t["muted"])
    svg.add(f'<path d="M{x0} {base}H{x1}" stroke="{t["muted"]}" stroke-width="1" opacity=".6"/>')

    # the milestone, if its week is on screen and there is room to its left
    ms = PROFILE.get("milestone")
    if ms:
        md = day(ms["date"])
        mw = md - dt.timedelta(days=(md.weekday() + 1) % 7)
        if mw in shown:
            i = shown.index(mw)
            cx = x0 + band * (i + .5)
            label_w = measure(ms["label"], 19, 800)
            left_peak = max(values[:i] or [0])
            ly = top + 14
            if cx - 16 - label_w > x0 + 6 and y(left_peak) > ly + 14 and y(values[i]) > ly + 14:
                svg.add(f'<g{svg.anim("fade", 1.3)}>')
                svg.add(f'<path d="M{n(cx)} {n(y(values[i]) - 8)}V{n(ly - 6)}H{n(cx - 10)}" fill="none" '
                        f'stroke="{t["accent"]}" stroke-width="1.5"/>')
                svg.text(cx - 16, ly, ms["label"], 19, 800, t["ink"], anchor="end")
                svg.add("</g>")

    # footer
    fy = H - 30
    site = data.get("site") or {}
    fresh = site.get("verified") and (today - day(site["verified"])).days <= 3
    x = 56
    if fresh:
        svg.add(f'<circle cx="{x + 5}" cy="{fy - 6.5}" r="5" fill="{t["teal"]}"/>')
        x += 20
        x += svg.text(x, fy, PROFILE["site"]["label"], 19, 800, t["ink"])
        svg.text(x, fy, f" is live · checked {nice_date(day(site['verified']))}", 19, 500, t["ink2"])
    else:
        svg.text(x, fy, PROFILE["site"]["label"], 19, 800, t["ink"])
    lw = svg.text(W - 56, fy, "this week so far", 19, 500, t["muted"], anchor="end")
    svg.add(f'<rect x="{n(W - 56 - lw - 24)}" y="{fy - 14}" width="14" height="14" rx="3" fill="{t["bar_soft"]}"/>')
    return svg.render()


# ------------------------------------------------------------------------- data

def refresh() -> dict:
    """Pulls the contribution calendar and checks the site. Keeps what it had on failure."""
    data = json.loads(PULSE_FILE.read_text()) if PULSE_FILE.exists() else {"days": {}, "site": {}}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("--live needs GH_TOKEN")
    query = ('{user(login:"%s"){contributionsCollection{contributionCalendar{weeks{contributionDays'
             "{date contributionCount}}}}}}" % PROFILE["login"])
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-pulse"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    if body.get("errors") or not body.get("data", {}).get("user"):
        sys.exit(f"GitHub did not return the calendar: {body.get('errors')}")
    cal = body["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    data["days"] = {d["date"]: d["contributionCount"] for w in cal["weeks"] for d in w["contributionDays"]}
    today = dt.datetime.now(dt.timezone.utc).date()
    data["updated"] = today.isoformat()

    try:
        req = urllib.request.Request(PROFILE["site"]["url"], headers={"User-Agent": "Mozilla/5.0 (profile-pulse)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            if r.status == 200:
                data.setdefault("site", {})["verified"] = today.isoformat()
    except Exception as e:  # a blocked or slow check is not news: the card just drops the date
        print(f"site check skipped: {e}")
    PULSE_FILE.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="refresh data/pulse.json first")
    ap.add_argument("--static", action="store_true", help="no animation (for screenshots)")
    ap.add_argument("--out", default=str(ROOT / "assets"))
    a = ap.parse_args()
    data = refresh() if a.live else json.loads(PULSE_FILE.read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for theme in THEMES:
        files[f"hero-{theme}.svg"] = hero(theme, a.static)
        files[f"pulse-{theme}.svg"] = pulse(theme, a.static, data)
        for b in PROFILE["buttons"]:
            files[f'btn-{b["id"]}-{theme}.svg'] = button(theme, a.static, b["label"], b.get("primary", False))
        for i, item in enumerate(PROFILE["doors"], 1):
            files[f'door-{item["id"]}-{theme}.svg'] = door(theme, a.static, i, item)
        for i, item in enumerate(PROFILE["stats"], 1):
            files[f'stat-{item["id"]}-{theme}.svg'] = stat(theme, a.static, i, item)
    for name, content in files.items():
        (out / name).write_text(content)
    print(f"{len(files)} images, {sum(len(c) for c in files.values()) // 1024} KB → {out}")


if __name__ == "__main__":
    main()
