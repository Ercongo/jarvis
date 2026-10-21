#!/bin/bash
# Guarda el token del bot de Telegram en ~/jarvis/telegram.json (solo legible por ti) y reinicia Jarvis.
J="$HOME/jarvis"
echo "Pega el token que te dio @BotFather y pulsa Intro (no se mostrará en pantalla):"
read -rs TOKEN
echo
TOKEN=$(echo "$TOKEN" | tr -d '[:space:]')
if ! [[ "$TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]]; then
    echo "Eso no parece un token de Telegram (debe ser algo como 123456789:AAF...). No he guardado nada."
    exit 1
fi
NOMBRE=$(python3 -c "
import json, sys, urllib.request
try:
    r = json.load(urllib.request.urlopen('https://api.telegram.org/bot' + sys.argv[1] + '/getMe', timeout=15))
    print(r['result']['username'])
except Exception as e:
    print('')
" "$TOKEN")
if [ -z "$NOMBRE" ]; then
    echo "Telegram no acepta ese token (o no hay internet). No he guardado nada."
    exit 1
fi
umask 077
python3 -c "
import json, sys
json.dump({'token': sys.argv[1]}, open(sys.argv[2], 'w'), indent=2)
" "$TOKEN" "$J/telegram.json"
chmod 600 "$J/telegram.json"
echo "Token guardado. Tu bot es @$NOMBRE"
echo "Reiniciando Jarvis… en unos segundos dirá en voz alta un código de 4 cifras: envíaselo a @$NOMBRE."
pkill -xf "python core-orchestrator/jarvis.py"
sleep 2
DISPLAY=:0 setsid -f bash "$J/arrancar_jarvis.sh" >/dev/null 2>&1
