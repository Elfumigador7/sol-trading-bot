"""
📰 Reglas de noticias compartidas por el recolector, el motor y el panel.

FRENO DE NOTICIAS (reglas fijadas el 2026-09-30, antes de ver resultados; no se ajustan a posteriori):
una noticia genera una ALERTA para una moneda si
  1. la moneda aparece en el TITULAR (no solo en el resumen),
  2. el titular contiene una palabra de evento grave (RISK_PATTERN), y
  3. el titular menciona como máximo 2 monedas (los resúmenes de mercado no cuentan).
La cuenta `rotacion_top3_noticias` no mantiene una moneda con alerta en las últimas 72 h.
"""

import re

COIN_ALIASES = {
    'BTC': r'bitcoin|btc',
    'ETH': r'ethereum|ether|eth',
    'BNB': r'bnb|bnb chain',
    'XRP': r'xrp|ripple',
    'ADA': r'cardano|ada',
    'DOGE': r'dogecoin|doge',
    'SOL': r'solana|sol',
    'DOT': r'polkadot',
    'LTC': r'litecoin|ltc',
    'AVAX': r'avalanche|avax',
    'LINK': r'chainlink',
}
_COIN_RES = {coin: re.compile(rf'\b({alias})\b', re.IGNORECASE) for coin, alias in COIN_ALIASES.items()}

RISK_PATTERN = re.compile(
    r'\b(hack(s|ed|er|ers)?|exploit(s|ed)?|drain(s|ed)?|breach(es|ed)?|vulnerabilit(y|ies)|stolen|theft|'
    r'outage|halt(s|ed)?|downtime|goes down|network (stall|stop|freeze)s?|'
    r'sues?|sued|lawsuit|charges?|charged|indict(ed|ment)?|'
    r'delist(s|ed|ing)?|insolven(t|cy)|bankrupt(cy)?|withdrawals? (paused|halted|suspended|frozen)|'
    r'depeg(s|ged)?|rug ?pull|ponzi|fraud)\b',
    re.IGNORECASE)

# MACRO: noticias que mueven todo el mercado (Fed, tipos, inflación, empleo…). Se registran para usarlas
# como features de mercado (no activan el freno, que es solo para eventos graves de una moneda).
MACRO_SOURCES = {'fed_press', 'fed_monetary', 'fed_speeches', 'bls_cpi'}
MACRO_PATTERN = re.compile(
    r'\b(fed|federal reserve|fomc|powell|interest rates?|rate (cut|hike)s?|basis points?|monetary policy|'
    r'inflation|cpi|pce|jobs report|nonfarm|payrolls|unemployment|treasur(y|ies)|yields?|tariffs?|'
    r'recession|gdp)\b', re.IGNORECASE)
FOMC_PATTERN = re.compile(r'\b(fomc|rate decision|federal open market committee)\b', re.IGNORECASE)

ALERT_WINDOW_H = 72
MAX_COINS_IN_TITLE = 2


def coins_in(text: str) -> list[str]:
    return [coin for coin, rx in _COIN_RES.items() if rx.search(text or '')]


def topics_in(title: str, source: str = '') -> list[str]:
    """Etiquetas de tema: 'macro' (Fed, inflación, empleo…) y 'fomc' (decisiones de tipos)."""
    topics = []
    if source in MACRO_SOURCES or MACRO_PATTERN.search(title or ''):
        topics.append('macro')
    if FOMC_PATTERN.search(title or ''):
        topics.append('fomc')
    return topics


def alert_coins(title: str) -> list[str]:
    """Monedas para las que este titular es una alerta de evento grave (vacío si no lo es)."""
    coins = coins_in(title)
    if not coins or len(coins) > MAX_COINS_IN_TITLE or not RISK_PATTERN.search(title or ''):
        return []
    return coins


# SENTIMIENTO: VADER (léxico general) + léxico financiero/cripto. Puntuación compuesta en [-1, 1].
# Es una primera aproximación ligera para la Pi; más adelante se comparará con FinBERT en el PC.
CRYPTO_LEXICON = {
    'surge': 2.0, 'surges': 2.0, 'soar': 2.2, 'soars': 2.2, 'rally': 2.0, 'rallies': 2.0, 'jumps': 1.5,
    'record': 1.0, 'ath': 2.0, 'bullish': 2.2, 'breakout': 1.2, 'inflows': 1.2, 'adoption': 1.2,
    'approval': 1.5, 'approves': 1.5, 'approved': 1.5, 'upgrade': 1.0, 'partnership': 1.0, 'etf': 0.5,
    'crash': -3.0, 'crashes': -3.0, 'plunge': -2.5, 'plunges': -2.5, 'tumbles': -2.2, 'slumps': -2.0,
    'dump': -2.0, 'dumps': -2.0, 'bearish': -2.2, 'outflows': -1.2, 'liquidation': -1.5, 'liquidations': -1.5,
    'sues': -2.2, 'sued': -2.2, 'lawsuit': -2.2, 'charges': -1.5, 'indicted': -2.5, 'ban': -2.0, 'bans': -2.0,
    'hack': -3.0, 'hacked': -3.0, 'exploit': -3.0, 'exploited': -3.0, 'drained': -2.8, 'breach': -2.5,
    'outage': -2.5, 'halted': -2.0, 'delist': -2.5, 'delisting': -2.5, 'insolvency': -3.0, 'bankruptcy': -3.0,
    'fraud': -3.0, 'rug': -2.5, 'ponzi': -3.0, 'depeg': -2.5, 'stolen': -2.8,
}
_analyzer = None


def sentiment(text: str) -> float:
    global _analyzer
    if _analyzer is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _analyzer = SentimentIntensityAnalyzer()
        _analyzer.lexicon.update(CRYPTO_LEXICON)
    return _analyzer.polarity_scores(text or '')['compound']
