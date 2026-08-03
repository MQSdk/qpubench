#!/usr/bin/env python3
"""Generate the front-page logo tiles and inject the grid markup into index.html.

Reads ``docs/site/packages.json``, writes one SVG tile per package into
``docs/site/assets/logos/``, and rewrites the block between the
``<!-- GRID:BEGIN -->`` / ``<!-- GRID:END -->`` markers in ``docs/site/index.html``.

The tiles are *generated placeholder marks*, not vendor artwork — the package
name set as a wordmark, so the grid reads as one system and the site
carries no third-party trademarks. To use a real logo instead, drop your own
``assets/logos/<slug>.svg`` (or ``.png``, and set ``"file"`` in packages.json)
in place of the generated file; this script only overwrites files it generated,
which it marks with a ``data-generated="qpubench"`` attribute on the root.

Each tile is a single-ink silhouette. The page does not render it as an image but
as a CSS mask tinted with the current text colour (``.logo-mark`` in style.css),
because an ``<img>`` cannot see the page's ``data-theme`` — the day/night switch
would leave the tiles behind. Two consequences for anything drawn here:

* every shape must be opaque where ink belongs and absent elsewhere, which is
  why the mark is type only, with nothing drawn around the wordmark; and
* colour inside the tile carries no meaning — the stylesheet supplies it, which
  is also what turns a tile MQS orange on hover.

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

# The mask is tinted by CSS, so this only has to be opaque. Black keeps the file
# sensible when opened on its own.
INK = "#000000"

# IBM Plex Mono is the MQS display face. A tile used as a CSS mask is loaded as an
# isolated image: it cannot reach the page's @font-face rules, so the stack falls
# back to whatever monospace the viewer has. Every advance in a monospace face is
# 0.6em, which is also what MONO_ADVANCE below assumes.
FONT_STACK = '"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace'
MONO_ADVANCE = 0.6

TILE_W = 232
TILE_H = 64
# Every wordmark starts in the same column, so the grid lines up down the page.
TEXT_X = 4
TEXT_MAX = TILE_W - TEXT_X - 6


def slugify(name: str) -> str:
    """ASCII, lowercase, hyphen-separated — safe as a filename and an anchor."""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_name = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def text_width(text: str, size: float) -> float:
    """Advance width in a monospace face — exact for the stack in FONT_STACK, and
    an over-estimate for any proportional fallback, so the text never overflows."""
    return size * MONO_ADVANCE * len(text)


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
    for size in (14.0, 13.0, 12.0, 11.0, 10.0):
        lines = wrap(name, size)
        if all(text_width(line, size) <= TEXT_MAX for line in lines):
            return lines, size
    return wrap(name, 10.0), 10.0


def render_tile(name: str) -> str:
    lines, size = fit(name)
    leading = size * 1.25
    first_y = TILE_H / 2 + size * 0.35 - (leading * (len(lines) - 1)) / 2

    spans = "\n".join(
        f'  <text class="wm" x="{TEXT_X}" y="{first_y + i * leading:.1f}" '
        f'font-size="{size:g}">{html.escape(line)}</text>'
        for i, line in enumerate(lines)
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" {GENERATED_MARKER}
     viewBox="0 0 {TILE_W} {TILE_H}" width="{TILE_W}" height="{TILE_H}"
     role="img" aria-label="{html.escape(name)}">
  <title>{html.escape(name)}</title>
  <style>
    text {{ font-family: {FONT_STACK}; fill: {INK}; letter-spacing: -0.02em; }}
    .wm {{ font-weight: 600; }}
  </style>
{spans}
</svg>
"""


def is_generated(path: Path) -> bool:
    """Did we write this tile? Anything else is the caller's own artwork.

    A file that does not exist yet counts as ours: the generator is about to
    write it. Binary and unreadable files are not.
    """
    try:
        return GENERATED_MARKER in path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return True
    except (OSError, UnicodeDecodeError):
        return False


def render_grid(groups: list[dict]) -> str:
    out: list[str] = []
    for group in groups:
        out.append(f'<section class="logo-band" id="pkg-{group["id"]}">')
        out.append(f'  <h3>{group["title"]}</h3>')
        out.append(f'  <p class="band-blurb">{group["blurb"]}</p>')
        out.append('  <ul class="logo-grid">')
        for pkg in group["packages"]:
            slug = pkg.get("slug") or slugify(pkg["name"])
            supplied = pkg.get("file")
            file = supplied or f"{slug}.svg"
            name = html.escape(pkg["name"])
            note = html.escape(pkg.get("note", ""))
            # "upstream" names the repository qpubench actually integrates
            # against, as maintainer/package. Vendors that ship no public
            # source repository leave it out and get the bare label.
            repo = html.escape(pkg.get("upstream", ""))
            up_label = f"Upstream: {repo} ↗" if repo else "Upstream ↗"
            # A project whose schema was read off a publication rather than off
            # source gets a second line in the same strip.
            paper = pkg.get("paper")
            if supplied or not is_generated(LOGO_DIR / file):
                # Real artwork, whether pointed at by "file" or dropped in place of
                # a generated tile: render it as an image, never masked or tinted.
                mark = (f'<img class="logo-art" src="assets/logos/{file}" alt="{name}"'
                        f' loading="lazy" width="{TILE_W}" height="{TILE_H}">')
            else:
                # Generated silhouette: tinted by CSS, so it follows the theme.
                # mask-image has to live here rather than in style.css behind a
                # custom property — see the .logo-mark comment in style.css.
                url = f"url(assets/logos/{file})"
                mark = (f'<span class="logo-mark" role="img" aria-label="{name}"'
                        f' style="-webkit-mask-image:{url};mask-image:{url}"></span>')
            strip = (f'<a class="logo-up" href="{pkg["url"]}" rel="noopener"'
                     f' title="{name} upstream project">{up_label}</a>')
            if paper:
                cite = html.escape(paper["label"])
                strip += (f'<a class="logo-up" href="{paper["url"]}" rel="noopener"'
                          f' title="{name} pre-print / paper">'
                          f'Pre-print/Paper: {cite} ↗</a>')
            out.append(
                f'    <li class="logo-cell">'
                f'<a class="logo-link" href="{pkg["doc"]}" '
                f'title="{name}: {note}">'
                f'{mark}'
                f'<span class="logo-note">{note}</span></a>'
                f'<div class="logo-strip">{strip}</div></li>'
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
    for group in groups:
        for pkg in group["packages"]:
            slug = pkg.get("slug") or slugify(pkg["name"])
            if pkg.get("file"):
                continue  # caller supplied their own artwork; never touch it
            path = LOGO_DIR / f"{slug}.svg"
            wanted.add(path.name)
            if not is_generated(path):
                continue  # hand-replaced artwork — leave it alone
            svg = render_tile(pkg["name"])
            existing = path.read_text(encoding="utf-8") if path.exists() else None
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
