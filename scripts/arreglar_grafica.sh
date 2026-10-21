#!/bin/bash
# Arregla el arranque gráfico de Jarvis: espera a que la gráfica AMD esté lista antes de abrir la pantalla.
set -e
echo "== 1/3 Permisos de vídeo para $USER"
sudo usermod -aG video,render "$USER"

echo "== 2/3 Lanzador con espera y reintentos"
cat > "$HOME/.jarvis_startx.sh" <<'EOF'
#!/bin/bash
# Lo llama ~/.profile al entrar en la consola 1. Espera a la gráfica y reintenta si falla.
for intento in 1 2 3; do
    for _ in $(seq 1 40); do                       # hasta 20 s esperando a la gráfica
        [ -e /dev/dri/card0 ] && break
        sleep 0.5
    done
    command -v udevadm >/dev/null && udevadm settle --timeout=15
    sleep 3                                        # margen para que termine de cargar el firmware
    startx -- vt1 >>"$HOME/jarvis/logs/startx.log" 2>&1 && exit 0
    echo "$(date '+%F %T') startx falló (intento $intento), reintentando…" >>"$HOME/jarvis/logs/startx.log"
    sleep 5
done
echo "La pantalla gráfica no ha podido arrancar. Prueba a escribir: startx"
EOF
chmod +x "$HOME/.jarvis_startx.sh"
mkdir -p "$HOME/jarvis/logs"

echo "== 3/3 Usar el lanzador nuevo al encender"
PERFIL="$HOME/.profile"
[ -f "$HOME/.bash_profile" ] && PERFIL="$HOME/.bash_profile"
sed -i '/# jarvis-autostart/d' "$PERFIL"
echo '[ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ] && "$HOME/.jarvis_startx.sh"  # jarvis-autostart' >> "$PERFIL"
grep jarvis-autostart "$PERFIL"

echo
echo "== Listo. Reinicia con: sudo reboot"
