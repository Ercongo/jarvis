#!/bin/bash
# Lanza Jarvis directamente desde el arranque gráfico (.xinitrc), sin depender del autoarranque de Xfce.
set -e
cat > "$HOME/.xinitrc" <<'EOF'
#!/bin/sh
# Jarvis arranca 10 s después del escritorio (para que las pantallas y el gestor de ventanas estén listos).
( sleep 10; "$HOME/jarvis/arrancar_jarvis.sh" >> "$HOME/jarvis/logs/arranque.log" 2>&1 ) &
exec startxfce4
EOF
chmod +x "$HOME/.xinitrc" "$HOME/jarvis/arrancar_jarvis.sh"
rm -f "$HOME/.config/autostart/jarvis.desktop"     # evitamos que se lance dos veces
echo "== .xinitrc nuevo:"; cat "$HOME/.xinitrc"
echo "== Reiniciando la sesión gráfica para probar"
pkill -f core-orchestrator/jarvis.py || true
sudo systemctl restart getty@tty1
echo "   En unos 30-60 s: escritorio en el portátil, Jarvis en el ASUS y saludo."
