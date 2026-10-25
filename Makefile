# Developer entry points for suil-modules.

PROJECT := suil-modules
VENV    := .venv
PIP     := $(VENV)/bin/pip

# Hook environments live in the repository, not in ~/.cache/pre-commit.
export PRE_COMMIT_HOME := $(CURDIR)/.pre-commit

.DEFAULT_GOAL := shell
.PHONY: install shell lint docs docs-build module bump clean


install:
	python3 -m venv --prompt $(PROJECT) $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(VENV)/bin/pre-commit install

lint:
	$(VENV)/bin/pre-commit run --all-files

docs:
	$(VENV)/bin/mkdocs serve --dev-addr 127.0.0.1:8005

docs-build:
	$(VENV)/bin/mkdocs build

# modules/<name>/.cz.yaml from cz-module.yaml; the first tag, <name>-0.1.0, is set by hand.
module:
	@test -n "$(MODULE)" || { echo 'usage: make module MODULE=<name>'; exit 1; }
	@test -d modules/$(MODULE) || { echo 'modules/$(MODULE) does not exist'; exit 1; }
	@test ! -e modules/$(MODULE)/.cz.yaml || { echo 'modules/$(MODULE)/.cz.yaml exists'; exit 1; }
	sed 's/MODULE/$(MODULE)/g' cz-module.yaml | sed '1,2d' > modules/$(MODULE)/.cz.yaml

bump:
	@test -n "$(MODULE)" || { echo 'usage: make bump MODULE=<name>'; exit 1; }
	$(VENV)/bin/cz --config modules/$(MODULE)/.cz.yaml bump

clean:
	rm -rf $(VENV) .pre-commit site

shell:
	@rc="$$(mktemp)"; \
	trap 'rm -f "$$rc"' EXIT; \
	cat ~/.bashrc 2> /dev/null > "$$rc" || true; \
	echo 'export PRE_COMMIT_HOME="$(PRE_COMMIT_HOME)"' >> "$$rc"; \
	echo 'source $(CURDIR)/$(VENV)/bin/activate' >> "$$rc"; \
	bash --rcfile "$$rc" -i
