.PHONY: install test clean stats import verify queue send-dry report weekly help web dev api

# Default campaign name (override with CAMPAIGN=name)
CAMPAIGN ?= Q1_2026_initial

help:
	@echo "Outreach Campaign Manager"
	@echo ""
	@echo "Setup:"
	@echo "  make install          Install dependencies"
	@echo "  make test             Run all tests"
	@echo "  make clean            Remove cache files"
	@echo ""
	@echo "Data Pipeline:"
	@echo "  make import           Import CSV + pasted emails + dedupe"
	@echo "  make verify           Verify email addresses (needs API key)"
	@echo "  make stats            Database statistics"
	@echo ""
	@echo "Daily Workflow:"
	@echo "  make queue            Show today's actions"
	@echo "  make send-dry         Preview today's emails (dry run)"
	@echo "  make expandi-export   Export LinkedIn actions for Expandi"
	@echo ""
	@echo "Weekly:"
	@echo "  make weekly           Weekly check-in + plan"
	@echo "  make report           Full campaign dashboard"
	@echo ""
	@echo "Set campaign: make queue CAMPAIGN=my_campaign"
	@echo "Full CLI:     python3 -m src.cli --help"

install:
	pip3 install -e ".[dev]"

test:
	PATH="/opt/homebrew/opt/postgresql@16/bin:$$PATH" python3 -m pytest tests/ -v

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +

# --- Data Pipeline ---

import:
	python3 -m src.cli import-csv "data/imports/Crypto_Fund_List CSV_new.csv"
	python3 -m src.cli import-emails "data/imports/pasted_emails.txt"
	python3 -m src.cli dedupe

verify:
	python3 -m src.cli verify

stats:
	python3 -m src.cli stats

# --- Daily Workflow ---

queue:
	python3 -m src.cli queue "$(CAMPAIGN)" --limit 20

send-dry:
	python3 -m src.cli send "$(CAMPAIGN)" --dry-run

expandi-export:
	python3 -m src.cli export-expandi "$(CAMPAIGN)"

# --- Weekly ---

weekly:
	python3 -m src.cli weekly-plan "$(CAMPAIGN)"

report:
	python3 -m src.cli report "$(CAMPAIGN)"

# --- Web Dashboard ---

web:
	python3 -m src.cli web

api:
	uvicorn src.web.app:app --host 0.0.0.0 --port 8000 --reload

dev:
	cd frontend && npm run dev &
	python3 -m src.cli web --reload
