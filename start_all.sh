#!/bin/bash
# 🚀 INICIO RÁPIDO - Inicia todos los componentes del sistema
# Ejecutar en Raspberry Pi: bash start_all.sh

echo "🎯 Iniciando Sistema de Trading Solana..."
echo ""

# 1. Verificar Docker
if ! docker ps | grep -q timescaledb; then
    echo "🐳 Levantando TimescaleDB..."
    docker-compose up -d timescaledb
    sleep 3
fi

# 2. Iniciar Data Ingester (en segundo plano)
echo "📡 Iniciando Data Ingester..."
source venv/bin/activate
nohup python scripts/data_ingester.py > logs/ingester.log 2>&1 &
INGESTER_PID=$!
echo "   PID: $INGESTER_PID"

# 3. Iniciar Trading Engine (en segundo plano)
echo "🎯 Iniciando Trading Engine..."
nohup python scripts/trading_engine.py > logs/engine.log 2>&1 &
ENGINE_PID=$!
echo "   PID: $ENGINE_PID"

# 4. Iniciar Hot Reload (en segundo plano)
echo "🔄 Iniciando Hot Reload Watcher..."
nohup python scripts/hot_reload.py > logs/reload.log 2>&1 &
RELOAD_PID=$!
echo "   PID: $RELOAD_PID"

echo ""
echo "✅ Todos los servicios iniciados!"
echo ""
echo "📊 Logs en tiempo real:"
echo "   - Data Ingester: tail -f logs/ingester.log"
echo "   - Trading Engine: tail -f logs/engine.log"
echo "   - Hot Reload: tail -f logs/reload.log"
echo ""
echo "💡 Para detener todo: bash stop_all.sh"
