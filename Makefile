# Convenience wrappers around the bot's scripts and uv workflows.
# Run `make` (or `make help`) to list targets.
#
# The pi-* and deploy targets shell out to scripts/, which read PI_HOST from
# .env (see README's "Local development" / "Auto-deploy" sections).

.DEFAULT_GOAL := help

.PHONY: help sync run pi-start pi-stop pi-restart pi-status deploy

help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

sync: ## Create/update the .venv from uv.lock
	uv sync

run: ## Run the bot locally (uv run bot.py)
	uv run bot.py

pi-start: ## Start the bot's service on the Pi
	scripts/pi-bot.sh start

pi-stop: ## Stop the bot's service on the Pi (before a local run)
	scripts/pi-bot.sh stop

pi-restart: ## Restart the bot's service on the Pi
	scripts/pi-bot.sh restart

pi-status: ## Show the bot's service status on the Pi
	scripts/pi-bot.sh status

deploy: ## Trigger an immediate deploy on the Pi
	scripts/pi-deploy.sh
