.PHONY: init install test lint data-pull data-convert research risk paper report

PYTHON ?= python

install:
	$(PYTHON) -m pip install -e .[dev]

init:
	$(PYTHON) scripts/init_project.py --config configs/env/dev.yaml

test:
	pytest -q

lint:
	ruff check src tests scripts
	mypy src

data-pull:
	$(PYTHON) scripts/pull_data.py --sample --config configs/env/dev.yaml

data-convert:
	$(PYTHON) scripts/convert_to_qlib.py --config configs/env/dev.yaml

research:
	@echo "Research phase is not implemented in Phase 0/1"

risk:
	@echo "Risk phase is not implemented in Phase 0/1"

paper:
	@echo "Paper trading phase is not implemented in Phase 0/1"

report:
	@echo "Report phase is not implemented in Phase 0/1"
