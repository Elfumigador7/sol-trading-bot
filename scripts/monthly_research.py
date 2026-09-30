#!/usr/bin/env python3
"""
🔬 INVESTIGACIÓN MENSUAL (autoentrenamiento con barreras). Cron: día 1 de cada mes.

1. Actualiza los datos (11 monedas, 2020 → hoy).
2. Seguimiento: backtest de cada cuenta hasta hoy y comparación con lo que hizo en paper.
3. Retador: meta-labeling sobre la rotación (research/meta.py), reentrenado con TODOS los datos
   disponibles, más variantes con noticias cuando haya ≥ 90 días de titulares.
4. BARRERA (fijada el 2026-09-30, antes de ver resultados). Un retador se ACTIVA en paper solo si:
     - su Sharpe fuera de muestra supera al de la rotación sin filtro en el periodo completo
       y en cada subperiodo (2021-07 → 2023-08 y 2023-09 → hoy),
     - su caída máxima no es peor que la de la rotación, y
     - su Deflated Sharpe Ratio ≥ 0,95 contando TODAS las variantes probadas en todos los meses
       (registro acumulado en models/research_trials.json).
   Si deja de cumplirla, se desactiva. Nunca opera con dinero real.
5. Escribe reports/investigacion_AAAA-MM.md.

Ejecutar desde ~/1TRADING: python scripts/monthly_research.py
"""

import asyncio
import json
import os
import pickle
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'research'))
sys.path.insert(0, str(ROOT / 'scripts'))
warnings.filterwarnings('ignore')

import meta  # noqa: E402
from lab import deflated_sharpe, metrics  # noqa: E402
from portfolio import load_universe  # noqa: E402

load_dotenv()
MODELS = ROOT / 'models'
REPORTS = ROOT / 'reports'
TRIALS_FILE = MODELS / 'research_trials.json'
CHALLENGER_FILE = MODELS / 'challenger.json'
CHALLENGER_MODEL = MODELS / 'challenger.pkl'
SPLIT = pd.Timestamp('2023-09-01', tz='UTC')
MIN_NEWS_DAYS = 90
THRESHOLDS = (0.50, 0.55)

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'), 'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'solana_trading'), 'user': os.getenv('DB_USER', 'solana_user'),
    'password': os.getenv('DB_PASSWORD'),
}


async def news_features() -> tuple[pd.DataFrame | None, int]:
    """Sentimiento medio y nº de alertas por (día, moneda) en los 3 días previos. None si hay poco historial."""
    conn = await asyncpg.connect(**DB_CONFIG)
    rows = await conn.fetch("SELECT published, coins, alerts, sentiment FROM news_headlines "
                            "WHERE coins <> '' AND published >= (SELECT min(collected) FROM news_headlines)")
    macro_rows = await conn.fetch("SELECT published, topics, sentiment FROM news_headlines "
                                  "WHERE topics LIKE '%macro%' AND published >= (SELECT min(collected) FROM news_headlines)")
    # Historial = desde que empezamos a RECOGER (algunas fuentes publican artículos antiguos)
    first = await conn.fetchval("SELECT min(collected) FROM news_headlines")
    await conn.close()
    days = (datetime.now(timezone.utc) - first).days if first else 0
    if days < MIN_NEWS_DAYS or not rows:
        return None, days
    recs = []
    for r in rows:
        for coin in r['coins'].split(','):
            recs.append((pd.Timestamp(r['published']).floor('D'), coin, r['sentiment'] or 0.0,
                         float(coin in (r['alerts'] or '').split(','))))
    df = pd.DataFrame(recs, columns=['day', 'coin', 'sent', 'alert'])
    out = []
    for coin, g in df.groupby('coin'):
        d = g.groupby('day').agg(sent=('sent', 'mean'), alert=('alert', 'sum'))
        d = d.reindex(pd.date_range(d.index.min(), pd.Timestamp.now(tz='UTC').floor('D'), freq='D')).fillna(0)
        # usar solo días ANTERIORES al de la decisión (shift 1) para no mirar al futuro
        roll = pd.DataFrame({'sent_3d': d['sent'].rolling(3).mean().shift(1),
                             'alerts_3d': d['alert'].rolling(3).sum().shift(1)})
        roll['coin'] = coin
        out.append(roll)
    nf = pd.concat(out).reset_index(names='day')
    # Macro (Fed, inflación, empleo…): mismo valor para todas las monedas de un día
    m = pd.DataFrame([(pd.Timestamp(r['published']).floor('D'), r['sentiment'] or 0.0, float('fomc' in (r['topics'] or '')))
                      for r in macro_rows], columns=['day', 'sent', 'fomc'])
    if len(m):
        md = m.groupby('day').agg(sent=('sent', 'mean'), fomc=('fomc', 'sum'))
        md = md.reindex(pd.date_range(md.index.min(), pd.Timestamp.now(tz='UTC').floor('D'), freq='D')).fillna(0)
        macro = pd.DataFrame({'macro_sent_3d': md['sent'].rolling(3).mean().shift(1),
                              'fomc_3d': md['fomc'].rolling(3).sum().shift(1)})
        nf = nf.merge(macro, left_on='day', right_index=True, how='left')
    nf = nf.set_index(['day', 'coin'])
    return nf, days


def sharpe(r: pd.Series) -> float:
    return float(r.mean() / r.std() * np.sqrt(24 * 365)) if r.std() > 0 else 0.0


def load_trials() -> dict:
    return json.loads(TRIALS_FILE.read_text()) if TRIALS_FILE.exists() else {}


def main():
    MODELS.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    month = datetime.now(timezone.utc).strftime('%Y-%m')
    u = load_universe(start='2020-01')
    close = u['close']
    lines = [f"# 🔬 Investigación mensual — {month}", "",
             f"Datos: {close.index[0]:%Y-%m-%d} → {close.index[-1]:%Y-%m-%d %H:%M} UTC, {close.shape[1]} monedas.", ""]

    # --- Retadores ---
    news, news_days = asyncio.run(news_features())
    variants = [('meta', meta.FEATURES, None)]
    if news is not None:
        variants.append(('meta_noticias', meta.FEATURES + meta.NEWS_FEATURES, news))
    lines.append(f"Noticias: {news_days} días de historial "
                 + ("→ variante con noticias incluida." if news is not None
                    else f"(se incluirán al llegar a {MIN_NEWS_DAYS} días)."))

    champion = meta.evaluate(u, meta.rotation_weights(close), meta.FIRST_TEST)
    periods = {'completo': (meta.FIRST_TEST, None), '2021-07→2023-08': (meta.FIRST_TEST, SPLIT),
               '2023-09→hoy': (SPLIT, None)}

    def per_period(r):
        return {k: sharpe(r[(r.index >= a) & ((r.index < b) if b is not None else True)]) for k, (a, b) in periods.items()}

    champ_sr = per_period(champion)
    champ_m = metrics(champion)
    trials = load_trials()
    results = []
    for name, feats, nf in variants:
        ds = meta.build_dataset(close, u['funding_last'], nf)
        probs = meta.walk_forward(ds, feats)
        ok = ~np.isnan(probs) & ds['y'].notna().to_numpy()
        auc = roc_auc_score(ds['y'].to_numpy()[ok], probs[ok]) if ok.sum() > 50 else float('nan')
        for thr in THRESHOLDS:
            key = f"{name}_thr{thr}"
            r = meta.evaluate(u, meta.filtered_weights(close, ds, probs, thr), meta.FIRST_TEST)
            trials[f"{month}:{key}"] = float(r.mean() / r.std()) if r.std() > 0 else 0.0
            results.append({'key': key, 'feats': feats, 'news': nf is not None, 'thr': thr, 'auc': auc,
                            'r': r, 'm': metrics(r), 'sr': per_period(r)})
    TRIALS_FILE.write_text(json.dumps(trials, indent=1))

    all_trials = list(trials.values())
    lines += ["", "## Retadores vs rotación sin filtro (fuera de muestra, walk-forward mensual, con costes)", "",
              f"Pruebas acumuladas en todos los meses (para el DSR): **{len(all_trials)}**", "",
              "| Variante | AUC | Retorno | Sharpe completo | Sharpe 21-23 | Sharpe 23-hoy | Caída máx. | DSR | ¿Pasa? |",
              "|---|---|---|---|---|---|---|---|---|",
              f"| rotación sin filtro (campeón) | — | {champ_m['retorno_total']:+.0%} | {champ_sr['completo']:.2f} | "
              f"{champ_sr['2021-07→2023-08']:.2f} | {champ_sr['2023-09→hoy']:.2f} | {champ_m['max_drawdown']:.0%} | — | — |"]
    best = None
    for res in results:
        _, dsr = deflated_sharpe(res['r'], all_trials)
        passes = (all(res['sr'][k] > champ_sr[k] for k in periods)
                  and res['m']['max_drawdown'] >= champ_m['max_drawdown'] and dsr >= 0.95)
        res['dsr'], res['passes'] = dsr, passes
        lines.append(f"| {res['key']} | {res['auc']:.3f} | {res['m']['retorno_total']:+.0%} | {res['sr']['completo']:.2f} | "
                     f"{res['sr']['2021-07→2023-08']:.2f} | {res['sr']['2023-09→hoy']:.2f} | "
                     f"{res['m']['max_drawdown']:.0%} | {dsr:.2f} | {'✅' if passes else '❌'} |")
        if passes and (best is None or res['sr']['completo'] > best['sr']['completo']):
            best = res

    # --- Activar / desactivar ---
    if best:
        ds = meta.build_dataset(close, u['funding_last'], news if best['news'] else None)
        train = ds[ds['y'].notna()]
        model = meta.make_model().fit(train[best['feats']], train['y'])
        with open(CHALLENGER_MODEL, 'wb') as f:
            pickle.dump(model, f)
        state = {'enabled': True, 'variant': best['key'], 'threshold': best['thr'], 'features': best['feats'],
                 'uses_news': best['news'], 'trained_until': str(close.index[-1]), 'activated': month,
                 'sharpe_oos': best['sr']['completo'], 'dsr': best['dsr']}
        lines += ["", f"**✅ Retador activado en paper: `{best['key']}`** (cuenta `rotacion_ml`)."]
    else:
        state = {'enabled': False, 'checked': month}
        lines += ["", "**Ningún retador pasa la barrera: no se activa nada.**"]
    CHALLENGER_FILE.write_text(json.dumps(state, indent=1))

    # --- Seguimiento: paper vs backtest ---
    lines += ["", "## Seguimiento: paper trading vs backtest de los mismos días", "",
              "(Si difieren mucho, algo del bot en vivo no se comporta como en el backtest.)", ""]
    lines += asyncio.run(tracking(u))

    text = '\n'.join(lines) + '\n'
    (REPORTS / f"investigacion_{month}.md").write_text(text)
    print(text)


async def tracking(u) -> list[str]:
    import trend_engine as te
    conn = await asyncpg.connect(**DB_CONFIG)
    rows = await conn.fetch("SELECT account, day, seq, equity FROM trend_accounts ORDER BY account, day, seq")
    await conn.close()
    if not rows:
        return ["- sin datos de paper todavía"]
    df = pd.DataFrame([dict(r) for r in rows])
    first_day = pd.Timestamp(df['day'].min(), tz='UTC')
    out = ["| Cuenta | Días | Paper | Backtest mismos días | Diferencia |", "|---|---|---|---|---|"]
    for name, fn in te.ACCOUNTS.items():
        g = df[df['account'] == name]
        if g.empty:
            continue
        paper = float(g['equity'].iloc[-1]) / float(g['equity'].iloc[0]) - 1
        r, _ = __import__('portfolio').simulate(u, fn(u['close']).fillna(0), start=str(first_day.date()))
        bt = float((1 + r).prod() - 1)
        out.append(f"| {name} | {g['day'].nunique()} | {paper:+.1%} | {bt:+.1%} | {paper - bt:+.1%} |")
    return out


if __name__ == '__main__':
    main()
