.PHONY: up down server ingest test test-sarah lint format typecheck audit

# Infrastructure
up:
	docker-compose up -d

down:
	docker-compose down

# Dev server
server:
	uvicorn main:app --reload --port 8084

# Data ingestion
ingest:
	python scripts/ingest_docs.py --sample

ingest-pdf:
	@[ "$(PDF)" ] || (echo "Usage: make ingest-pdf PDF=<path> CATEGORY='...' SOURCE='...' RISK='High Risk'" && exit 1)
	python scripts/ingest_docs.py --pdf "$(PDF)" --category "$(CATEGORY)" --source "$(SOURCE)" --risk "$(RISK)"

# Tests (standalone smoke runners — not pytest)
test:
	python scripts/test_triage.py
	python scripts/test_rag.py
	python scripts/test_evaluator.py
	python scripts/test_cross_check.py
	python scripts/test_pipeline.py

test-sarah:
	python scripts/test_sarah_note.py

# Code quality
lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy . --ignore-missing-imports

# DB audit — last 5 pipeline runs
audit:
	docker exec -it sena-ai-db psql -U sena_ai -d sena_ai \
	  -c "SELECT case_note_id, triage_flagged, authorisation_status, alert_required, processing_time_ms FROM rp_case_note_runs ORDER BY created_at DESC LIMIT 5;"

# Chunk counts by document type
audit-chunks:
	docker exec -it sena-ai-db psql -U sena_ai -d sena_ai \
	  -c "SELECT document_type, COUNT(*) AS chunks FROM rp_ndis_policy_chunks GROUP BY document_type ORDER BY chunks DESC;"

# Download and ingest all official NDIS PDFs
ingest-ndis:
	mkdir -p pdfs
	python scripts/ingest_ndis_policies.py

# Seed demo BSPs
seed-demo:
	python scripts/seed_demo.py

# Full demo setup: DB up + ingest real PDFs + seed BSPs
demo-setup: up ingest-ndis seed-demo
	@echo ""
	@echo "Demo ready. Run: make server"
