.PHONY: up down logs test lint migrate seed clean

# Start all services
up:
	docker compose up -d

# Stop all services
down:
	docker compose down

# Tail logs
logs:
	docker compose logs -f

# Run tests (locally, not in Docker)
test:
	pytest -v

# Run linting and type checking
lint:
	ruff check .
	ruff format --check .
	mypy shared/src services/ocr/src

# Format code
format:
	ruff format .
	ruff check --fix .

# Run database migrations
migrate:
	docker compose exec ocr-service alembic upgrade head

# Seed development data
seed:
	docker compose exec ocr-service python /app/scripts/seed_dev_data.py

# Destroy everything including volumes
clean:
	docker compose down -v

# Build Docker images without cache
rebuild:
	docker compose build --no-cache

# Check if RLS is working (quick smoke test)
check-rls:
	docker compose exec postgres psql -U sena -d sena_ai -c "SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public' AND rowsecurity = true;"
