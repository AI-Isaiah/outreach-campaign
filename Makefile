.PHONY: install test clean stats import verify queue send-dry report weekly help web dev api whatsapp-setup whatsapp-scan docker-build docker-up docker-up-d docker-down docker-prod docker-prod-down deploy deploy-logs

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
	pip3 install -e ".[dev,whatsapp]"

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
	cd frontend && PATH="/opt/homebrew/opt/node@22/bin:$$PATH" npx vite --port 8000 &
	.venv/bin/uvicorn src.web.app:app --host 0.0.0.0 --port 8001

# --- WhatsApp ---

whatsapp-setup:
	python3 -c "from src.services.whatsapp_scanner import WhatsAppScanner; s = WhatsAppScanner(); s.setup(); input('Press Enter to save session and exit...'); s.close()"

whatsapp-scan:
	python3 -c "from src.services.whatsapp_scanner import WhatsAppScanner; from src.models.database import get_connection, run_migrations; from src.config import SUPABASE_DB_URL; conn = get_connection(SUPABASE_DB_URL); run_migrations(conn); s = WhatsAppScanner(); s.setup(); print(s.scan_contacts(conn)); s.close(); conn.close()"

# --- Docker ---

docker-build:
	docker build -t outreach-campaign .

docker-up:
	docker compose up --build

docker-up-d:
	docker compose up --build -d

docker-down:
	docker compose down

docker-prod:
	docker compose -f docker-compose.prod.yml up --build

docker-prod-down:
	docker compose -f docker-compose.prod.yml down

# --- Deploy ---

deploy:
	railway up --detach

deploy-logs:
	railway logs
