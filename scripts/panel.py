#!/usr/bin/env python3
"""
📊 PANEL - genera reports/panel.html (cron cada 15 min). Se ve en http://<IP-de-la-Pi>:8899/panel.html
(lo sirve scripts/panel_server.py, que arranca bot.sh).

Contenido: salud del sistema, capital y caídas de cada cuenta paper, posiciones, alertas y sentimiento
de noticias, estado del mercado en Hyperliquid y del autoentrenamiento mensual.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

import report  # salud, límites de alarma y referencias del backtest (una sola fuente)

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports" / "panel.html"
DB_CONFIG = report.DB_CONFIG

# Color fijo por cuenta (sigue a la cuenta, no a su posición). Paleta validada (dataviz) en claro y oscuro.
ACCOUNT_ORDER = ['rotacion_top3', 'cesta11_btc', 'sol_20d', 'rotacion_top3_noticias', 'sol_50d',
                 'cesta_20d', 'sol_50d_vol', 'rotacion_ml']
LIGHT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948']
DARK = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767']
LABELS = {
    'rotacion_top3': 'Rotación top-3', 'cesta11_btc': 'Cesta 11 + BTC', 'sol_20d': 'SOL EMA 20d',
    'rotacion_top3_noticias': 'Rotación + noticias', 'sol_50d': 'SOL EMA 50d', 'cesta_20d': 'SOL/BTC/ETH 20d',
    'sol_50d_vol': 'SOL 50d + vol', 'rotacion_ml': 'Rotación + ML', 'buy_and_hold': 'Comprar y mantener SOL',
}


async def collect() -> dict:
    now = datetime.now(timezone.utc)
    conn = await asyncpg.connect(**DB_CONFIG)
    health = []
    for name, query, max_delay in report.HEALTH:
        try:
            last = await conn.fetchval(query)
        except Exception:
            last = None
        ok = last is not None and now - last <= max_delay
        health.append({'name': name, 'ok': ok, 'ago': report.ago(now - last) if last else 'sin datos'})

    rows = await conn.fetch("SELECT account, day, seq, equity, weights, signals FROM trend_accounts ORDER BY day, seq")
    days = sorted({str(r['day']) for r in rows})
    series, table = {}, []
    for acc in dict.fromkeys(r['account'] for r in rows):
        hist = [r for r in rows if r['account'] == acc]
        by_day = {}
        for r in hist:  # último valor de cada día (incluye ajustes de emergencia)
            by_day[str(r['day'])] = float(r['equity'])
        eq = [by_day.get(d) for d in days]
        vals = [float(r['equity']) for r in hist]
        peak, worst, dd_series = vals[0], 0.0, []
        for v in vals:
            peak = max(peak, v)
            worst = min(worst, v / peak - 1)
        run_peak, dd = None, []
        for v in eq:
            if v is None:
                dd.append(None)
                continue
            run_peak = v if run_peak is None else max(run_peak, v)
            dd.append(round((v / run_peak - 1) * 100, 2))
        current_dd = vals[-1] / max(vals) - 1
        sr, bt_dd, limit = report.BACKTEST.get(acc, (None, None, None))
        weights = json.loads(hist[-1]['weights'])
        series[acc] = {'equity': eq, 'dd': dd}
        table.append({
            'account': acc, 'label': LABELS.get(acc, acc), 'equity': vals[-1], 'ret': vals[-1] / 1000 - 1,
            'dd': current_dd, 'worst': worst, 'limit': limit, 'alarm': limit is not None and current_dd < limit,
            'bt_sharpe': sr, 'bt_dd': bt_dd,
            'held': {c: w for c, w in weights.items() if w > 1e-9},
            'emergencies': sum(1 for r in hist if r['seq'] > 0),
        })
    table.sort(key=lambda t: -t['equity'])

    news_daily, alerts, snapshot = [], [], []
    if await conn.fetchval("SELECT to_regclass('news_headlines') IS NOT NULL"):
        news_daily = [dict(day=str(r['d']), sent=float(r['s'] or 0), n=r['n']) for r in await conn.fetch(
            "SELECT date_trunc('day', published)::date d, avg(sentiment) s, count(*) n FROM news_headlines "
            "WHERE published >= (SELECT min(collected) FROM news_headlines) - interval '1 day' "
            "AND published > now() - interval '30 days' GROUP BY 1 ORDER BY 1")]
        alerts = [dict(when=f"{r['published']:%m-%d %H:%M}", coins=r['alerts'], title=r['title'], sent=r['sentiment'])
                  for r in await conn.fetch("SELECT published, alerts, title, sentiment FROM news_headlines "
                                            "WHERE alerts <> '' AND published > now() - interval '7 days' "
                                            "ORDER BY published DESC LIMIT 15")]
    if await conn.fetchval("SELECT to_regclass('hl_snapshots') IS NOT NULL"):
        snapshot = [dict(coin=r['coin'], px=r['mid_px'], funding_apr=(r['funding'] or 0) * 24 * 365,
                         oi_usd=(r['open_interest'] or 0) * (r['mid_px'] or 0), vol=r['day_volume_usd'],
                         spread=r['spread_pct'], depth=(r['bid_usd_05'] or 0) + (r['ask_usd_05'] or 0))
                    for r in await conn.fetch(
                        "SELECT s.*, b.spread_pct, b.bid_usd_05, b.ask_usd_05 FROM hl_snapshots s "
                        "LEFT JOIN hl_book b USING (time, coin) WHERE s.time = (SELECT max(time) FROM hl_snapshots) "
                        "ORDER BY s.open_interest * s.mid_px DESC")]
    await conn.close()

    challenger_file = ROOT / 'models' / 'challenger.json'
    trials_file = ROOT / 'models' / 'research_trials.json'
    research = {
        'challenger': json.loads(challenger_file.read_text()) if challenger_file.exists() else None,
        'trials': len(json.loads(trials_file.read_text())) if trials_file.exists() else 0,
        'reports': sorted(p.name for p in (ROOT / 'reports').glob('investigacion_*.md')),
    }
    return {'generated': f"{now:%Y-%m-%d %H:%M} UTC", 'health': health, 'days': days, 'series': series,
            'table': table, 'news': news_daily, 'alerts': alerts, 'market': snapshot, 'research': research,
            'order': ACCOUNT_ORDER, 'light': LIGHT, 'dark': DARK, 'labels': LABELS}


PAGE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>Panel del bot</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root {
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --good: #006300; --bad: #d03b3b; --warn-bg: #fff4dc; --border: #e1e0d9;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --good: #0ca30c; --bad: #e66767; --warn-bg: #3a2e12; --border: #2c2c2a;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink); font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 20px 16px 48px; }
h1 { font-size: 22px; margin: 0 0 2px; }
h2 { font-size: 15px; margin: 0 0 4px; }
.sub { color: var(--ink2); font-size: 13px; margin: 0 0 12px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; margin-top: 16px; }
.pills { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.pill { border: 1px solid var(--border); border-radius: 999px; padding: 4px 10px; font-size: 13px; background: var(--surface); }
.pill b { font-weight: 600; }
.ok { color: var(--good); } .bad { color: var(--bad); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-top: 16px; }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; }
.tile .k { color: var(--ink2); font-size: 12px; } .tile .v { font-size: 22px; font-weight: 650; margin-top: 2px; }
.chart { position: relative; height: 320px; }
.grid2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
.grid2 > *, .card, .tile { min-width: 0; }
@media (max-width: 820px) { .grid2 { grid-template-columns: minmax(0, 1fr); } .chart { height: 260px; } }
ul.news li { overflow-wrap: anywhere; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--border); white-space: nowrap; }
th { color: var(--ink2); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }
tr.alarm td { background: var(--warn-bg); }
ul.news { margin: 0; padding-left: 18px; } ul.news li { margin: 4px 0; }
.muted { color: var(--muted); }
a { color: inherit; }
</style>
</head>
<body>
<main>
  <h1>Panel del bot</h1>
  <p class="sub">Paper trading (sin dinero real) · actualizado <span id="gen"></span> · se recarga cada 15 min</p>
  <div class="pills" id="health"></div>
  <div class="tiles" id="tiles"></div>

  <section class="card">
    <h2>Capital de cada cuenta</h2>
    <p class="sub">1.000 USD virtuales al empezar · la línea discontinua es comprar y mantener SOL · pulsa la leyenda para ocultar cuentas</p>
    <div class="chart"><canvas id="equity"></canvas></div>
  </section>

  <section class="card">
    <h2>Caída desde el máximo</h2>
    <p class="sub">Lo que más importa vigilar: si una cuenta cae más que el peor caso del backtest, se marca en la tabla</p>
    <div class="chart"><canvas id="drawdown"></canvas></div>
  </section>

  <section class="card">
    <h2>Cuentas</h2>
    <div class="scroll"><table id="accounts"></table></div>
  </section>

  <div class="grid2">
    <section class="card">
      <h2>Sentimiento de las noticias</h2>
      <p class="sub">Media diaria de los titulares recogidos (−1 muy negativo, +1 muy positivo)</p>
      <div class="chart" style="height:220px"><canvas id="sentiment"></canvas></div>
    </section>
    <section class="card">
      <h2>Alertas de noticias (7 días)</h2>
      <p class="sub">Activan el freno de la cuenta “Rotación + noticias” durante 72 h</p>
      <ul class="news" id="alerts"></ul>
    </section>
  </div>

  <section class="card">
    <h2>Mercado en Hyperliquid</h2>
    <p class="sub">Última foto (cada 5 min): funding anualizado, open interest, spread y liquidez a ±0,5 % del precio</p>
    <div class="scroll"><table id="market"></table></div>
  </section>

  <section class="card">
    <h2>Autoentrenamiento mensual</h2>
    <div id="research"></div>
  </section>
</main>
<script>
const D = __DATA__;
const dark = matchMedia('(prefers-color-scheme: dark)').matches;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const pal = dark ? D.dark : D.light;
const color = acc => acc === 'buy_and_hold' ? css('--muted') : pal[D.order.indexOf(acc) % pal.length];
const pct = (v, d = 1) => { if (v == null) return '—'; const x = Math.abs(v) < 0.5 * 10 ** (-d - 2) ? 0 : v;
  return (x > 0 ? '+' : '') + (x * 100).toFixed(d) + ' %'; };
const tone = v => Math.abs(v) < 0.0005 ? '' : v > 0 ? 'ok' : 'bad';
const usd = v => v == null ? '—' : v.toLocaleString('es-ES', {maximumFractionDigits: 2});
const big = v => v >= 1e9 ? (v / 1e9).toFixed(2) + ' B' : v >= 1e6 ? (v / 1e6).toFixed(1) + ' M' : (v / 1e3).toFixed(0) + ' k';
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

document.getElementById('gen').textContent = D.generated;
document.getElementById('health').innerHTML = D.health.map(h =>
  `<span class="pill"><b class="${h.ok ? 'ok' : 'bad'}">${h.ok ? '✅' : '❌'}</b> ${esc(h.name)} <span class="muted">· ${esc(h.ago)}</span></span>`).join('');

const bh = D.table.find(t => t.account === 'buy_and_hold');
const best = D.table.filter(t => t.account !== 'buy_and_hold')[0];
const alarms = D.table.filter(t => t.alarm).length;
document.getElementById('tiles').innerHTML = [
  ['Días en paper', D.days.length],
  ['Mejor cuenta', best ? `${esc(best.label)} <span style="font-size:15px">${pct(best.ret)}</span>` : '—'],
  ['Comprar y mantener SOL', bh ? pct(bh.ret) : '—'],
  ['Alarmas de degradación', alarms ? `<span class="bad">⚠️ ${alarms}</span>` : '<span class="ok">0</span>'],
].map(([k, v]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');

Chart.defaults.color = css('--ink2');
Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
const axes = (ytick) => ({
  x: {grid: {display: false}, ticks: {maxTicksLimit: 8, color: css('--muted')}, border: {color: css('--axis')}},
  y: {grid: {color: css('--grid')}, ticks: {callback: ytick, color: css('--muted')}, border: {display: false}},
});
const common = (ytick, fmt) => ({
  responsive: true, maintainAspectRatio: false, animation: false,
  interaction: {mode: 'index', intersect: false},
  plugins: {legend: {position: 'bottom', labels: {usePointStyle: true, pointStyle: 'line', boxWidth: 24}},
            tooltip: {callbacks: {label: c => ` ${c.dataset.label}: ${fmt(c.parsed.y)}`}}},
  scales: axes(ytick), elements: {point: {radius: 0, hoverRadius: 5, hitRadius: 8}, line: {borderWidth: 2, tension: 0}},
});
const accs = [...D.order.filter(a => D.series[a]), 'buy_and_hold'].filter(a => D.series[a]);
const ds = key => accs.map(a => ({
  label: D.labels[a] || a, data: D.series[a][key], borderColor: color(a), backgroundColor: color(a),
  borderDash: a === 'buy_and_hold' ? [6, 4] : [], spanGaps: true,
}));
new Chart(document.getElementById('equity'), {type: 'line', data: {labels: D.days, datasets: ds('equity')},
  options: common(v => v.toLocaleString('es-ES') + ' $', v => usd(v) + ' USD')});
new Chart(document.getElementById('drawdown'), {type: 'line', data: {labels: D.days, datasets: ds('dd')},
  options: common(v => v + ' %', v => v.toFixed(1) + ' %')});

const bt = t => t.bt_sharpe == null ? '—' : `${t.bt_sharpe.toFixed(2)} · ${pct(t.bt_dd, 0)}`;
document.getElementById('accounts').innerHTML =
  `<tr><th>Cuenta</th><th class="num">Capital</th><th class="num">Retorno</th><th class="num">Caída actual</th>
   <th class="num">Peor caída</th><th class="num">Límite alarma</th><th>Posición actual</th><th class="num">Backtest (Sharpe · caída)</th></tr>` +
  D.table.map(t => `<tr class="${t.alarm ? 'alarm' : ''}">
    <td><span class="sw" style="background:${color(t.account)}"></span>${esc(t.label)}${t.alarm ? ' ⚠️' : ''}${t.emergencies ? ` <span class="muted">(${t.emergencies} freno${t.emergencies > 1 ? 's' : ''} de noticias)</span>` : ''}</td>
    <td class="num">${usd(t.equity)}</td><td class="num ${tone(t.ret)}">${pct(t.ret)}</td>
    <td class="num">${pct(t.dd)}</td><td class="num">${pct(t.worst)}</td><td class="num">${t.limit == null ? '—' : pct(t.limit, 0)}</td>
    <td>${Object.entries(t.held).map(([c, w]) => `${c} ${(w * 100).toFixed(0)}%`).join(', ') || 'liquidez'}</td>
    <td class="num">${bt(t)}</td></tr>`).join('');

new Chart(document.getElementById('sentiment'), {type: 'line',
  data: {labels: D.news.map(n => n.day), datasets: [{label: 'Sentimiento medio', data: D.news.map(n => n.sent),
         borderColor: pal[0], backgroundColor: pal[0], pointRadius: 3}]},
  options: {...common(v => v.toFixed(1), v => v.toFixed(2)), plugins: {legend: {display: false},
            tooltip: {callbacks: {label: c => ` sentimiento ${c.parsed.y.toFixed(2)} · ${D.news[c.dataIndex].n} titulares`}}},
            scales: {...axes(v => v.toFixed(1)), y: {...axes(v => v.toFixed(1)).y, min: -1, max: 1}}}});
document.getElementById('alerts').innerHTML = D.alerts.length ? D.alerts.map(a =>
  `<li><span class="muted">${a.when}</span> · <b>${esc(a.coins)}</b> · ${esc(a.title)}</li>`).join('') : '<li class="muted">ninguna</li>';

document.getElementById('market').innerHTML =
  `<tr><th>Moneda</th><th class="num">Precio</th><th class="num">Funding anual</th><th class="num">Open interest</th>
   <th class="num">Volumen 24 h</th><th class="num">Spread</th><th class="num">Liquidez ±0,5 %</th></tr>` +
  D.market.map(m => `<tr><td>${m.coin}</td><td class="num">${usd(m.px)}</td>
    <td class="num ${m.funding_apr > 0.3 ? 'bad' : ''}">${pct(m.funding_apr)}</td><td class="num">${big(m.oi_usd)} $</td>
    <td class="num">${big(m.vol)} $</td><td class="num">${(m.spread * 100).toFixed(3)} %</td><td class="num">${big(m.depth)} $</td></tr>`).join('');

const R = D.research, C = R.challenger;
document.getElementById('research').innerHTML = `
  <p>${C && C.enabled
      ? `<b class="ok">✅ Retador activo en paper:</b> ${esc(C.variant)} (desde ${esc(C.activated)}, Sharpe fuera de muestra ${C.sharpe_oos.toFixed(2)}, DSR ${C.dsr.toFixed(2)})`
      : `<b>Ningún retador activo.</b> <span class="muted">Última revisión: ${C ? esc(C.checked) : 'pendiente'}. Solo se activa si bate a la rotación en todos los periodos y pasa la corrección por suerte.</span>`}</p>
  <p class="muted">Pruebas acumuladas (para el Deflated Sharpe): ${R.trials}.
     Informes: ${R.reports.map(r => `<a href="${r}">${r}</a>`).join(' · ') || 'ninguno aún'}</p>`;
</script>
</body>
</html>
"""


def main():
    data = asyncio.run(collect())
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(PAGE.replace('__DATA__', json.dumps(data, default=str).replace('</', '<\\/')))
    print(f"Panel generado: {OUT}")


if __name__ == '__main__':
    main()
