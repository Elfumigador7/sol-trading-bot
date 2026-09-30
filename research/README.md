# 🧪 Laboratorio de estrategias (PC)

Backtesting honesto de estrategias de papers para SOL, con operaciones de ≤ 48 h.

## Copiar al PC (desde la terminal de Windows)
```
scp -r fumi7@192.168.1.94:~/1TRADING/research .
cd research
jupyter notebook laboratorio_estrategias.ipynb
```
La primera ejecución descarga unos 3 años de velas de Binance (~1 min) y las guarda en `data/`.

## Archivos
| Archivo | Qué hace |
|---|---|
| `data.py` | Descarga y caché: Binance futuros SOLUSDT (2023 → hoy) y Hyperliquid (~7 meses), velas de 1 h + funding |
| `lab.py` | Backtest con costes (0,065 %/lado + funding), walk-forward, métricas, Deflated Sharpe |
| `strategies.py` | Una función por paper/hipótesis + su rejilla de parámetros |
| `run_lab.py` | Todo de una vez en terminal: `python run_lab.py [--source hyperliquid --train-days 60 --test-days 14]` |
| `laboratorio_estrategias.ipynb` | Lo mismo con gráficos, análisis de robustez y plantilla para nuevos papers |
| `results/` | CSV de cada ejecución (resumen, operaciones, ventanas) |

## Criterio para "PASA"
Fuera de muestra y con costes: gana dinero, Sharpe mayor que buy & hold y que la regla simple,
DSR ≥ 0.95 y positiva también en los últimos 6 meses.

## Modelo combinado y datos extra
| Archivo | Qué hace |
|---|---|
| `features_h.py` | 67 features horarias (estructura, flujo, derivados, BTC/ETH, sentimiento). Mismo código para entrenar y en vivo |
| `ml.py` | Etiquetas de triple barrera, walk-forward mensual, simulación con TP/SL |
| `run_ml.py` | Evalúa 16 configuraciones contra benchmarks: `python run_ml.py` (~35 min en la Pi, menos en el PC) |
| `live_data.py` | Las mismas series en vivo desde la API de Binance (para el bot) |

`data.load_full()` descarga además BTC/ETH, open interest y ratios (≈1.400 archivos diarios, ~15 min
la primera vez), Fear & Greed y Wikipedia. Las noticias GDELT se bajan aparte con
`python -c "import data; data.gdelt_news()"` (la API limita mucho; si falla, reintenta otro día).
