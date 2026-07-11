.PHONY: doctor contracts-export eval-contracts eval-data eval-research init install test lint data-pull data-snapshot data-research-snapshot data-convert research research-snapshot risk paper report

PYTHON ?= python

install:
	$(PYTHON) -m pip install -e .[dev]

doctor:
	$(PYTHON) -m quant_agent.cli doctor --profile mvp --config configs/env/dev.yaml

contracts-export:
	$(PYTHON) -m quant_agent.cli contracts export --output artifacts/contracts

eval-contracts:
	$(PYTHON) -m quant_agent.cli eval contracts --suite evals/contracts/v0.1.yaml
	$(PYTHON) -m quant_agent.cli eval contracts --suite evals/contracts/v0.1-hardening.yaml

eval-data:
	$(PYTHON) -m quant_agent.cli eval data --suite evals/data/v0.2.yaml

eval-research:
	$(PYTHON) -m quant_agent.cli eval research --suite evals/research/v0.3.yaml

init:
	$(PYTHON) scripts/init_project.py --config configs/env/dev.yaml

test:
	pytest -q

lint:
	ruff check src tests scripts
	mypy src

data-pull:
	$(PYTHON) scripts/pull_data.py --sample --config configs/env/dev.yaml

data-snapshot:
	$(PYTHON) -m quant_agent.cli data snapshot --config configs/env/dev.yaml

data-research-snapshot:
	$(PYTHON) -m quant_agent.cli data snapshot --provider synthetic-research --config configs/env/dev.yaml

data-convert:
	$(PYTHON) scripts/convert_to_qlib.py --config configs/env/dev.yaml

research:
	$(PYTHON) scripts/run_qlib_backtest.py --env-config configs/env/dev.yaml

research-snapshot:
	@echo "Run: quant-agent research snapshot --snapshot <snapshot_dir>"

risk:
	$(PYTHON) scripts/validate_targets.py --env-config configs/env/dev.yaml

paper:
	$(PYTHON) scripts/run_paper_trading.py --env-config configs/env/dev.yaml

report:
	$(PYTHON) scripts/generate_report.py --env-config configs/env/dev.yaml
