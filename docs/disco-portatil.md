# Disco portátil del asistente

Un disco externo (USB) con Ubuntu y el asistente que arranca en casi cualquier PC de 64 bits: UEFI (también con
Secure Boot) o BIOS antigua. No toca el disco del PC.

## Construirlo (en un Ubuntu, por ejemplo el portátil original)
1. Conecta el disco externo **al Ubuntu** (no a Windows).
2. Míralo: `lsblk -d -o NAME,SIZE,TRAN,MODEL`. Será algo como `sdb … usb`.
3. Desde la carpeta del proyecto: `sudo bash portable/construir_disco.sh /dev/sdb`
   - Comprueba que es un disco **USB** y que **no** es el del sistema.
   - Enseña el modelo y el tamaño, y solo sigue si escribes `BORRAR`.
   - Tarda entre 30 y 90 minutos, según internet y el disco (los mecánicos van más despacio). El registro se guarda en `/var/log/construir_disco_asistente.log`.
4. Al terminar, desconéctalo.

Qué lleva:
- Ubuntu (la misma versión que el equipo que lo construye) con el núcleo genérico, todo el firmware y los controladores de vídeo.
- Xfce, red (NetworkManager, wifi y cable), sonido (PipeWire) y Firefox de Mozilla.
- LibreOffice y KDE Connect.
- El asistente en `/opt/jarvis`: entorno de Python, voz «sharvard» y reconocimiento de voz local ya descargado.

## Qué PC hace falta
- Procesador de 64 bits con **AVX** (casi todos desde 2011: Intel Core de 2.ª generación o posteriores, AMD desde
  las APU A4/A6/A8/A10). En uno más antiguo el escritorio y la configuración funcionan, pero el asistente no puede
  escuchar: lo avisa en pantalla al arrancar.
- 4 GB de RAM como mínimo (8 GB o más va holgado).
- Mejor en un puerto **USB 3** (azul): un disco mecánico por USB 2 arranca, pero va lento.

## Arrancarlo
1. Conecta el disco al PC apagado.
2. Enciéndelo y entra en el **menú de arranque**. La tecla depende de la marca: F12 (Dell, Lenovo), F9 (HP), F8 (Asus), F11 (MSI), Esc o F10.
3. Elige el disco USB. Si no aparece, en la BIOS desactiva «Fast Boot» o activa el arranque desde USB.

**La primera vez** sale una pantalla azul en modo texto:
- Pide tu nombre, tu usuario y tu contraseña.
- Pregunta si quieres entrar sin contraseña al encender.
- Crea tu usuario con el asistente ya preparado y entra en el escritorio.
- El asistente se presenta y abre su configuración: nombre, voz, color, pantallas, cuentas y, si quieres, traer tu perfil cifrado de otro PC.

**En cada PC** el asistente mira la gráfica y las pantallas y se adapta. Las gráficas AMD antiguas con el controlador «radeon» dibujan con el procesador para que no se cuelguen.

## Instalarlo en el disco interno de un PC
Desde el propio disco portátil, con el PC ya en Ubuntu: copia la carpeta del proyecto (`/opt/jarvis` incluye `instalar.sh`) y ejecuta `bash instalar.sh`.

La opción de copiar el sistema entero al disco interno (que lo borra) llegará más adelante, con doble confirmación.

## Cuidado
- Si se pierde el disco, quien lo tenga puede arrancarlo. Usa contraseña y no entres sin ella si llevas cuentas conectadas.
- Las claves del asistente van en `~/jarvis`, solo legibles por tu usuario, pero el disco no va cifrado entero.
