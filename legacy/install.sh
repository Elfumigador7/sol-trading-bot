#!/bin/bash
# 🚀 INSTALACIÓN RÁPIDA - Sistema de Trading Solana
# Ejecutar en Raspberry Pi: bash install.sh

set -e  # Salir si hay error

echo "🔧 Iniciando instalación..."

# 1. Actualizar sistema
echo "📦 Actualizando paquetes..."
sudo apt update && sudo apt upgrade -y

# 2. Instalar Docker
echo "🐳 Instalando Docker..."
curl -fsSL https://get.docker.com | bash
sudo usermod -aG docker $USER
newgrp docker

# 3. Instalar Python y dependencias
echo "🐍 Instalando Python y pip..."
sudo apt install python3-pip python3-venv -y

# 4. Clonar o actualizar repositorio
if [ ! -d "trading_system" ]; then
    echo "📥 Clonando repositorio..."
    git clone <tu-repo-url> trading_system
else
    echo "🔄 Actualizando repositorio existente..."
    cd trading_system && git pull && cd ..
fi

# 5. Configurar entorno virtual
echo "⚙️ Configurando entorno Python..."
cd trading_system
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 6. Levantar contenedor Docker
echo "🐳 Iniciando TimescaleDB..."
docker-compose up -d

# 7. Crear estructura de directorios
mkdir -p data/exports models scripts notebooks docs

# 8. Copiar .env.example a .env si no existe
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "📝 Archivo .env creado (recuerda editar con tus claves)"
fi

echo ""
echo "✅ ¡Instalación completada!"
echo ""
echo "📋 Próximos pasos:"
echo "1. Ejecutar: source venv/bin/activate"
echo "2. Iniciar Data Ingester: python scripts/data_ingester.py"
echo "3. Ver logs: tail -f trading_ingester.log"
echo ""
