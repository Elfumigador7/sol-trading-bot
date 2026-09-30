"""Reglas del freno de noticias (fijadas antes de ver resultados) y sentimiento."""
import pytest

from news_rules import alert_coins, coins_in, sentiment


@pytest.mark.parametrize("title, expected", [
    ("Solana network suffers outage, block production halted", ["SOL"]),
    ("SEC sues Ripple over XRP sales", ["XRP"]),
    ("Avalanche bridge exploited for $12M", ["AVAX"]),
    ("Solana hackathon winners announced", []),                       # 'hackathon' no es 'hack'
    ("Chainlink launches new oracle product", []),                    # sin evento grave
    ("Crypto crash: bitcoin, ether, solana and xrp hacked", []),      # > 2 monedas: resumen de mercado
    ("Polkadot dot com", []),                                         # 'dot' suelto no es DOT
])
def test_alert_rules(title, expected):
    assert alert_coins(title) == expected


def test_coin_tagging_uses_tickers():
    assert coins_in("Ethereum and Solana lead the rally") == ["ETH", "SOL"]


def test_sentiment_has_crypto_vocabulary():
    assert sentiment("Bitcoin surges to record high as ETF inflows soar") > 0.5
    assert sentiment("Solana network suffers outage, block production halted") < -0.5
