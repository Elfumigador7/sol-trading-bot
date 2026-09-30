"""
Conexión WebSocket a Hyperliquid con heartbeat y reconexión automática.

Hyperliquid cierra ("Expired") las conexiones que no envían nada en 60 s,
así que mandamos {"method": "ping"} periódicamente.
"""

import asyncio
import json
import logging

import websockets

PING_INTERVAL_S = 30
MAX_BACKOFF_S = 60


async def _heartbeat(ws):
    while True:
        await asyncio.sleep(PING_INTERVAL_S)
        await ws.send(json.dumps({"method": "ping"}))


async def run_ws(url: str, subscriptions: list, handler, logger: logging.Logger):
    """Conectar, suscribirse y pasar cada mensaje (dict) a `await handler(data)`, para siempre."""
    backoff = 1
    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as ws:
                logger.info(f"📡 Conectado a {url}")
                for sub in subscriptions:
                    await ws.send(json.dumps({"method": "subscribe", "subscription": sub}))
                    logger.info(f"✅ Suscrito a {sub['type']} de {sub.get('coin', '')}")

                heartbeat = asyncio.create_task(_heartbeat(ws))
                try:
                    async for message in ws:
                        backoff = 1
                        data = json.loads(message)
                        if data.get('channel') in ('pong', 'subscriptionResponse'):
                            continue
                        try:
                            await handler(data)
                        except Exception as e:
                            logger.error(f"❌ Error en procesamiento: {e}")
                finally:
                    heartbeat.cancel()

            logger.warning("🔴 Conexión cerrada por el servidor")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"🔴 Error de conexión: {e}")

        logger.info(f"🔄 Reconectando en {backoff}s...")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, MAX_BACKOFF_S)
