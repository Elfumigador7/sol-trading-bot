#!/usr/bin/env python3
"""
🎯 DATA INGESTER - Módulo 1 del Sistema de Trading
Escucha transacciones SOL en tiempo real desde Hyperliquid WebSocket
y las guarda en TimescaleDB localmente.

Ejecutar: python data_ingester.py
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional
import asyncpg
import websockets

from ws_utils import run_ws
import os

from dotenv import load_dotenv

load_dotenv()

# Configuración de logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_ingester.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuración de la base de datos
DB_CONFIG = {
    'host': 'localhost',  # Cambiar a IP de Pi si se ejecuta externamente
    'port': 5432,
    'database': 'solana_trading',
    'user': 'solana_user',
    'password': os.getenv('DB_PASSWORD')
}

# WebSocket de Hyperliquid (Testnet/Mainnet)
HYPERLIQUID_WS_URL = "wss://api.hyperliquid.xyz/ws"  # Testnet
# HYPERLIQUID_WS_URL = "wss://api.hyperliquid.xyz/information"  # Mainnet


async def init_database():
    """Inicializar la base de datos y crear tablas si no existen."""
    try:
        conn = await asyncpg.connect(**DB_CONFIG)
        
        # Crear tabla principal de trades
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS solana_trades (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                trade_id TEXT,
                side TEXT,
                size NUMERIC(20, 8),
                price NUMERIC(20, 8),
                usd_value NUMERIC(30, 2),
                is_buyer_maker BOOLEAN
            )
        """)
        
        # Crear tabla de precios agregados (para análisis)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS solana_prices (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                price NUMERIC(20, 8),
                volume_1m NUMERIC(30, 4),
                volume_5m NUMERIC(30, 4),
                high_1m NUMERIC(20, 8),
                low_1m NUMERIC(20, 8)
            )
        """)
        
        # Crear índices para mejor rendimiento en consultas temporales
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON solana_trades(timestamp);
            CREATE INDEX IF NOT EXISTS idx_prices_timestamp ON solana_prices(timestamp);
        """)

        # Hyperliquid reenvía los últimos trades al (re)conectar: evitar duplicados
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_trade_id ON solana_trades(trade_id);
        """)
        
        logger.info("✅ Base de datos inicializada correctamente")
        await conn.close()
        
    except Exception as e:
        logger.error(f"❌ Error inicializando DB: {e}")
        raise


async def insert_trades(pool: asyncpg.Pool, trades: list):
    """Insertar un lote de trades de Hyperliquid (ignora los ya guardados)."""
    rows = []
    for trade in trades:
        size = float(trade['sz'])
        price = float(trade['px'])
        rows.append((
            datetime.fromtimestamp(trade['time'] / 1000, tz=timezone.utc),  # hora real del trade
            str(trade['tid']),
            trade['side'].upper(),  # 'B' = compra agresiva, 'A' = venta agresiva
            size,
            price,
            size * price,
            trade['side'].upper() == 'A',  # el comprador era maker si el agresor vendió
        ))

    await pool.executemany("""
        INSERT INTO solana_trades
        (timestamp, trade_id, side, size, price, usd_value, is_buyer_maker)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (trade_id) DO NOTHING
    """, rows)


async def main():
    """Función principal - Bucle de escucha WebSocket con reconexión."""

    # Inicializar base de datos
    await init_database()
    pool = await asyncpg.create_pool(**DB_CONFIG, min_size=1, max_size=2)

    logger.info("🚀 Iniciando Data Ingester...")
    received = 0

    async def handle(data: dict):
        nonlocal received
        if data.get('channel') == 'trades':
            await insert_trades(pool, data['data'])
            received += len(data['data'])
            if received >= 1000:
                logger.info(f"💾 {received} trades recibidos (último @ ${float(data['data'][-1]['px']):.2f})")
                received = 0

    await run_ws(HYPERLIQUID_WS_URL, [{"type": "trades", "coin": "SOL"}], handle, logger)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Data Ingester detenido por el usuario")
