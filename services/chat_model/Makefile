.PHONY: install test lint format clean run

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v --cov=src/chat_model --cov-report=term-missing

test-unit:
	pytest tests/test_chat_service.py tests/test_audit.py -v

test-integration:
	pytest tests/test_routes.py -v

lint:
	ruff check src/ tests/
	mypy src/chat_model/ --strict

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

clean:
	rm -rf __pycache__ .pytest_cache .mypy_cache .coverage htmlcov
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

run:
	uvicorn src.chat_model.main:create_app --factory --reload --port 8085

dev:
	SENA_AI_LOG_LEVEL=DEBUG make run
