PYTHON ?= python
SKILLHUB ?= skillhub
REF ?= HEAD
DIST_DIR ?= dist
VERSION ?= $(shell if git cat-file -e "$(REF):wcl_raid_coach/__init__.py" 2>/dev/null; then git show "$(REF):wcl_raid_coach/__init__.py"; else $(PYTHON) -c 'print(open("wcl_raid_coach/__init__.py", encoding="utf-8").read())'; fi | $(PYTHON) -c 'import sys; text = sys.stdin.read(); marker = "__version__ = " + chr(34); print(text.split(marker, 1)[1].split(chr(34), 1)[0] if marker in text else "")')
ARCHIVE := $(DIST_DIR)/wcl-raid-coach-$(VERSION).zip
PACKAGE_PATHS := CONTEXT.md LICENSE.md README.md README.en.md SKILL.md assets references wcl_raid_coach

.PHONY: check package package-smoke publish-dry-run publish clean-package

check:
	$(PYTHON) -m unittest -v
	$(PYTHON) -m compileall -q wcl_raid_coach tests tools
	git diff --check

package:
	@test -n "$(VERSION)" || (printf '%s\n' "Unable to resolve the version from $(REF)." >&2; exit 2)
	@mkdir -p "$(DIST_DIR)"
	git archive --format=zip --output="$(ARCHIVE)" "$(REF)" $(PACKAGE_PATHS)
	$(PYTHON) -m zipfile -t "$(ARCHIVE)"
	$(PYTHON) -c 'import sys, zipfile; names = set(zipfile.ZipFile(sys.argv[1]).namelist()); required = {"SKILL.md", "wcl_raid_coach/__main__.py"}; missing = sorted(required - names); forbidden = {".gitignore", "AGENTS.md", "Makefile", "pyproject.toml"}; found = sorted(names & forbidden); assert not missing, f"release archive is missing runtime files: {missing}"; assert not found, f"release archive contains repository-only files: {found}"' "$(ARCHIVE)"
	@printf '%s\n' "Created $(ARCHIVE)"

package-smoke: package
	@tmp="$$(mktemp -d)"; trap 'rm -rf "$$tmp"' EXIT; $(PYTHON) -m zipfile -e "$(ARCHIVE)" "$$tmp"; cd "$$tmp" && $(PYTHON) -m wcl_raid_coach --help >/dev/null

publish-dry-run: package-smoke
	$(SKILLHUB) publish "$(ARCHIVE)" --dry-run --json

publish: publish-dry-run
	@test -n "$(CHANGELOG)" || (printf '%s\n' 'CHANGELOG is required: make publish CHANGELOG="..."' >&2; exit 2)
	$(SKILLHUB) publish "$(ARCHIVE)" --changelog "$(CHANGELOG)" --json

clean-package:
	rm -f "$(ARCHIVE)"
