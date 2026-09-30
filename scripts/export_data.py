#!/usr/bin/env python3
"""
📤 DATA EXPORTER - Conector PC ↔ Raspberry Pi
Descarga datos históricos desde la base de datos de la Pi para análisis en Jupyter.
"""

import asyncio
import asyncpg
import pandas as pd
from datetime import datetime, timedelta
import argparse
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def fetch_trades(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    days: int = 7,
    limit: int = None
) -> pd.DataFrame:
    """Descargar trades desde la base de datos remota."""
    
    conn = await asyncpg.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password
    )
    
    query = """
    SELECT 
        timestamp,
        trade_id,
        side,
        size,
        price,
        usd_value,
        is_buyer_maker
    FROM solana_trades 
    WHERE timestamp > NOW() - INTERVAL '{} days'
    ORDER BY timestamp DESC
    """.format(days)
    
    if limit:
        query += f" LIMIT {limit}"
    
    df = await conn.fetchdf(query)
    await conn.close()
    
    return df


async def fetch_price_summary(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    days: int = 7
) -> pd.DataFrame:
    """Obtener resumen de precios agregados por minuto."""
    
    conn = await asyncpg.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password
    )
    
    query = """
    SELECT 
        date_trunc('minute', timestamp) as minute,
        COUNT(*) as trade_count,
        AVG(price) as avg_price,
        MAX(price) as high_price,
        MIN(price) as low_price,
        SUM(size) as total_volume_sol,
        SUM(usd_value) as total_volume_usd
    FROM solana_trades 
    WHERE timestamp > NOW() - INTERVAL '{} days'
    GROUP BY minute
    ORDER BY minute DESC
    """.format(days)
    
    df = await conn.fetchdf(query)
    await conn.close()
    
    return df


def save_to_csv(df: pd.DataFrame, filename: str):
    """Guardar DataFrame en CSV con timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"data/exports/{filename}_{timestamp}.csv"
    
    # Asegurar que existe el directorio
    import os
    os.makedirs("data/exports", exist_ok=True)
    
    df.to_csv(filepath, index=False)
    logger.info(f"✅ Datos guardados en: {filepath}")


async def main():
    parser = argparse.ArgumentParser(description="Exportar datos de Solana desde la Pi")
    parser.add_argument("--host", default="192.168.1.X", help="IP de la Raspberry Pi")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--days", type=int, default=7, help="Días a descargar")
    parser.add_argument("--limit", type=int, help="Límite de filas (opcional)")
    parser.add_argument("--type", choices=["trades", "summary"], default="trades")
    
    args = parser.parse_args()
    
    # Cargar desde .env si existe
    try:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        db_config = {
            'host': args.host,
            'port': args.port,
            'database': os.getenv('DB_NAME', 'solana_trading'),
            'user': os.getenv('DB_USER', 'solana_user'),
            'password': os.getenv('DB_PASSWORD')
        }
    except ImportError:
        db_config = {
            'host': args.host,
            'port': args.port,
            'database': 'solana_trading',
            'user': 'solana_user',
            'password': os.getenv('DB_PASSWORD')
        }
    
    logger.info(f"📡 Conectando a {db_config['host']}...")
    
    if args.type == "trades":
        df = await fetch_trades(**db_config, days=args.days, limit=args.limit)
        filename = f"solana_trades_{args.days}d"
        
    elif args.type == "summary":
        df = await fetch_price_summary(**db_config, days=args.days)
        filename = f"solana_summary_{args.days}d"
    
    logger.info(f"📊 Descargados {len(df)} registros")
    
    if len(df) > 0:
        save_to_csv(df, filename)
        
        # Mostrar estadísticas básicas
        logger.info("📈 Estadísticas:")
        logger.info(df.describe())


if __name__ == "__main__":
    import os
    asyncio.run(main())
