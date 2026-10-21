#!/bin/bash
cd ~/jarvis
pkill -xf 'python core-orchestrator/jarvis.py' || true
sleep 2
DISPLAY=:0 setsid -f bash arrancar_jarvis.sh >/dev/null 2>&1
sleep 50
tail -n 25 logs/jarvis.log | grep -av 'ruido de fondo' | cut -c1-220
