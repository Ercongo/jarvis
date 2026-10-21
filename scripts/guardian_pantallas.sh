#!/bin/bash
# Guardián de pantallas: el monitor externo es solo para Jarvis.
# Cualquier otra ventana que aparezca allí se mueve al portátil y se maximiza (una vez, al abrirse;
# si luego la arrastras tú a mano, se respeta).
export DISPLAY="${DISPLAY:-:0}"
ID_JARVIS="$HOME/.cache/jarvis_ventana"
declare -A vista movida
ciclo=0

geometrias() {
    INT=$(xrandr --query | awk '/ connected/ && $1 ~ /^(eDP|LVDS)/ {print $1; exit}')
    EXT=$(xrandr --query | awk -v i="$INT" '/ connected/ && $1 != i {print $1; exit}')
    GI=$(xrandr --query | grep "^$INT connected" | grep -oE '[0-9]+x[0-9]+\+[0-9]+\+[0-9]+' | head -1)
    GE=""
    [ -n "$EXT" ] && GE=$(xrandr --query | grep "^$EXT connected" | grep -oE '[0-9]+x[0-9]+\+[0-9]+\+[0-9]+' | head -1)
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
            echo "$(date +%T) $id '$resto' -> portátil" >> "$HOME/jarvis/logs/guardian.log"
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
