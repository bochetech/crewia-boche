# CrewIA — Makefile
# Uso: make           → levanta todo
#      make panel     → solo panel web + API
#      make nia       → solo Nia (Telegram + email)
#      make stop      → mata todos los procesos de CrewIA
#      make logs      → tail de logs en tiempo real (si se usa nohup)
#      make test      → corre tests básicos
#      make build     → build del frontend

PYTHON  := .venv313/bin/python3
UVICORN := .venv313/bin/uvicorn
NPM     := npm

.PHONY: all panel nia stop logs test build help

## Levanta todos los servicios (panel + Nia)
all:
	@chmod +x start.sh && ./start.sh

## Solo panel web (API + frontend)
panel:
	@chmod +x start.sh && ./start.sh --no-nia

## Solo Nia agent (Telegram + email watcher)
nia:
	@$(PYTHON) main.py --mode telegram

## Build del frontend Next.js
build:
	@cd web && $(NPM) run build

## Corre tests básicos
test:
	@$(PYTHON) test_conversation_memory.py
	@$(PYTHON) test_memory_clustering.py
	@$(PYTHON) test_conversation_format.py
	@echo "✅ Tests básicos OK"

## Mata todos los procesos de CrewIA
stop:
	@echo "Deteniendo servicios…"
	@pkill -f "uvicorn api.main" 2>/dev/null || true
	@pkill -f "main.py --mode telegram" 2>/dev/null || true
	@pkill -f "next dev" 2>/dev/null || true
	@echo "✓ Listo"

## Muestra ayuda
help:
	@echo ""
	@echo "  make          → todos los servicios"
	@echo "  make panel    → solo panel (API + web)"
	@echo "  make nia      → solo Nia (Telegram + email)"
	@echo "  make build    → build frontend"
	@echo "  make test     → tests básicos"
	@echo "  make stop     → detener todo"
	@echo ""
