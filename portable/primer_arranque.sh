#!/bin/bash
# Primera vez que se arranca el disco del asistente: pide el nombre, el usuario y la contraseña de la persona,
# crea su usuario con el asistente ya preparado y entra en el escritorio. Se ejecuta en la consola (tty1)
# antes de la pantalla de entrada, una sola vez.
set -u
export NEWT_COLORS='root=,black window=,black border=cyan,black title=cyan,black textbox=white,black
button=black,cyan entry=white,black checkbox=white,black actbutton=black,cyan'
T="Asistente · primer arranque"
chvt 1 2>/dev/null || true

pregunta() { whiptail --title "$T" --inputbox "$1" 10 70 "${2:-}" 3>&1 1>&2 2>&3; }
clave() { whiptail --title "$T" --passwordbox "$1" 10 70 3>&1 1>&2 2>&3; }

whiptail --title "$T" --msgbox "Hola. Vamos a crear tu usuario en este disco.\n\nDespués entrarás en el escritorio y el asistente te ayudará a configurarlo (nombre, voz, color, cuentas…).\n\nSe maneja con el teclado: Tab para moverse, Intro para aceptar." 14 70

while :; do
    NOMBRE=$(pregunta "¿Cómo te llamas?" "") || continue
    [ -n "$NOMBRE" ] && break
done
SUGERIDO=$(echo "$NOMBRE" | iconv -f utf-8 -t ascii//TRANSLIT 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9' | cut -c1-20)
[ -n "$SUGERIDO" ] || SUGERIDO=usuario
while :; do
    USUARIO=$(pregunta "Nombre de usuario (minúsculas, sin espacios ni tildes):" "$SUGERIDO") || continue
    if ! echo "$USUARIO" | grep -qE '^[a-z][a-z0-9_-]{1,30}$'; then
        whiptail --title "$T" --msgbox "Solo minúsculas, números, - y _, empezando por una letra." 8 70; continue
    fi
    if id "$USUARIO" >/dev/null 2>&1; then
        whiptail --title "$T" --msgbox "Ese usuario ya existe; elige otro." 8 70; continue
    fi
    break
done
while :; do
    C1=$(clave "Contraseña (mínimo 6 caracteres):") || continue
    C2=$(clave "Repítela:") || continue
    if [ "$C1" != "$C2" ]; then whiptail --title "$T" --msgbox "No coinciden. Otra vez." 8 60; continue; fi
    if [ ${#C1} -lt 6 ]; then whiptail --title "$T" --msgbox "Demasiado corta." 8 60; continue; fi
    break
done
AUTO=0
whiptail --title "$T" --yesno "¿Entrar directamente al encender, sin pedir la contraseña?\n\n(Más cómodo; pero quien tenga el disco podrá entrar. La contraseña se seguirá pidiendo para instalar o cambiar cosas del sistema.)" 12 70 && AUTO=1

{
    echo 10; useradd -m -s /bin/bash -c "$NOMBRE" -G sudo,adm,audio,video,plugdev,netdev,lpadmin,users "$USUARIO" 2>/dev/null \
        || useradd -m -s /bin/bash -c "$NOMBRE" -G sudo,audio,video,plugdev,users "$USUARIO"
    echo "$USUARIO:$C1" | chpasswd
    echo 30
    H="/home/$USUARIO"
    # el asistente: copia de la plantilla del disco (programa, entorno de Python y voz)
    cp -a /opt/jarvis "$H/jarvis"
    if [ -d "$H/jarvis/hf-cache" ]; then                  # modelo de voz local ya descargado
        mkdir -p "$H/.cache"; mv "$H/jarvis/hf-cache" "$H/.cache/huggingface"
    fi
    echo 80
    mkdir -p "$H/.config/autostart"
    cat > "$H/.config/autostart/asistente.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Asistente
Exec=bash $H/jarvis/arrancar_jarvis.sh
X-GNOME-Autostart-enabled=true
EOF
    echo "alias jarvis='bash ~/jarvis/arrancar_jarvis.sh'" >> "$H/.bashrc"
    # el entorno de Python se copió de /opt/jarvis: sus scripts tienen que apuntar a la copia
    grep -rlI "/opt/jarvis/venv" "$H/jarvis/venv/bin" "$H/jarvis/venv/pyvenv.cfg" 2>/dev/null \
        | xargs -r sed -i "s#/opt/jarvis/venv#$H/jarvis/venv#g"
    chown -R "$USUARIO:$USUARIO" "$H"
    sudo -u "$USUARIO" env NOMBRE_P="$NOMBRE" JARVIS_DATOS="$H/jarvis" JARVIS_INSTALACION="$H/jarvis" \
        "$H/jarvis/venv/bin/python" -c "import os, sys; sys.path.insert(0, '$H/jarvis/core-orchestrator'); import perfil; perfil.guardar(usuario={'nombre': os.environ['NOMBRE_P']})" >/dev/null 2>&1 || true
    if [ "$AUTO" = 1 ]; then
        mkdir -p /etc/lightdm/lightdm.conf.d
        printf '[Seat:*]\nautologin-user=%s\nautologin-session=xfce\n' "$USUARIO" > /etc/lightdm/lightdm.conf.d/50-asistente.conf
    fi
    echo 100
} | whiptail --title "$T" --gauge "Preparando tu usuario y el asistente…" 8 70 0

C1=""; C2=""
rm -f /etc/jarvis/primer-arranque
systemd-machine-id-setup >/dev/null 2>&1 || true
whiptail --title "$T" --msgbox "Listo, $NOMBRE. Ahora se abre el escritorio y, en un momento, la configuración del asistente." 9 70
exit 0
