# 📖 Historia del proyecto

De la idea inicial al sistema actual. Para el estado de hoy y los resultados detallados, ver
[`ESTADO_BOT.md`](ESTADO_BOT.md).

---

## 1. La idea inicial (septiembre 2026)

Descrita en [`SUMARIO.md`](../SUMARIO.md) (se conserva como referencia):

```
Raspberry Pi 5 (24/7)                          PC (RTX 3060 + Ryzen 7 5700X3D)
─────────────────────                          ─────────────────────────────────
Hyperliquid WebSocket                          Jupyter Notebook
   → data_ingester.py → TimescaleDB  ───────►  descarga los trades de la Pi
                                               entrena un modelo (scikit-learn)
trading_engine.py  ◄── modelo .onnx  ◄──────── exporta a ONNX y lo copia con scp
   (hot swap del modelo)
```

Hoja de ruta en 4 fases: datos → primer modelo → paper trading → "modo quant" (NLP, RL).

## 2. Lo que se hizo con Jupyter y ONNX

1. **`notebooks/train_simple_model.ipynb`**: Random Forest con 3 features (RSI, SMA 20,
   volumen medio) para predecir si SOL sube en los siguientes ~5 minutos.
2. **`scripts/train_enhanced_model_paper.ipynb`**: versión mejorada inspirada en el paper
   *"Rise of the Machines? Intraday High-Frequency Trading Patterns of Cryptocurrencies"*
   (Petukhina, Reule, Härdle): 8 features (RSI, SMA 20/50, volumen, hora, día de la semana,
   hora pico, ATR). Resultado: **91 % de accuracy**. Se exportó a `solana_model_v1.onnx`
   y se copió a la Pi con `scp` para que el motor lo recargara.

## 3. Lo que salió a la luz al ponerlo en marcha (30-sep-2026)

| Problema | Consecuencia |
|---|---|
| Suscripción al WebSocket con formato incorrecto | No llegaba ningún precio |
| El motor leía el libro de órdenes con un formato que no es el de Hyperliquid | Nunca calculaba señales |
| El motor pasaba 1 feature y el modelo esperaba 8 | Cada predicción daba error |
| El modelo se entrenó con `StandardScaler` y el escalador no se exportó | Aunque cuadraran las features, recibiría datos en otra escala |
| **El 91 % era fuga de datos**: split aleatorio sobre trades separados por milisegundos, con el mismo objetivo a 60 trades | Train y test eran casi copias. La validación cruzada del propio notebook daba **42 %**, peor que una moneda al aire |
| `is_peak_hour` era siempre 1 y `day_of_week` constante con 3 h de datos | Features que no aportaban nada |
| Hyperliquid corta las conexiones sin heartbeat y el ingester no se reconectaba | Llevaba horas sin guardar datos |
| `send_order` escribía "Orden enviada" sin enviar nada, y la URL era de mainnet | Falsa sensación de estar operando |

**Lección principal:** un backtest espectacular suele ser un error. Con series temporales,
nunca se valida con un split aleatorio: siempre se entrena con el pasado y se prueba con el futuro.

## 4. Reconstrucción y búsqueda honesta de una ventaja

1. **Arreglos de base:** WebSocket con heartbeat y reconexión, ingester con la hora real del trade,
   sin duplicados, y features compartidas entre entrenamiento y motor para que nunca más se
   desalineen.
2. **Modelo de 5 minutos con validación walk-forward** y una barrera: solo se despliega si gana
   dinero después de comisiones. Nunca la superó: AUC 0,506, que es azar.
3. **Laboratorio de investigación (`research/`):** backtest con costes reales, walk-forward,
   Deflated Sharpe Ratio (corrige la suerte de probar muchas combinaciones) y benchmarks.
4. **Estrategias de papers (SSRN y revistas) a 1-48 h:** momentum y reversión intradía,
   estacionalidad horaria, funding extremo, rupturas de volatilidad y flujo de órdenes. 255
   configuraciones, con órdenes a mercado y con órdenes límite. **Ninguna bate a comprar y mantener.**
5. **Modelo combinado con 67 features:** estructura de mercado, open interest, ratios
   largo/corto, BTC/ETH, Fear & Greed y Wikipedia. AUC 0,49-0,51. **No predice.**

Conclusión: a corto plazo, con datos públicos y comisiones de particular, no hay ventaja. Ese
terreno es de los profesionales, con más velocidad, menos costes y mejores datos.

## 5. El giro: seguimiento de tendencia

Lo único que mejoró a comprar y mantener fue **estar comprado solo cuando hay tendencia**:
- SOL por encima de su media de 20/50 días: más retorno y la caída máxima baja de −78 % a −50 %.
- **Rotación:** las 3 monedas más fuertes de 11, si BTC está en tendencia. Fue la más rentable.
- **Cesta de 11 monedas con filtro de BTC:** la más estable, con caídas de −40 %.

Validado en un periodo que no se usó para diseñarlo (2020-2023, con el bull de 2021 y el crash
de 2022), en mercados tradicionales (confirma que lo robusto es **reducir las caídas**) y con
Monte Carlo (en un año suelto hay ~40 % de probabilidad de perder; la ventaja se ve a varios años).

## 6. Dónde está hoy

- La Pi opera **7 cuentas en paper trading** (`scripts/trend_engine.py`) y recoge datos que no
  se pueden descargar después: trades, noticias, open interest y libro de órdenes de Hyperliquid.
- El PC queda para investigación (`research/laboratorio_estrategias.ipynb`) y, dentro de unos
  meses, para puntuar el sentimiento de las noticias con la RTX 3060.
- El flujo "Jupyter → ONNX → scp → hot swap" ya no se usa: las estrategias actuales son reglas,
  no modelos entrenados. El código de ese flujo sigue en el repositorio (`trading_engine.py`,
  `train_model.py`) por si algún día aparece un modelo que pase la validación.
- Calendario de revisión y criterios de decisión: [`ESTADO_BOT.md`](ESTADO_BOT.md), sección 0.1.

Los modelos ONNX antiguos (el de 8 features y el de 3) se conservan en la Pi en `models/*.bak`,
pero no están en el repositorio.
