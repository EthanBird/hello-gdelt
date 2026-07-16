PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
export PYTHONPATH := src

.PHONY: install lint test check preflight probe

install:
	$(PIP) install -e '.[dev]'

lint:
	$(PYTHON) -m ruff check .

test:
	$(PYTHON) -m pytest

check: lint test

preflight:
	$(PYTHON) -m gdelt_world preflight --data-root data

probe:
	$(PYTHON) -m gdelt_world probe --allow-http-fallback \
		--output data/reports/diagnostics/source_probe.json
