#!/usr/bin/env python3
"""
Genera los gráficos del README (docs/img/). Uso, desde research/:  python make_figures.py

1. equity.png    capital (escala log) 2020-10 → 2026-09 de las estrategias activas vs comprar y mantener
2. drawdown.png  caída desde máximos de las mismas estrategias
3. research.png  Sharpe fuera de muestra de todo lo probado (2023-09 → 2026-09)
"""

import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from portfolio import btc_regime, ema_trend, equal_weight, load_universe, simulate, top_momentum  # noqa: E402

warnings.filterwarnings("ignore")
OUT = Path(__file__).resolve().parent.parent / "docs" / "img"

# Paleta de referencia validada (dataviz): slots categóricos 1-3 + tinta neutra para el benchmark
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SERIES = {
    "Momentum rotation (top-3 of 11 coins)": "#2a78d6",
    "11-coin trend basket + BTC filter": "#eb6834",
    "SOL trend (20-day EMA)": "#1baf7a",
    "Buy & hold SOL (benchmark)": MUTED,
}
VALIDATION_END = pd.Timestamp("2023-09-01", tz="UTC")


def style(ax, title, subtitle, pad=44, sub_y=1.035):
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color=INK, pad=pad)
    ax.text(0, sub_y, subtitle, transform=ax.transAxes, fontsize=9.5, color=INK2, va="bottom", linespacing=1.4)


def strategy_returns():
    u = load_universe(start="2020-01")
    c = u["close"]
    weights = {
        "Momentum rotation (top-3 of 11 coins)": btc_regime(top_momentum(c, 14, 3, 20), c, 50),
        "11-coin trend basket + BTC filter": btc_regime(equal_weight(ema_trend(c, 20)), c, 50),
        "SOL trend (20-day EMA)": ema_trend(c[["SOL"]], 20),
        "Buy & hold SOL (benchmark)": pd.DataFrame({"SOL": c["SOL"].notna().astype(float)}, index=c.index),
    }
    daily = {}
    for name, w in weights.items():
        r, _ = simulate(u, w.fillna(0), start="2020-10-01")
        daily[name] = r.groupby(r.index.floor("D")).apply(lambda x: (1 + x).prod() - 1)
    return pd.DataFrame(daily)


def period_bands(ax):
    ax.axvline(VALIDATION_END, color=AXIS, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(VALIDATION_END - pd.Timedelta(days=20), 1.01, "← independent validation (never used to design rules)",
            transform=ax.get_xaxis_transform(), ha="right", va="bottom", fontsize=8.5, color=INK2)
    ax.text(VALIDATION_END + pd.Timedelta(days=20), 1.01, "selection period (rules were chosen here) →",
            transform=ax.get_xaxis_transform(), ha="left", va="bottom", fontsize=8.5, color=INK2)


def equity_chart(daily):
    eq = (1 + daily).cumprod()
    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
    style(ax, "Trend following vs buy & hold (2020–2026)",
          "Growth of $1, log scale · daily rebalance · fees, slippage and funding included", pad=52, sub_y=1.075)
    for name, color in SERIES.items():
        ls = (0, (5, 3)) if "benchmark" in name else "-"
        ax.plot(eq.index, eq[name], color=color, linewidth=2, linestyle=ls, label=name, solid_capstyle="round")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:g}"))
    period_bands(ax)
    # Etiquetas directas al final de cada línea (valor final), en tinta de texto
    ends = sorted(((eq[n].iloc[-1], n) for n in SERIES), reverse=True)
    last_y = None
    for value, name in ends:
        y = value if last_y is None or last_y / value > 1.35 else last_y / 1.35
        ax.annotate(f"${value:.1f}", xy=(eq.index[-1], value), xytext=(eq.index[-1] + pd.Timedelta(days=25), y),
                    fontsize=9, color=INK, va="center",
                    arrowprops=dict(arrowstyle="-", color=SERIES[name], lw=1))
        last_y = y
    ax.set_xlim(eq.index[0], eq.index[-1] + pd.Timedelta(days=160))
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, -0.07), frameon=False, fontsize=9, labelcolor=INK2, ncol=2)
    fig.tight_layout()
    fig.savefig(OUT / "equity.png", facecolor=SURFACE)
    plt.close(fig)


def drawdown_chart(daily):
    eq = (1 + daily).cumprod()
    dd = eq / eq.cummax() - 1
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    style(ax, "Drawdowns: the main benefit is losing less",
          "Decline from previous peak · worst drawdown in legend", pad=52, sub_y=1.085)
    for name, color in SERIES.items():
        ls = (0, (5, 3)) if "benchmark" in name else "-"
        ax.plot(dd.index, dd[name] * 100, color=color, linewidth=2 if "benchmark" not in name else 1.6,
                linestyle=ls, label=f"{name}: {dd[name].min():.0%}")
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_ylim(-100, 5)
    period_bands(ax)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.09), frameon=False, fontsize=9, labelcolor=INK2, ncol=2)
    fig.tight_layout()
    fig.savefig(OUT / "drawdown.png", facecolor=SURFACE)
    plt.close(fig)


def research_chart():
    """Sharpe fuera de muestra (2023-09 → 2026-09) de cada enfoque; valores de docs/ESTADO_BOT.md."""
    rows = [
        ("Intraday: momentum", -0.28, "short"), ("Intraday: mean reversion", -0.33, "short"),
        ("Intraday: hour-of-day seasonality", -0.93, "short"), ("Intraday: funding extremes", -0.30, "short"),
        ("Intraday: order-flow imbalance", -0.84, "short"), ("Intraday: volatility breakout", 0.81, "short"),
        ("ML model, 67 features (best of 16)", 0.45, "short"),
        ("Buy & hold SOL (benchmark)", 1.05, "bench"),
        ("11-coin trend basket + BTC filter", 1.01, "trend"), ("SOL trend (50-day EMA)", 1.22, "trend"),
        ("SOL trend (20-day EMA)", 1.25, "trend"), ("Momentum rotation (top-3 of 11)", 1.43, "trend"),
    ]
    colors = {"short": "#eb6834", "trend": "#2a78d6", "bench": MUTED}
    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=150)
    style(ax, "What worked: >300 configurations, 2023-09 → 2026-09",
          "Annualised Sharpe after costs · dashed line = buy & hold\n"
          "orange: 1–48 h strategies, walk-forward out-of-sample · blue: trend rules (chosen here, validated on 2020–23)",
          pad=48)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    names = [r[0] for r in rows]
    vals = [r[1] for r in rows]
    bars = ax.barh(names, vals, color=[colors[r[2]] for r in rows], height=0.62, edgecolor=SURFACE, linewidth=2)
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.axvline(1.05, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
    for bar, v in zip(bars, vals):
        x = bar.get_width()
        ax.text(x + (0.03 if v >= 0 else -0.03), bar.get_y() + bar.get_height() / 2, f"{v:+.2f}",
                va="center", ha="left" if v >= 0 else "right", fontsize=9, color=INK)
    ax.tick_params(axis="y", labelsize=9.5, colors=INK2)
    ax.set_xlim(-1.25, 1.75)
    fig.tight_layout()
    fig.savefig(OUT / "research.png", facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    d = strategy_returns()
    equity_chart(d)
    drawdown_chart(d)
    research_chart()
    print(f"Gráficos guardados en {OUT}")
