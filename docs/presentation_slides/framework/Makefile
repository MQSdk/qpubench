# QPUBench presentation build pipeline
#
# Formats
#   slides.md   — Markdown source (pandoc YAML front matter)  ← edit this
#   slides.org  — Org-mode (generated; open in Emacs for further editing)
#   slides.tex  — LaTeX/Beamer (generated; inspect or customise)
#   slides.pdf  — Final PDF (generated; the deliverable)
#
# Requirements
#   pandoc >= 2.11    (apt: pandoc)
#   pdflatex / xelatex (apt: texlive-full  or  texlive-xetex texlive-fonts-extra)
#   metropolis theme  (apt: texlive-latex-extra  or  texlive-full)
#
# Usage
#   make             build the PDF
#   make pdf         build the PDF
#   make tex         generate LaTeX only (no PDF compilation)
#   make org         generate Org-mode only
#   make all         generate all derived formats (org, tex, pdf)
#   make watch       rebuild PDF on every save of slides.md (requires entr)
#   make clean       remove all generated files
#   make clean-aux   remove LaTeX auxiliary files only (keep pdf)

SRC  := slides.md
ORG  := slides.org
TEX  := slides.tex
PDF  := slides.pdf

# Pandoc flags shared by all targets
PANDOC       := pandoc
PANDOC_FLAGS := --slide-level=2 --standalone --highlight-style=breezedark

# Beamer-specific flags
BEAMER_FLAGS := -t beamer $(PANDOC_FLAGS)

# PDF engine — xelatex gives best results with metropolis + Fira fonts
PDF_ENGINE   := xelatex

# LaTeX auxiliary file extensions to remove
AUX_EXTS := aux log nav out snm toc vrb blg bbl fls fdb_latexmk

.PHONY: all pdf tex org watch clean clean-aux

# Default target
pdf: $(PDF)

all: $(ORG) $(TEX) $(PDF)

# ── PDF via pandoc → xelatex ────────────────────────────────────────────────
$(PDF): $(SRC)
	$(PANDOC) $(BEAMER_FLAGS) \
	    --pdf-engine=$(PDF_ENGINE) \
	    -o $@ $<
	@echo "✓  $(PDF) ready"

# ── LaTeX/Beamer source ─────────────────────────────────────────────────────
$(TEX): $(SRC)
	$(PANDOC) $(BEAMER_FLAGS) \
	    -o $@ $<
	@echo "✓  $(TEX) ready"

tex: $(TEX)

# ── Org-mode ────────────────────────────────────────────────────────────────
# Pandoc converts headings and blocks; add #+BEAMER_* headers manually
# if you want to export directly from Emacs org-beamer.
$(ORG): $(SRC)
	$(PANDOC) -f markdown -t org $(PANDOC_FLAGS) \
	    -o $@ $<
	@# Prepend org-beamer export headers
	@{ printf '#+OPTIONS: H:2 toc:nil num:nil\n'; \
	   printf '#+BEAMER_THEME: metropolis\n'; \
	   printf '#+BEAMER_HEADER: \\metroset{block=fill}\n'; \
	   printf '#+BEAMER_HEADER: \\setbeamertemplate{navigation symbols}{}\n'; \
	   printf '#+LATEX_HEADER: \\usepackage{booktabs}\n\n'; \
	   cat $@; } > $@.tmp && mv $@.tmp $@
	@echo "✓  $(ORG) ready"

org: $(ORG)

# ── Watch mode (requires entr) ───────────────────────────────────────────────
watch:
	@command -v entr >/dev/null 2>&1 || \
	    { echo "entr not found — install with: apt install entr"; exit 1; }
	echo $(SRC) | entr -c make pdf

# ── Cleanup ─────────────────────────────────────────────────────────────────
clean-aux:
	@for ext in $(AUX_EXTS); do \
	    rm -f slides.$$ext; \
	done
	@echo "✓  LaTeX auxiliary files removed"

clean: clean-aux
	rm -f $(ORG) $(TEX) $(PDF)
	@echo "✓  All generated files removed"
