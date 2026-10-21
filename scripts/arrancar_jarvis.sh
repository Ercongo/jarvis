#!/bin/bash
# Arranca el asistente: motor de voz en segundo plano + interfaz a pantalla completa.
# Con dos pantallas, la interfaz va en una para ella sola; con una, a pantalla completa sin estorbar
# (lo decide core-orchestrator/pantallas.py según el PC y el perfil).
# Lo lanza el inicio automático de Xfce; también puedes ejecutarlo a mano (alias: jarvis).

J="${JARVIS_INSTALACION:-$HOME/jarvis}"
M="${JARVIS_MOTOR:-$J/core-orchestrator}"
PY="$J/venv/bin/python"; [ -x "$PY" ] || PY=python3
DATOS="${JARVIS_DATOS:-$J}"
LOG="$DATOS/logs/jarvis.log"
URL="http://127.0.0.1:8765/"
mkdir -p "$DATOS/logs"
export JARVIS_WHISPER="${JARVIS_WHISPER:-base}"
# export JARVIS_USUARIO="Tu nombre"      # descomenta para que te salude por tu nombre

# ---- si se lanza por SSH, copiar el entorno de la sesión gráfica (para que las apps que abra Jarvis
#      encuentren la pantalla, el bus de escritorio y el navegador igual que al arrancar el portátil)
SES=$(pgrep -u "$(id -u)" -x xfce4-session | head -1)
if [ -n "$SES" ] && [ -r "/proc/$SES/environ" ]; then
    while IFS= read -r -d '' VAR; do
        case "$VAR" in
            DISPLAY=*|XAUTHORITY=*|DBUS_SESSION_BUS_ADDRESS=*|XDG_RUNTIME_DIR=*|XDG_SESSION_*|XDG_CURRENT_DESKTOP=*|XDG_DATA_DIRS=*|XDG_CONFIG_DIRS=*|DESKTOP_SESSION=*|PATH=*)
                export "$VAR" ;;
        esac
    done < "/proc/$SES/environ"
fi

# ---- música de arranque: una sola vez por encendido (no cada vez que se reinicia Jarvis)
BOOT_ID=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
MARCA="$HOME/.cache/jarvis_musica_boot"
if [ "${JARVIS_MUSICA:-1}" != "0" ] && [ -n "$BOOT_ID" ] && [ "$(cat "$MARCA" 2>/dev/null)" != "$BOOT_ID" ]; then
    mkdir -p "$HOME/.cache"; echo "$BOOT_ID" > "$MARCA"
    setsid -f bash "$J/musica_arranque.sh" >/dev/null 2>&1
fi

# ---- motor de voz (solo uno a la vez)
if pgrep -xf "python core-orchestrator/jarvis.py" >/dev/null; then   # coincidencia exacta: no confundirse con otros comandos
    echo "Jarvis ya estaba en marcha."
else
    ( cd "$J" && source venv/bin/activate && exec nice -n 10 python core-orchestrator/jarvis.py ) >>"$LOG" 2>&1 &
    echo "Jarvis arrancado. Registro: $LOG"
fi

# Sin pantalla (por ejemplo, por SSH) no abrimos navegador.
[ -z "$DISPLAY" ] && exit 0
xset s off -dpms 2>/dev/null

# ---- pantallas: cuál es para la interfaz y cuál para trabajar (pantallas.py, según el PC y el perfil)
eval "$(cd "$M" && "$PY" pantallas.py --shell 2>/dev/null)"
if [ "$DEDICADA" = "1" ] && [ "$COLOCAR" != "no" ] && [ -n "$TRABAJO" ]; then
    case "$COLOCAR" in izquierda) POS=--left-of ;; derecha) POS=--right-of ;; arriba) POS=--above ;; *) POS=--below ;; esac
    xrandr --output "$TRABAJO" --auto --primary --output "$INTERFAZ" --auto $POS "$TRABAJO"
    sleep 2
    eval "$(cd "$M" && "$PY" pantallas.py --shell 2>/dev/null)"        # posiciones nuevas
fi
# Barra de tareas e iconos en la pantalla de trabajo
if [ "$DEDICADA" = "1" ] && [ -n "$TRABAJO" ] && command -v xfconf-query >/dev/null; then
    for P in $(xfconf-query -c xfce4-panel -p /panels 2>/dev/null | grep -E '^[0-9]+$'); do
        xfconf-query -c xfce4-panel -p "/panels/panel-$P/output-name" -n -t string -s "$TRABAJO" 2>/dev/null
    done
fi

GEOM=""; [ "$DEDICADA" = "1" ] && GEOM="$GEO_INTERFAZ"
POS_X="${X_INTERFAZ:-0}"; POS_Y="${Y_INTERFAZ:-0}"
if [ -n "$GEOM" ]; then
    echo "Interfaz en $INTERFAZ ($GEOM); trabajo en $TRABAJO"
else
    echo "Una sola pantalla (${INTERFAZ:-?}): la interfaz va a pantalla completa y las ventanas se abren encima."
fi

# ---- esperar a que la interfaz responda (hasta 60 s)
for _ in $(seq 1 60); do
    python3 -c "import urllib.request; urllib.request.urlopen('$URL', timeout=1)" 2>/dev/null && break
    sleep 1
done

# ---- navegador sin barras, en el monitor externo
PERFIL_NAV="$HOME/.config/jarvis-navegador"
if command -v chromium >/dev/null || command -v chromium-browser >/dev/null || command -v google-chrome >/dev/null; then
    NAV=$(command -v chromium || command -v chromium-browser || command -v google-chrome)
    "$NAV" --app="$URL" --user-data-dir="$PERFIL_NAV" --window-position="$POS_X,$POS_Y" \
           --noerrdialogs --disable-infobars --no-first-run $([ "$VENTANA" = "1" ] || echo --start-fullscreen) >/dev/null 2>&1 &
elif command -v firefox >/dev/null; then
    # Firefox en snap solo puede usar carpetas dentro de ~/snap/firefox: el perfil de Jarvis va ahí.
    PERFIL_FF="$HOME/snap/firefox/common/jarvis-perfil"
    mkdir -p "$PERFIL_FF"
    bash "$J/sin_aceleracion.sh"          # preferencias del navegador (y sin aceleración si la gráfica lo pide)
    pkill -f "jarvis-perfil" 2>/dev/null; sleep 1
    firefox --new-instance --no-remote --profile "$PERFIL_FF" $([ "$VENTANA" = "1" ] || echo --kiosk) "$URL" \
        >"$DATOS/logs/navegador.log" 2>&1 &
else
    xdg-open "$URL" >/dev/null 2>&1 &
fi

# ---- colocar la ventana en el monitor externo y ponerla a pantalla completa
command -v wmctrl >/dev/null || exit 0
JID=""
for _ in $(seq 1 120); do                      # Firefox snap tarda en abrir la primera vez
    # solo la ventana de la interfaz: el título EMPIEZA por "Jarvis —" (no vale "Calendario · Jarvis — …")
    JID=$(wmctrl -l | awk '{t=""; for (i = 4; i <= NF; i++) t = t (i > 4 ? " " : "") $i} t ~ /^Jarvis (—|-) / {print $1; exit}')
    [ -n "$JID" ] && break
    sleep 0.5
done
[ -z "$JID" ] && exit 0
sleep 1
wmctrl -i -r "$JID" -b remove,fullscreen 2>/dev/null
wmctrl -i -r "$JID" -b remove,maximized_vert,maximized_horz 2>/dev/null
wmctrl -i -r "$JID" -e "0,$POS_X,$POS_Y,-1,-1" 2>/dev/null
sleep 0.5
[ "$VENTANA" = "1" ] || wmctrl -i -r "$JID" -b add,fullscreen 2>/dev/null
[ -n "$GEOM" ] && wmctrl -i -r "$JID" -b add,above 2>/dev/null   # siempre visible, solo si está en su propio monitor
mkdir -p "$HOME/.cache"
echo "$JID" > "$HOME/.cache/jarvis_ventana"

# Guardián: todo lo que se abra en la pantalla de la interfaz se pasa a la de trabajo (solo uno a la vez)
if [ -n "$GEOM" ] && ! pgrep -xf "bash $J/guardian_pantallas.sh" >/dev/null; then   # exacto: no confundirse con otros comandos
    setsid -f bash "$J/guardian_pantallas.sh" >/dev/null 2>&1
fi
exit 0
