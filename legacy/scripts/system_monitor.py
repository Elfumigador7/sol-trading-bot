#!/usr/bin/env python3
"""
📊 SYSTEM MONITOR - Dashboard del estado del sistema
Verifica que todos los componentes estén funcionando correctamente.
"""

import psutil
import asyncpg
from datetime import datetime, timedelta
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def check_database_health():
    """Verificar estado de la base de datos."""
    
    try:
        conn = await asyncpg.connect(
            host='localhost',
            port=5432,
            database='solana_trading',
            user='solana_user',
            password=os.getenv('DB_PASSWORD')
        )
        
        # Contar trades recientes
        result = await conn.fetchval("""
            SELECT COUNT(*) FROM solana_trades 
            WHERE timestamp > NOW() - INTERVAL '1 hour'
        """)
        
        await conn.close()
        
        if result is None or result == 0:
            return {"status": "OK", "trades_last_hour": 0}
            
        return {
            "status": "HEALTHY",
            "total_trades": result,
            "last_check": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ DB Health Check failed: {e}")
        return {"status": "ERROR", "error": str(e)}


def check_system_resources():
    """Verificar recursos del sistema."""
    
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    return {
        "cpu_percent": cpu_percent,
        "memory_percent": memory.percent,
        "disk_percent": disk.percent,
        "disk_free_gb": disk.free / (1024**3)
    }


def check_processes():
    """Verificar procesos críticos."""
    
    processes = {
        "data_ingester": False,
        "trading_engine": False,
        "timescaledb": False
    }
    
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            name = proc.info['name'].lower()
            if 'ingester' in name:
                processes["data_ingester"] = True
            elif 'trading_engine' in name:
                processes["trading_engine"] = True
            elif 'postgres' in name or 'timescale' in name:
                processes["timescaledb"] = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    return processes


def generate_report():
    """Generar reporte completo del sistema."""
    
    logger.info("=" * 60)
    logger.info("📊 REPORTE DEL SISTEMA DE TRADING")
    logger.info(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    # Recursos del sistema
    resources = check_system_resources()
    logger.info("\n💻 RECURSOS DEL SISTEMA:")
    logger.info(f"   CPU: {resources['cpu_percent']:.1f}%")
    logger.info(f"   RAM: {resources['memory_percent']:.1f}%")
    logger.info(f"   Disco: {resources['disk_free_gb']:.2f} GB libres")
    
    # Procesos
    processes = check_processes()
    logger.info("\n🔄 PROCESOS ACTIVOS:")
    for proc, active in processes.items():
        status = "✅" if active else "❌"
        logger.info(f"   {status} {proc}")
    
    # Base de datos (async)
    import asyncio
    db_health = asyncio.run(check_database_health())
    logger.info("\n🗄️ BASE DE DATOS:")
    logger.info(f"   Estado: {db_health['status']}")
    if 'trades_last_hour' in db_health:
        logger.info(f"   Trades (última hora): {db_health['trades_last_hour']}")


if __name__ == "__main__":
    generate_report()
