#!/bin/bash
# 🤖 Control del bot: ./bot.sh start | stop | restart | status | rendimiento | retrain (modelo antiguo de 5 min)
# "start" es idempotente: solo arranca lo que no esté corriendo (sirve como watchdog en cron).

cd "$(dirname "$0")" || exit 1
PY=venv/bin/python
SERVICES="data_ingester panel_server"   # trading_engine (5 min) retirado el 2026-09-30: sin ventaja; ver docs/ESTADO_BOT.md

is_running() { pgrep -f "python scripts/$1.py" > /dev/null; }
log_of() { case "$1" in data_ingester) echo logs/ingester.log ;; panel_server) echo logs/panel.log ;; *) echo logs/engine.log ;; esac; }

start() {
    for s in $SERVICES; do
        if is_running "$s"; then
            echo "✅ $s ya está corriendo"
        else
            setsid nohup $PY "scripts/$s.py" >> "$(log_of "$s")" 2>&1 < /dev/null &
            echo "🚀 $s iniciado (PID $!)"
        fi
    done
}

stop() {
    for s in $SERVICES; do
        pkill -f "python scripts/$s.py" && echo "🛑 $s detenido"
    done
}

status() {
    for s in $SERVICES; do
        if is_running "$s"; then echo "✅ $s: corriendo"; else echo "❌ $s: parado"; fi
    done
    echo "📊 Panel: http://$(hostname -I | awk '{print $1}'):8899/panel.html"
    echo
    $PY scripts/report.py --terminal 2>/dev/null | sed -n '3,$p'
}

case "$1" in
    start) start ;;
    stop) stop ;;
    restart) stop; sleep 2; start ;;
    status) status ;;
    rendimiento) $PY scripts/performance.py --terminal ;;
    retrain) echo "=== $(date -u '+%F %T') UTC ==="; $PY scripts/train_model.py 2>&1 | grep -v Warning ;;
    *) echo "Uso: $0 start|stop|restart|status|rendimiento|retrain"; exit 1 ;;
esac
