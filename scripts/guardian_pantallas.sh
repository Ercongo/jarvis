#!/bin/bash
# Guardián de pantallas: la pantalla de la interfaz es solo para el asistente.
# Cualquier otra ventana que aparezca allí se mueve a la de trabajo y se maximiza (una vez, al abrirse;
# si luego la arrastras tú a mano, se respeta). Qué pantalla es cada una lo decide pantallas.py.
export DISPLAY="${DISPLAY:-:0}"
J="${JARVIS_INSTALACION:-$HOME/jarvis}"
M="${JARVIS_MOTOR:-$J/core-orchestrator}"
PY="$J/venv/bin/python"; [ -x "$PY" ] || PY=python3
LOGD="${JARVIS_DATOS:-$J}/logs"
ID_JARVIS="$HOME/.cache/jarvis_ventana"
declare -A vista movida
ciclo=0

geometrias() {
    DEDICADA=0; GEO_TRABAJO=""; GEO_INTERFAZ=""
    eval "$(cd "$M" && "$PY" pantallas.py --shell 2>/dev/null)"
    GI="$GEO_TRABAJO"; GE=""
    [ "$DEDICADA" = "1" ] && GE="$GEO_INTERFAZ"           # con una sola pantalla no hay nada que vigilar
    IX=$(echo "$GI" | cut -d+ -f2); IY=$(echo "$GI" | cut -d+ -f3)
    EX=$(echo "$GE" | cut -d+ -f2); EW=$(echo "$GE" | cut -dx -f1)
}

while true; do
    (( ciclo % 10 == 0 )) && geometrias          # las pantallas se revisan cada 10 s
    ciclo=$((ciclo + 1))
    if [ -z "$GE" ] || [ -z "$GI" ]; then sleep 2; continue; fi
    jarvis_id=$(cat "$ID_JARVIS" 2>/dev/null)
    while read -r id escritorio x y w h resto; do
        [ "$escritorio" = "-1" ] && continue                 # fondo de escritorio, paneles…
        [ "${movida[$id]:-0}" -ge 6 ] && continue           # solo se vigila al abrirse (luego, libre)
        [ -n "$jarvis_id" ] && [ "$((id))" = "$((jarvis_id))" ] && continue   # la ventana de Jarvis se queda
        titulo="${resto#* }"                                   # quitar el nombre del equipo
        case "$titulo" in "Jarvis — "*|"Jarvis - "*) continue ;; esac
        if [ -z "${vista[$id]}" ]; then vista[$id]=1; continue; fi   # esperar a que el gestor la coloque
        movida[$id]=$(( ${movida[$id]:-0} + 1 ))
        cx=$((x + w / 2))
        if [ "$cx" -ge "$EX" ] && [ "$cx" -lt "$((EX + EW))" ]; then
            echo "$(date +%T) $id '$resto' -> pantalla de trabajo" >> "$LOGD/guardian.log"
            wmctrl -i -r "$id" -b remove,fullscreen 2>/dev/null
            wmctrl -i -r "$id" -b remove,maximized_vert,maximized_horz 2>/dev/null
            sleep 0.3
            wmctrl -i -r "$id" -e "0,$((IX + 30)),$((IY + 30)),800,600" 2>/dev/null
            sleep 0.2
            wmctrl -i -r "$id" -b add,maximized_vert,maximized_horz 2>/dev/null
        fi
    done < <(wmctrl -lG 2>/dev/null)
    sleep 1
done
