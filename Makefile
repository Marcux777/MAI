.DEFAULT_GOAL := help

COMPOSE ?= docker compose

HOST_HOME ?= $(shell sh -c 'if [ -n "$$SUDO_USER" ]; then eval echo "~$$SUDO_USER"; else echo "$$HOME"; fi')
COMPOSE_ENV = HOME="$(HOST_HOME)"

.PHONY: help up up-d down logs ps build qt qt-d

help:
	@printf "%s\n" "MAI (Docker) - comandos rapidos:"
	@printf "%s\n" ""
	@printf "%s\n" "  make up     - sobe a API (foreground)"
	@printf "%s\n" "  make up-d   - sobe a API (background)"
	@printf "%s\n" "  make qt     - sobe API + app Qt (Linux/X11)"
	@printf "%s\n" "  make qt-d   - idem (background)"
	@printf "%s\n" "  make logs   - logs do compose"
	@printf "%s\n" "  make ps     - status dos containers"
	@printf "%s\n" "  make down   - para e remove containers"
	@printf "%s\n" ""
	@printf "%s\n" "Dica: sobrescreva COMPOSE se preciso (ex.: COMPOSE=docker-compose)."

up:
	$(COMPOSE_ENV) $(COMPOSE) up --build

up-d:
	$(COMPOSE_ENV) $(COMPOSE) up --build -d

qt:
	@if command -v xhost >/dev/null 2>&1; then xhost +local: >/dev/null 2>&1 || true; fi
	$(COMPOSE_ENV) $(COMPOSE) --profile qt up --build

qt-d:
	@if command -v xhost >/dev/null 2>&1; then xhost +local: >/dev/null 2>&1 || true; fi
	$(COMPOSE_ENV) $(COMPOSE) --profile qt up --build -d

build:
	$(COMPOSE_ENV) $(COMPOSE) build

logs:
	$(COMPOSE_ENV) $(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE_ENV) $(COMPOSE) ps -a

down:
	$(COMPOSE_ENV) $(COMPOSE) down
