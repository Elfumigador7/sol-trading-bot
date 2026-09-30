#!/usr/bin/env python3
"""
🔄 HOT RELOAD - Vigilante de cambios en carpetas de modelos
Detecta nuevos archivos .onnx y notifica al Trading Engine para recargar.
"""

import os
import time
from pathlib import Path
import logging
import hashlib

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ModelWatcher:
    """Vigila cambios en la carpeta de modelos."""
    
    def __init__(self, model_path: str, callback=None):
        self.model_path = Path(model_path)
        self.callback = callback
        self.last_hash = None
        
        if self.model_path.exists():
            self.last_hash = self._calculate_hash(self.model_path)
            
    def _calculate_hash(self, filepath: Path) -> str:
        """Calcular hash MD5 del archivo."""
        with open(filepath, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    
    def check_for_updates(self) -> bool:
        """Verificar si hay nuevo modelo."""
        
        if not self.model_path.exists():
            return False
            
        current_hash = self._calculate_hash(self.model_path)
        
        if self.last_hash and current_hash != self.last_hash:
            logger.info(f"🔄 Nuevo modelo detectado: {self.model_path.name}")
            self.last_hash = current_hash
            return True
            
        return False
    
    def watch_loop(self, interval_seconds: int = 5):
        """Bucle de vigilancia continua."""
        
        logger.info(f"👁️ Vigilando carpeta: {self.model_path}")
        
        while True:
            if self.check_for_updates():
                if self.callback:
                    self.callback()
            
            time.sleep(interval_seconds)


def on_model_update():
    """Callback cuando se detecta nuevo modelo."""
    logger.info("🎯 Recargando modelo en memoria...")
    # Aquí puedes llamar a una función para recargar el modelo
    # o enviar señal al Trading Engine


if __name__ == "__main__":
    watcher = ModelWatcher(
        model_path="models/",  # Carpeta a vigilar
        callback=on_model_update
    )
    
    try:
        watcher.watch_loop(interval_seconds=5)
    except KeyboardInterrupt:
        logger.info("👋 Vigilante detenido")
