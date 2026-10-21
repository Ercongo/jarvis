# Jarvis portable e instalable: plan (21 oct 2026)

## Decisiones
- **Disco:** SSD externo USB (128 GB o más). Dos usos: **arrancable con instalador** para instalarlo en el PC y **usarlo siempre desde el disco**.
- **Sistemas:** solo Linux/Ubuntu.
- **Para quién:** familia y amigos. **Cada uno con su clave de Groq** y **su propio proyecto de Google** (asistente guiado).
- **Datos:** al instalar se elige empezar limpio o importar un perfil desde una caja cifrada.
- **Varias personas por PC**, reconocidas por la voz y la cámara.
- **Activación:** con el nombre que le pongan (se prueba con su voz al instalar).
- **Mejoras:** desde este GitHub privado, siempre preguntando antes de actualizar.
- **Escritorio del disco:** modo Jarvis a pantalla completa, con el escritorio detrás.
- **Idiomas:** español (España y latino), inglés y otros.
- **Equipos:** de todo tipo. Jarvis mide RAM, CPU y gráfica y **recomienda** qué instalar.
- **Voces:** Piper local, online (Edge) y clonar una voz.
- **WhatsApp:** asistido (WhatsApp Web con el mensaje preparado) más avisos del móvil. Nada no oficial.
- **Móviles:** Android e iPhone.
- **Cuentas:** GitHub, YouTube (su cuenta), Facebook e Instagram (asistido y automático), Snapchat, X, LinkedIn, Pinterest, Discord y Twitch.
- **Instalador:** pantalla con pasos y voz.
- **El disco se construye en el portátil original.**

## Lo que de verdad se puede hacer con cada cuenta (oct 2026)
| Cuenta | Nivel realista | Qué hace falta |
|---|---|---|
| Telegram | Completo (ya está) | Cada uno su bot con BotFather (el asistente le guía) |
| Gmail y Calendario | Completo (ya está) | Su proyecto de Google Cloud en modo Prueba: el permiso caduca cada 7 días (Jarvis avisa) |
| YouTube (su cuenta) | Suscripciones, listas, «mis vídeos», subir vídeos | Mismo proyecto de Google. **Ojo:** sin auditoría de Google, lo subido por la API queda **privado** |
| GitHub | Completo | Token fino (fine-grained) |
| Discord | Bot en sus servidores (avisos, mensajes, órdenes) | Bot propio. Los mensajes privados de su cuenta personal no se pueden (va contra las normas) |
| Twitch | Quién está en directo, avisos, chat | App gratuita en dev.twitch.tv |
| LinkedIn | Publicar en su perfil | App con «Share on LinkedIn» (autoservicio) |
| Instagram automático | Publicar fotos y vídeos | Cuenta de **creador/empresa** + página de Facebook + app de Meta con él como probador |
| Facebook personal | **Solo asistido** (Meta quitó publicar en perfiles personales) | — |
| X | Asistido; automático con su clave de desarrollador (casi seguro de pago) | — |
| Snapchat y Pinterest | Asistido (sin API de publicación para particulares) | — |
| WhatsApp | Asistido (`web.whatsapp.com/send?phone=&text=`) más lectura de avisos del móvil | — |
| Android | Avisos, SMS, llamadas, buscar el móvil, archivos y portapapeles con **KDE Connect**; pantalla con **scrcpy** | Emparejar en el asistente |
| iPhone | Limitado en Linux: avisos por Telegram o Atajos, y archivos | — |

**Norma fija:** publicar, enviar o borrar en cualquier cuenta pide **siempre** confirmación.

## Arquitectura: tres capas
1. **Motor**, igual para todos: `/opt/jarvis` (o en el disco). El código y los módulos, sin nada personal.
2. **Perfil** de cada persona: `~/.local/share/jarvis/perfiles/<persona>/`. Contiene `ajustes.yaml` (nombre, color, voz, idioma y pantallas), la memoria, el saber, el calendario y los aprendizajes.
3. **Secretos**: `secretos.age`, cifrado con la contraseña de la persona (age o gocryptfs). Nunca van en el paquete ni en GitHub.
- **Exportar/importar perfil:** un archivo `.jarvisperfil` cifrado.

## Trabajo por fases
- **F0. Refactorizar, separando las tres capas.**
  - Quitar lo propio del portátil original: usuario, IP, monitor a la izquierda, arreglos de la AMD (solo si se detecta una gráfica ARUBA) y Firefox snap/deb.
  - El nombre «Jarvis» de las frases pasa a ser `{nombre}`.
  - Catálogo de frases por idioma.
  - Esquema de ajustes con migraciones.
- **F1. Asistente de instalación.** Página web en la propia interfaz HUD, con voz y una prueba en cada paso:
  - Idioma.
  - Personas: registrar su voz (unos 20 s) y su cara.
  - Nombre del asistente, con prueba de activación.
  - Color de la interfaz.
  - Voz: Piper, Edge o clonada (solo la propia o con permiso).
  - Pantallas: detecta las de xrandr y deja elegir dónde va la interfaz.
  - Equipo: prueba de 30 s y recomendación (tamaño de whisper, modelo de Ollama, efectos de la interfaz, MusicGen sí/no).
  - Cuentas, una a una con guía: Groq, bot de Telegram, proyecto de Google, GitHub, Discord, Twitch, LinkedIn, Meta, KDE Connect e iPhone.
  - Importar un perfil.
- **F2. Conectores nuevos.** KDE Connect, WhatsApp asistido, GitHub, YouTube (cuenta), Discord, Twitch, LinkedIn, Instagram por la Graph API y el resto asistido.
- **F3. Varias personas.** Reconocer la voz (incrustaciones ECAPA o resemblyzer, en CPU) y la cara (OpenCV SFace). Perfil activo y «soy Ana».
- **F4. SSD portable.** Ubuntu 26.04 instalado de verdad en el SSD (no live con persistencia), UEFI y Secure Boot con shim, controladores genéricos y firmware.
  - Sesión «Jarvis» a pantalla completa, con Xfce detrás.
  - El asistente sale en el primer arranque de cada PC (perfil de hardware por equipo).
  - Botón «Instalar Jarvis en este PC»: (a) en un Ubuntu que ya tenga, o (b) copiar el sistema al disco interno, **solo con doble confirmación porque lo borra**.
- **F5. Actualizaciones.** Este repositorio privado, con un token de **solo lectura** en cada PC. Canal estable y de pruebas, copia antes de actualizar y vuelta atrás.
- **F6. Idiomas.** El cerebro en la nube entiende cualquier idioma y lo traduce a la orden canónica en español (las reglas no cambian) y contesta en el idioma de la persona. Hay que traducir las frases fijas. Sin internet, solo español.

## Riesgos
- El alcance es enorme (más de 10 cuentas). Hay que entregar por fases y probar cada una en un segundo PC.
- Probar el SSD en varios PC: gráficas NVIDIA y Wi-Fi Broadcom pueden necesitar controladores aparte.
- Clonar voces: solo la voz propia o con permiso. En PCs modestos es lento (se genera por adelantado).
- Si el SSD se pierde, los secretos van cifrados, pero el motor no. Que no lleve nada personal sin cifrar.
