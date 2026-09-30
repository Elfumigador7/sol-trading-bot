# 🤖 Estado del bot SOL y plan de mejora

> Actualizado: 2026-09-30. Sustituye a las partes obsoletas de `legacy/SUMARIO.md`
> (que queda como referencia de la idea original: Pi 24/7 + PC para entrenar).

---

## 0. Estrategia activa (desde 2026-09-30): tendencia en paper trading

`scripts/trend_engine.py` (cron cada hora, actúa una vez al día al cerrar la vela de 00:00 UTC).
8 cuentas virtuales de 1.000 USD (tabla `trend_accounts`, log `logs/trend.log`), más una novena si el autoentrenamiento activa un retador:

| Cuenta | Regla | Backtest 2023-09 → 2026-09 (cambios/año, retorno, Sharpe, DD) |
|---|---|---|
| `sol_20d` | 100 % SOL si precio > EMA 20 d | 43 · +498 % · 1.25 · −50 % |
| `sol_50d` | 100 % SOL si precio > EMA 50 d | 26 · +473 % · 1.22 · −56 % |
| `sol_50d_vol` | EMA 50 d + exposición min(1, 60 %/vol) | — · +321 % · 1.27 · −51 % |
| `cesta_20d` | SOL/BTC/ETH 1/3 cada una, EMA 20 d | 127 · +228 % · 1.20 · −34 % |
| `rotacion_top3` | Top-3 de 11 monedas por retorno 14 d, si en tendencia 20 d y BTC > EMA 50 d | 135 días/año · +634 % · 1.43 · −48 % (*) |
| `cesta11_btc` | 11 monedas 1/11 con EMA 20 d, solo si BTC > EMA 50 d | 153 días/año · +160 % · 1.01 · −41 % |
| `rotacion_top3_noticias` | Igual que `rotacion_top3`, sin monedas con alerta de noticias grave en 72 h + freno de emergencia cada hora | Experimento (sin backtest posible) |
| `rotacion_ml` | Solo si el autoentrenamiento mensual lo activa (ver abajo) | — |
| `buy_and_hold` | Siempre 100 % SOL (referencia) | 0 · +417 % · 1.05 · −78 % |

(*) Robustez de la rotación (27 combinaciones de lookback 7/14/28 d × top 2/3/5 × EMA BTC 20/50/100):
el 70 % bate a comprar y mantener SOL, mediana Sharpe 1.17 (< 1.25 de `sol_20d`). El 1.43 de la
combinación elegida tiene parte de suerte (14 d sale la mejor en todas las filas). Ventaja real frente
a `sol_20d`: no depende de que SOL vuelva a ser la mejor moneda, como lo fue en 2023-2026.
Universo: top-20 de enero de 2023 (BTC ETH BNB XRP ADA DOGE SOL DOT LTC AVAX LINK), sin sesgo de supervivencia.
Otras mejoras probadas: multi-velocidad 10/20/50 (≈ igual), filtro de funding (+18 pp, marginal),
volatilidad objetivo en cesta (≈ igual). Código: `research/portfolio.py`.

- Sin cortos: ponerse corto en bajista empeoró todas las variantes (crypto sube a largo plazo).
- Probadas 12 variantes de tendencia (10/20/50 d × cortos sí/no × SOL/cesta): las diferencias
  entre 20 y 50 días son pequeñas y pueden ser ruido; lo robusto es "largo con tendencia, fuera sin ella".
- Señales calculadas con `research/portfolio.py` (el mismo código del backtest; verificado 30 días × 7 cuentas). Datos de Binance; precio y funding de Hyperliquid.
- **Nada de dinero real** hasta que el paper confirme durante meses lo que dice el backtest.

El bot antiguo de 5 min (`trading_engine.py`) y su reentreno cada 6 h quedan **retirados**
(sin ventaja demostrable). El recolector de trades y el de noticias siguen activos.

### Validación en datos nunca usados: 2020-10 → 2023-08 (2026-09-30)
Mismas reglas fijas, sin cambiar ningún parámetro. Incluye el bull de 2021 y el crash de 2022 (FTX).

| Estrategia | Retorno | Sharpe | Max DD | 2021 | 2022 |
|---|---|---|---|---|---|
| Comprar y mantener SOL | +602 % | 1.18 | **−97 %** | +8.366 % | −93 % |
| Comprar y mantener 11 monedas | +349 % | 1.02 | −81 % | +729 % | −70 % |
| `sol_20d` | +783 % | 1.23 | −73 % | +2.518 % | −58 % |
| `rotacion_top3` | **+850 %** | **1.37** | −69 % | +1.293 % | −54 % |
| `cesta11_btc` | +430 % | **1.37** | **−40 %** | +535 % | −31 % |

- Las 27 combinaciones de la rotación baten a comprar y mantener SOL en Sharpe (mediana 1.58).
- **El concepto se confirma en un periodo independiente.** Pero la rotación cayó −69 % en 2022:
  el filtro de BTC no bastó en un bear market largo. `cesta11_btc` es la más estable en ambos
  periodos (DD −40 % / −41 %).

### Misma regla en mercados tradicionales (11 ETFs, 2007-2026, datos de Yahoo) (2026-09-30)
- Reglas rápidas (EMA 20/50 d, las de cripto): mejoran el Sharpe en solo 1/11 activos, pero
  reducen la caída máxima en 9-10/11.
- Regla lenta clásica (SMA 200 d, Faber 2007): mejora el Sharpe en 5/11 y la caída en 10/11.
- Cartera de los 11 a partes iguales: comprar y mantener +7,4 %/año (Sharpe 0.63, DD −35 %);
  tendencia SMA 200 +4,6 %/año (Sharpe 0.71, **DD −11 %**); 2008: −19 % vs −5 %.
  (Sin contar el interés de la liquidez, que sumaría ~0,5-1 %/año.)
- **Conclusión:** lo robusto del trend following es **reducir las caídas**. Ganar *más* que
  comprar y mantener depende de que el mercado tenga tendencias fuertes (cripto las ha tenido);
  en mercados tradicionales las reglas rápidas se comen el beneficio con entradas y salidas en falso.

### Monte Carlo: qué puede pasar en 1 año (10.000 simulaciones, bloques de 30 días) (2026-09-30)
Con toda la historia 2020-10 → 2026-09 (incluye la euforia de 2021, optimista):

| Estrategia | Peor 5 % | Mediana | Mejor 5 % | P(perder) | P(>+35 %) | P(caída >50 %) |
|---|---|---|---|---|---|---|
| `rotacion_top3` | −41 % | +86 % | +849 % | 21 % | 65 % | 18 % |
| `cesta11_btc` | −30 % | +46 % | +316 % | 23 % | 56 % | 2 % |
| `sol_20d` | −54 % | +75 % | +964 % | 26 % | 61 % | 41 % |
| Comprar y mantener SOL | −74 % | +78 % | +1.419 % | 32 % | 59 % | 82 % |

Sin 2021 (2022-01 → 2026-09, **escenario prudente**):

| Estrategia | Peor 5 % | Mediana | Mejor 5 % | P(perder) | P(>+35 %) | P(caída >50 %) |
|---|---|---|---|---|---|---|
| `rotacion_top3` | −52 % | +13 % | +314 % | 42 % | 40 % | 21 % |
| `cesta11_btc` | −39 % | +6 % | +130 % | 44 % | 29 % | 3 % |
| `sol_20d` | −55 % | +19 % | +310 % | 40 % | 43 % | 32 % |
| Comprar y mantener SOL | −79 % | −2 % | +406 % | 51 % | 37 % | 80 % |

Lectura: en un año cualquiera hay ~40 % de probabilidad de perder dinero incluso con la mejor
estrategia; la ventaja se ve en varios años y, sobre todo, en caídas mucho menores
(`cesta11_btc`: 3 % de probabilidad de caer más de un 50 % frente al 80 % de comprar y mantener SOL).

### "¿Qué da más profit?" (2026-09-30)
- A posteriori, la más rentable de 32 candidatas fue la rotación top-2 (+1.038 %), pero elegirla viendo
  todo el periodo es sobreajuste.
- Simulando esa búsqueda sin mirar el futuro (cada mes, usar la más rentable de los últimos 3/6/12 meses):
  **+113 % a +322 %**, peor que comprar y mantener SOL (+417 %). Con las 3 mejores: +337 % a +586 %,
  muy inestable. **Perseguir a la ganadora no funciona.** Mejor: reglas fijas robustas.
- Apalancamiento sobre `rotacion_top3`: 1,5x → +1.341 % con DD −65 %; 2x → DD −79 %;
  3x → DD −94 % (liquidación probable). Multiplica el beneficio del pasado y, sobre todo, el riesgo.

### Experimento de noticias (desde 2026-09-30)
Reglas fijadas **antes** de ver resultados (`scripts/news_rules.py`, con tests): una alerta para una moneda
exige que la moneda esté en el **titular**, que haya una palabra de evento grave (hack, exploit, outage,
demanda, delisting, insolvencia…) y que el titular mencione **como máximo 2 monedas**. Falsos positivos
conocidos y aceptados (p. ej. el primero: "…after the Kelp Hack, Chainlink lets institutions…" excluyó LINK).
Se evalúa comparando `rotacion_top3_noticias` con `rotacion_top3` tras varios meses.
Sentimiento de cada titular: VADER + léxico cripto (columna `sentiment`), para usarlo como feature.

### Autoentrenamiento mensual (`scripts/monthly_research.py`, día 1 a las 05:00)
Reentrena con todos los datos un **meta-modelo** (López de Prado) que decide si fiarse de cada elección
de la rotación (momentum, volatilidad, BTC, funding y, con ≥ 90 días de titulares, noticias).
**Barrera** para activarlo en paper (`rotacion_ml`): Sharpe fuera de muestra mejor que la rotación en el
periodo completo **y** en cada subperiodo (2021-07→2023-08, 2023-09→hoy), caída no peor, y DSR ≥ 0,95
contando todas las variantes probadas en todos los meses (`models/research_trials.json`).
Informe en `reports/investigacion_AAAA-MM.md`.

Primera ejecución (2026-09): AUC 0,543. Con umbral 0,5: Sharpe 1,09 vs 0,91 y caída −37 % vs −71 %
en el total, **pero peor en 2023-09→hoy (1,16 vs 1,43)** → **no pasa, no se activa**.

### Panel
`http://192.168.1.94:8899/panel.html` (red local; `scripts/panel.py` cada 15 min, servido por
`scripts/panel_server.py`): salud, capital y caídas por cuenta, posiciones, alarmas, sentimiento y
alertas de noticias, mercado en Hyperliquid y estado del autoentrenamiento. El puerto 8080 lo usa otro servicio.

## 0.1 Calendario de revisión (decidido el 2026-09-30, antes de ver resultados)

**Cada semana (opcional, 1 min):** abrir el panel (`http://192.168.1.94:8899/panel.html`) o `./bot.sh status` → que todo esté en ✅.

**Al mes (~2026-10-30): revisión técnica, NO de rentabilidad**
1. `./bot.sh status`: todas las piezas en ✅ y ~30 días en la tabla de cuentas.
2. `ls reports/semanal/`: debe haber ~4 informes.
3. Mirar la columna "Peor caída" de cada cuenta: dentro de lo visto en el backtest (≤ ~50 %).
4. La rentabilidad de 1 mes es ruido: no cambiar nada por ella (ni para bien ni para mal).
5. Copiar las copias de seguridad al PC: `scp -r fumi7@192.168.1.94:~/1TRADING/backups .`

**A los 3 meses (~2026-12-30): primera revisión de resultados**
Para cada cuenta, comparar con `buy_and_hold` y con el backtest:
- ✅ Sigue el plan si: sin fallos técnicos, caídas dentro del rango del backtest, y el
  comportamiento cuadra con el mercado (si SOL subió fuerte, las cuentas de tendencia deberían
  haber subido también, algo menos; si cayó, deberían haber perdido bastante menos).
- ❌ Revisar si: una cuenta cae más que en el peor momento del backtest, o hace algo que la regla
  no explica (p. ej. pierde mucho en un mercado alcista claro).
Decisión: (a) seguir en paper, (b) empezar con poco dinero real en la cuenta elegida
(`rotacion_top3` más rentable, `cesta11_btc` más estable), sin apalancamiento y en spot, o (c) parar.

**A los 3-6 meses: noticias**
Con ~3-6 meses de titulares en `news_headlines`: puntuar sentimiento (FinBERT en la RTX 3060)
y probar en walk-forward si un filtro de noticias mejora `rotacion_top3`.

**Si se decide dinero real:** conectar primero a Hyperliquid **testnet** (SDK oficial,
órdenes firmadas, límites de tamaño y pérdida diaria, botón de parada) y después mainnet
con una cantidad pequeña.

## 1. Qué hay funcionando ahora (Raspberry Pi)

| Pieza | Archivo | Qué hace |
|---|---|---|
| Recolector | `scripts/data_ingester.py` | Guarda cada trade de SOL de Hyperliquid en `solana_trades` (hora real del trade, sin duplicados por `trade_id`, pool de conexiones). |
| Conexión WS | `scripts/ws_utils.py` | Heartbeat cada 30 s + reconexión automática. Hyperliquid corta ("Expired") si no envías nada en 60 s: por eso el ingester llevaba horas muerto. |
| Features | `scripts/features.py` | Única fuente de features para entrenamiento **y** motor. Todas relativas (no dependen del nivel de precio). |
| Entrenamiento | `scripts/train_model.py` | Target "¿sube más que las comisiones en 5 min?", validación walk-forward purgada, **solo despliega si el retorno neto simulado es > 0** con ≥ 30 operaciones. |
| Motor | `scripts/trading_engine.py` | Paper trading: 1 posición, SL 0,5 %, TP 1 %, salida a 5 min, cooldown 60 s, fills al bid/ask + comisiones 0,045 %/lado. Recarga el modelo solo. Rechaza modelos cuyas features no coinciden. **Nunca envía órdenes reales.** |
| Noticias | `scripts/news_collector.py` | Cron cada 15 min: 10 fuentes RSS/Atom (CoinDesk, Cointelegraph, Decrypt, The Block, Bitcoin Magazine, CryptoSlate, CryptoPotato, Blockworks, Solana News, Reddit r/solana) → `news_headlines` con monedas mencionadas. Para puntuar sentimiento más adelante (FinBERT en el PC). |
| Fotos de mercado | `scripts/market_snapshots.py` | Cron cada 5 min, 11 monedas en Hyperliquid: open interest, funding, prima, precios (`hl_snapshots`) y spread + profundidad del libro a ±0,1/0,5/1 % (`hl_book`). Hyperliquid no ofrece este histórico: solo existe si lo guardamos. |
| Tendencia (paper) | `scripts/trend_engine.py` | Ver sección 0. |
| Informe | `scripts/report.py` | Cron cada hora → `reports/informe_actual.md` (salud de cada recolector + tabla de cuentas); los lunes copia en `reports/semanal/`. Lo muestra `./bot.sh status`. |
| Copias | `scripts/backup.sh` | Cron diario 03:30: `pg_dump` comprimido en `backups/`, últimos 14 días. Copiar de vez en cuando al PC (protege de un fallo del disco). |
| Logs | `logrotate.conf` | Cron diario 04:00: rotación semanal, 4 semanas, comprimidos. |
| Panel | `scripts/panel.py` + `panel_server.py` | Panel web en el puerto 8899 (ver sección 0). |
| Investigación mensual | `scripts/monthly_research.py` | Autoentrenamiento con barrera (ver sección 0). |
| Reglas de noticias | `scripts/news_rules.py` | Etiquetado de monedas, alertas y sentimiento (compartido por recolector, motor y panel). |
| Control | `bot.sh` | `./bot.sh start | stop | restart | status | retrain` |
| Cron | `crontab -l` | Arranque al encender, watchdog cada 5 min, reentreno cada 6 h (log en `logs/train.log`). Quitar: `crontab -r`. |

### Tablas en PostgreSQL (`solana_trading`, contenedor Docker `solana_trading_db`)
- `solana_trades`: trades de mercado (materia prima del modelo).
- `paper_trades`: operaciones simuladas del bot (entrada, salida, prob., motivo, PnL).
- `executed_trades`: tabla antigua, sin uso.

### Parámetros (en `.env`, todos opcionales)
`PROBABILITY_THRESHOLD` (0.60), `TRADE_SIZE_SOL` (1.0), `STOP_LOSS_PCT` (0.5), `TAKE_PROFIT_PCT` (1.0), `COOLDOWN_S` (60).

### Comandos del día a día
```bash
./bot.sh status               # servicios + último estado + modelo
tail -f logs/engine.log       # motor en directo
cat logs/train.log            # resultado de cada reentreno automático
```

---

## 2. Lecciones aprendidas (no repetir)

1. **El 91 % de accuracy del notebook `train_enhanced_model_paper.ipynb` era fuga de datos**: split aleatorio sobre trades separados por milisegundos con el mismo target a 60 trades. Su propia validación cruzada daba 42 %. **Nunca usar `train_test_split` aleatorio con series temporales.**
2. Ese modelo se entrenó con `StandardScaler` y el escalador no se exportó → en la Pi habría recibido datos en otra escala.
3. `is_peak_hour` del notebook era siempre 1 (las tres franjas cubren las 24 h). `day_of_week` con 3 h de datos es constante.
4. Features en precio absoluto (`sma_20` en dólares) hacen que el modelo memorice "a qué precio estaba SOL" → señales falsas del 75-80 %.
5. Con 4 h de datos: AUC 0,506 (azar) y −0,08 %/operación tras comisiones. **Sin datos suficientes no hay modelo, y el bot lo sabe y no opera.**
6. A 5 minutos, las comisiones (0,09 % ida y vuelta + spread) se comen casi cualquier ventaja. Horizontes más largos (1 h – 1 día) lo ponen mucho más fácil.
7. `send_order` antiguo no enviaba nada aunque decía "Orden enviada". Las órdenes reales en Hyperliquid requieren **firmar** la acción (SDK oficial `hyperliquid-python-sdk`). No implementar hasta que un modelo gane en paper durante semanas.
8. `legacy/start_all.sh` / `legacy/stop_all.sh` / `legacy/scripts/hot_reload.py` quedan obsoletos (`stop_all.sh` además hace `docker-compose down` y apaga la DB).

---

## 3. ¿Puede autoentrenarse con sus propias operaciones?

**Sí, pero no como fuente principal.** Las operaciones del bot son pocas (decenas al mes) y
están sesgadas (solo existen donde el modelo ya quiso entrar). Lo correcto es:

1. **Reentreno con datos de mercado** (ya funciona: cada 6 h con todo `solana_trades`).
2. **Control de degradación con `paper_trades`**: comparar el acierto y PnL reales con lo
   que prometió la validación (`models/model_metadata.json`). Si el real cae claramente por
   debajo durante N operaciones → el bot se pausa solo. *(Pendiente de implementar.)*
3. **Meta-labeling** (López de Prado, *Advances in Financial Machine Learning*): cuando haya
   cientos de operaciones, un segundo modelo aprende **cuándo fiarse** de las señales del
   primero usando `paper_trades` como etiquetas. Es la forma sana de "aprender de sus
   propias operaciones". *(Pendiente, necesita volumen de operaciones.)*

---

## 4. Plan: estrategias de papers (SSRN), patrones y noticias

### Principio: "mejor que una persona" se mide, no se promete
Un modelo solo se despliega si, **fuera de muestra y después de comisiones y spread**, bate a:
- **Buy & hold de SOL** en el mismo periodo (retorno ajustado a riesgo: Sharpe, drawdown máximo).
- **Una regla simple** (p. ej. cruce de medias o momentum de 1 semana): si un modelo
  complejo no mejora una regla de dos líneas, no aporta nada.
- **Lo que harías tú**: tus operaciones reales, si las apuntas, son otro benchmark.

Aviso honesto: la mayoría de estrategias publicadas pierden gran parte de su rentabilidad
tras publicarse (McLean & Pontiff, 2016) y muchas no sobreviven a costes reales. Por eso
cada paper se trata como **hipótesis a refutar**, no como receta.

### Restricción del usuario: operaciones cortas
- **Duración máxima de una operación: 2 días (48 h).** Nada de swing de semanas.
- Franja objetivo: **1 h – 24 h**, donde las comisiones pesan poco y hay operaciones
  suficientes para validar. Por debajo de ~30 min las comisiones se comen la ventaja.
- Las señales de horizonte largo (tendencia semanal, momentum de semanas) se usan solo como
  **filtro de régimen / feature** (p. ej. "solo largos si la tendencia semanal es alcista"),
  nunca para mantener posiciones más de 48 h.
- El motor siempre cierra por tiempo al llegar al horizonte del modelo (≤ 48 h).

### Reparto de trabajo
- **PC (RTX 3060 + Ryzen 7 5700X3D)**: investigación y entrenamiento: descarga de años de
  datos, backtests de cada estrategia, búsqueda de hiperparámetros, LightGBM/XGBoost en
  GPU, modelos de NLP para noticias. Exporta un `.onnx` + metadatos.
- **Raspberry Pi**: solo ejecuta: recoge datos en vivo, calcula features, inferencia ONNX,
  paper trading, vigilancia de degradación.

### Fase A: Datos históricos (sin esto nada tiene sentido)
- **Binance public data** (`data.binance.vision`): años de velas, `aggTrades` y futuros de
  SOLUSDT gratis. Base principal para entrenar patrones.
- **Hyperliquid API** (`candleSnapshot`, `fundingHistory`): para validar que lo aprendido
  en Binance se sostiene en el mercado donde opera el bot, y funding de perpetuos.
- Los datos de la Pi (`solana_trades`) sirven para validar microestructura en vivo.

### Fase B: Laboratorio de backtesting (PC)
- Motor de backtest vectorizado con costes realistas (comisión + spread + slippage).
- Validación walk-forward purgada con embargo (misma idea que `train_model.py`).
- Métricas: retorno neto, Sharpe, Sortino, drawdown máx., nº de operaciones,
  **Deflated Sharpe Ratio** (Bailey & López de Prado) para no engañarse al probar muchas
  estrategias.
- Un archivo por estrategia/paper con: referencia, hipótesis, reglas, resultado. Las que no
  pasen quedan documentadas como descartadas.

### Fase C: Familias de estrategias a probar (orden sugerido)
1. **Momentum y reversión intradía** (retorno de las últimas horas → siguientes horas;
   p. ej. el efecto "la primera/última parte del día predice el resto"). Momentum de
   semanas (Liu & Tsyvinski, *Risks and Returns of Cryptocurrency*) solo como filtro.
2. **Estacionalidad intradía / día de la semana** (la idea del paper de Petukhina et al.),
   ahora con muchos meses de datos donde la hora del día sí varía.
3. **Funding rate de perpetuos**: extremos de funding (Hyperliquid lo paga cada hora) como
   señal de posicionamiento excesivo y reversión en horas.
4. **Rupturas de volatilidad**: compresión de volatilidad seguida de ruptura (horas).
5. **Flujo de órdenes** (desequilibrio comprador/vendedor, volumen
   anómalo): ya hay features en `features.py`; con más datos se sabrá si sirven.
6. **Régimen de volatilidad**: operar solo en regímenes donde la estrategia históricamente
   funciona (filtro, no señal).
7. **Modelo combinado (ML)**: las señales de 1-6 como features de un LightGBM, con
   meta-labeling encima.

### Fase D: Noticias (secundario, como pediste)
- Fuentes: CryptoPanic API, GDELT, RSS de medios cripto; sentimiento con un modelo tipo
  FinBERT/CryptoBERT en la 3060.
- Uso principal: **filtro de riesgo** (no abrir posiciones justo en noticias de alto
  impacto) más que señal de entrada. Los datos históricos de noticias con hora exacta
  son el cuello de botella; se valida igual que el resto o no entra.

### Fase E: Paso a real (solo si todo lo anterior pasa)
1. Semanas en paper con resultados coherentes con el backtest.
2. Hyperliquid **testnet** con el SDK oficial (órdenes firmadas).
3. Mainnet con tamaño mínimo, límites de pérdida diaria y *kill switch*.

---

## 5. Resultados del laboratorio (`research/`, 2026-09-30)

Walk-forward 90 d train / 30 d test en Binance SOLUSDT 1 h (fuera de muestra 2023-04 → 2026-09),
costes 0,065 %/lado + funding, 255 configuraciones probadas en total.

| Estrategia | Retorno | Sharpe | Max DD | Últimos 6 m | Veredicto |
|---|---|---|---|---|---|
| **Buy & hold (benchmark)** | +372 % | 0.95 | −78 % | +47 % | — |
| Regla simple (benchmark) | −95 % | −0.60 | −96 % | −28 % | — |
| Momentum intradía | −71 % | −0.28 | −86 % | +14 % | ❌ |
| Reversión intradía | −77 % | −0.33 | −84 % | −25 % | ❌ |
| Estacionalidad horaria | −84 % | −0.93 | −90 % | −31 % | ❌ |
| Funding extremo | −49 % | −0.30 | −54 % | −6 % | ❌ |
| Ruptura de volatilidad | +126 % | 0.81 | −39 % | +9 % | ❌ (la mejor) |
| Flujo de órdenes | −81 % | −0.84 | −87 % | −21 % | ❌ |

Conclusiones:
- **Ninguna pasa.** Casi todas pierden por los costes: sus ventajas brutas son más pequeñas que 0,13 % por operación.
- **Ruptura de volatilidad** es la única robusta en parámetros (67 % de combinaciones ganan,
  mejor con hold 24-48 h), pero casi todo su beneficio viene de los largos (+97 % vs +13 %
  cortos) y de 2025-2026; en 2023-2024 fue plana. Parece más "ir largo en mercado alcista"
  que una ventaja propia. En Hyperliquid (mayo-sep 2026) pierde (−8 %).
- En Hyperliquid solo el momentum intradía gana algo (+9 %, Sharpe 0.70), sin batir a buy & hold (+41 %).
- DSR ≈ 0: con 255 configuraciones, ningún resultado se distingue de la suerte.

### Órdenes límite (maker), 2026-09-30
Modelo conservador: límite al cierre de la señal, solo se llena si el precio lo **cruza**
en las 2 h siguientes (selección adversa incluida); salida límite y, si no se llena en 1 h,
a mercado. Comisión maker 0,015 % vs 0,045 % + 0,02 % slippage taker.

| Estrategia | Taker | Maker (límite al cierre) | Maker (límite 0,1 % mejor) |
|---|---|---|---|
| Momentum intradía | −71 % | −22 % | −22 % (últimos 6 m: +19 %, Sharpe 0.97) |
| Reversión intradía | −77 % | −85 % | −80 % |
| Estacionalidad horaria | −84 % | −80 % | −24 % |
| Funding extremo | −49 % | −32 % | +2 % |
| Ruptura de volatilidad | **+126 %** | +64 % | +19 % |
| Flujo de órdenes | −81 % | −52 % | −67 % |

- Bajar costes **mejora** momentum, funding y estacionalidad, pero **ninguna pasa** ni bate a buy & hold (+372 %).
- La ruptura **empeora** con maker: las rupturas buenas se escapan sin llenar la orden (selección adversa).
- El modelo de llenado con velas de 1 h es optimista (no sabe la posición en la cola): en real sería peor.
- Única pista a vigilar: momentum intradía con límite 0,1 % en los últimos 6 meses. Puede ser ruido:
  en el periodo completo pierde.

### Modelo combinado (ML), 2026-09-30 — `research/run_ml.py`
67 features sin fuga de datos (verificado): precio multi-horizonte, **estructura de mercado**
(swings HH/HL, rupturas), volatilidad, flujo de órdenes, **funding, open interest y ratios
largo/corto**, **BTC/ETH**, calendario, **Fear & Greed y visitas a Wikipedia**.
Etiquetas de triple barrera (TP/SL a ±1σ√H, tiempo H), HistGradientBoosting, walk-forward
mensual 2023-09 → 2026-09, 16 configuraciones (H 12/24 h × ventana 1 año/todo × 4 umbrales).

- **AUC 0.49-0.51 en todas**: el modelo no distingue una buena entrada de una mala.
- Mejor variante +11,5 % (Sharpe 0.45, DD −77 %) vs buy & hold +413 % (Sharpe 1.05); su
  ventaja se degrada cada año (2023 +76 % → 2026 −57 %). DSR 0.10. ❌ No pasa.
- Noticias GDELT: la API bloqueó la IP de la Pi (límite de peticiones), no entraron. Se
  sustituye por el recolector RSS propio (`scripts/news_collector.py`, cron cada 15 min,
  tabla `news_headlines`) para acumular historial con hora exacta.
- Datos en vivo (`research/live_data.py`) comparados con el histórico: precios idénticos;
  OI y ratios con ruido de 0,1-0,4 % (Binance retoca sus archivos) → `oi_chg_1h` no es fiable en vivo.

**Conclusión:** con datos públicos, en SOL, a horizontes de 1-48 h, no hemos encontrado
ninguna ventaja explotable tras costes: 6 estrategias de papers (255 configuraciones),
ejecución a mercado y límite, y un modelo con 67 features. Es coherente con un mercado
muy competido.

### Exposición gestionada (lo único que mejora a buy & hold), 2026-09-30
3 variantes fijadas de antemano (sin optimizar), ajuste diario a las 00 UTC, con costes y funding,
fuera de muestra 2023-09 → 2026-09:

| Variante | Retorno | Sharpe | Max DD | Exposición media |
|---|---|---|---|---|
| Comprar y mantener | +417 % | 1.05 | −78 % | 100 % |
| A) Volatilidad objetivo 60 % anual | +330 % | 1.08 | −71 % | 76 % |
| **B) Filtro de tendencia (precio > EMA 50 días)** | **+473 %** | **1.22** | **−56 %** | 51 % |
| **C) A + B** | +321 % | **1.27** | **−51 %** | 39 % |

- Coherente con la literatura (Moreira & Muir 2017 "Volatility-Managed Portfolios";
  trend following / time-series momentum de Moskowitz, Ooi & Pedersen 2012).
- Pocas pruebas (3) → poco riesgo de sobreajuste, pero es un solo activo y ~3 años: la
  evidencia es moderada. 2025 sigue en negativo y el DD sigue siendo alto (−51 %).
- **Rompe la regla de "operaciones ≤ 48 h"**: las posiciones duran semanas (se revisan a diario).

## 6. Próximos pasos
1. **Combinar en lugar de elegir**: las señales como features de un LightGBM (en el PC) con
   pesos mayores para datos recientes, validado con el mismo walk-forward.
2. **Filtro de régimen**: ruptura solo a favor de la tendencia diaria/semanal (solo largos
   en tendencia alcista), para ver si queda ventaja además del beta.
3. ~~Reducir costes con órdenes límite~~ ✅ probado (ver arriba): ayuda, pero no basta.
4. **Más papers**: añadirlos en `research/strategies.py` y apuntar aquí el resultado.

## 7. Próximo paso concreto (original)
✅ Hecho: fases A y B en `research/` (ver sección 5). Uso en el PC: `research/README.md`.
