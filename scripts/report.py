#!/usr/bin/env python3
"""
📋 INFORME - salud del sistema + resultados de las cuentas paper.

Escribe reports/informe_actual.md (cron cada hora) y, los lunes, una copia en
reports/semanal/informe_AAAA-MM-DD.md. `./bot.sh status` lo muestra.

Ejecutar desde ~/1TRADING: python scripts/report.py
"""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'solana_trading'),
    'user': os.getenv('DB_USER', 'solana_user'),
    'password': os.getenv('DB_PASSWORD'),
}

# (nombre, consulta de la última actualización, máximo retraso aceptable)
HEALTH = [
    ('Trades de SOL (ingester)', "SELECT max(timestamp) FROM solana_trades", timedelta(minutes=15)),
    ('Noticias', "SELECT max(collected) FROM news_headlines", timedelta(hours=1)),
    ('Fotos de Hyperliquid', "SELECT max(time) FROM hl_snapshots", timedelta(minutes=30)),
    ('Revisión diaria de tendencia', "SELECT max(run_time) FROM trend_accounts", timedelta(hours=26)),
]

# Referencia del backtest 2023-09 → 2026-09: (Sharpe, caída máxima), y peor caída vista en CUALQUIER periodo
# probado (incluida la validación 2020-23). Si una cuenta cae más que eso → alarma de degradación.
BACKTEST = {  # peor caída calculada con research/portfolio.py sobre 2020-10 → 2026-09
    'sol_20d': (1.25, -0.50, -0.73), 'sol_50d': (1.22, -0.56, -0.69), 'sol_50d_vol': (1.27, -0.51, -0.53),
    'cesta_20d': (1.20, -0.34, -0.56), 'rotacion_top3': (1.43, -0.48, -0.71), 'cesta11_btc': (1.01, -0.41, -0.42),
    'rotacion_top3_noticias': (None, None, -0.71), 'buy_and_hold': (1.05, -0.78, None),
}


def ago(delta: timedelta) -> str:
    m = int(delta.total_seconds() // 60)
    return f"hace {m} min" if m < 120 else f"hace {m // 60} h" if m < 2880 else f"hace {m // 1440} días"


async def main():
    now = datetime.now(timezone.utc)
    conn = await asyncpg.connect(**DB_CONFIG)
    lines = [f"# 📋 Informe del bot — {now:%Y-%m-%d %H:%M} UTC", "", "## Salud del sistema", ""]

    problems = 0
    for name, query, max_delay in HEALTH:
        try:
            last = await conn.fetchval(query)
        except Exception:
            last = None
        if last is None:
            lines.append(f"- ❌ **{name}**: sin datos")
            problems += 1
        elif now - last > max_delay:
            lines.append(f"- ❌ **{name}**: parado, último dato {ago(now - last)}")
            problems += 1
        else:
            lines.append(f"- ✅ {name}: {ago(now - last)}")
    lines.insert(3, "**Todo funciona.**" if not problems else f"**⚠️ {problems} problema(s): revisar con `./bot.sh status` y los logs.**")

    rows = await conn.fetch("SELECT account, day, seq, equity, weights, signals FROM trend_accounts "
                            "ORDER BY account, day, seq")
    alerts = await conn.fetch("SELECT published, alerts, title FROM news_headlines WHERE alerts <> '' "
                              "AND published > now() - interval '7 days' ORDER BY published DESC") \
        if await conn.fetchval("SELECT to_regclass('news_headlines') IS NOT NULL") else []
    await conn.close()

    accounts = {}
    for r in rows:
        accounts.setdefault(r['account'], []).append(r)

    degraded = []
    lines += ["", "## Cuentas paper (1.000 USD iniciales cada una)", "",
              "| Cuenta | Capital | Retorno | Caída desde máximo | Peor caída | Días con cambios | Posición actual | Backtest (Sharpe · peor caída) |",
              "|---|---|---|---|---|---|---|---|"]
    for name, hist in sorted(accounts.items(), key=lambda kv: -float(kv[1][-1]['equity'])):
        eq = [float(h['equity']) for h in hist]
        peak, worst = eq[0], 0.0
        for e in eq:
            peak = max(peak, e)
            worst = min(worst, e / peak - 1)
        current_dd = eq[-1] / max(eq) - 1
        weights = [json.loads(h['weights']) for h in hist]
        changes = sum(1 for a, b in zip(weights, weights[1:])
                      if any(abs(a.get(c, 0) - b.get(c, 0)) > 1e-9 for c in set(a) | set(b)))
        held = ', '.join(f"{c} {w:.0%}" for c, w in weights[-1].items() if w > 1e-9) or 'liquidez'
        sr, dd, limit = BACKTEST.get(name, (None, None, None))
        ref = f"{sr:.2f} · {dd:.0%}" if sr else '—'
        flag = ''
        if limit is not None and current_dd < limit:
            flag = ' ⚠️'
            degraded.append(f"{name}: cae {current_dd:.0%} desde su máximo, peor que el peor caso del backtest ({limit:.0%})")
        lines.append(f"| {name}{flag} | {eq[-1]:,.2f} | {eq[-1] / 1000 - 1:+.1%} | {current_dd:+.1%} | {worst:+.1%} | "
                     f"{changes} | {held} | {ref} |")
    if degraded:
        lines[3] = f"**⚠️ Alarma de degradación: {len(degraded)} cuenta(s) fuera de lo visto en el backtest.**"
        lines += ["", "## ⚠️ Alarmas de degradación", ""] + [f"- {d}" for d in degraded] + [
            "", "Qué hacer: no es motivo para cambiar nada de inmediato, pero sí para revisar (ver docs/ESTADO_BOT.md §0.1)."]
    lines += ["", "## 📰 Alertas de noticias (últimos 7 días)", ""]
    lines += [f"- {a['published']:%m-%d %H:%M} · **{a['alerts']}** · {a['title'][:110]}" for a in alerts] or ["- ninguna"]
    days = len({r['day'] for r in rows if r['account'] == 'buy_and_hold'})
    lines += ["", f"Días en paper: {days}. Con menos de ~60 días los resultados son sobre todo ruido: "
              "fíjate en que funcione y en que las caídas no superen lo visto en el backtest."]

    REPORTS.mkdir(exist_ok=True)
    text = '\n'.join(lines) + '\n'
    (REPORTS / "informe_actual.md").write_text(text)
    if now.weekday() == 0:  # lunes
        (REPORTS / "semanal").mkdir(exist_ok=True)
        (REPORTS / "semanal" / f"informe_{now:%Y-%m-%d}.md").write_text(text)
    print(text)


if __name__ == '__main__':
    asyncio.run(main())
