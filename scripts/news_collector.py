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

from news_rules import alert_coins, coins_in, sentiment, topics_in

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
    # Macro: Reserva Federal, inflación y economía de EE.UU.
    'fed_press': 'https://www.federalreserve.gov/feeds/press_all.xml',
    'fed_monetary': 'https://www.federalreserve.gov/feeds/press_monetary.xml',
    'fed_speeches': 'https://www.federalreserve.gov/feeds/speeches.xml',
    'bls_cpi': 'https://www.bls.gov/feed/cpi.rss',
    'cnbc_economy': 'https://www.cnbc.com/id/20910258/device/rss/rss.html',
}
ATOM = '{http://www.w3.org/2005/Atom}'
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
        coins = coins_in(f"{title} {desc}")
        rows.append((published, source, title, desc, link, 'SOL' in coins, ','.join(coins),
                     ','.join(alert_coins(title)), ','.join(topics_in(title, source))))
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
    await conn.execute("ALTER TABLE news_headlines ADD COLUMN IF NOT EXISTS coins TEXT")   # monedas mencionadas
    await conn.execute("ALTER TABLE news_headlines ADD COLUMN IF NOT EXISTS alerts TEXT")  # alertas de evento grave
    await conn.execute("ALTER TABLE news_headlines ADD COLUMN IF NOT EXISTS topics TEXT")  # macro, fomc
    total = 0
    for source, url in FEEDS.items():
        try:
            rows = fetch_feed(source, url)
            result = await conn.executemany("""
                INSERT INTO news_headlines (published, source, title, summary, link, mentions_sol, coins, alerts, topics)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT (link) DO NOTHING
            """, rows)
            total += len(rows)
        except Exception as e:
            logger.warning(f"⚠️ {source}: {e}")
    # Recalcular etiquetas con las reglas vigentes (titulares antiguos o sin etiquetar)
    old = await conn.fetch("SELECT id, title, summary FROM news_headlines WHERE alerts IS NULL")
    if old:
        await conn.executemany("UPDATE news_headlines SET coins = $2, alerts = $3, mentions_sol = $4 WHERE id = $1", [
            (r['id'], ','.join(coins_in(f"{r['title']} {r['summary']}")), ','.join(alert_coins(r['title'])),
             'SOL' in coins_in(f"{r['title']} {r['summary']}")) for r in old])
    untopiced = await conn.fetch("SELECT id, title, source FROM news_headlines WHERE topics IS NULL")
    if untopiced:
        await conn.executemany("UPDATE news_headlines SET topics = $2 WHERE id = $1",
                               [(r['id'], ','.join(topics_in(r['title'], r['source']))) for r in untopiced])
    # Sentimiento de los titulares aún sin puntuar (VADER + léxico cripto)
    unscored = await conn.fetch("SELECT id, title FROM news_headlines WHERE sentiment IS NULL")
    if unscored:
        await conn.executemany("UPDATE news_headlines SET sentiment = $2 WHERE id = $1",
                               [(r['id'], sentiment(r['title'])) for r in unscored])
    count = await conn.fetchval("SELECT count(*) FROM news_headlines")
    sol = await conn.fetchval("SELECT count(*) FROM news_headlines WHERE mentions_sol")
    await conn.close()
    logger.info(f"📰 {total} titulares leídos | en la DB: {count} ({sol} mencionan SOL)")


if __name__ == '__main__':
    asyncio.run(main())
