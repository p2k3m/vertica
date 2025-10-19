.PHONY: install fmt lint test local-up local-down destroy

install:
	pip install uv
	uv sync

fmt:
	uv run ruff check --fix

lint:
	uv run ruff check

test:
	uv run pytest -q

local-up:
	docker compose up --build -d

local-down:
	docker compose down

destroy:
	cd infra && terraform destroy -auto-approve
