"""
Mantenimiento del portátil para Jarvis.

Órdenes:
  "limpia el ordenador", "borra la caché", "borra los temporales", "haz mantenimiento", "libera espacio"
  "limpieza a fondo"            → además, la caché del navegador
  "vacía la papelera"           → pide confirmación
  "qué ocupa más espacio"       → las carpetas más grandes de tu carpeta personal
  "busca actualizaciones"       → cuántas hay (apt y snap)
  "actualiza el sistema"        → instala las actualizaciones (pide confirmación)
  "actualízate" / "actualiza tu inteligencia" → descarga la última versión del modelo de IA
  "haz un chequeo"              → revisión rápida: disco, servicios con fallos, actualizaciones, limpieza

Lo que necesita permisos de administrador (caché de apt, paquetes huérfanos, registros del sistema,
instalar actualizaciones) pasa por UN script fijo: /usr/local/sbin/jarvis-mantenimiento, que se
instala una sola vez con: sudo bash ~/jarvis/configurar_mantenimiento.sh
Sin eso, Jarvis limpia lo que es tuyo (caché, temporales, registros de Jarvis) y te avisa.

Nunca toca tus documentos, fotos ni descargas, ni los modelos de voz e IA de Jarvis.
Cada semana hace una limpieza ligera sola y, si hay actualizaciones, te avisa por Telegram.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

from herramientas import guardar_config, leer_config, normalizar
from sistema import Respuesta

HOME = Path.home()
CACHE = HOME / ".cache"
LOGS = HOME / "jarvis" / "logs"
SCRIPT_ROOT = "/usr/local/sbin/jarvis-mantenimiento"

# Cachés que se pueden borrar sin perder nada (se regeneran solas). NUNCA huggingface: ahí está whisper.
CACHES_SEGURAS = ["pip", "thumbnails", "mesa_shader_cache", "radv_builtin_shaders", "gstreamer-1.0",
                  "glycin", "babl", "gegl-0.4", "yarn", "npm", "go-build"]
CACHES_NAVEGADOR = [HOME / "snap" / "firefox" / "common" / ".cache" / "mozilla",
                    CACHE / "mozilla", CACHE / "google-chrome", CACHE / "chromium"]
PAPELERA = HOME / ".local" / "share" / "Trash"


def tamano(ruta: Path) -> int:
    """Bytes que ocupa un archivo o carpeta (sin seguir enlaces)."""
    try:
        if ruta.is_symlink():
            return 0
        if ruta.is_file():
            return ruta.stat().st_size
        total = 0
        for raiz, _, archivos in os.walk(ruta, onerror=lambda e: None):
            for a in archivos:
                try:
                    total += os.lstat(os.path.join(raiz, a)).st_size
                except OSError:
                    pass
        return total
    except OSError:
        return 0


def borrar(ruta: Path) -> int:
    """Borra una carpeta o archivo y devuelve los bytes liberados."""
    t = tamano(ruta)
    try:
        if ruta.is_dir() and not ruta.is_symlink():
            shutil.rmtree(ruta, ignore_errors=True)
        else:
            ruta.unlink(missing_ok=True)
    except OSError:
        return 0
    return t - (tamano(ruta) if ruta.exists() else 0)


def vaciar_carpeta(ruta: Path) -> int:
    """Borra el contenido de una carpeta, pero deja la carpeta."""
    if not ruta.is_dir():
        return 0
    return sum(borrar(p) for p in ruta.iterdir())


def mb(b: float) -> str:
    if b >= 1024 ** 3:
        return f"{b / 1024 ** 3:.1f} gigas".replace(".", ",")
    return f"{round(b / 1024 ** 2)} megas"


def recortar_log(ruta: Path, max_bytes: int, lineas: int) -> int:
    """Si un registro de Jarvis crece demasiado, se queda con las últimas líneas."""
    try:
        if ruta.stat().st_size <= max_bytes:
            return 0
        antes = ruta.stat().st_size
        cola = ruta.read_bytes().splitlines(keepends=True)[-lineas:]
        ruta.write_bytes(b"".join(cola))
        return antes - ruta.stat().st_size
    except OSError:
        return 0


class Mantenimiento:
    def __init__(self, decir: Callable[..., None], confirmar: Callable[[str], bool], log=print,
                 avisar: Callable[[str], None] | None = None, es_telegram: Callable[[], bool] | None = None,
                 modelo_llm: str = "qwen2.5:1.5b", ollama_url: str = "http://127.0.0.1:11434", ui=None):
        self.decir = decir
        self.confirmar = confirmar
        self.log = log
        self.avisar = avisar or (lambda t: None)
        self.es_telegram = es_telegram or (lambda: False)
        self.modelo = modelo_llm
        self.ollama_url = ollama_url
        self.ui = ui
        self._ocupado = threading.Lock()

    # ---------- permisos de administrador
    def tiene_root(self) -> bool:
        if not Path(SCRIPT_ROOT).exists():
            return False
        try:
            return subprocess.run(["sudo", "-n", SCRIPT_ROOT, "ping"], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _root(self, orden: str, timeout: int) -> tuple[bool, str]:
        try:
            r = subprocess.run(["sudo", "-n", SCRIPT_ROOT, orden], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, "tardó demasiado"
        except OSError as e:
            return False, str(e)
        LOGS.mkdir(parents=True, exist_ok=True)
        with open(LOGS / "mantenimiento.log", "a", encoding="utf-8") as f:
            f.write(f"\n===== {dt.datetime.now():%Y-%m-%d %H:%M} {orden} (código {r.returncode})\n"
                    f"{r.stdout[-6000:]}{r.stderr[-3000:]}")
        return r.returncode == 0, (r.stderr or r.stdout)[-300:]

    # ---------- informar (por voz, o por Telegram si la orden llegó de allí)
    def _contar(self, texto: str, por_telegram: bool) -> None:
        self.log(f"mantenimiento: {texto}")
        if por_telegram:
            self.avisar(texto)
        else:
            self.decir(texto)

    # ---------- limpieza
    def limpiar(self, a_fondo: bool = False, automatica: bool = False) -> tuple[int, list[str], bool]:
        """Devuelve (bytes liberados, qué se ha limpiado, ¿se pudo hacer la parte de administrador?)."""
        libre_antes = shutil.disk_usage("/").free
        hechos: list[str] = []
        liberado = 0

        b = sum(vaciar_carpeta(CACHE / n) for n in CACHES_SEGURAS)
        if b:
            liberado += b
            hechos.append("caché")

        # Temporales tuyos con más de un día (los recientes pueden estar en uso).
        limite = time.time() - 86400
        b = 0
        for raiz in (Path("/tmp"), Path("/var/tmp")):
            for dirpath, dirnames, archivos in os.walk(raiz, onerror=lambda e: None):
                dirnames[:] = [d for d in dirnames if not d.startswith((".X", ".ICE", ".font", "systemd-", "snap"))]
                for a in archivos:
                    p = os.path.join(dirpath, a)
                    try:
                        st = os.lstat(p)
                        if st.st_uid == os.getuid() and os.path.isfile(p) and not os.path.islink(p) \
                                and st.st_mtime < limite:
                            os.unlink(p)
                            b += st.st_size
                    except OSError:
                        pass
        if b:
            liberado += b
            hechos.append("temporales")

        b = (recortar_log(LOGS / "jarvis.log", 5 * 1024 ** 2, 5000)
             + recortar_log(LOGS / "auditoria.jsonl", 10 * 1024 ** 2, 20000)
             + recortar_log(LOGS / "mantenimiento.log", 2 * 1024 ** 2, 3000))
        if b:
            liberado += b
            hechos.append("registros de Jarvis")

        if a_fondo:
            b = 0
            for base in CACHES_NAVEGADOR:
                if base.is_dir():
                    for cache2 in list(base.rglob("cache2")) + list(base.rglob("startupCache")):
                        b += vaciar_carpeta(cache2)
                    if base.name in ("google-chrome", "chromium"):
                        b += vaciar_carpeta(base)
            if b:
                liberado += b
                hechos.append("caché del navegador")

        con_root = self.tiene_root()
        if con_root:
            ok, _ = self._root("limpiar", timeout=900)
            if ok:
                hechos.append("paquetes y registros del sistema")

        liberado = max(liberado, shutil.disk_usage("/").free - libre_antes)
        guardar_config(ultimo_mantenimiento=dt.date.today().isoformat())
        return liberado, hechos, con_root

    def _limpiar_y_contar(self, a_fondo: bool, por_telegram: bool) -> None:
        with self._ocupado:
            try:
                liberado, hechos, con_root = self.limpiar(a_fondo)
            except Exception as e:
                self._contar(f"La limpieza ha fallado: {e}", por_telegram)
                return
            libre = shutil.disk_usage("/").free
            texto = (f"Limpieza terminada. He liberado {mb(liberado)}" if liberado >= 1024 ** 2
                     else "Limpieza terminada. Estaba todo bastante limpio") + f". Tienes {mb(libre)} libres."
            papelera = tamano(PAPELERA / "files")
            if papelera >= 50 * 1024 ** 2:
                texto += f" En la papelera hay {mb(papelera)}; si quieres, dime: vacía la papelera."
            if not con_root:
                texto += (" Para limpiar también los paquetes y registros del sistema, ejecuta una vez en el portátil: "
                          "sudo bash jarvis/configurar_mantenimiento.sh")
            self._contar(texto, por_telegram)

    # ---------- actualizaciones
    def contar_actualizaciones(self, refrescar: bool = True) -> tuple[int, int, list[str]]:
        if refrescar and self.tiene_root():
            self._root("refrescar", timeout=300)
        apt: list[str] = []
        try:
            r = subprocess.run(["apt", "list", "--upgradable"], capture_output=True, text=True, timeout=60,
                               env={**os.environ, "LC_ALL": "C"})
            apt = [l.split("/")[0] for l in r.stdout.splitlines() if "[upgradable" in l]
        except (OSError, subprocess.TimeoutExpired):
            pass
        snaps = 0
        try:
            r = subprocess.run(["snap", "refresh", "--list"], capture_output=True, text=True, timeout=60,
                               env={**os.environ, "LC_ALL": "C"})
            filas = [l for l in r.stdout.splitlines()[1:] if l.strip()]
            snaps = len(filas) if r.returncode == 0 and "up to date" not in (r.stdout + r.stderr) else 0
        except (OSError, subprocess.TimeoutExpired):
            pass
        return len(apt), snaps, apt

    def _actualizar_y_contar(self, por_telegram: bool) -> None:
        with self._ocupado:
            inicio = time.time()
            ok, error = self._root("actualizar", timeout=3600)
            minutos = max(1, round((time.time() - inicio) / 60))
            if ok:
                texto = f"Actualización terminada en {minutos} minuto{'s' if minutos > 1 else ''}."
                if Path("/var/run/reboot-required").exists():
                    texto += " Hace falta reiniciar para completarla; cuando te venga bien, dime: reinicia el ordenador."
            else:
                texto = "La actualización no ha terminado bien. Lo tienes apuntado en el registro de mantenimiento."
                self.log(f"mantenimiento: error al actualizar: {error}")
            self._contar(texto, por_telegram)

    def _actualizar_modelo(self, por_telegram: bool) -> None:
        with self._ocupado:
            try:
                req = urllib.request.Request(self.ollama_url + "/api/pull",
                                             data=json.dumps({"model": self.modelo, "stream": False}).encode(),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=3600) as r:
                    estado = json.load(r).get("status", "")
                texto = ("Mi inteligencia ya está en la última versión." if estado == "success"
                         else f"He intentado actualizarme, pero Ollama dice: {estado}.")
            except Exception as e:
                texto = f"No he podido actualizar mi modelo de IA ({type(e).__name__}). Puede que no haya internet."
            self._contar(texto, por_telegram)

    # ---------- revisión
    def carpetas_grandes(self, n: int = 6) -> list[tuple[str, int]]:
        try:
            r = subprocess.run(["du", "-x", "-d1", "-b", str(HOME)], capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired):
            return []
        filas = []
        for l in r.stdout.splitlines():
            partes = l.split("\t", 1)
            if len(partes) == 2 and partes[1] != str(HOME):
                filas.append((Path(partes[1]).name, int(partes[0])))
        return sorted(filas, key=lambda x: -x[1])[:n]

    def chequeo(self) -> str:
        partes = []
        uso = shutil.disk_usage("/")
        partes.append(f"Disco: {mb(uso.free)} libres de {mb(uso.total)}.")
        try:
            r = subprocess.run(["systemctl", "--failed", "--no-legend", "--plain"], capture_output=True, text=True,
                               timeout=20)
            fallos = [l.split()[0] for l in r.stdout.splitlines() if l.strip()]
            partes.append(f"Hay {len(fallos)} servicio{'s' if len(fallos) > 1 else ''} con fallos: "
                          f"{', '.join(f.removesuffix('.service') for f in fallos[:3])}." if fallos
                          else "Todos los servicios funcionan.")
        except (OSError, subprocess.TimeoutExpired):
            pass
        apt, snaps, _ = self.contar_actualizaciones(refrescar=False)
        partes.append(f"Hay {apt + snaps} actualizaciones pendientes." if apt + snaps
                      else "El sistema está al día.")
        ultimo = leer_config().get("ultimo_mantenimiento")
        if ultimo:
            dias = (dt.date.today() - dt.date.fromisoformat(ultimo)).days
            partes.append("La última limpieza fue hoy." if dias == 0 else
                          f"La última limpieza fue hace {dias} día{'s' if dias > 1 else ''}.")
        else:
            partes.append("Todavía no he hecho ninguna limpieza.")
        if Path("/var/run/reboot-required").exists():
            partes.append("Hay un reinicio pendiente para terminar unas actualizaciones.")
        return " ".join(partes)

    # ---------- automático (cada semana)
    def arrancar_vigilante(self) -> None:
        threading.Thread(target=self._automatico, daemon=True).start()

    def _automatico(self) -> None:
        time.sleep(600)                                   # que el arranque termine tranquilo
        while True:
            try:
                cfg = leer_config()
                ultimo = cfg.get("ultimo_mantenimiento")
                if not ultimo or (dt.date.today() - dt.date.fromisoformat(ultimo)).days >= 7:
                    with self._ocupado:
                        liberado, _, _ = self.limpiar(automatica=True)
                    self.log(f"mantenimiento semanal: {mb(liberado)} liberados")
                    if liberado >= 20 * 1024 ** 2:
                        self.avisar(f"🧹 Mantenimiento semanal hecho: he liberado {mb(liberado)}.")
                hoy = dt.date.today().isoformat()
                if cfg.get("aviso_actualizaciones") != hoy:
                    apt, snaps, _ = self.contar_actualizaciones()
                    guardar_config(aviso_actualizaciones=hoy)
                    if apt + snaps >= 1:
                        self.avisar(f"⬆️ Hay {apt + snaps} actualizaciones disponibles. "
                                    "Cuando quieras, dime «actualiza el sistema».")
            except Exception as e:
                self.log(f"mantenimiento automático: {e!r}")
            time.sleep(6 * 3600)

    # ---------- órdenes
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).replace(",", "")
        tg = self.es_telegram()

        if re.search(r"\b(vacia\w*|limpia\w*|borra\w*)\s+(la |mi )?papelera\b", t):
            papelera = tamano(PAPELERA / "files")
            if papelera == 0:
                return Respuesta("La papelera ya está vacía.")
            if not self.confirmar(f"vaciar la papelera, que tiene {mb(papelera)}"):
                return Respuesta("Vale, no la toco.")
            vaciar_carpeta(PAPELERA / "files")
            vaciar_carpeta(PAPELERA / "info")
            return Respuesta(f"Papelera vacía. Has recuperado {mb(papelera)}.")

        if re.search(r"\b(limpia\w*|borra\w*|elimina\w*|vacia\w*|libera\w*)\b.*"
                     r"\b(caches?|cach|temporal\w*|basura|espacio|ordenador|portatil|sistema|equipo|pc|disco)\b"
                     r"|\b(haz|hazme|realiza|pasa|ejecuta)\w* (un |una )?(mantenimiento|limpieza)\b"
                     r"|^(mantenimiento|limpieza)\b|\boptimiza\w* (el |mi )?(ordenador|portatil|sistema|equipo|pc)\b", t):
            a_fondo = bool(re.search(r"\b(a fondo|completa|profunda|total|navegador)\b", t))
            if self._ocupado.locked():
                return Respuesta("Ya estoy con una tarea de mantenimiento. Te aviso cuando termine.")
            threading.Thread(target=self._limpiar_y_contar, args=(a_fondo, tg), daemon=True).start()
            return Respuesta("Empiezo la limpieza" + (" a fondo" if a_fondo else "")
                             + ". Tardaré un poco; te aviso al terminar.")

        if re.search(r"\b(actualiza\w*)\s+(tu |tus |la |el )?(inteligencia|cerebro|modelo|ia|conocimientos?)\b"
                     r"|^actualizate$", t):
            if self._ocupado.locked():
                return Respuesta("Ya estoy con una tarea de mantenimiento. Te aviso cuando termine.")
            threading.Thread(target=self._actualizar_modelo, args=(tg,), daemon=True).start()
            return Respuesta("Voy a buscar la última versión de mi modelo de IA. Te aviso al terminar.")

        if re.search(r"\b(hay|busca\w*|busqu\w*|comprueba\w*|mira\w*|revisa\w*|cuantas)\b.*\bactualizacion\w*\b"
                     r"|\bactualizaciones pendientes\b", t):
            apt, snaps, nombres = self.contar_actualizaciones()
            if apt + snaps == 0:
                return Respuesta("El sistema está al día, no hay actualizaciones.")
            if self.ui and nombres:
                self.ui.enviar(tipo="resultados", titulo="Actualizaciones", items=nombres[:12])
            texto = f"Hay {apt + snaps} actualizaciones: {apt} de paquetes y {snaps} de aplicaciones snap."
            texto += (" Si quieres instalarlas, dime: actualiza el sistema." if self.tiene_root() else
                      " Para que pueda instalarlas yo, ejecuta una vez en el portátil: "
                      "sudo bash jarvis/configurar_mantenimiento.sh")
            return Respuesta(texto)

        if re.search(r"\b(actualiza\w*|instala\w*)\s+(el |la |los |las |todo el |mi )?"
                     r"(sistema|ordenador|portatil|equipo|ubuntu|programas|paquetes|pc|actualizaciones|todo)\b", t):
            if not self.tiene_root():
                return Respuesta("Para instalar actualizaciones necesito permiso de administrador una sola vez. "
                                 "Ejecuta en el portátil: sudo bash jarvis/configurar_mantenimiento.sh")
            if self._ocupado.locked():
                return Respuesta("Ya estoy con una tarea de mantenimiento. Te aviso cuando termine.")
            if not self.confirmar("instalar las actualizaciones del sistema. Puede tardar varios minutos"):
                return Respuesta("Vale, lo dejamos para otro momento.")
            threading.Thread(target=self._actualizar_y_contar, args=(tg,), daemon=True).start()
            return Respuesta("Actualizando el sistema. Puedes seguir usando el ordenador; te aviso cuando acabe.")

        if re.search(r"\bque (es lo que )?(ocupa|esta ocupando|gasta)\w* (mas |tanto )?(espacio|disco|sitio)\b"
                     r"|\b(carpetas|archivos) (mas )?grandes\b|\bdonde (se va|esta) el espacio\b", t):
            filas = self.carpetas_grandes()
            if not filas:
                return Respuesta("No he podido medir las carpetas.")
            if self.ui:
                self.ui.enviar(tipo="resultados", titulo="Lo que más ocupa", items=[f"{n} — {mb(b)}" for n, b in filas])
            lista = ", ".join(f"{n} con {mb(b)}" for n, b in filas[:4])
            return Respuesta(f"Lo que más ocupa en tu carpeta personal: {lista}.")

        if re.search(r"\b(haz|hazme|pasa)\w* (un |una )?(chequeo|diagnostico|revision)\b"
                     r"|\brevisa\w* (el |mi )?(ordenador|sistema|portatil|equipo|pc)\b|\bchequeo\b", t):
            return Respuesta(self.chequeo())
        return None
