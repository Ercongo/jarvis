#!/bin/bash
# Guarda la clave de Groq para el cerebro y el oído en la nube de Jarvis.
#   bash ~/jarvis/configurar_groq.sh
# (También se puede mandar por Telegram al bot: "clave groq gsk_…")
set -e
read -r -s -p "Pega tu clave de Groq (empieza por gsk_) y pulsa Intro: " CLAVE
echo
case "$CLAVE" in gsk_*) ;; *) echo "Eso no parece una clave de Groq."; exit 1 ;; esac
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $CLAVE" https://api.groq.com/openai/v1/models)
if [ "$CODIGO" != "200" ]; then echo "Groq rechaza la clave (código $CODIGO)."; exit 1; fi
umask 077
printf '{"api_key": "%s"}\n' "$CLAVE" > "$HOME/jarvis/groq.json"
chmod 600 "$HOME/jarvis/groq.json"
echo "Clave guardada. Reiniciando Jarvis para que la use…"
pkill -xf 'python core-orchestrator/jarvis.py' || true
sleep 2
cd "$HOME/jarvis" && DISPLAY=:0 setsid -f bash arrancar_jarvis.sh >/dev/null 2>&1
echo "Listo."
