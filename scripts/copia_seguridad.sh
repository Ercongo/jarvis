#!/bin/bash
# Copia de seguridad de Jarvis: deja ~/jarvis_copia.tar.gz (sin el entorno de Python ni los registros).
# El PC con Windows la recoge cada día con su tarea programada.
cd "$HOME" || exit 1
tar czf jarvis_copia.tar.gz.tmp \
    --exclude='jarvis/venv' --exclude='jarvis/logs' --exclude='*/__pycache__' --exclude='*.tar.gz' \
    --exclude='jarvis/**/.git' --exclude='jarvis/herramientas/*/.venv' \
    --exclude='jarvis/herramientas/*/storage' --exclude='jarvis/nexus/kaggle' jarvis 2>/dev/null
mv -f jarvis_copia.tar.gz.tmp jarvis_copia.tar.gz
ls -la jarvis_copia.tar.gz | awk '{print "copia lista:", $5, "bytes"}'
