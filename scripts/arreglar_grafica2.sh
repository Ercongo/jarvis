#!/bin/bash
# Usa solo la gráfica integrada (la que va a la pantalla) e ignora la dedicada, que hacía fallar el arranque.
set -e
echo "== Gráficas detectadas:"
lspci -nn | grep -Ei 'vga|display|3d' || true

echo "== Configurando la parte gráfica para usar solo la integrada (PCI 0:1:0)"
sudo mkdir -p /etc/X11/xorg.conf.d
sudo tee /etc/X11/xorg.conf.d/20-jarvis-grafica.conf >/dev/null <<'EOF'
# Jarvis: solo la gráfica integrada. La dedicada (sin salida de pantalla) hacía fallar el arranque.
Section "ServerFlags"
    Option "AutoAddGPU" "off"
EndSection

Section "Device"
    Identifier "Integrada"
    Driver     "modesetting"
    BusID      "PCI:0:1:0"
EndSection
EOF
cat /etc/X11/xorg.conf.d/20-jarvis-grafica.conf

echo "== Relanzando la consola 1 para probar sin reiniciar"
: > "$HOME/jarvis/logs/startx.log"
sudo systemctl restart getty@tty1
echo "   Mira la pantalla del portátil: debería abrirse Jarvis en 30-60 s."
