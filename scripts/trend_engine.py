#!/usr/bin/env python3
"""
📈 TREND ENGINE - exposición gestionada con filtro de tendencia (paper trading), revisión diaria.

Cuentas virtuales (validadas fuera de muestra 2023-09 → 2026-09 en research/, ver docs/ESTADO_BOT.md):
  sol_20d        100 % en SOL si precio > EMA 20 días, 0 % si no
  sol_50d        igual con EMA 50 días
  sol_50d_vol    EMA 50 días + exposición = min(1, 60 % / vol anual 30 d)
  cesta_20d      SOL, BTC y ETH a 1/3 cada una, cada una con su EMA 20 d
  rotacion_top3  las 3 monedas (de 11) que más subieron en 14 d, si están en tendencia y BTC > EMA 50 d
  cesta11_btc    las 11 monedas a 1/11, cada una con su EMA 20 d, solo si BTC > EMA 50 d
  buy_and_hold   referencia: siempre 100 % en SOL
Las señales usan research/portfolio.py: exactamente el mismo código que el backtest.
Sin cortos: en las pruebas, ponerse corto en bajista empeoró todas las variantes.

Funcionamiento: cron lo lanza cada hora (minuto 2). Actúa una vez al día con la señal de la vela de
1 h de las 00:00 UTC (igual que en el backtest); si la primera ejecución falla, la recupera la siguiente. Señal con datos de Binance
(los mismos del backtest); precio de ejecución y funding de Hyperliquid (donde operaría).
Costes por cambio de exposición: comisión taker + slippage. Nada de órdenes reales.

Ejecutar desde ~/1TRADING: python scripts/trend_engine.py [--force]
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import asyncpg
import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research'))
from portfolio import btc_regime, ema_trend, equal_weight, top_momentum  # noqa: E402  (mismo código que el backtest)

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

VOL_WINDOW_H = 24 * 30
VOL_TARGET = 0.60
COST = 0.00045 + 0.0002     # taker + slippage por unidad de exposición cambiada
START_CAPITAL = 1000.0
HISTORY_H = 6000            # suficiente para que la EMA no dependa de su arranque
UNIVERSE = ['BTC', 'ETH', 'BNB', 'XRP', 'ADA', 'DOGE', 'SOL', 'DOT', 'LTC', 'AVAX', 'LINK']  # top-20 en ene-2023


def _sol_50d_vol(c):
    vol = c['SOL'].pct_change().rolling(VOL_WINDOW_H).std() * np.sqrt(24 * 365)
    return ema_trend(c[['SOL']], 50).mul((VOL_TARGET / vol).clip(0, 1), axis=0)


# nombre: función(closes horas × monedas) -> pesos objetivo (mismas funciones que el backtest)
ACCOUNTS = {
    'sol_20d': lambda c: ema_trend(c[['SOL']], 20),
    'sol_50d': lambda c: ema_trend(c[['SOL']], 50),
    'sol_50d_vol': _sol_50d_vol,
    'cesta_20d': lambda c: equal_weight(ema_trend(c[['SOL', 'BTC', 'ETH']], 20)),
    'rotacion_top3': lambda c: btc_regime(top_momentum(c, 14, 3, 20), c, 50),
    'cesta11_btc': lambda c: btc_regime(equal_weight(ema_trend(c, 20)), c, 50),
    'buy_and_hold': lambda c: pd.DataFrame({'SOL': 1.0}, index=c.index),
}

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'solana_trading'),
    'user': os.getenv('DB_USER', 'solana_user'),
    'password': os.getenv('DB_PASSWORD'),
}


def binance_hourly(symbol: str = "SOLUSDT", hours: int = HISTORY_H) -> pd.DataFrame:
    rows, end = [], None
    while len(rows) < hours:
        params = {'symbol': symbol, 'interval': '1h', 'limit': 1500}
        if end:
            params['endTime'] = end
        batch = requests.get("https://fapi.binance.com/fapi/v1/klines", params=params, timeout=30).json()
        if not batch:
            break
        rows = batch + rows
        end = batch[0][0] - 1
        time.sleep(0.3)
    df = pd.DataFrame(rows).iloc[:, :5]
    df.columns = ['open_time', 'open', 'high', 'low', 'close']
    df.index = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    df = df[~df.index.duplicated()].sort_index()
    df = df[df.index + pd.Timedelta(hours=1) <= pd.Timestamp.now(tz='UTC')]  # solo velas cerradas
    return df[['close']].astype(float)


def target_weights(closes: pd.DataFrame) -> dict:
    """Peso objetivo de cada moneda (fracción del capital) por cuenta, al cierre de la última vela."""
    out = {}
    for name, fn in ACCOUNTS.items():
        w = fn(closes).iloc[-1].fillna(0.0)
        out[name] = {coin: float(v) for coin, v in w.items()}
    return out


def hyperliquid_mids() -> dict:
    mids = requests.post("https://api.hyperliquid.xyz/info", json={"type": "allMids"}, timeout=30).json()
    return {coin: float(mids[coin]) for coin in UNIVERSE}


def hyperliquid_funding_sum(since: datetime, coin: str = "SOL") -> float:
    rows = requests.post("https://api.hyperliquid.xyz/info", json={
        "type": "fundingHistory", "coin": coin, "startTime": int(since.timestamp() * 1000)}, timeout=30).json()
    return float(sum(float(r['fundingRate']) for r in rows))


async def main(force: bool):
    closes = pd.DataFrame({coin: binance_hourly(f'{coin}USDT')['close'] for coin in UNIVERSE}).ffill()
    # La señal del día se calcula SIEMPRE con datos hasta la vela de las 00:00 UTC (como en el backtest).
    # Si la ejecución de la 01:02 UTC falla (Pi apagada, sin internet...), cualquier ejecución
    # posterior del mismo día la recupera con la misma señal.
    day_bar = closes.index[-1].floor('D')
    closes = closes[closes.index <= day_bar]
    day = day_bar.date()

    conn = await asyncpg.connect(**DB_CONFIG)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS trend_accounts (
            id SERIAL PRIMARY KEY,
            run_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            day DATE,
            account TEXT,
            equity NUMERIC(20, 4),     -- capital virtual tras ajustar
            weights JSONB,             -- {moneda: peso objetivo}
            prices JSONB,              -- {moneda: mid de Hyperliquid al ajustar}
            funding JSONB,             -- {moneda: funding acumulado desde la revisión anterior}
            signals JSONB,             -- datos de la señal (cierre, EMA, volatilidad)
            UNIQUE (day, account)
        )
    """)
    if await conn.fetchval("SELECT count(*) FROM trend_accounts WHERE day = $1", day) and not force:
        await conn.close()
        return  # ya revisado hoy

    targets = target_weights(closes)
    prices = hyperliquid_mids()
    lines = []
    for name, weights in targets.items():
        prev = await conn.fetchrow(
            "SELECT * FROM trend_accounts WHERE account = $1 AND day < $2 ORDER BY day DESC LIMIT 1", name, day)
        funding = {}
        if prev is None:
            equity, prev_w = START_CAPITAL, {}
        else:
            prev_w = json.loads(prev['weights'])
            prev_px = json.loads(prev['prices'])
            pnl = 0.0
            for coin, w in prev_w.items():
                if w:
                    funding[coin] = hyperliquid_funding_sum(prev['run_time'], coin)
                    pnl += w * (prices[coin] / prev_px[coin] - 1) - w * funding[coin]
            equity = float(prev['equity']) * (1 + pnl)
        turnover = sum(abs(weights.get(c, 0) - prev_w.get(c, 0)) for c in set(weights) | set(prev_w))
        equity *= 1 - turnover * COST
        await conn.execute("""
            INSERT INTO trend_accounts (day, account, equity, weights, prices, funding, signals)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (day, account) DO UPDATE SET run_time = now(), equity = EXCLUDED.equity,
                weights = EXCLUDED.weights, prices = EXCLUDED.prices, funding = EXCLUDED.funding,
                signals = EXCLUDED.signals
        """, day, name, equity, json.dumps(weights), json.dumps(prices), json.dumps(funding), json.dumps({}))

        changes = [f"{c} {prev_w.get(c, 0):.0%}→{weights.get(c, 0):.0%}" for c in sorted(set(weights) | set(prev_w))
                   if abs(weights.get(c, 0) - prev_w.get(c, 0)) > 1e-9]
        held = ', '.join(f"{c} {w:.0%}" for c, w in weights.items() if w > 1e-9) or 'liquidez'
        lines.append(f"{name:<14} capital {equity:>9,.2f} USD ({equity / START_CAPITAL - 1:+6.1%}) | {held}"
                     + (f" | cambios: {'; '.join(changes)}" if changes else ''))
    await conn.close()

    up20 = ema_trend(closes, 20).iloc[-1]
    trend = ' '.join(f"{c}{'↑' if up20[c] else '↓'}" for c in UNIVERSE)
    logger.info(f"📈 {day} | SOL ${prices['SOL']:.2f} | tendencia 20d: {trend}")
    for line in lines:
        logger.info("   " + line)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true', help='Revisar ahora aunque no sea la vela de las 00 UTC')
    asyncio.run(main(parser.parse_args().force))
