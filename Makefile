PYTHON ?= python
SKILLHUB ?= skillhub
REF ?= HEAD
DIST_DIR ?= dist
VERSION ?= $(shell git show "$(REF):wcl_report_data/__init__.py" | $(PYTHON) -c 'import re, sys; match = re.search(r"__version__ = \"([^\"]+)\"", sys.stdin.read()); print(match.group(1) if match else "")')
ARCHIVE := $(DIST_DIR)/wcl-report-data-$(VERSION).zip
PACKAGE_PATHS := CONTEXT.md LICENSE.md README.md SKILL.md references wcl_report_data

.PHONY: check package publish-dry-run publish clean-package

check:
	$(PYTHON) -m unittest -v
	$(PYTHON) -m compileall -q wcl_report_data tests
	git diff --check

package:
	@test -n "$(VERSION)" || (printf '%s\n' "Unable to resolve the version from $(REF)." >&2; exit 2)
	@mkdir -p "$(DIST_DIR)"
	git archive --format=zip --output="$(ARCHIVE)" "$(REF)" $(PACKAGE_PATHS)
	$(PYTHON) -m zipfile -t "$(ARCHIVE)"
	$(PYTHON) -c 'import sys, zipfile; names = set(zipfile.ZipFile(sys.argv[1]).namelist()); forbidden = {".gitignore", "AGENTS.md", "Makefile"}; found = sorted(names & forbidden); assert not found, f"release archive contains repository-only files: {found}"' "$(ARCHIVE)"
	@printf '%s\n' "Created $(ARCHIVE)"

publish-dry-run: package
	$(SKILLHUB) publish "$(ARCHIVE)" --dry-run --json

publish: publish-dry-run
	@test -n "$(CHANGELOG)" || (printf '%s\n' 'CHANGELOG is required: make publish CHANGELOG="..."' >&2; exit 2)
	$(SKILLHUB) publish "$(ARCHIVE)" --changelog "$(CHANGELOG)" --json

clean-package:
	rm -f "$(ARCHIVE)"
