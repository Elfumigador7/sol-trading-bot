# 🏗️ Arquitectura Técnica - Sistema de Trading Solana

## Topología de Red

```
┌─────────────────────────────────────────────────────────────────┐
│                        RED LOCAL (LAN)                          │
│                                                                 │
│  ┌──────────────────────┐         ┌─────────────────────────┐  │
│  │   NODO 1: RASPBERRY  │         │    NODO 2: PC ESCRITORIO│  │
│  │      PI (24/7)       │◄───────►│     (Bajo Demanda)      │  │
│  └──────────────────────┘  TCP/IP └─────────────────────────┘  │
│         │                              │                        │
│         ▼                              ▼                        │
│  ┌──────────────┐              ┌──────────────┐                │
│  │ TimescaleDB  │              │ Jupyter      │                │
│  │ (PostgreSQL) │              │ Notebook     │                │
│  │ Port: 5432   │              │ Python       │                │
│  └──────────────┘              └──────────────┘                │
│         │                              │                        │
│  ┌──────────────┐              ┌──────────────┐                │
│  │ Data         │              │ Entrenar     │                │
│  │ Ingester     │              │ Modelo       │                │
│  │ Python       │              │ .onnx        │                │
│  └──────────────┘              └──────────────┘                │
│         │                              │                        │
│  ┌──────────────┐              ┌──────────────┐                │
│  │ Trading      │              │ Export       │                │
│  │ Engine       │◄────────────►│ SCP/SSH      │                │
│  │ ONNX         │   Modelo     │ Transfer     │                │
│  └──────────────┘              └──────────────┘                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Componentes del Sistema

### 🗄️ Base de Datos: TimescaleDB (PostgreSQL)

**Ubicación:** Raspberry Pi  
**Puerto:** 5432  
**Tabla Principal:** `solana_trades`

```sql
CREATE TABLE solana_trades (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    trade_id TEXT,
    side TEXT,           -- 'B' = Buy, 'S' = Sell
    size NUMERIC(20, 8), -- Cantidad en SOL
    price NUMERIC(20, 8),-- Precio de ejecución
    usd_value NUMERIC(30, 2), -- Valor en USD
    is_buyer_maker BOOLEAN
);

-- Índices para consultas temporales
CREATE INDEX idx_trades_timestamp ON solana_trades(timestamp);
```

**Ventajas:**
- Optimizado para series temporales
- Compresión automática de datos antiguos
- Consultas SQL rápidas con agregaciones
- Compatible con herramientas existentes (Grafana, pgAdmin)

---

### 📡 Módulo 1: Data Ingester

**Ubicación:** Raspberry Pi  
**Lenguaje:** Python + Asyncio  
**Conexión:** WebSocket Hyperliquid

```python
# Arquitectura del Data Ingester
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ WebSocket   │────►│ Parser       │────►│ Database     │
│ Listener    │     │ de Mensajes  │     │ Insert       │
└─────────────┘     └──────────────┘     └──────────────┘
```

**Características:**
- Consume <1% CPU, <50MB RAM
- Reconnection automática si se desconecta
- Logs detallados en `logs/ingester.log`
- Inserta ~100-500 trades/minuto (dependiendo de volumen SOL)

---

### 🧠 Módulo 2: Trading Engine

**Ubicación:** Raspberry Pi  
**Modelo:** ONNX Runtime (CPU optimizado)  
**Latencia Objetivo:** <50ms por predicción

```python
# Flujo del Trading Engine
┌──────────┐    ┌─────────────┐    ┌──────────┐    ┌──────────┐
│ Precio   │───►│ Extraer     │───►│ Inferir  │───►│ Enviar   │
│ Tiempo   │    │ Features    │    │ Modelo   │    │ Orden    │
│ Real      │    │             │    │ ONNX     │    │          │
└──────────┘    └─────────────┘    └──────────┘    └──────────┘
```

**Features Calculadas:**
- RSI (14 períodos)
- MACD (12, 26, 9)
- Volumen promedio móvil (20 períodos)
- Volatilidad (ATR 14)
- Precio actual y cambios porcentuales

**Hot Reload:**
- Vigila carpeta `models/` cada 5 segundos
- Recarga modelo en memoria sin reiniciar proceso
- Backup automático de modelos anteriores

---

### 💻 Módulo 3: Export Data (PC Escritorio)

**Ubicación:** PC con RTX 3060  
**Conexión:** TCP/IP a Raspberry Pi  
**Función:** Descargar datos históricos para análisis

```python
# Ejemplo de consulta optimizada
SELECT 
    date_trunc('minute', timestamp) as minute,
    AVG(price) as avg_price,
    MAX(price) - MIN(price) as range_1m,
    SUM(size) as volume_sol
FROM solana_trades 
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY minute;
```

**Optimizaciones:**
- Usa índices de tiempo en la DB
- Limita resultados con `LIMIT` si es necesario
- Exporta a CSV/Parquet para análisis rápido

---

### 🎯 Módulo 4: Entrenamiento (Jupyter Notebook)

**Ubicación:** PC Escritorio  
**Librerías:** pandas, scikit-learn, xgboost, onnx

```python
# Pipeline de entrenamiento típico
1. Cargar datos desde DB → pd.read_csv()
2. Calcular features técnicas → ta-lib / pandas
3. Crear target (subida/bajada futura)
4. Split train/test (80/20, shuffle=False para series temporales)
5. Entrenar modelo → RandomForest / XGBoost
6. Evaluar con backtesting walk-forward
7. Exportar a ONNX → skl2onnx.convert_sklearn()
```

**Métricas de Evaluación:**
- Accuracy (objetivo: >55%, mejor que aleatorio)
- Precision/Recall por clase
- F1-Score
- Backtest P&L acumulado

---

## Flujo de Datos Completo

### Ciclo 24/7 (Producción)
```
Hyperliquid WebSocket
        │
        ▼
[Data Ingester] → [TimescaleDB] ←───┐
        │                            │
        ▼                            │
[Trading Engine] ◄─── Modelo ONNX   │
        │                            │
        ▼                            │
[Enviar Orden a Hyperliquid]         │
        │                            │
        └────────────────────────────┘
```

### Ciclo Bajo Demanda (Análisis)
```
[PC Escritorio] → [Conectar a DB Pi] → [Descargar Datos]
        │                                    │
        ▼                                    ▼
[Entrenar Modelo] ←─── [Analizar Datos]  [Exportar CSV]
        │
        ▼
[Exportar .onnx] → [SCP a Raspberry Pi] → [Hot Reload]
```

---

## Especificaciones de Hardware

### Raspberry Pi (Nodo 1)
- **RAM:** 16 GB DDR4
- **Almacenamiento:** SSD M.2 NVMe 500GB+
- **CPU:** Raspberry Pi 5 (8 cores) o similar
- **Consumo:** ~10W en reposo, ~20W bajo carga
- **OS:** Raspberry Pi OS 64-bit

### PC Escritorio (Nodo 2)
- **GPU:** RTX 3060 12GB VRAM (opcional para deep learning)
- **RAM:** 32 GB DDR4
- **CPU:** Ryzen 7 / Intel i7
- **Almacenamiento:** SSD NVMe 1TB+
- **OS:** Windows/Linux

---

## Rendimiento Esperado

| Componente | CPU | RAM | Latencia |
|------------|-----|-----|----------|
| Data Ingester | <1% | ~50MB | <10ms por trade |
| Trading Engine | <5% | ~200MB | <50ms por predicción |
| TimescaleDB | <10% | ~1GB | <5ms por query |

---

## Escalabilidad

### Fase 1 (Actual): Solana Solo
- Un solo par: SOL/USD
- ~100-500 trades/minuto

### Fase 2 (Futura): Multi-Pair
- Añadir BTC, ETH, otros altcoins
- Múltiples modelos ONNX simultáneos
- Escalar a Raspberry Pi 4B con más RAM

### Fase 3 (Avanzada): Deep Learning
- Modelos LSTM/Transformer en GPU del PC
- Análisis de sentimiento NLP en noticias
- Aprendizaje por Refuerzo para optimización de órdenes

---

## Backup & Recovery

### Base de Datos
```bash
# Backup diario automático
docker exec timescaledb pg_dump -U solana_user solana_trading > backup_$(date +%Y%m%d).sql

# Restaurar desde backup
docker exec -i timescaledb psql -U solana_user -d solana_trading < backup_20260930.sql
```

### Modelos
- Mantener 3 versiones anteriores en `models/backup/`
- Cada nuevo modelo reemplaza al anterior pero se guarda copia

---

## Monitoreo & Alertas

### Herramientas Sugeridas
1. **Grafana + Prometheus:** Métricas de sistema (CPU, RAM, Disk)
2. **Custom Python Script:** Verificar uptime de procesos
3. **Telegram Bot:** Notificaciones de trades ejecutados

### KPIs Críticos
- Trades/minuto recibidos
- Latencia de predicción
- Uptime del sistema (>99%)
- P&L acumulado (paper trading)

---

## Referencias Técnicas

- [Hyperliquid API Docs](https://hyperliquid.xyz/developers/api)
- [TimescaleDB Documentation](https://docs.timescale.com/)
- [ONNX Runtime Guide](https://onnxruntime.ai/docs/)
- [Asyncio Python Docs](https://docs.python.org/3/library/asyncio.html)

---

**Versión:** 1.0.0  
**Fecha:** 2026-09-30  
**Autor:** Sistema de Trading Automatizado
