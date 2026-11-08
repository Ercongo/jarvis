# Athena / Jarvis · asistente de voz para Ubuntu

Asistente de voz en español que vive en un PC con Ubuntu:
- Lo despiertas por su nombre: «Jarvis», o el que le pongas.
- Entiende lo que le pides con un cerebro en la nube gratuito (Groq) y, si los instalas, OmniRoute u Ollama de reserva.
- Contesta con voz natural (Piper).
- Hace cosas de verdad:
  - maneja el PC, el calendario y el correo de Google, Telegram, Word, Excel, PDF, planos y presentaciones;
  - crea imágenes, música y vídeos;
  - pone YouTube y música, mira la pantalla o la cámara e investiga en internet;
  - recuerda lo que le cuentas.

Tiene una interfaz tipo HUD que se abre a pantalla completa, y un asistente de configuración web que te guía la primera vez.

---

## Instalación rápida (unos 15-20 minutos)

### Qué necesitas
- Un PC con **Ubuntu 24.04 o posterior** (o Xubuntu, Kubuntu, Linux Mint…) **con escritorio**, de 64 bits.
  Está probado a diario en Ubuntu 26.04 con Xfce; en otras versiones debería funcionar, pero es menos probado.
- **Micrófono y altavoces.** Los del portátil valen; con unos cascos con micrófono va mejor.
- **4 GB de RAM** como mínimo (8 GB o más, recomendado) y unos **10 GB libres** en el disco.
- Internet durante la instalación.
- Una **cuenta gratuita de Groq** para el cerebro: https://console.groq.com → *API Keys* → *Create API Key*. Copia la clave, que empieza por `gsk_`.

### Pasos
Abre una terminal (**Ctrl + Alt + T**) y escribe:

```bash
sudo apt install -y git
git clone https://github.com/Ercongo/jarvis.git
cd jarvis
bash instalar.sh
```

- **No uses `sudo` con `instalar.sh`.** Él mismo pide tu contraseña cuando la necesita, para instalar programas del sistema.
- La primera vez tarda unos minutos: instala los programas del sistema, crea su entorno de Python y descarga una voz.
- Si el repositorio es privado, `git clone` te pedirá tu usuario de GitHub y un *token*; la contraseña de GitHub no sirve. Lo más fácil es que el dueño te invite como colaborador.

Al terminar se abre solo el **asistente de configuración** en el navegador. Si no se abre, entra en http://127.0.0.1:8765/asistente.

En el asistente:
1. **Idioma y tú:** cómo te llamas y cómo quieres que te trate.
2. **Nombre del asistente** («Jarvis», «Athena»…): pruébalo con el micrófono para ver que te entiende.
3. **Color y voz:** escucha las voces y elige.
4. **Pantallas:** si tienes dos, una puede quedarse solo para la interfaz.
5. **Cuentas:** pega la **clave de Groq** (obligatoria). El resto es opcional y se puede añadir más tarde:
   - **Telegram:** para hablarle desde el móvil. Crea un bot con @BotFather y pega su token.
   - **Google:** calendario y correo. Necesitas tu propio proyecto en Google Cloud; el asistente explica los pasos.
6. **Terminar:** arranca el asistente.

Desde entonces **arranca solo al entrar en el escritorio**. También puedes lanzarlo con `jarvis` en una terminal.

### Opcional: IA local de reserva (funciona sin internet)
```bash
bash instalar.sh --con-ollama
```
Instala Ollama y un modelo adecuado a tu equipo (unos 2 GB). Con internet sigue usando Groq, que es más rápido y más listo.

### Primeras cosas que probar
- «Jarvis, qué hora es» · «qué tiempo hace mañana»
- «apunta el dentista el jueves a las 5» · «qué tengo esta semana»
- «crea un excel de gastos con fecha, concepto e importe»
- «pon en youtube música de los 80» · «pausa»
- «qué ves en la pantalla» · «investiga sobre la aerotermia»
- «abre la configuración» para cambiar el nombre, la voz o las cuentas

---

## Problemas frecuentes
| Problema | Solución |
|---|---|
| No me oye | Comprueba en *Configuración → Sonido* que el micrófono correcto está seleccionado y con volumen. En la configuración del asistente hay una prueba de micrófono. |
| Contesta «no tengo cerebro» o va muy limitado | Falta la clave de Groq o es incorrecta: «abre la configuración» → Cuentas. |
| La interfaz se ve negra o el PC se cuelga al abrirla | Pasa con algunas gráficas AMD antiguas. El instalador las detecta y quita la aceleración gráfica; si no, ejecuta `bash ~/jarvis/sin_aceleracion.sh` y reinicia la sesión. |
| `instalar.sh` falla en las librerías de Python | Vuelve a ejecutarlo: si las versiones exactas no encajan con tu Python, instala las últimas compatibles. |
| Quiero ver qué hace por dentro | Registro: `tail -f ~/jarvis/logs/jarvis.log` |
| Quiero quitarlo | Borra `~/jarvis` y `~/.config/autostart/jarvis.desktop`, y quita la línea `alias jarvis=…` de `~/.bashrc`. |

---

## Estructura del repositorio
- `instalar.sh`: instalador (ejecútalo desde esta carpeta, sin sudo). Opciones: `--con-ollama`, `--destino DIR` y `--sin-arranque`.
- `core-orchestrator/`: el programa.
  - `jarvis.py` arranca todo y `asistente.py` es la configuración.
  - Hay un módulo por área: calendario, correo, oficina, creativo, saber…
  - `ui/` contiene la interfaz.
- `scripts/`: arranque, pantallas, copias de seguridad, mantenimiento e instaladores opcionales (SearXNG, OmniRoute, Open WebUI, ComfyUI, Alexa…).
- `portable/`: para construir un disco USB arrancable con Ubuntu y el asistente (ver `docs/disco-portatil.md`).
- `requirements.txt`: librerías de Python.
- **Nexus** (`core-orchestrator/nexus*.py`) es un módulo opcional para gestionar redes sociales de un personaje. No se activa si no lo configuras.

## Lo que NO está aquí (ni debe estar nunca)
Las claves y permisos (`groq.json`, `google.json`, `telegram.json`…), la memoria, el calendario, las notas, los registros y las voces descargadas. Cada instalación crea los suyos en `~/jarvis`, y el `.gitignore` impide subirlos. **No compartas tu carpeta `~/jarvis`**: dentro están tus claves.
