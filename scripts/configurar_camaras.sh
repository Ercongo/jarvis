#!/bin/bash
# Añade una cámara de casa para verla en la pantalla del asistente («enseña la cámara del salón»).
# Lo escribe TODO usted: la contraseña de la cámara se teclea aquí (no se ve en pantalla) y se guarda solo en
# ~/jarvis/camaras.json, que únicamente puede leer su usuario. Prueba las direcciones de vídeo más comunes (cámaras
# JUAN, XMeye, Tapo, Imou, Reolink…) hasta dar con la que funciona.
#
#   bash ~/jarvis/configurar_camaras.sh
set -uo pipefail
J="${JARVIS_INSTALACION:-$HOME/jarvis}"
F="$J/camaras.json"
command -v ffprobe >/dev/null || { echo "Falta ffprobe (paquete ffmpeg)."; exit 1; }

read -rp "Nombre de la cámara (por ejemplo: salón, oficina): " NOMBRE
read -rp "Dirección IP de la cámara en casa (mírela en la app de la cámara o en el router): " IP
read -rp "Usuario de la cámara [admin]: " USU; USU=${USU:-admin}
read -rsp "Contraseña de la cámara (no se ve al escribir; vacía si no tiene): " CLAVE; echo
[ -n "$NOMBRE" ] && [ -n "$IP" ] || { echo "Faltan datos."; exit 1; }

cod() { python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"; }
CRED="$(cod "$USU")"; [ -n "$CLAVE" ] && CRED="$CRED:$(cod "$CLAVE")"
RUTAS=("554/ch0_0.264" "554/ch0_1.264" "554/live/ch1" "554/live/ch0" "554/11" "554/12" "554/stream1" "554/stream2"
       "554/h264Preview_01_sub" "554/cam/realmonitor?channel=1&subtype=1" "554/user=${USU}_password=${CLAVE}_channel=1_stream=1.sdp"
       "10554/tcp/av0_1" "10554/tcp/av0_0" "8554/live" "554/onvif1" "554/")
echo "Probando la cámara en $IP…"
BUENA=""
for r in "${RUTAS[@]}"; do
    URL="rtsp://$CRED@$IP:$r"
    if timeout 8 ffprobe -v error -rtsp_transport tcp -select_streams v:0 -show_entries stream=width,height \
            -of csv=p=0 "$URL" 2>/dev/null | grep -q '[0-9]'; then
        BUENA="$URL"; echo "  ✔ vídeo en el puerto/ruta ${r%%\?*}"; break
    fi
done
[ -n "$BUENA" ] || { echo "✖ No consigo ver vídeo. Compruebe la IP, el usuario y la contraseña, y que la cámara tenga"
                     echo "  activado RTSP u ONVIF en su app (a veces se llama «NVR», «ONVIF» o «Protocolo RTSP»)."; exit 1; }

umask 077
python3 - "$F" "$NOMBRE" "$BUENA" <<'EOF'
import json, sys, pathlib
f, nombre, url = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
try:
    d = json.loads(f.read_text(encoding="utf-8"))
except (OSError, ValueError):
    d = {}
d[nombre] = url
f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
EOF
chmod 600 "$F"
echo "✔ Guardada «$NOMBRE». Dígale al asistente: «enseña la cámara de $NOMBRE» (y «quita la cámara» para cerrarla)."
