#!/bin/bash
# Conecta Facebook (página), Instagram y X de Asuka para que Athena publique sola.
#   bash ~/jarvis/configurar_redes_nexus.sh
# Lo que pegues aquí no se ve al escribir y se guarda solo en este portátil (~/.config/athena-nexus/redes.json, 600).
exec python3 "$HOME/jarvis/core-orchestrator/configurar_redes.py" "$@"
