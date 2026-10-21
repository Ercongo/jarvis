#!/bin/bash
# Música de arranque de Jarvis.
# Pon tu canción en ~/jarvis/musica/ con el nombre "arranque" (arranque.mp3, arranque.ogg, arranque.flac…).
# Duración: JARVIS_MUSICA_SEGUNDOS (por defecto 30 s, con fundido al final). 0 = la canción entera.

DIR="$HOME/jarvis/musica"
F=$(ls "$DIR"/arranque.* 2>/dev/null | head -1)
[ -z "$F" ] && exit 0
SEG="${JARVIS_MUSICA_SEGUNDOS:-30}"
PIDF="$HOME/.cache/jarvis_musica.pid"
mkdir -p "$HOME/.cache"

if command -v ffplay >/dev/null; then
    if [ "$SEG" -gt 0 ]; then
        ffplay -nodisp -autoexit -loglevel quiet -t "$SEG" -af "afade=t=in:d=1,afade=t=out:st=$((SEG - 4)):d=4" "$F" &
    else
        ffplay -nodisp -autoexit -loglevel quiet "$F" &
    fi
elif command -v mpv >/dev/null; then
    if [ "$SEG" -gt 0 ]; then mpv --no-video --really-quiet --length="$SEG" "$F" &
    else mpv --no-video --really-quiet "$F" &
    fi
elif command -v mpg123 >/dev/null && [[ "$F" == *.mp3 ]]; then
    if [ "$SEG" -gt 0 ]; then timeout "$SEG" mpg123 -q "$F" & else mpg123 -q "$F" & fi
else
    if [ "$SEG" -gt 0 ]; then timeout "$SEG" pw-play "$F" & else pw-play "$F" & fi
fi
echo $! > "$PIDF"
wait
rm -f "$PIDF"
