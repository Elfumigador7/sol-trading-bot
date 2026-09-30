#!/bin/bash
# 💾 Copia diaria de la base de datos (comprimida). Guarda los últimos 14 días en backups/.
# Protege contra errores y borrados; para protegerte de un fallo del disco, copia de vez en cuando
# la carpeta backups/ al PC:  scp -r fumi7@192.168.1.94:~/1TRADING/backups .
cd "$(dirname "$0")/.." || exit 1
mkdir -p backups
FILE="backups/db_$(date -u +%Y%m%d).sql.gz"
if docker exec solana_trading_db pg_dump -U solana_user solana_trading | gzip > "$FILE.tmp" && [ -s "$FILE.tmp" ]; then
    mv "$FILE.tmp" "$FILE"
    echo "$(date -u '+%F %T') ✅ copia $FILE ($(du -h "$FILE" | cut -f1))"
else
    rm -f "$FILE.tmp"
    echo "$(date -u '+%F %T') ❌ falló la copia"
    exit 1
fi
ls -1t backups/db_*.sql.gz | tail -n +15 | xargs -r rm --
