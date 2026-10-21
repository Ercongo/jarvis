#!/bin/bash
# Muestra qué está gastando el portátil (CPU y memoria).
echo "== Memoria"
free -h
echo "== Lo que más CPU gasta ahora mismo"
top -b -n 2 -d 3 -o %CPU | awk '/^top -/{n++} n==2' | head -16
echo "== Lo que más memoria gasta"
ps -eo pid,comm,%mem,rss --sort=-rss | head -8
echo "== Temperatura (si está disponible)"
sensors 2>/dev/null | grep -iE 'temp|tctl|edge' | head -5 || echo "(sin sensores)"
