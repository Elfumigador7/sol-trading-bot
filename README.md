# 🚀 Sistema de Trading Automatizado - Solana/Hyperliquid

> **📌 Estado actual (30-sep-2026):** este README describe la idea original. Cómo funciona hoy el sistema: [`docs/ESTADO_BOT.md`](docs/ESTADO_BOT.md). Historia completa (Jupyter, ONNX, qué falló y cómo se llegó aquí): [`docs/HISTORIA.md`](docs/HISTORIA.md).


## 🏗️ Arquitectura Dual

```
┌─────────────────────────────────────────────────────────────┐
│                    RED LOCAL (LAN/WiFi)                      │
├──────────────────────────┬──────────────────────────────────┤
│  NODO 1: RASPBERRY PI    │  NODO 2: PC ESCRITORIO           │
│  (Ejecución 24/7)        │  (Entrenamiento bajo demanda)    │
├──────────────────────────┼──────────────────────────────────┤
│  • TimescaleDB           │  • Jupyter Notebook              │
│  • Data Ingester         │  • Python + ML Libraries         │
│  • Trading Engine        │  • SQL Connector                 │
│  • Modelo ONNX           │  • Exportador .onnx              │
└──────────────────────────┴──────────────────────────────────┘
```

---

## 📋 Hoja de Ruta (4 Fases)

### ✅ **FASE 1: La Fundación de Datos** (Dificultad: Baja)

#### Paso 1: Preparar Raspberry Pi
```bash
# 1. Instalar Raspberry Pi OS 64-bit en SSD M.2
# 2. Actualizar sistema
sudo apt update && sudo apt upgrade -y

# 3. Instalar Docker
curl -fsSL https://get.docker.com | bash
sudo usermod -aG docker $USER
newgrp docker

# 4. Clonar este repositorio en la Pi
cd ~
git clone <tu-repo>
cd trading_system
```

#### Paso 2: Levantar TimescaleDB con Docker
```bash
# Iniciar contenedor
docker-compose up -d

# Verificar que funciona
docker ps
docker logs timescaledb

# Conectar a la base de datos (opcional)
docker exec -it timescaledb psql -U solana_user -d solana_trading
```

#### Paso 3: Instalar dependencias Python en la Pi
```bash
# Instalar Python y pip si no existen
sudo apt install python3-pip -y

# Crear entorno virtual (recomendado)
python3 -m venv venv
source venv/bin/activate

# Instalar requirements
pip install -r requirements.txt
```

#### Paso 4: Ejecutar el Data Ingester
```bash
# Ejecutar en segundo plano (usando nohup o systemd)
nohup python3 scripts/data_ingester.py > ingester.log 2>&1 &

# O usar screen/tmux para sesión persistente
screen -S trading
python3 scripts/data_ingester.py
# Ctrl+A, D para desconectar
```

#### Paso 5: Verificar que funciona
```bash
# Chequear logs
tail -f ingester.log

# Consultar datos en DB
docker exec -it timescaledb psql -U solana_user -d solana_trading -c "SELECT COUNT(*) FROM solana_trades;"
```

**✅ Éxito cuando:** Ves trades llegando cada segundo y la tabla crece.

---

### 🧠 **FASE 2: El Cerebro Base** (Dificultad: Media)

#### Paso 1: Conectar PC al DB de la Pi
En tu PC escritorio, crear `scripts/db_connector.py`:
```python
import asyncpg
import pandas as pd

async def fetch_trades(days=7):
    conn = await asyncpg.connect(
        host='192.168.1.X',  # IP de tu Pi
        port=5432,
        database='solana_trading',
        user='solana_user',
        password=os.getenv('DB_PASSWORD')
    )
    
    query = """
    SELECT * FROM solana_trades 
    WHERE timestamp > NOW() - INTERVAL '{} days'
    ORDER BY timestamp DESC
    """.format(days)
    
    df = await conn.fetchdf(query)
    await conn.close()
    return df

# Ejecutar
trades = asyncio.run(fetch_trades(7))
print(f"Descargados {len(trades)} trades de los últimos 7 días")
```

#### Paso 2: Entrenar modelo simple (Jupyter Notebook)
Crear `notebooks/train_simple_model.ipynb`:
- Cargar datos desde DB
- Crear features (RSI, MACD, volumen)
- Entrenar Random Forest / XGBoost
- Evaluar con backtesting básico

#### Paso 3: Exportar a ONNX
```python
from sklearn.ensemble import RandomForestClassifier
import onnx

# Entrenar modelo
model = RandomForestClassifier()
model.fit(X_train, y_train)

# Exportar a ONNX
from skl2onnx import convert_sklearn
onnx_model = convert_sklearn(model, initial_types=[('input', FloatTensorType([None, X_train.shape[1]]))])

with open("models/solana_model.onnx", "wb") as f:
    onnx.save(onnx_model, f)
```

#### Paso 4: Enviar modelo a la Pi
```bash
# Opción A: SCP desde PC
scp models/solana_model.onnx pi@192.168.1.X:/home/pi/trading_system/models/

# Opción B: Carpeta compartida SMB/NFS
mount -t cifs //PI_IP/share /mnt/pi_share -o user=pi,password=...
cp solana_model.onnx /mnt/pi_share/
```

**✅ Éxito cuando:** Tienes un modelo .onnx en la carpeta `models/` de la Pi.

---

### 🎯 **FASE 3: Ejecución en Papel** (Dificultad: Alta)

#### Paso 1: Hyperliquid Testnet Setup
1. Ir a https://testnet.hyperliquid.xyz/
2. Crear cuenta y obtener API Agent Key
3. Guardar en archivo `.env`:
```
HYPERLIQUID_API_KEY=tu_clave_aqui
HYPERLIQUID_API_SECRET=tu_secret_aqui
TESTNET=True
```

#### Paso 2: Trading Engine (Raspberry Pi)
Crear `scripts/trading_engine.py` (similar al Data Ingester pero con lógica de trading):
- Cargar modelo .onnx en memoria
- Escuchar WebSocket en tiempo real
- Calcular predicción cada segundo
- Enviar órdenes si probabilidad > umbral

#### Paso 3: Hot Reload System
Crear `scripts/model_watcher.py`:
```python
import watchdog
import os

class ModelReloader(watchdog.observers.Observer):
    def on_created(self, event):
        if event.src_path.endswith('.onnx'):
            logger.info("🔄 Nuevo modelo detectado, recargando...")
            # Recargar modelo en memoria sin reiniciar engine
```

#### Paso 4: Backtesting Manual
- Ejecutar Trading Engine con órdenes "en papel" (sin ejecutar realmente)
- Guardar señales y resultados en `trading_history.csv`
- Comparar con precio real después

**✅ Éxito cuando:** El sistema genera señales de compra/venta consistentes.

---

### 📈 **FASE 4: Modo Quant** (Dificultad: Continua)

#### Análisis Avanzado (PC Escritorio)
- NLP en noticias crypto (sentimiento)
- Aprendizaje por Refuerzo (RL)
- Modelos ensemble (XGBoost + Neural Networks)

#### Monitorización (Dashboard)
- Grafana + Prometheus para métricas en tiempo real
- Alertas Telegram/Discord para trades
- Reporte semanal de P&L

---

## 📂 Estructura del Proyecto

```
trading_system/
├── docker-compose.yml          # Configuración Docker TimescaleDB
├── requirements.txt            # Dependencias Python
├── .env                        # Variables de entorno (API keys)
│
├── scripts/
│   ├── data_ingester.py       # Módulo 1: Recolector de datos
│   ├── trading_engine.py      # Módulo 2: Motor de trading
│   └── model_watcher.py       # Hot reload de modelos
│
├── notebooks/                  # Jupyter Notebooks para análisis
│   ├── train_simple_model.ipynb
│   └── backtest_strategy.ipynb
│
├── models/                     # Modelos ONNX exportados
│   └── solana_model.onnx
│
├── data/                       # Datos locales (opcional)
│   └── exports/
│
└── docs/                       # Documentación
    ├── arquitectura.md
    └── guia_rapida.md
```

---

## 🔧 Comandos Útiles

### En Raspberry Pi:
```bash
# Reiniciar contenedor Docker
docker-compose restart timescaledb

# Ver logs de ingester
tail -f trading_ingester.log

# Detener todo
docker-compose down

# Backup de base de datos
docker exec timescaledb pg_dump -U solana_user solana_trading > backup_$(date +%Y%m%d).sql
```

### En PC Escritorio:
```bash
# Conectar a DB remota
psql -h 192.168.1.X -U solana_user -d solana_trading

# Exportar datos a CSV
python scripts/export_data.py --days 30 --output data/exports/trades_30d.csv
```

---

## 🎯 Próximos Pasos Inmediatos

1. **HOY:** Formatear SSD M.2 e instalar Raspberry Pi OS en la Pi
2. **MAÑANA:** Levantar TimescaleDB y ejecutar Data Ingester por 24h
3. **SEMANA 1:** Conectar PC a DB, descargar datos, entrenar primer modelo
4. **SEMANA 2:** Implementar Trading Engine con órdenes en papel
5. **SEMANA 3+:** Modo Quant con análisis avanzado

---

## 📊 Métricas de Éxito

- ✅ Data Ingester: Recibe >100 trades/minuto sin lag
- ✅ Modelo: Acuracidad >55% en backtesting (mejor que aleatorio)
- ✅ Trading Engine: Latencia <100ms desde señal a orden
- ✅ Sistema: Uptime 99.5% en producción

---

## 🛠️ Troubleshooting

**Problema:** Data Ingester se desconecta del WebSocket  
**Solución:** Agregar reconnection logic con `asyncio.sleep(5)` antes de reconnectar

**Problema:** DB llena de datos (TBs)  
**Solución:** Implementar particionamiento por tiempo en TimescaleDB

**Problema:** Modelo lento en Pi  
**Solución:** Usar ONNX Runtime con optimización para CPU, reducir complejidad del modelo

---

## 📞 Soporte y Recursos

- [Documentación Hyperliquid API](https://hyperliquid.xyz/developers/api)
- [TimescaleDB Docs](https://docs.timescale.com/)
- [ONNX Runtime Guide](https://onnxruntime.ai/docs/)

**¡Manos a la obra! 🚀**
