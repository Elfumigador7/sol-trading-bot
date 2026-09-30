#!/bin/bash
# 🛑 DETENER TODO - Detiene todos los componentes del sistema
echo "🛑 Deteniendo Sistema de Trading..."

# Detener procesos
pkill -f data_ingester.py
pkill -f trading_engine.py
pkill -f hot_reload.py

# Detener Docker
docker-compose down

echo "✅ Todos los servicios detenidos"
