# CrewIA — Makefile
# Uso: make                           → levanta todo
#      make panel                     → solo panel web + API
#      make nia                       → solo Nia (Telegram + email)
#      make meeting FILE=reunion.mp4  → transcribir y analizar una grabación
#      make stop                      → mata todos los procesos de CrewIA
#      make logs                      → tail de logs en tiempo real (si se usa nohup)
#      make test                      → corre tests básicos
#      make build                     → build del frontend

PYTHON  := .venv313/bin/python3
UVICORN := .venv313/bin/uvicorn
NPM     := npm
FILE    ?= $(error Debes indicar el archivo: make meeting FILE=reunion.mp4)
MODEL   ?= base

.PHONY: all panel nia telegram meeting live stop logs test build help

## Levanta todos los servicios (panel + Nia)
all:
	@chmod +x start.sh && ./start.sh

## Solo panel web (API + frontend)
panel:
	@chmod +x start.sh && ./start.sh --no-nia

## Solo Nia agent (Telegram + Email — modo producción recomendado)
nia:
	@$(PYTHON) main.py --mode nia

## Solo bot de Telegram (sin email)
telegram:
	@$(PYTHON) main.py --mode telegram

## Transcribir y analizar grabación de reunión
## Uso: make meeting FILE=reunion.mp4
##      make meeting FILE=reunion.mp4 MODEL=small
##      make meeting FILE=reunion.mp4 FLOW=strategy_crew
meeting:
	@$(PYTHON) main.py --mode meeting --file "$(FILE)" --whisper-model $(MODEL) $(if $(FLOW),--flow $(FLOW),) $(if $(OUTPUT),--output $(OUTPUT),)

## Escuchar reunión en vivo desde el micrófono (Ctrl+C para detener y analizar)
## Uso: make live
##      make live TITLE="reunion_lunes" MODEL=small
##      make live DEVICE=1  (BlackHole/Loopback para audio del sistema)
live:
	@$(PYTHON) main.py --mode live --title "$(or $(TITLE),reunion)" --whisper-model $(MODEL) $(if $(FLOW),--flow $(FLOW),)

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
	@echo "  make                          → todos los servicios"
	@echo "  make panel                    → solo panel (API + web)"
	@echo "  make nia                      → Nia completa (Telegram + Email)"
	@echo "  make telegram                 → solo bot de Telegram"
	@echo "  make meeting FILE=reunion.mp4 → transcribir grabación de reunión"
	@echo "    opciones: MODEL=small  FLOW=strategy_crew  OUTPUT=informe.md"
	@echo "  make live                     → escuchar reunión en vivo (mic)"
	@echo "    opciones: TITLE=nombre  MODEL=small  DEVICE=1 (audio sistema)"
	@echo "  make build                    → build frontend"
	@echo "  make test                     → tests básicos"
	@echo "  make stop                     → detener todo"
	@echo ""
