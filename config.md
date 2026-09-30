# Sistema de Trading Automatizado - Configuración Principal

## 🎯 Estado del Proyecto (2026-09-30)

### ✅ Fase 1: La Fundación de Datos
- [x] `docker-compose.yml` - TimescaleDB configurado
- [x] `data_ingester.py` - Recolector de datos Hyperliquid
- [x] `requirements.txt` - Dependencias instaladas
- [ ] **PENDIENTE:** Ejecutar en Raspberry Pi

### 🔄 Fase 2: El Cerebro Base  
- [x] `export_data.py` - Conector PC ↔ Pi
- [x] `train_simple_model.ipynb` - Notebook de entrenamiento
- [x] `model_config.json` - Configuración del modelo
- [ ] **PENDIENTE:** Entrenar primer modelo

### ⏳ Fase 3: Ejecución en Papel
- [x] `trading_engine.py` - Motor de trading ONNX
- [x] `hot_reload.py` - Vigilante de modelos
- [x] `.env` - Variables de entorno (configurar API Keys)
- [ ] **PENDIENTE:** Configurar Hyperliquid Testnet

### 🚀 Fase 4: Modo Quant
- [x] `system_monitor.py` - Dashboard de monitorización
- [ ] **PENDIENTE:** Análisis NLP + RL

---

## 📋 Comandos Rápidos

### En Raspberry Pi (Nodo 1):
```bash
# Iniciar todo el sistema
cd trading_system
source venv/bin/activate
docker-compose up -d
python scripts/data_ingester.py &
python scripts/trading_engine.py &
python scripts/system_monitor.py
```

### En PC Escritorio (Nodo 2):
```bash
# Conectar a la base de datos
psql -h 192.168.1.X -U solana_user -d solana_trading

# Exportar datos para análisis
python scripts/export_data.py --days 7 --type trades

# Ejecutar notebook Jupyter
jupyter notebook notebooks/train_simple_model.ipynb
```

---

## 🔑 Variables de Entorno (`.env`)

```bash
# Hyperliquid API (obtener en testnet.hyperliquid.xyz)
HYPERLIQUID_API_KEY=tu_clave_aqui
HYPERLIQUID_API_SECRET=tu_secret_aqui

# Base de Datos
DB_PASSWORD=<tu_contraseña>

# Trading
TRADE_SIZE_SOL=1.0
PROBABILITY_THRESHOLD=0.60
```

---

## 📊 URLs Útiles

- **Hyperliquid Testnet:** https://testnet.hyperliquid.xyz/
- **TimescaleDB UI (si configuras pgAdmin):** http://localhost:5432
- **Jupyter Notebook:** http://localhost:8888

---

## 🛠️ Troubleshooting Común

**Problema:** Data Ingester no conecta  
**Solución:** Verificar que Docker está corriendo: `docker ps`

**Problema:** Modelo ONNX no carga  
**Solución:** Asegurar que el modelo fue exportado con skl2onnx correctamente

**Problema:** Latencia alta en trading  
**Solución:** Usar ONNX Runtime con optimización CPU: `ort.InferenceSession(..., providers=['CPUExecutionProvider'])`

---

## 📈 Métricas a Monitorear

- **Trades/minuto:** Debería ser >100 para SOL
- **Latencia de predicción:** <50ms por inferencia
- **Uptime del sistema:** >99%
- **P&L acumulado:** Registrar en `paper_trades.csv`

---

## 📚 Documentación Adicional

Ver archivos en `/docs/`:
- `arquitectura.md` - Detalles técnicos de la arquitectura
- `guia_rapida.md` - Guía paso a paso para principiantes
