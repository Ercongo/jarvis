# Jarvis

Asistente de voz en español para Ubuntu (Xfce): escucha con una palabra de activación, entiende con un cerebro en la
nube (Groq) o en local (Ollama), habla con Piper y maneja el PC, el calendario, el correo de Google, Telegram,
documentos de oficina, imágenes, música, vídeo, YouTube, TikTok y más.

> Estado: **v27**, la que funciona en el portátil original. Esta es la base para la versión instalable y portable
> (ver `docs/plan-portable.md`). Ahora mismo **todavía tiene cosas propias de ese portátil** (usuario, pantallas,
> arreglos de su gráfica); la fase 0 las quita.

## Estructura
- `core-orchestrator/`: el programa (`jarvis.py` arranca todo; un módulo por área) y `ui/` (la interfaz HUD).
- `scripts/`: arranque, pantallas, mantenimiento y configuración.
- `requirements.txt`: librerías de Python del entorno de Jarvis.

## Lo que NO está aquí (y nunca debe estar)
Claves y permisos (`groq.json`, `google.json`, `telegram.json`, `openrouter.json`, `estudio.json`), la memoria, el
calendario, las notas, los registros y las voces descargadas. El `.gitignore` lo impide.
