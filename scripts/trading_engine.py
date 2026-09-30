#!/usr/bin/env python3
"""
🎯 TRADING ENGINE - Módulo 2 del Sistema de Trading
Carga modelo ONNX, recibe trades en tiempo real y opera en paper trading.

- Solo opera con un modelo validado por scripts/train_model.py (features en sus metadatos).
- Recarga el modelo automáticamente cuando train_model.py exporta uno nuevo.
- Una posición a la vez, con stop-loss, take-profit, salida por tiempo y cooldown.
- Las órdenes reales NO están implementadas: todo es paper trading con comisiones.

Ejecutar desde ~/1TRADING: python scripts/trading_engine.py
"""

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import numpy as np
import onnxruntime as ort
import pandas as pd
from dotenv import load_dotenv

from features import MIN_HISTORY, add_features
from ws_utils import run_ws

# Cargar variables de entorno
load_dotenv()

# Configuración de logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_engine.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuración
MODEL_PATH = Path("models/solana_model_v1.onnx")
PROBABILITY_THRESHOLD = float(os.getenv('PROBABILITY_THRESHOLD', 0.60))
TRADE_SIZE_SOL = float(os.getenv('TRADE_SIZE_SOL', 1.0))
STOP_LOSS_PCT = float(os.getenv('STOP_LOSS_PCT', 0.5))       # % bajo la entrada
TAKE_PROFIT_PCT = float(os.getenv('TAKE_PROFIT_PCT', 1.0))   # % sobre la entrada
COOLDOWN_S = float(os.getenv('COOLDOWN_S', 60))              # espera tras cerrar
FEE_PCT = 0.045                                              # taker Hyperliquid por lado
STATUS_EVERY_S = 60
MODEL_CHECK_EVERY_S = 30

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'solana_trading'),
    'user': os.getenv('DB_USER', 'solana_user'),
    'password': os.getenv('DB_PASSWORD'),
}

HYPERLIQUID_WS_URL = "wss://api.hyperliquid.xyz/ws"


@dataclass
class Position:
    entry_time: float
    entry_price: float
    size: float
    prob: float


class TradingEngine:
    """Motor de trading con modelo ONNX (paper trading)."""

    def __init__(self):
        self.model = None
        self.features = []
        self.horizon_s = 300
        self.model_mtime = -1.0  # distinto de None (= no hay archivo) para loguear el primer estado

        self.trades = deque(maxlen=300)  # (time, price, size, side)
        self.best_bid = 0.0
        self.best_ask = 0.0
        self.last_prob = None

        self.position: Position | None = None
        self.cooldown_until = 0.0
        self.closed = 0
        self.wins = 0
        self.pnl_usd = 0.0
        self.pool = None
        self.last_status = 0.0
        self.last_model_check = 0.0

    # ---------- Modelo ----------

    def maybe_reload_model(self):
        """Cargar el modelo si ha cambiado en disco (o quitarlo si ya no es válido)."""
        mtime = MODEL_PATH.stat().st_mtime if MODEL_PATH.exists() else None
        if mtime == self.model_mtime:
            return
        self.model_mtime = mtime
        self.model, self.features = None, []

        if mtime is None:
            logger.warning(f"⏸️ Sin modelo en {MODEL_PATH}: solo observando. "
                           f"Entrena con: python scripts/train_model.py")
            return

        try:
            session = ort.InferenceSession(str(MODEL_PATH))
            meta = session.get_modelmeta().custom_metadata_map
            features = meta.get('features', '').split(',') if meta.get('features') else []

            # Comprobar que sabemos calcular exactamente las features del modelo
            sample = add_features(pd.DataFrame({
                'time': pd.date_range('2026-01-01', periods=MIN_HISTORY, freq='s', tz='UTC'),
                'price': 100.0, 'size': 1.0, 'side': 'B'}))
            n_inputs = session.get_inputs()[0].shape[1]
            if not features or any(f not in sample.columns for f in features) or len(features) != n_inputs:
                logger.error(f"⛔ Modelo incompatible (features: {features or 'desconocidas'}). "
                             f"Reentrena con: python scripts/train_model.py")
                return

            self.model, self.features = session, features
            self.horizon_s = int(meta.get('horizon_s', 300))
            logger.info(f"✅ Modelo ONNX cargado | features: {features} | horizonte: {self.horizon_s}s")
        except Exception as e:
            logger.error(f"❌ Error cargando modelo: {e}")

    def predict(self) -> float | None:
        """Probabilidad de que el precio supere la entrada + comisiones en el horizonte."""
        if self.model is None or len(self.trades) < MIN_HISTORY:
            return None

        df = add_features(pd.DataFrame(self.trades, columns=['time', 'price', 'size', 'side']))
        last = df[self.features].iloc[-1]
        if last.isna().any():
            return None

        input_data = last.to_numpy(dtype=np.float32).reshape(1, -1)
        probabilities = self.model.run(None, {'float_input': input_data})[1][0]
        return float(probabilities.get(1, 0.0) if isinstance(probabilities, dict) else probabilities[1])

    # ---------- Datos de mercado ----------

    async def on_message(self, data: dict):
        channel = data.get('channel')

        if channel == 'l2Book':
            bids, asks = data['data']['levels']
            if bids and asks:
                self.best_bid = float(bids[0]['px'])
                self.best_ask = float(asks[0]['px'])
                await self.manage_position()

        elif channel == 'trades':
            last_time = self.trades[-1][0] if self.trades else None
            for trade in data['data']:
                t = pd.Timestamp(trade['time'], unit='ms', tz='UTC')
                if last_time is not None and t < last_time:
                    continue  # ya lo teníamos (snapshot al reconectar)
                self.trades.append((t, float(trade['px']), float(trade['sz']), trade['side']))

            self.last_prob = self.predict()
            await self.manage_position()

        now = time.time()
        if now - self.last_model_check >= MODEL_CHECK_EVERY_S:
            self.last_model_check = now
            self.maybe_reload_model()
        self.log_status()

    # ---------- Gestión de la posición ----------

    async def manage_position(self):
        if not (self.best_bid and self.best_ask):
            return
        now = time.time()

        if self.position:
            pos = self.position
            change_pct = (self.best_bid / pos.entry_price - 1) * 100
            if change_pct <= -STOP_LOSS_PCT:
                await self.close_position('STOP_LOSS')
            elif change_pct >= TAKE_PROFIT_PCT:
                await self.close_position('TAKE_PROFIT')
            elif now - pos.entry_time >= self.horizon_s:
                await self.close_position('TIEMPO')
            return

        if (self.last_prob is not None and self.last_prob >= PROBABILITY_THRESHOLD
                and now >= self.cooldown_until):
            await self.open_position(self.last_prob)

    async def open_position(self, prob: float):
        # Paper: compramos al mejor ask (como una orden a mercado)
        self.position = Position(time.time(), self.best_ask, TRADE_SIZE_SOL, prob)
        logger.info(f"🟢 [PAPER] COMPRA {TRADE_SIZE_SOL} SOL @ ${self.best_ask:.3f} | "
                    f"prob {prob:.1%} | SL -{STOP_LOSS_PCT}% TP +{TAKE_PROFIT_PCT}%")

    async def close_position(self, reason: str):
        pos = self.position
        exit_price = self.best_bid
        gross = (exit_price - pos.entry_price) * pos.size
        fees = (pos.entry_price + exit_price) * pos.size * FEE_PCT / 100
        pnl = gross - fees
        pnl_pct = pnl / (pos.entry_price * pos.size) * 100

        self.closed += 1
        self.wins += pnl > 0
        self.pnl_usd += pnl
        self.position = None
        self.cooldown_until = time.time() + COOLDOWN_S

        logger.info(f"🔴 [PAPER] VENTA {pos.size} SOL @ ${exit_price:.3f} ({reason}) | "
                    f"PnL {pnl:+.3f} USD ({pnl_pct:+.3f}%) | "
                    f"total {self.pnl_usd:+.2f} USD en {self.closed} ops ({self.wins / self.closed:.0%} ganadoras)")
        await self.save_trade(pos, exit_price, reason, pnl, pnl_pct)

    async def save_trade(self, pos: Position, exit_price: float, reason: str, pnl: float, pnl_pct: float):
        if self.pool is None:
            return
        try:
            await self.pool.execute("""
                INSERT INTO paper_trades
                (entry_time, exit_time, size, entry_price, exit_price, probability, exit_reason, pnl_usd, pnl_pct)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """, datetime.fromtimestamp(pos.entry_time, tz=timezone.utc), datetime.now(timezone.utc),
                pos.size, pos.entry_price, exit_price, pos.prob, reason, pnl, pnl_pct)
        except Exception as e:
            logger.warning(f"⚠️ No se pudo guardar la operación en la DB: {e}")

    async def warm_up(self):
        """Rellenar el búfer con los últimos trades que guardó el ingester."""
        if self.pool is None:
            return
        try:
            rows = await self.pool.fetch(
                "SELECT timestamp, price, size, side FROM solana_trades "
                "WHERE timestamp > NOW() - INTERVAL '10 minutes' "
                "ORDER BY timestamp DESC, id DESC LIMIT $1", self.trades.maxlen)
            for r in reversed(rows):
                self.trades.append((pd.Timestamp(r['timestamp']), float(r['price']), float(r['size']), r['side']))
            logger.info(f"🔥 Búfer precargado con {len(rows)} trades de la DB")
        except Exception as e:
            logger.warning(f"⚠️ No se pudo precargar el búfer: {e}")

    def log_status(self):
        now = time.time()
        if now - self.last_status < STATUS_EVERY_S:
            return
        self.last_status = now

        prob = f"{self.last_prob:.1%}" if self.last_prob is not None else "—"
        if self.position:
            pos = f"LONG desde ${self.position.entry_price:.3f} ({(self.best_bid / self.position.entry_price - 1) * 100:+.3f}%)"
        else:
            pos = "sin posición"
        model = "activo" if self.model else "ninguno (observando)"
        logger.info(f"📊 SOL ${self.best_bid:.3f}/{self.best_ask:.3f} | prob {prob} | {pos} | "
                    f"modelo {model} | PnL paper {self.pnl_usd:+.2f} USD ({self.closed} ops)")


async def init_db():
    """Pool de conexiones y tabla de operaciones paper."""
    try:
        pool = await asyncpg.create_pool(**DB_CONFIG, min_size=1, max_size=2)
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id SERIAL PRIMARY KEY,
                entry_time TIMESTAMPTZ,
                exit_time TIMESTAMPTZ,
                size NUMERIC(20, 8),
                entry_price NUMERIC(20, 8),
                exit_price NUMERIC(20, 8),
                probability REAL,
                exit_reason TEXT,
                pnl_usd NUMERIC(20, 8),
                pnl_pct NUMERIC(10, 5)
            )
        """)
        logger.info("✅ Tabla paper_trades lista")
        return pool
    except Exception as e:
        logger.warning(f"⚠️ DB no disponible, las operaciones solo irán al log: {e}")
        return None


async def main():
    """Función principal del Trading Engine."""
    engine = TradingEngine()
    engine.maybe_reload_model()

    logger.info(f"🎯 Umbral de probabilidad: {PROBABILITY_THRESHOLD:.0%}")
    logger.info(f"💰 Tamaño de operación: {TRADE_SIZE_SOL} SOL | SL {STOP_LOSS_PCT}% | "
                f"TP {TAKE_PROFIT_PCT}% | cooldown {COOLDOWN_S:.0f}s")
    logger.info("📝 Modo PAPER TRADING (las órdenes reales no están implementadas)")

    engine.pool = await init_db()
    await engine.warm_up()

    subscriptions = [
        {"type": "l2Book", "coin": "SOL"},   # mejor bid/ask para simular fills
        {"type": "trades", "coin": "SOL"},   # el modelo trabaja trade a trade
    ]
    await run_ws(HYPERLIQUID_WS_URL, subscriptions, engine.on_message, logger)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Trading Engine detenido")
