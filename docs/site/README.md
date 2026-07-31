# docs/site: the GitHub Pages landing page

Everything the published front page needs lives in this folder. There is no
build step and no external request: the page is one hand-written `index.html`,
one stylesheet, self-hosted fonts, and a directory of SVG tiles.

```
docs/site/
├── index.html            the landing page (grid markup is generated; see below)
├── packages.json         the inventory behind the logo grid; edit this
├── assets/
│   ├── style.css         the whole site's styles, landing page and Markdown docs alike
│   ├── theme.js          the day/night switch
│   ├── mark.svg          site mark / favicon
│   ├── mqs-mark.png      MQS mark for the footer credit
│   ├── fonts/*.woff2     IBM Plex Sans + Mono (OFL-1.1, licence alongside)
│   └── logos/*.svg       one tile per package (generated)
└── tools/make_logos.py   regenerates assets/logos/ and the grid in index.html
```

`style.css` and `theme.js` are shared with the Markdown docs, which
`docs/_layouts/default.html` renders, so the whole site is one look. That layout
repeats the header and footer markup by hand, because this page has to render
straight off the filesystem and therefore cannot be a Jekyll template. **Change
the header or footer in one, change it in the other.**

## Design system

The palette, type and spacing come from MQS's own site (the `webpage`
repository, `src/themes/`): IBM Plex Mono for headings and data, IBM Plex Sans
for prose, `#22043B` dark and `#F9F9F9` light surfaces, one orange accent
(`#D36135`), square edges. The ramps are copied verbatim into the custom
properties at the top of `style.css`; take new colours from there rather than
inventing them.

## Day / night

`data-theme="light" | "dark"` on `<html>` selects the palette. A short inline
script in the `<head>` of every page sets it before first paint: stored choice,
then OS preference, then dark (mqs.dk is dark-first); `theme.js` wires the
switch in the header and remembers the choice under `qpubench-theme-mode`. With
JavaScript off, `prefers-color-scheme` blocks in `style.css` still give both
palettes; only the switch is missing.

Both the inline bootstrap and the header markup are duplicated between
`index.html` and `docs/_layouts/default.html`. Anything themed must therefore
respond to `[data-theme]`, not to `prefers-color-scheme` alone; a bare media
query ignores a visitor who has clicked the switch.

## How it gets published

`.github/workflows/pages.yml` assembles the site on every push to `main`:

1. Jekyll renders every Markdown file under `docs/` using `docs/_config.yml`
   (`installation.md` → `/installation.html`, `integrations/hqs.md` →
   `/integrations/hqs.html`, and so on).
2. Jekyll's render of `docs/index.md` is moved to `/guide.html`, so the Markdown
   user guide stays reachable.
3. `docs/site/` is copied over the render, putting this `index.html` at the site
   root. `packages.json`, `tools/` and this README are stripped from the output.

`docs/_config.yml` excludes `site/` so Jekyll does not also publish a copy at
`/site/`.

## Domain and one-time setup

The site is served from **https://qpubench.org**.

`CNAME` in this folder carries that domain. The overlay step copies it to the
artifact root, and the workflow fails the build if it goes missing; without it
a deploy reverts the site to `mqsdk.github.io/qpubench/`.

In the repository, under **Settings → Pages**:

1. **Source** → `GitHub Actions`.
2. **Custom domain** → `qpubench.org`, then Save. GitHub runs a DNS check;
   it will not pass until the records below have propagated.
3. Once the check passes and the certificate is issued (minutes to a few hours),
   tick **Enforce HTTPS**.

### DNS records

Set these at the registrar holding `qpubench.org`. The apex domain is the
canonical one; `www` redirects to it.

| Host | Type | Value |
|---|---|---|
| `@` | A | `185.199.108.153` |
| `@` | A | `185.199.109.153` |
| `@` | A | `185.199.110.153` |
| `@` | A | `185.199.111.153` |
| `@` | AAAA | `2606:50c0:8000::153` |
| `@` | AAAA | `2606:50c0:8001::153` |
| `@` | AAAA | `2606:50c0:8002::153` |
| `@` | AAAA | `2606:50c0:8003::153` |
| `www` | CNAME | `mqsdk.github.io.` |

All four A records (and, for IPv6 visitors, all four AAAA records) are needed;
GitHub load-balances across them. Do **not** add a CNAME on the apex; that
breaks MX and other apex records at most providers.

Optionally, to restrict who may issue certificates for the domain:

| Host | Type | Value |
|---|---|---|
| `@` | CAA | `0 issue "letsencrypt.org"` |

GitHub Pages provisions its certificates through Let's Encrypt, so this record
must be present *before* enforcing HTTPS or the issuance will fail.

### Optional: verify the domain

Without verification, anyone who points a Pages site at `qpubench.org` after this
one stops serving it can take the name over. To claim it for the account,
open **Settings → Pages → Verified domains → Add a domain**, which issues a
one-time token, then add:

| Host | Type | Value |
|---|---|---|
| `_github-pages-challenge-MQSdk` | TXT | *(token shown in the GitHub UI)* |

The token is not reusable and is not recorded here; read it from GitHub at the
time you add the record.

Verify propagation before saving the custom domain in Settings:

```sh
dig +short qpubench.org A
dig +short www.qpubench.org CNAME
```

Every link on the landing page is **relative** (`assets/style.css`,
`backends.html`), so the site also renders correctly at
`mqsdk.github.io/qpubench/` while DNS is still propagating. Only the
`<link rel="canonical">` and `og:url` tags in `index.html` and the `url:` key in
`docs/_config.yml` hard-code the domain; update those three places together if
the domain ever changes.

Because links on the landing page point at Jekyll's *output* paths, they end in
`.html`, not `.md`. Opening `index.html` straight off the filesystem therefore
shows a page with dead documentation links; that is expected.

Prefer a static server over `file://` even for a quick look at the landing page:

```sh
python3 -m http.server --directory docs/site 8000   # then open localhost:8000
```

Browsers treat every `file://` document as its own opaque origin, which can stop
the self-hosted `@font-face` files and the tiles' `mask-image` from loading; the
page then falls back to system fonts and blank tiles, neither of which is a real
problem with the site. To preview the Markdown docs and the shared layout too,
run `bundle exec jekyll serve --source docs` (or push to a branch and let the
workflow build it).

## Editing the package grid

`packages.json` is the single source of truth. Each entry:

```json
{
  "name": "Qiskit Aer",
  "mono": "Aer",
  "url":  "https://github.com/Qiskit/qiskit-aer",
  "upstream": "Qiskit/qiskit-aer",
  "doc":  "backends.html",
  "note": "state-vector simulator, Estimator path"
}
```

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | Wordmark shown on the tile, and its accessible name |
| `url` | yes | Target of the "Upstream" link at the foot of the tile |
| `doc` | yes | QPUBench documentation page, as a published path (`.html`) |
| `note` | yes | One-line caption under the tile |
| `upstream` | no | `maintainer/package` of the repository QPUBench integrates against, shown as "Upstream: `maintainer/package`". Omit it for vendors that publish no source repository; the tile then reads plain "Upstream" and `url` points at the vendor's own page |
| `mono` | no | Monogram override; otherwise derived from initials |
| `slug` | no | Filename override; otherwise slugified from `name` |
| `file` | no | Use this file in `assets/logos/` verbatim instead of generating one |

Name the repository whose code the adapter or loader actually imports, not the
vendor umbrella: the IBM tile is `Qiskit/qiskit-ibm-runtime`, the Braket tile is
`amazon-braket/qiskit-braket-provider` (what `braket_adapter.py` imports), and
Quantinuum is `Quantinuum/pytket-quantinuum`. `url` should point at that same
repository so the label and the link agree.

After editing, regenerate:

```sh
python docs/site/tools/make_logos.py
```

This writes the SVG tiles, deletes orphaned generated tiles, and rewrites the
markup between the `<!-- GRID:BEGIN -->` / `<!-- GRID:END -->` markers in
`index.html`. Do not hand-edit that block; it will be overwritten.

CI runs `python3 docs/site/tools/make_logos.py --check`, which fails the Pages
build if the committed output is stale.

## Logos

<a name="logos"></a>

The tiles are **generated placeholder wordmarks, not vendor artwork**: an
outlined monogram badge plus the package name, in a consistent style. This is
deliberate: the grid reads as one system rather than forty mismatched raster
logos, the site ships no third-party trademarks, and nothing is hotlinked from
another host.

Each tile is a **single-ink silhouette** that the page renders as a CSS mask
(`.logo-mark`) tinted with the current text colour, so tiles follow the day/night
switch and turn orange on hover. An `<img>` could not do that; it cannot see the
page's `data-theme`. Two things follow for anyone editing the generator:

- shapes must be opaque where ink belongs and absent elsewhere, which is why the
  badge is a stroked outline rather than a filled block; and
- colour inside the tile means nothing; the stylesheet supplies it. There is no
  per-package accent any more.

`mask-image` is declared inline on each cell rather than in `style.css`, because
routing the URL through a custom property makes Chrome resolve it against the
stylesheet (`/assets/`) instead of the document, which silently 404s every tile.

To use a project's real logo instead, do either of:

- **Replace the file.** Drop your artwork at `assets/logos/<slug>.svg`. The
  generator only overwrites files carrying its own `data-generated="qpubench"`
  marker on the root element, so a hand-supplied file is left alone from then on.
- **Point at a different file.** Add `"file": "qiskit-aer.png"` to the entry in
  `packages.json` and put that file in `assets/logos/`. The generator skips such
  entries entirely.

Either way the grid marks that entry as real artwork and renders it as an
`<img class="logo-art">`, never masked or tinted, only darkened in the light
theme and greyscaled in the dark one, the way mqs.dk treats partner logos.

Tiles are laid out for a 232 × 64 viewport; artwork of a different aspect ratio
still works (the CSS scales to width) but will look inconsistent beside the
generated ones. Check each project's trademark policy before using its mark.
