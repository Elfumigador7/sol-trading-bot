#!/usr/bin/env python3
"""
📰 NEWS COLLECTOR - guarda titulares cripto (RSS) en la tabla news_headlines.

Se ejecuta por cron cada 15 min. Construye un historial propio de noticias con hora exacta
para, más adelante, puntuar el sentimiento (p. ej. FinBERT en el PC) y probarlo como feature
o como filtro de riesgo con el mismo walk-forward que el resto.

Ejecutar desde ~/1TRADING: python scripts/news_collector.py
"""

import asyncio
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

import asyncpg
import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

FEEDS = {
    'coindesk': 'https://www.coindesk.com/arc/outboundfeeds/rss/',
    'cointelegraph': 'https://cointelegraph.com/rss',
    'decrypt': 'https://decrypt.co/feed',
    'theblock': 'https://www.theblock.co/rss.xml',
    'bitcoinmagazine': 'https://bitcoinmagazine.com/.rss/full/',
    'cryptoslate': 'https://cryptoslate.com/feed/',
    'cryptopotato': 'https://cryptopotato.com/feed/',
    'blockworks': 'https://blockworks.co/feed',
    'solana_news': 'https://solana.com/news/rss.xml',
    'reddit_solana': 'https://www.reddit.com/r/solana/.rss',   # Atom
}
ATOM = '{http://www.w3.org/2005/Atom}'
COIN_PATTERN = re.compile(r'\b(bitcoin|btc|ethereum|eth|bnb|xrp|ripple|cardano|ada|dogecoin|doge|'
                          r'polkadot|litecoin|ltc|avalanche|avax|chainlink|solana|sol)\b', re.IGNORECASE)
SOL_PATTERN = re.compile(r'\b(solana|sol)\b', re.IGNORECASE)

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'solana_trading'),
    'user': os.getenv('DB_USER', 'solana_user'),
    'password': os.getenv('DB_PASSWORD'),
}


def _clean(html: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html or '')).strip()[:1000]


def fetch_feed(source: str, url: str) -> list[tuple]:
    r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0 (news-collector)'})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    entries = []
    for item in root.iter('item'):  # RSS
        pub = item.findtext('pubDate')
        entries.append((item.findtext('title'), item.findtext('link'),
                        parsedate_to_datetime(pub) if pub else None, item.findtext('description')))
    for e in root.iter(f'{ATOM}entry'):  # Atom (Reddit)
        link = e.find(f'{ATOM}link')
        pub = e.findtext(f'{ATOM}published') or e.findtext(f'{ATOM}updated')
        entries.append((e.findtext(f'{ATOM}title'), link.get('href') if link is not None else None,
                        datetime.fromisoformat(pub) if pub else None, e.findtext(f'{ATOM}content')))
    rows = []
    for title, link, published, desc in entries:
        title, link, desc = (title or '').strip(), (link or '').strip(), _clean(desc)
        if not title or not link or published is None:
            continue
        text = f"{title} {desc}"
        coins = sorted({m.lower() for m in COIN_PATTERN.findall(text)})
        rows.append((published, source, title, desc, link, bool(SOL_PATTERN.search(text)), ','.join(coins)))
    return rows


async def main():
    conn = await asyncpg.connect(**DB_CONFIG)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS news_headlines (
            id SERIAL PRIMARY KEY,
            published TIMESTAMPTZ,
            collected TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            source TEXT,
            title TEXT,
            summary TEXT,
            link TEXT UNIQUE,
            mentions_sol BOOLEAN,
            sentiment REAL          -- se rellenará al puntuar (p. ej. FinBERT)
        )
    """)
    await conn.execute("ALTER TABLE news_headlines ADD COLUMN IF NOT EXISTS coins TEXT")  # monedas mencionadas
    total = 0
    for source, url in FEEDS.items():
        try:
            rows = fetch_feed(source, url)
            result = await conn.executemany("""
                INSERT INTO news_headlines (published, source, title, summary, link, mentions_sol, coins)
                VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (link) DO NOTHING
            """, rows)
            total += len(rows)
        except Exception as e:
            logger.warning(f"⚠️ {source}: {e}")
    count = await conn.fetchval("SELECT count(*) FROM news_headlines")
    sol = await conn.fetchval("SELECT count(*) FROM news_headlines WHERE mentions_sol")
    await conn.close()
    logger.info(f"📰 {total} titulares leídos | en la DB: {count} ({sol} mencionan SOL)")


if __name__ == '__main__':
    asyncio.run(main())
