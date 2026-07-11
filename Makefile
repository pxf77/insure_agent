.PHONY: doctor init install test lint data-pull data-convert research risk paper report

PYTHON ?= python

install:
	$(PYTHON) -m pip install -e .[dev]

doctor:
	$(PYTHON) -m quant_agent.cli doctor --profile mvp --config configs/env/dev.yaml

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
	$(PYTHON) scripts/run_qlib_backtest.py --env-config configs/env/dev.yaml

risk:
	$(PYTHON) scripts/validate_targets.py --env-config configs/env/dev.yaml

paper:
	$(PYTHON) scripts/run_paper_trading.py --env-config configs/env/dev.yaml

report:
	$(PYTHON) scripts/generate_report.py --env-config configs/env/dev.yaml
