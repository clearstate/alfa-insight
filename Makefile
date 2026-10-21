SHELL := /bin/bash
COMPOSE := docker compose
PY := uv run

.PHONY: help install up down logs ps test test-unit test-contract test-e2e lint fmt typecheck \
        seed eval fetch-data openapi clean

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Установить зависимости (Python + фронтенд)
	uv sync --all-packages
	cd frontend && npm ci

up: ## Поднять всё окружение одной командой
	$(COMPOSE) up --build -d

down: ## Остановить окружение
	$(COMPOSE) down

logs: ## Поток логов всех сервисов
	$(COMPOSE) logs -f

ps: ## Статус контейнеров
	$(COMPOSE) ps

test: test-unit test-contract ## Все быстрые тесты (LLM заглушён)

test-unit: ## Юнит-тесты сервисов
	$(PY) pytest services

test-contract: ## Проверка сервисов на соответствие contracts/
	$(PY) pytest tests/contract

test-e2e: ## Playwright: вход -> лента -> инсайт -> вопрос -> смена клиента
	cd frontend && npm run test:e2e

lint: ## Линтеры
	uv run ruff check . && cd frontend && npm run lint

fmt: ## Форматирование
	uv run ruff format . && uv run ruff check --fix .

typecheck: ## Проверка типов
	uv run mypy services scripts

seed: ## Залить демо-клиентов и предрасчитать инсайты
	$(PY) scripts/seed_demo.py

eval: ## Посчитать оффлайн-метрики качества
	$(PY) scripts/run_eval.py

fetch-data: ## Скачать исходные данные кейса
	bash scripts/fetch_data.sh

openapi: ## Проверить и собрать спецификацию
	uv run python -m openapi_spec_validator contracts/openapi.yaml

clean: ## Удалить кеши и артефакты
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
