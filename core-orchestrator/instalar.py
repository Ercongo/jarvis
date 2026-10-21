"""
Instalar programas sin contraseña cuando se puede, y con ayuda cuando no:

  "instala la aplicación terminado punto app imagine de descargas"   → AppImage: se extrae en ~/Aplicaciones,
                                                                        se crea su icono en el menú y se abre
  "instala el programa que acabo de descargar"                        → el instalador más reciente de Descargas
  "instala Spotify" / "instala GIMP"                                  → lo busca en la tienda de Ubuntu (snap) y te
                                                                        abre su página: pulsas Instalar y pones
                                                                        la contraseña (Jarvis no la tiene)
  "qué programas me has instalado" / "desinstala terminado"           → solo los que instaló Jarvis (con confirmación)

.deb: te abre el instalador de Ubuntu (pide la contraseña). .flatpakref: flatpak --user (sin contraseña) si está.
Whisper oye "punto app imagine" o "app image" por ".AppImage": se entiende igual.
"""

from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
import tarfile
import threading
import zipfile
from pathlib import Path
from typing import Callable

from perfil import DATOS
from herramientas import carpeta_usuario, lanzar, normalizar
from sistema import Respuesta

HOME = Path.home()
APPS = HOME / "Aplicaciones"
MENU = HOME / ".local" / "share" / "applications"
REGISTRO = DATOS / "instalados.json"
EXT_INSTALABLES = (".appimage", ".deb", ".flatpakref", ".tar.gz", ".tgz", ".tar.xz", ".zip", ".run", ".snap")


def _leer() -> list[dict]:
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _guardar(datos: list[dict]) -> None:
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    REGISTRO.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def _ext(p: Path) -> str:
    n = p.name.lower()
    for e in EXT_INSTALABLES:
        if n.endswith(e):
            return e
    return p.suffix.lower()


def _base(p: Path) -> str:
    n = p.name
    n = re.sub(r"(?i)(\.tar\.gz|\.tar\.xz|\.tgz|\.appimage|\.deb|\.flatpakref|\.zip|\.run|\.snap)$", "", n)
    n = re.sub(r"(?:[-_.](?:x86[-_]?64|amd64|arm64|aarch64|linux|v?\d[\d.]*))+$", "", n, flags=re.I)   # versión y arquitectura
    return n.strip("-_. ") or p.stem


def instaladores(carpeta: Path | None = None) -> list[Path]:
    carpeta = carpeta or carpeta_usuario("DOWNLOAD")
    if not carpeta.is_dir():
        return []
    fuera = [p for p in carpeta.iterdir() if p.is_file() and _ext(p) in EXT_INSTALABLES]
    return sorted(fuera, key=lambda p: -p.stat().st_mtime)


def elegir(nombre: str, rutas: list[Path]) -> Path | None:
    if not rutas:
        return None
    clave = normalizar(nombre)
    m = re.search(r"\b(?:se llama|llamad[oa]|que pone|de nombre)\s+(.+)$", clave)
    if m:
        clave = m.group(1)
    clave = re.sub(r"\b(punto )?(app ?imagine|app ?image|appimage|app imagen)\b", "", clave)
    clave = re.sub(r"\b(punto|deb|el|la|lo|programa|aplicacion|app|que|esta|en|de|las|los|descargas|carpeta|"
                   r"archivo|instalador|mi|mis|ahi)\b", " ", clave)
    clave = re.sub(r"\s+", " ", clave).strip()
    if not clave:
        return rutas[0]
    puntos = []
    for p in rutas:
        nom = normalizar(_base(p)).replace("-", " ").replace("_", " ")
        r = max(difflib.SequenceMatcher(None, clave, nom).ratio(),
                1.0 if clave in nom or nom in clave else 0.0)
        puntos.append((r, p))
    r, p = max(puntos, key=lambda x: x[0])
    return p if r >= 0.5 else None


class Instalar:
    def __init__(self, decir: Callable[..., None], confirmar: Callable[[str], bool], log=print,
                 es_telegram: Callable[[], bool] | None = None, avisar=None):
        self.decir = decir
        self.confirmar = confirmar
        self.log = log
        self.es_telegram = es_telegram or (lambda: False)
        self.avisar = avisar or (lambda t: None)

    def _contar(self, texto: str, tg: bool) -> None:
        self.log(f"instalar: {texto}")
        (self.avisar if tg else self.decir)(texto)

    # ---------- AppImage (sin contraseña)
    def _appimage(self, origen: Path, tg: bool) -> str:
        nombre = _base(origen)
        destino = APPS / nombre
        if destino.exists():
            shutil.rmtree(destino, ignore_errors=True)
        destino.mkdir(parents=True, exist_ok=True)
        archivo = destino / origen.name
        shutil.copy2(origen, archivo)
        archivo.chmod(0o755)
        # Se extrae: así funciona aunque falte FUSE (Ubuntu 26.04 no trae libfuse2)
        r = subprocess.run([str(archivo), "--appimage-extract"], cwd=destino, capture_output=True, timeout=600)
        raiz = destino / "squashfs-root"
        ejecutable = raiz / "AppRun" if (raiz / "AppRun").exists() else archivo
        if r.returncode == 0 and raiz.exists():
            archivo.unlink(missing_ok=True)              # ya no hace falta la copia comprimida
        icono = next((p for p in [raiz / ".DirIcon", *sorted(raiz.glob("*.png")), *sorted(raiz.glob("*.svg"))]
                      if p.exists()), None) if raiz.exists() else None
        visible = nombre.replace("-", " ").replace("_", " ").strip().title()
        MENU.mkdir(parents=True, exist_ok=True)
        lanzador = MENU / f"jarvis-{re.sub(r'[^a-z0-9]+', '-', nombre.lower())}.desktop"
        lanzador.write_text("[Desktop Entry]\nType=Application\n"
                            f"Name={visible}\nExec=\"{ejecutable}\" %U\n"
                            f"Icon={icono or 'application-x-executable'}\nTerminal=false\n"
                            "Categories=Utility;\nComment=Instalado por Jarvis\n", encoding="utf-8")
        lanzador.chmod(0o755)
        datos = [d for d in _leer() if d.get("nombre") != visible]
        datos.append({"nombre": visible, "carpeta": str(destino), "lanzador": str(lanzador), "tipo": "appimage"})
        _guardar(datos)
        subprocess.Popen([str(ejecutable)], cwd=str(ejecutable.parent), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return (f"Instalado {visible}: lo tienes en el menú de aplicaciones y te lo acabo de abrir. "
                f"Está en la carpeta Aplicaciones.")

    def _comprimido(self, origen: Path) -> str:
        nombre = _base(origen)
        destino = APPS / nombre
        destino.mkdir(parents=True, exist_ok=True)
        if origen.name.lower().endswith(".zip"):
            with zipfile.ZipFile(origen) as z:
                z.extractall(destino)
        else:
            with tarfile.open(origen) as t:
                t.extractall(destino, filter="data")
        ejecutables = [p for p in destino.rglob("*") if p.is_file() and p.stat().st_mode & 0o111
                       and not p.suffix and normalizar(nombre)[:4] in normalizar(p.name)]
        datos = _leer() + [{"nombre": nombre, "carpeta": str(destino), "tipo": "comprimido"}]
        _guardar(datos)
        if ejecutables:
            lanzar([str(ejecutables[0])])
            return f"He descomprimido {nombre} en Aplicaciones y te lo abro."
        lanzar(["xdg-open", str(destino)])
        return f"He descomprimido {nombre} en Aplicaciones; te abro la carpeta porque no veo claro cuál es el programa."

    def instalar_archivo(self, ruta: Path) -> Respuesta:
        tg = self.es_telegram()
        ext = _ext(ruta)
        if ext == ".appimage":
            def hilo():
                try:
                    self._contar(self._appimage(ruta, tg), tg)
                except Exception as e:
                    self._contar(f"No he podido instalar {ruta.name} ({type(e).__name__}).", tg)
            threading.Thread(target=hilo, daemon=True).start()
            return Respuesta(f"Instalo {_base(ruta)}. Un momento.")
        if ext in (".tar.gz", ".tgz", ".tar.xz", ".zip"):
            try:
                return Respuesta(self._comprimido(ruta))
            except Exception as e:
                return Respuesta(f"No he podido descomprimirlo ({type(e).__name__}).")
        if ext == ".flatpakref" and shutil.which("flatpak"):
            r = subprocess.run(["flatpak", "install", "--user", "-y", "--from", str(ruta)], capture_output=True,
                               text=True, timeout=1800)
            return Respuesta("Instalado con Flatpak; lo tienes en el menú." if r.returncode == 0 else
                             f"Flatpak no ha podido: {r.stderr.strip()[:150]}")
        if ext == ".deb":
            lanzar(["xdg-open", str(ruta)])
            return Respuesta(f"Los .deb necesitan tu contraseña, que yo no tengo. Te abro el instalador de Ubuntu con "
                             f"{ruta.name}: pulsa Instalar y escribe la contraseña.")
        if ext == ".run":
            return Respuesta(f"{ruta.name} es un instalador .run: puede tocar el sistema y prefiero que lo lances tú, "
                             f"desde la terminal, con: bash ~/Descargas/{ruta.name}")
        if ext == ".snap":
            return Respuesta("Los .snap sueltos necesitan la contraseña. Mejor dime instala y el nombre del programa, "
                             "y te abro su página en la tienda de Ubuntu.")
        return Respuesta(f"No sé instalar archivos {ext}.")

    def desde_tienda(self, nombre: str) -> Respuesta:
        if not shutil.which("snap"):
            return Respuesta("No encuentro la tienda de Ubuntu en este equipo.")
        try:
            r = subprocess.run(["snap", "find", nombre], capture_output=True, text=True, timeout=40)
        except (OSError, subprocess.TimeoutExpired):
            return Respuesta("La tienda no responde ahora mismo.")
        filas = [l.split() for l in r.stdout.splitlines()[1:] if l.strip()]
        if not filas:
            return Respuesta(f"No encuentro {nombre} en la tienda de Ubuntu.")
        clave = normalizar(nombre).replace(" ", "-")
        exacto = next((f for f in filas if f[0] == clave), None) or filas[0]
        paquete = exacto[0]
        instalado = subprocess.run(["snap", "list", paquete], capture_output=True, timeout=20).returncode == 0
        if instalado:
            lanzar(["gtk-launch", paquete]) if shutil.which("gtk-launch") else None
            return Respuesta(f"{paquete} ya está instalado.")
        lanzar(["xdg-open", f"snap://{paquete}"])
        return Respuesta(f"Te abro {paquete} en la tienda de Ubuntu: pulsa Instalar y escribe tu contraseña "
                         "(yo no la tengo, y mejor así).")

    # ---------- órdenes
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).strip(" .¿?¡!")
        t = re.sub(r"^(?:por favor|oye|venga|jarvis)[ ,]+", "", t)
        if re.search(r"\bque (programas|aplicaciones|apps) (me )?has instalado\b", t):
            datos = _leer()
            if not datos:
                return Respuesta("Todavía no te he instalado nada.")
            return Respuesta("Te he instalado: " + ", ".join(d["nombre"] for d in datos) + ".")
        m = re.match(r"^(?:desinstala(?:me)?\s+(?:el programa |la aplicacion |la app )?|(?:quita|borra|elimina)\w*\s+"
                     r"(?:el programa|la aplicacion|la app)\s+)(.+)$", t)
        if m:
            datos = _leer()
            nombres = {normalizar(d["nombre"]): d for d in datos}
            cerca = difflib.get_close_matches(normalizar(m.group(1)), list(nombres), n=1, cutoff=0.6)
            if not cerca:
                return None                               # no es algo que instalara Jarvis: que lo mire otro módulo
            d = nombres[cerca[0]]
            if not self.confirmar(f"desinstalar {d['nombre']}"):
                return Respuesta("Vale, lo dejo.")
            shutil.rmtree(d["carpeta"], ignore_errors=True)
            if d.get("lanzador"):
                Path(d["lanzador"]).unlink(missing_ok=True)
            _guardar([x for x in datos if x is not d])
            return Respuesta(f"{d['nombre']} desinstalado.")
        m = re.match(r"^(?:instala|instalame|instalar|puedes instalar|quiero que instales|me instalas)\s+(.+)$", t)
        if not m:
            return None
        resto = m.group(1).strip()
        rutas = instaladores()
        if re.search(r"\b(descarg|que acabo de|ultimo|el archivo|el instalador|app ?imag|appimage|punto deb|\.deb)\b",
                     resto) or re.search(r"\bdescargas\b", t):
            if re.search(r"\b(que acabo de|ultimo|el instalador)\b", resto) and rutas:
                return self.instalar_archivo(rutas[0])
            ruta = elegir(resto, rutas)
            if ruta is None:
                if not rutas:
                    return Respuesta("No veo ningún instalador en Descargas (AppImage, deb, zip…).")
                return Respuesta("En Descargas tengo: " + ", ".join(p.name for p in rutas[:5]) + ". ¿Cuál instalo?")
            return self.instalar_archivo(ruta)
        nombre = re.sub(r"^(?:el programa|la aplicacion|la app|el juego|el)\s+", "", resto).strip()
        ruta = elegir(nombre, rutas)
        if ruta is not None:
            return self.instalar_archivo(ruta)
        return self.desde_tienda(nombre)
