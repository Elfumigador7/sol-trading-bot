#!/usr/bin/env python3
"""
📸 MARKET SNAPSHOTS - foto cada 5 min del estado de Hyperliquid para las 11 monedas.

Guarda lo que Hyperliquid NO ofrece en histórico y no se podrá descargar después:
  hl_snapshots  open interest, funding, prima, precios mark/oracle/mid, volumen 24 h
  hl_book       spread y profundidad del libro (USD a ±0,1 %, ±0,5 % y ±1 % del mid)

Sirve para: medir el coste real de ejecución de cada moneda (en vez de suponerlo), y tener
un historial propio de posicionamiento en Hyperliquid para investigar más adelante.

Cron: */5 * * * *   Ejecutar desde ~/1TRADING: python scripts/market_snapshots.py
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

import asyncpg
import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

HL_INFO = "https://api.hyperliquid.xyz/info"
COINS = ['BTC', 'ETH', 'BNB', 'XRP', 'ADA', 'DOGE', 'SOL', 'DOT', 'LTC', 'AVAX', 'LINK']
DEPTH_BANDS = (0.001, 0.005, 0.01)

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'solana_trading'),
    'user': os.getenv('DB_USER', 'solana_user'),
    'password': os.getenv('DB_PASSWORD'),
}


def _post(body: dict):
    r = requests.post(HL_INFO, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def asset_contexts(now: datetime) -> list[tuple]:
    meta, ctxs = _post({"type": "metaAndAssetCtxs"})
    names = [a['name'] for a in meta['universe']]
    rows = []
    for coin in COINS:
        c = ctxs[names.index(coin)]
        f = lambda k: float(c[k]) if c.get(k) not in (None, '') else None
        rows.append((now, coin, f('openInterest'), f('funding'), f('premium'), f('markPx'), f('oraclePx'),
                     f('midPx'), f('dayNtlVlm')))
    return rows


def book_metrics(now: datetime, coin: str) -> tuple:
    bids, asks = _post({"type": "l2Book", "coin": coin})['levels']
    best_bid, best_ask = float(bids[0]['px']), float(asks[0]['px'])
    mid = (best_bid + best_ask) / 2
    depth = []
    for band in DEPTH_BANDS:
        bid_usd = sum(float(l['px']) * float(l['sz']) for l in bids if float(l['px']) >= mid * (1 - band))
        ask_usd = sum(float(l['px']) * float(l['sz']) for l in asks if float(l['px']) <= mid * (1 + band))
        depth += [bid_usd, ask_usd]
    return (now, coin, mid, (best_ask - best_bid) / mid, *depth)


async def main():
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    conn = await asyncpg.connect(**DB_CONFIG)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS hl_snapshots (
            time TIMESTAMPTZ, coin TEXT,
            open_interest DOUBLE PRECISION, funding DOUBLE PRECISION, premium DOUBLE PRECISION,
            mark_px DOUBLE PRECISION, oracle_px DOUBLE PRECISION, mid_px DOUBLE PRECISION,
            day_volume_usd DOUBLE PRECISION,
            PRIMARY KEY (time, coin)
        );
        CREATE TABLE IF NOT EXISTS hl_book (
            time TIMESTAMPTZ, coin TEXT, mid DOUBLE PRECISION, spread_pct DOUBLE PRECISION,
            bid_usd_01 DOUBLE PRECISION, ask_usd_01 DOUBLE PRECISION,   -- ±0,1 %
            bid_usd_05 DOUBLE PRECISION, ask_usd_05 DOUBLE PRECISION,   -- ±0,5 %
            bid_usd_1 DOUBLE PRECISION, ask_usd_1 DOUBLE PRECISION,     -- ±1 %
            PRIMARY KEY (time, coin)
        );
    """)
    await conn.executemany("INSERT INTO hl_snapshots VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT DO NOTHING",
                           asset_contexts(now))
    books = []
    for coin in COINS:
        try:
            books.append(book_metrics(now, coin))
        except Exception as e:
            logger.warning(f"⚠️ libro {coin}: {e}")
    await conn.executemany("INSERT INTO hl_book VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT DO NOTHING",
                           books)
    n = await conn.fetchval("SELECT count(DISTINCT time) FROM hl_snapshots")
    await conn.close()
    if now.minute == 0:  # una línea por hora en el log
        spreads = ' '.join(f"{b[1]}:{b[3]:.3%}" for b in books)
        logger.info(f"📸 {n} fotos guardadas | spreads {spreads}")


if __name__ == '__main__':
    asyncio.run(main())
