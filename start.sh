#!/usr/bin/env zsh
# start.sh — Inicia todos los servicios de CrewIA en paralelo:
#   1. Backend FastAPI (panel API)
#   2. Frontend Next.js (panel web)
#   3. Nia Agent (Telegram bot + Email watcher)
#
# Uso:
#   ./start.sh              # todos los servicios
#   ./start.sh --no-nia     # solo panel (sin bot Telegram)
#   ./start.sh --no-panel   # solo Nia (sin panel web)

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# ── Flags ────────────────────────────────────────────────────────────────────
START_PANEL=true
START_NIA=true

for arg in "$@"; do
  case "$arg" in
    --no-nia)   START_NIA=false ;;
    --no-panel) START_PANEL=false ;;
  esac
done

# ── Colores ──────────────────────────────────────────────────────────────────
BOLD=$'\033[1m'
RESET=$'\033[0m'
GREEN=$'\033[32m'
CYAN=$'\033[36m'
YELLOW=$'\033[33m'
GRAY=$'\033[90m'

echo ""
echo "${BOLD}🤖  CrewIA — Iniciando servicios${RESET}"
echo "${GRAY}────────────────────────────────────────${RESET}"

PIDS=()

# ── 1. Backend FastAPI ───────────────────────────────────────────────────────
if $START_PANEL; then
  echo "${CYAN}🐍 Backend API${RESET}   → http://localhost:8000"
  echo "${GRAY}   Docs         → http://localhost:8000/docs${RESET}"
  .venv313/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload \
    --log-level warning 2>&1 | sed 's/^/  [api] /' &
  PIDS+=($!)
  sleep 1
fi

# ── 2. Frontend Next.js ──────────────────────────────────────────────────────
if $START_PANEL; then
  echo "${CYAN}⚛️  Panel web${RESET}     → http://localhost:3000"
  cd "$PROJECT_ROOT/web"
  NODE_TLS_REJECT_UNAUTHORIZED=0 npm run dev 2>&1 | sed 's/^/  [web] /' &
  PIDS+=($!)
  cd "$PROJECT_ROOT"
fi

# ── 3. Nia Agent (Telegram + Email) ─────────────────────────────────────────
if $START_NIA; then
  if [ -z "$TELEGRAM_BOT_TOKEN" ] && [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
  fi

  if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "${YELLOW}⚠️  Nia (Telegram)${RESET}  TELEGRAM_BOT_TOKEN no configurado — skipped"
    echo "${GRAY}   Agrega TELEGRAM_BOT_TOKEN=... a .env para activar el bot${RESET}"
  else
    echo "${GREEN}🤖 Nia Agent${RESET}      → Telegram + Email watcher"
    .venv313/bin/python3 main.py --mode nia 2>&1 | sed 's/^/  [nia] /' &
    PIDS+=($!)
  fi
fi

echo "${GRAY}────────────────────────────────────────${RESET}"
if $START_PANEL; then
  echo "${BOLD}✅ Panel activo en http://localhost:3000${RESET}"
fi
echo "${GRAY}   Presiona Ctrl+C para detener todo${RESET}"
echo "${GRAY}────────────────────────────────────────${RESET}"
echo ""

# ── Cleanup ──────────────────────────────────────────────────────────────────
cleanup() {
  echo ""
  echo "Deteniendo servicios (PIDs: ${PIDS[*]})…"
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  exit 0
}
trap cleanup INT TERM

wait "${PIDS[@]}"
