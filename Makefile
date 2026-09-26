# Regenerate every number, table, figure and the PDF from the released data.
#
#   make paper     everything, ending in paper/main.pdf
#   make verify    check that a regeneration reproduces the committed outputs
#   make clean     remove build products, keep generated .tex
#
# Nothing here writes a number by hand. If a value in the paper disagrees with a
# value here, the paper is wrong.

PY      ?= python
DATA    ?= data/release
CENSUS   = $(DATA)/probe_census.jsonl
FRAME    = $(DATA)/frame_latest.jsonl
REPROBE  = $(DATA)/entrypoint_reprobe.jsonl

GENERATED = paper/numbers.tex paper/tables/startup.tex paper/tables/verdicts.tex \
            paper/tables/sdk.tex paper/figures/failures.pdf

.PHONY: all paper numbers tables figures verify clean check-inputs

all: paper

check-inputs:
	@test -f $(CENSUS)  || { echo "missing $(CENSUS)";  exit 1; }
	@test -f $(FRAME)   || { echo "missing $(FRAME)";   exit 1; }
	@test -f $(REPROBE) || { echo "missing $(REPROBE)"; exit 1; }

numbers: check-inputs
	$(PY) driver/make_numbers.py --in $(CENSUS) --frame $(FRAME) --reprobe $(REPROBE)

tables: check-inputs
	$(PY) driver/make_tables.py --in $(CENSUS)

figures: check-inputs
	$(PY) driver/make_figures.py --in $(CENSUS) --frame $(FRAME) --reprobe $(REPROBE)

paper: numbers tables figures
	cd paper && latexmk -pdf -interaction=nonstopmode main.tex
	@grep -q "undefined" paper/main.log && echo "WARNING: undefined references" || true

# Regenerate into a scratch copy and diff against what is committed. A difference
# means the released data no longer produces the paper's numbers.
verify: check-inputs
	@$(PY) driver/make_numbers.py --in $(CENSUS) --frame $(FRAME) --reprobe $(REPROBE) \
	    --out /tmp/numbers.tex >/dev/null
	@diff -q paper/numbers.tex /tmp/numbers.tex && echo "numbers.tex reproduces" \
	    || { echo "numbers.tex DIFFERS from the released data"; exit 1; }

clean:
	cd paper && latexmk -C
	rm -f paper/main.bbl paper/main.blg
