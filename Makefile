# Cable-trunking elbow families - developer entry points.
PY := python3
PYDIR := python

.PHONY: help test verify preview dry-run build icons docs clean

help:
	@echo "make test      - unit tests (model, dimplan, builder, fake Revit)"
	@echo "make verify    - 6 families x 41 acceptance checks x 11 sizes, writes docs/04"
	@echo "make preview   - render docs/preview/*.png"
	@echo "make dry-run   - full build pipeline against the fake Revit document"
	@echo "make build     - build the real .rfa files (run inside Revit, needs TEMPLATE=...)"
	@echo "make icons     - redraw the pyRevit ribbon icons"
	@echo "make clean     - remove generated build output"

test:
	cd $(PYDIR) && $(PY) -m unittest discover -s tests -t . -v

verify:
	cd $(PYDIR) && $(PY) verify_families.py --model-only

preview:
	cd $(PYDIR) && $(PY) preview.py --out ../docs/preview

dry-run:
	cd $(PYDIR) && $(PY) build_families.py --dry-run --out ../build/dryrun \
		--report ../docs/05-build-report.md

build:
	cd $(PYDIR) && $(PY) build_families.py --out ../build/families \
		--template "$(TEMPLATE)" --report ../docs/05-build-report.md

icons:
	$(PY) $(PYDIR)/make_icons.py

clean:
	rm -rf build
