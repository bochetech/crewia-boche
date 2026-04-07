#!/usr/bin/env zsh
# start_panel.sh — Inicia el backend FastAPI y el frontend Next.js en paralelo
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "🚀 CrewIA Panel — iniciando servicios..."
echo "────────────────────────────────────────"

# Backend FastAPI en puerto 8000
echo "🐍 Backend FastAPI → http://localhost:8000"
echo "   Docs →            http://localhost:8000/docs"
cd "$PROJECT_ROOT"
.venv313/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Esperar un momento a que el backend arranque
sleep 2

# Frontend Next.js en puerto 3000
echo ""
echo "⚛️  Frontend Next.js → http://localhost:3000"
cd "$PROJECT_ROOT/web"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "────────────────────────────────────────"
echo "✅ Panel activo en http://localhost:3000"
echo "   Presiona Ctrl+C para detener ambos servicios"
echo "────────────────────────────────────────"

# Cleanup on Ctrl+C
trap "echo ''; echo 'Deteniendo servicios...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM

# Esperar a que ambos procesos terminen
wait $BACKEND_PID $FRONTEND_PID
