# 🚀 GUÍA RÁPIDA - Sistema de Trading Solana

## ⏱️ Primeros 30 Minutos

### Paso 1: Preparar Raspberry Pi (5 min)
```bash
# Instalar Docker
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | bash
sudo usermod -aG docker $USER
newgrp docker

# Clonar repositorio
cd ~
git clone <tu-repo>
cd trading_system
```

### Paso 2: Levantar Base de Datos (3 min)
```bash
docker-compose up -d
docker ps  # Verificar que timescaledb está corriendo
```

### Paso 3: Instalar Python y Dependencias (5 min)
```bash
sudo apt install python3-pip python3-venv -y
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Paso 4: Ejecutar Data Ingester (2 min)
```bash
# Crear carpeta de logs
mkdir -p logs

# Iniciar en segundo plano
nohup python scripts/data_ingester.py > logs/ingester.log 2>&1 &

# Verificar que funciona
tail -f logs/ingester.log
```

### Paso 5: Verificar Datos (3 min)
```bash
# Consultar base de datos
docker exec -it timescaledb psql -U solana_user -d solana_trading -c "SELECT COUNT(*) FROM solana_trades;"
```

---

## 📅 Primer Día Completo

### Mañana: Configuración Inicial
1. ✅ Formatear SSD M.2 con Raspberry Pi OS 64-bit
2. ✅ Instalar Docker y levantar TimescaleDB
3. ✅ Ejecutar Data Ingester por 2-3 horas
4. ✅ Verificar que la base de datos crece

### Tarde: Conectar PC a Pi
1. 📡 En tu PC, ejecutar `python scripts/export_data.py --days 1`
2. 📊 Ver los datos descargados en CSV
3. 🎯 Abrir Jupyter Notebook y entrenar modelo simple

### Noche: Primer Modelo ONNX
1. 💾 Exportar modelo a formato `.onnx`
2. 📤 Enviar a la Pi con `scp models/solana_model_v1.onnx pi@IP:/home/pi/trading_system/models/`
3. 🔄 Reiniciar Trading Engine en la Pi

---

## 🔑 Configuraciones Clave

### Archivo `.env` (en Raspberry Pi)
```bash
HYPERLIQUID_API_KEY=tu_clave_de_testnet
HYPERLIQUID_API_SECRET=tu_secret_aqui
PROBABILITY_THRESHOLD=0.60  # Ajustar según pruebas
TRADE_SIZE_SOL=1.0          # Empezar pequeño
```

### IP de tu Raspberry Pi
```bash
# En la Pi, obtener IP local
hostname -I

# Usar esta IP en:
# - export_data.py (host='192.168.X.X')
# - PC para conectar a DB
```

---

## 🎯 Próximos Pasos Inmediatos

### Semana 1: Validación
- [ ] Dejar Data Ingester corriendo 24/7
- [ ] Descargar datos cada día con `export_data.py`
- [ ] Entrenar modelo simple (Random Forest)
- [ ] Exportar y probar en Trading Engine

### Semana 2: Ejecución en Papel
- [ ] Configurar Hyperliquid Testnet API Keys
- [ ] Ejecutar Trading Engine con órdenes "reales" pero sin dinero
- [ ] Guardar historial de trades en `paper_trades.csv`
- [ ] Calcular P&L manual

### Semana 3+: Optimización
- [ ] Ajustar umbral de probabilidad (0.55 - 0.70)
- [ ] Añadir más features (RSI, MACD, volumen)
- [ ] Probar XGBoost en lugar de Random Forest
- [ ] Implementar stop loss y take profit

---

## 📊 KPIs a Monitorear

| Métrica | Objetivo | Cómo Medir |
|---------|----------|------------|
| Trades/minuto | >100 | `SELECT COUNT(*) FROM solana_trades WHERE timestamp > NOW() - INTERVAL '1 minute'` |
| Latencia predicción | <50ms | Tiempo entre recibir precio y obtener señal |
| Uptime sistema | >99% | Verificar logs diarios |
| Acuracidad modelo | >55% | Comparar señales con resultado real |

---

## 🛠️ Comandos Diarios Útiles

```bash
# Ver estado del sistema
python scripts/system_monitor.py

# Reiniciar Data Ingester
pkill -f data_ingester.py && nohup python scripts/data_ingester.py > logs/ingester.log 2>&1 &

# Exportar datos de hoy
python scripts/export_data.py --days 1 --type trades

# Ver últimos trades en DB
docker exec -it timescaledb psql -U solana_user -d solana_trading -c "SELECT * FROM solana_trades ORDER BY timestamp DESC LIMIT 10;"

# Backup de la base de datos
docker exec timescaledb pg_dump -U solana_user solana_trading > backup_$(date +%Y%m%d).sql
```

---

## 💡 Tips para Principiantes

1. **Empieza pequeño:** Usa Testnet primero, no Mainnet
2. **Monitoriza los logs:** `tail -f logs/*.log` cada día
3. **Backup diario:** Exporta datos de la DB al PC
4. **No sobreajustes:** Un modelo simple con 55% accuracy es mejor que uno complejo que falla
5. **Paciencia:** El sistema necesita días para generar datos suficientes

---

## 📞 ¿Problemas?

**Data Ingester se desconecta:** Agregar reconnection logic con `asyncio.sleep(5)` antes de reconnectar

**Modelo muy lento en Pi:** Usar ONNX Runtime optimizado para CPU

**DB llena de TBs:** Implementar particionamiento por tiempo (TimescaleDB lo hace automático)

---

## 🎉 ¡Felicidades!

Si llegaste hasta aquí, ya tienes tu sistema de trading automatizado funcionando. Ahora es cuestión de:
1. Dejarlo correr 24/7
2. Mejorar el modelo semanalmente
3. Ajustar parámetros según resultados
4. Escalar a Mainnet cuando estés listo

**¡Buena suerte y happy trading! 🚀📈**
