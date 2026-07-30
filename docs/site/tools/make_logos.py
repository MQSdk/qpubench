#!/usr/bin/env python3
"""Generate the front-page logo tiles and inject the grid markup into index.html.

Reads ``docs/site/packages.json``, writes one SVG tile per package into
``docs/site/assets/logos/``, and rewrites the block between the
``<!-- GRID:BEGIN -->`` / ``<!-- GRID:END -->`` markers in ``docs/site/index.html``.

The tiles are *generated placeholder marks*, not vendor artwork — a consistent
monogram + wordmark per package, so the grid reads as one system and the site
carries no third-party trademarks. To use a real logo instead, drop your own
``assets/logos/<slug>.svg`` (or ``.png``, and set ``"file"`` in packages.json)
in place of the generated file; this script only overwrites files it generated,
which it marks with a ``data-generated="qpubench"`` attribute on the root.

Usage:
    python docs/site/tools/make_logos.py            # regenerate everything
    python docs/site/tools/make_logos.py --check    # fail if output is stale
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
LOGO_DIR = SITE / "assets" / "logos"
INDEX = SITE / "index.html"
INVENTORY = SITE / "packages.json"

GENERATED_MARKER = 'data-generated="qpubench"'

# Curated accent palette. Every hue is legible as a solid fill behind white
# monogram text in both light and dark page backgrounds (contrast >= 4.5:1
# against #ffffff for the darker end, and the tile never sits on white alone).
PALETTE = [
    "#2f6fd0", "#1a9a7a", "#c0562e", "#7048c4", "#0f8ab5",
    "#a8382f", "#4a7a1e", "#b0722a", "#3d5aa8", "#8a3d86",
    "#177a94", "#96541f", "#5a6b1f", "#a03a63", "#2a6e5e",
]

TILE_W = 232
TILE_H = 64
BADGE = 44
BADGE_X = 4
BADGE_Y = (TILE_H - BADGE) / 2
TEXT_X = BADGE_X + BADGE + 12
TEXT_MAX = TILE_W - TEXT_X - 6


def slugify(name: str) -> str:
    """ASCII, lowercase, hyphen-separated — safe as a filename and an anchor."""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_name = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def monogram(name: str) -> str:
    """Up to three characters: initials for multi-word names, else a prefix."""
    words = [w for w in re.split(r"[\s_\-/]+", name) if w]
    if len(words) >= 2:
        return "".join(w[0] for w in words[:3]).upper()
    return name[:2].capitalize()


def accent(slug: str, index: int) -> str:
    """Deterministic colour — stable across runs, spread across the palette."""
    return PALETTE[(index * 7 + sum(slug.encode())) % len(PALETTE)]


def text_width(text: str, size: float) -> float:
    """Rough advance width for the sans stack. Wide enough to avoid overflow."""
    narrow = sum(1 for c in text if c in "iljtfrI.,:;'|()[]-")
    wide = sum(1 for c in text if c in "mwMW@")
    other = len(text) - narrow - wide
    return size * (0.30 * narrow + 0.90 * wide + 0.58 * other)


def wrap(name: str, size: float) -> list[str]:
    """Split the wordmark over at most two lines that fit ``TEXT_MAX``."""
    if text_width(name, size) <= TEXT_MAX:
        return [name]
    words = name.split(" ")
    if len(words) == 1:
        return [name]
    best: tuple[float, list[str]] | None = None
    for cut in range(1, len(words)):
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
        widest = max(text_width(line, size) for line in lines)
        if best is None or widest < best[0]:
            best = (widest, lines)
    assert best is not None
    return best[1]


def fit(name: str) -> tuple[list[str], float]:
    """Largest size in the ladder whose wrapped lines fit the tile."""
    for size in (15.0, 14.0, 13.0, 12.0, 11.0, 10.0):
        lines = wrap(name, size)
        if all(text_width(line, size) <= TEXT_MAX for line in lines):
            return lines, size
    return wrap(name, 10.0), 10.0


def render_tile(name: str, mono: str, colour: str) -> str:
    lines, size = fit(name)
    leading = size * 1.25
    first_y = TILE_H / 2 + size * 0.35 - (leading * (len(lines) - 1)) / 2
    mono_size = 19.0 if len(mono) <= 2 else 15.0

    spans = "\n".join(
        f'    <text class="wm" x="{TEXT_X}" y="{first_y + i * leading:.1f}" '
        f'font-size="{size:g}">{html.escape(line)}</text>'
        for i, line in enumerate(lines)
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" {GENERATED_MARKER}
     viewBox="0 0 {TILE_W} {TILE_H}" width="{TILE_W}" height="{TILE_H}"
     role="img" aria-label="{html.escape(name)}">
  <title>{html.escape(name)}</title>
  <style>
    .wm {{ font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
           font-weight: 600; fill: #1c2333; letter-spacing: -0.01em; }}
    .mg {{ font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
           font-weight: 700; fill: #ffffff; letter-spacing: -0.02em; }}
    @media (prefers-color-scheme: dark) {{ .wm {{ fill: #e6ebf5; }} }}
  </style>
  <rect x="{BADGE_X}" y="{BADGE_Y:g}" width="{BADGE}" height="{BADGE}" rx="13"
        fill="{colour}"/>
  <text class="mg" x="{BADGE_X + BADGE / 2:g}" y="{TILE_H / 2 + mono_size * 0.35:.1f}"
        font-size="{mono_size:g}" text-anchor="middle">{html.escape(mono)}</text>
{spans}
</svg>
"""


def render_grid(groups: list[dict]) -> str:
    out: list[str] = []
    for group in groups:
        out.append(f'<section class="logo-band" id="pkg-{group["id"]}">')
        out.append(f'  <h3>{group["title"]}</h3>')
        out.append(f'  <p class="band-blurb">{group["blurb"]}</p>')
        out.append('  <ul class="logo-grid">')
        for pkg in group["packages"]:
            slug = pkg.get("slug") or slugify(pkg["name"])
            file = pkg.get("file") or f"{slug}.svg"
            name = html.escape(pkg["name"])
            note = html.escape(pkg.get("note", ""))
            out.append(
                f'    <li class="logo-cell">'
                f'<a class="logo-link" href="{pkg["doc"]}" '
                f'title="{name} — {note}">'
                f'<img src="assets/logos/{file}" alt="{name}" loading="lazy" '
                f'width="{TILE_W}" height="{TILE_H}">'
                f'<span class="logo-note">{note}</span></a>'
                f'<a class="logo-up" href="{pkg["url"]}" rel="noopener"'
                f' title="{name} upstream project">upstream ↗</a></li>'
            )
        out.append("  </ul>")
        out.append("</section>")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify generated output is up to date; write nothing")
    args = parser.parse_args()

    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    groups = inventory["groups"]
    LOGO_DIR.mkdir(parents=True, exist_ok=True)

    stale: list[str] = []
    wanted: set[str] = set()
    index = 0
    for group in groups:
        for pkg in group["packages"]:
            slug = pkg.get("slug") or slugify(pkg["name"])
            if pkg.get("file"):
                continue  # caller supplied their own artwork; never touch it
            path = LOGO_DIR / f"{slug}.svg"
            wanted.add(path.name)
            svg = render_tile(pkg["name"], pkg.get("mono") or monogram(pkg["name"]),
                              pkg.get("color") or accent(slug, index))
            index += 1
            existing = path.read_text(encoding="utf-8") if path.exists() else None
            if existing is not None and GENERATED_MARKER not in existing:
                continue  # hand-replaced artwork — leave it alone
            if existing == svg:
                continue
            if args.check:
                stale.append(str(path.relative_to(SITE)))
            else:
                path.write_text(svg, encoding="utf-8")

    for orphan in sorted(LOGO_DIR.glob("*.svg")):
        if orphan.name in wanted:
            continue
        if GENERATED_MARKER not in orphan.read_text(encoding="utf-8"):
            continue
        if args.check:
            stale.append(f"{orphan.relative_to(SITE)} (orphaned)")
        else:
            orphan.unlink()

    grid = render_grid(groups)
    page = INDEX.read_text(encoding="utf-8")
    new_page, subs = re.subn(
        r"<!-- GRID:BEGIN -->.*?<!-- GRID:END -->",
        lambda _: f"<!-- GRID:BEGIN -->\n{grid}\n<!-- GRID:END -->",
        page,
        flags=re.DOTALL,
    )
    if subs != 1:
        print(f"error: expected 1 GRID marker block in {INDEX}, found {subs}",
              file=sys.stderr)
        return 1
    if new_page != page:
        if args.check:
            stale.append("index.html (grid markup)")
        else:
            INDEX.write_text(new_page, encoding="utf-8")

    if args.check and stale:
        print("Stale generated site output:", file=sys.stderr)
        for item in stale:
            print(f"  - {item}", file=sys.stderr)
        print("Run: python docs/site/tools/make_logos.py", file=sys.stderr)
        return 1

    total = sum(len(g["packages"]) for g in groups)
    print(f"{'checked' if args.check else 'wrote'} {total} tiles across "
          f"{len(groups)} groups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
