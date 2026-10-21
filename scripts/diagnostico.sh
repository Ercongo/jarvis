#!/bin/bash
export DISPLAY=:0
echo "== procesos"
pgrep -af 'jarvis.py|firefox|chromium|arrancar_jarvis' || echo "(ninguno)"
echo "== navegadores"
for n in chromium chromium-browser google-chrome firefox; do
    p=$(command -v "$n") && ls -l "$p"
done
snap list 2>/dev/null | grep -Ei 'firefox|chromium'
echo "== autostart"
cat "$HOME/.config/autostart/jarvis.desktop"
echo "== lanzando arrancar_jarvis.sh"
bash -x "$HOME/jarvis/arrancar_jarvis.sh" 2>&1 | tail -25
sleep 15
echo "== ventanas"
wmctrl -lG
echo "== log jarvis"
tail -5 "$HOME/jarvis/logs/jarvis.log"
