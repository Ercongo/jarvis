"""
Gestión de archivos para Jarvis.

Órdenes (por voz o Telegram):
  "crea una carpeta llamada facturas en documentos"
  "crea un archivo de texto llamado compra que diga leche, huevos y pan"
  "crea un word sobre la historia de Sevilla"          → lo redacta la IA (tarda un par de minutos)
  "hazme un pdf con una carta de reclamación a la compañía de la luz"
  "crea un pdf llamado avisos que diga mañana no hay agua"   → con tu texto exacto
  "convierte el archivo informe a pdf"
  "mándame el archivo presupuesto" / "envíame la carpeta facturas"  → por Telegram (las carpetas, en zip)
  "renombra el archivo compra a compra semanal"
  "mueve el archivo factura luz a documentos" / "copia el archivo X a escritorio"
  "borra el archivo X" / "elimina la carpeta Y"        → SIEMPRE pide confirmación y va a la papelera
Si hay varios archivos con ese nombre, los enseña y se elige con "el primero", "el 2"…

Seguridad: solo trabaja dentro de tu carpeta personal; nunca toca carpetas ocultas, ~/snap, ~/jarvis
ni las carpetas principales (Documentos, Escritorio…). Borrar es siempre a la papelera (recuperable).
"""

from __future__ import annotations

import datetime as dt
import difflib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable

from perfil import DATOS, INSTALACION, MOTOR
from herramientas import (CARPETAS_CONOCIDAS, HOME, carpeta_usuario, corto, lanzar, nombre_carpeta_conocida,
                          normalizar)
from sistema import Respuesta, con_tildes

LIMITE_TELEGRAM = 48 * 1024 ** 2
NUMEROS = {"primero": 1, "primera": 1, "uno": 1, "una": 1, "segundo": 2, "segunda": 2, "dos": 2, "tercero": 3,
           "tercera": 3, "tres": 3, "cuarto": 4, "cuarta": 4, "cuatro": 4, "quinto": 5, "quinta": 5, "cinco": 5,
           "sexto": 6, "seis": 6, "septimo": 7, "siete": 7, "octavo": 8, "ocho": 8, "ultimo": -1, "ultima": -1}
TIPOS = r"(?:archivo|fichero|documento|carpeta|directorio|pdf|word|excel|presentacion|foto|imagen|video|cancion|audio)"
NO_SON_ARCHIVOS = r"\b(cache|cach|caches|temporal\w*|basura|papelera|recordatorio\w*|alarma\w*|temporizador\w*|nota|notas|" \
                  r"memoria|historial|aprendido|atajo|vigilancia|camara|volumen|todo|eso|esto)\b"
EXT_TIPO = {"pdf": (".pdf",), "word": (".docx", ".doc", ".odt"), "excel": (".xlsx", ".xls", ".ods", ".csv"),
            "presentacion": (".pptx", ".ppt", ".odp"), "foto": (".jpg", ".jpeg", ".png", ".webp", ".heic"),
            "imagen": (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"), "video": (".mp4", ".mkv", ".avi", ".mov"),
            "cancion": (".mp3", ".ogg", ".flac", ".m4a", ".wav"), "audio": (".mp3", ".ogg", ".flac", ".m4a", ".wav")}


# =============================================================== utilidades

def protegida(p: Path) -> str | None:
    """¿Por qué no se puede tocar esta ruta? None si se puede."""
    try:
        p = p.resolve()
    except OSError:
        return "no la encuentro"
    if p == HOME or not str(p).startswith(str(HOME) + os.sep):
        return "está fuera de tu carpeta personal"
    relativa = p.relative_to(HOME)
    if any(parte.startswith(".") for parte in relativa.parts):
        return "es una carpeta oculta del sistema"
    if relativa.parts[0] == "snap" or any(p == r or r in p.parents for r in (DATOS.resolve(), INSTALACION.resolve(),
                                                                            MOTOR)):
        return "es una carpeta de programas o del propio asistente"
    principales = {carpeta_usuario(c) for c in set(CARPETAS_CONOCIDAS.values())}
    if p in principales:
        return "es una de tus carpetas principales"
    return None


def limpiar_nombre(nombre: str) -> str:
    nombre = re.sub(r"(?i)\.(docx?|odt|pdf|txt|xlsx?|ods|csv|pptx?|odp|md)\s*$", "", nombre.strip())   # sin extensión
    nombre = re.sub(r'[\\/:*?"<>|]+', " ", nombre).strip(" .,")
    nombre = re.sub(r"\s+", " ", nombre.replace("_", " "))
    return (nombre[:1].upper() + nombre[1:])[:80] or "Documento"


def sin_pisar(ruta: Path) -> Path:
    if not ruta.exists():
        return ruta
    for i in range(2, 100):
        otra = ruta.with_name(f"{ruta.stem} ({i}){ruta.suffix}")
        if not otra.exists():
            return otra
    return ruta.with_name(f"{ruta.stem} {int(time.time())}{ruta.suffix}")


def buscar_en_casa(texto: str, carpetas: bool | None = None, extensiones: tuple[str, ...] = (),
                   maximo: int = 8) -> list[Path]:
    """Busca en tu carpeta personal ahora mismo (sin índice: encuentra también lo recién creado)."""
    palabras = [w for w in re.split(r"[\s_\-.,]+", normalizar(texto)) if len(w) >= 2 and w not in
                ("el", "la", "los", "las", "de", "del", "mi", "mis", "un", "una")]
    if not palabras:
        return []
    clave = max(palabras, key=len)
    # "electrico" tiene que encontrar "Eléctrico": cada vocal (y la n) vale con o sin tilde
    variantes = {"a": "aáà", "e": "eéè", "i": "iíï", "o": "oóò", "u": "uúü", "n": "nñ"}
    patron = "".join(f"[{v}{v.upper()}]" if (v := variantes.get(c)) else ("?" if c in "[]*?\\" else c)
                     for c in clave[:5])
    try:
        r = subprocess.run(["find", str(HOME), "-maxdepth", "7", "(", "-name", ".*", "-o", "-path", f"{HOME}/snap",
                            "-o", "-path", f"{HOME}/jarvis", ")", "-prune", "-o", "-iname", f"*{patron}*", "-print"],
                           capture_output=True, text=True, timeout=10)
        rutas = [Path(x) for x in r.stdout.splitlines()]
    except (OSError, subprocess.TimeoutExpired):
        rutas = []
    puntuadas = []
    for p in rutas:
        nombre = normalizar(p.stem if p.is_file() else p.name)
        trozos = re.split(r"[\s_\-.,()]+", nombre)
        if not all(w in nombre or difflib.get_close_matches(w, trozos, n=1, cutoff=0.8) for w in palabras):
            continue
        try:
            es_dir = p.is_dir()
        except OSError:
            continue
        if carpetas is not None and es_dir != carpetas:
            continue
        if extensiones and not es_dir and p.suffix.lower() not in extensiones:
            continue
        puntos = difflib.SequenceMatcher(None, " ".join(palabras), nombre).ratio()
        try:
            puntos += min(0.2, max(0, 0.2 - (time.time() - p.stat().st_mtime) / 86400 / 150))   # lo reciente, antes
        except OSError:
            pass
        puntuadas.append((puntos, p))
    puntuadas.sort(key=lambda x: -x[0])
    return [p for _, p in puntuadas[:maximo]]


def carpeta_destino(texto: str) -> Path | None:
    """'escritorio', 'la carpeta facturas', 'documentos' → la ruta (si existe)."""
    t = re.sub(r"^(la |el |mi |mis |los |las )?(carpeta |directorio )?(de |del )?", "", normalizar(texto)).strip()
    if not t:
        return None
    if t in ("casa", "inicio", "personal", "carpeta personal"):
        return HOME
    conocida = nombre_carpeta_conocida(t)
    if conocida:
        return carpeta_usuario(CARPETAS_CONOCIDAS[conocida])
    encontradas = buscar_en_casa(t, carpetas=True, maximo=1)
    return encontradas[0] if encontradas else None


def separar_destino(resto: str) -> tuple[str, Path | None]:
    """'facturas en la carpeta documentos' → ('facturas', ~/Documentos). Solo si el destino existe."""
    for m in reversed(list(re.finditer(r"\s+(?:en|dentro de|a)\s+", resto))):
        destino = carpeta_destino(resto[m.end():])
        if destino is not None:
            return resto[:m.start()].strip(), destino
    return resto.strip(), None


def tamano(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())


def mb(b: int) -> str:
    return f"{b / 1024 ** 2:.1f} megas".replace(".", ",") if b >= 1024 ** 2 else f"{max(1, round(b / 1024))} kilobytes"


# =============================================================== documentos

def crear_docx(ruta: Path, titulo: str, texto: str) -> None:
    from docx import Document
    from docx.shared import Pt
    doc = Document()
    estilo = doc.styles["Normal"]
    estilo.font.name = "Calibri"
    estilo.font.size = Pt(11)
    if titulo:
        doc.add_heading(titulo, level=1)
    anadir_markdown_docx(doc, texto)
    pie = doc.sections[0].footer.paragraphs[0]
    pie.text = f"Creado por Jarvis el {dt.datetime.now():%d/%m/%Y}"
    pie.runs[0].font.size = Pt(8)
    doc.save(str(ruta))


def anadir_markdown_docx(doc, texto: str) -> None:
    """Añade texto con formato ligero: '## Apartado', '- lista', '1. lista', '**negrita**', tablas con '|'."""
    from docx.shared import Pt  # noqa: F401  (asegura que python-docx está)
    bloques = re.split(r"\n\s*\n", texto.strip())
    for bloque in bloques:
        lineas = [l.rstrip() for l in bloque.splitlines() if l.strip()]
        if not lineas:
            continue
        if all("|" in l for l in lineas) and len(lineas) >= 2:            # tabla
            filas = [[c.strip() for c in l.strip().strip("|").split("|")] for l in lineas
                     if not re.fullmatch(r"[\s|:\-]+", l)]
            if filas:
                ncol = max(len(f) for f in filas)
                tabla = doc.add_table(rows=len(filas), cols=ncol)
                try:
                    tabla.style = "Light Grid Accent 1"
                except (KeyError, ValueError):
                    tabla.style = "Table Grid"
                for i, fila in enumerate(filas):
                    for j in range(ncol):
                        celda = tabla.cell(i, j)
                        celda.text = fila[j] if j < len(fila) else ""
                        if i == 0:
                            for run in celda.paragraphs[0].runs:
                                run.bold = True
                continue
        for l in lineas:
            mi = re.match(r"^\[(?:IMAGEN|IMAGE|FOTO)\s*:\s*(.+?)\]$", l.strip(), re.I)
            if mi:
                _imagen_docx(doc, mi.group(1))
                continue
            m = re.match(r"^(#{1,3})\s+(.+)$", l.strip())
            if m:
                doc.add_heading(m.group(2).strip(" #"), level=min(3, len(m.group(1)) + (0 if len(m.group(1)) > 1 else 1)))
                continue
            if re.match(r"^[-•*]\s+", l.strip()):
                par = doc.add_paragraph(style="List Bullet")
                _con_negritas(par, re.sub(r"^[-•*]\s+", "", l.strip()))
            elif re.match(r"^\d+[.)]\s+", l.strip()):
                par = doc.add_paragraph(style="List Number")
                _con_negritas(par, re.sub(r"^\d+[.)]\s+", "", l.strip()))
            else:
                par = doc.add_paragraph()
                _con_negritas(par, l.strip())


def _imagen_docx(doc, prompt: str) -> None:
    """Pinta la imagen (Pollinations, gratis) y la mete en el Word; si falla, se omite sin más."""
    try:
        from docx.shared import Cm
        from creativo import descargar_imagen
        destino = Path(tempfile.gettempdir()) / f"jarvis_doc_{abs(hash(prompt)) % 10 ** 8}.jpg"
        descargar_imagen(prompt, 1024, 576, destino)
        doc.add_picture(str(destino), width=Cm(15))
        destino.unlink(missing_ok=True)
    except Exception:
        pass


def _con_negritas(par, texto: str) -> None:
    for i, trozo in enumerate(re.split(r"\*\*(.+?)\*\*", texto)):
        if trozo:
            run = par.add_run(trozo.replace("*", ""))
            run.bold = i % 2 == 1


def a_pdf(origen: Path, carpeta: Path) -> Path | None:
    """Convierte con LibreOffice (perfil propio, para no chocar si tienes LibreOffice abierto)."""
    perfil = Path(tempfile.gettempdir()) / "jarvis_libreoffice"
    try:
        subprocess.run(["soffice", f"-env:UserInstallation=file://{perfil}", "--headless", "--convert-to", "pdf",
                        "--outdir", str(carpeta), str(origen)], capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return None
    pdf = carpeta / (origen.stem + ".pdf")
    return pdf if pdf.exists() else None


def separar_titulo(texto: str, por_defecto: str) -> tuple[str, str]:
    lineas = texto.strip().splitlines()
    if lineas and len(lineas[0]) <= 90 and len(lineas) > 1:
        return lineas[0].strip(" #*:"), "\n".join(lineas[1:])
    return por_defecto, texto


# =============================================================== el módulo

class Archivos:
    def __init__(self, decir: Callable[..., None], confirmar: Callable[[str], bool], log=print, ui=None,
                 enviar_documento: Callable[[str, str], bool] | None = None,
                 es_telegram: Callable[[], bool] | None = None,
                 redactar: Callable[[str], str] | None = None, avisar: Callable[[str], None] | None = None):
        self.decir = decir
        self.confirmar = confirmar
        self.log = log
        self.ui = ui
        self.enviar_documento = enviar_documento or (lambda ruta, pie: False)
        self.es_telegram = es_telegram or (lambda: False)
        self.redactar = redactar
        self.avisar = avisar or (lambda t: None)
        self._pendiente: dict | None = None

    # ---------- elegir entre varios
    def _elegir(self, accion: str, rutas: list[Path], extra: dict | None = None) -> Respuesta:
        self._pendiente = {"accion": accion, "rutas": rutas, "t": time.time(), **(extra or {})}
        items = [corto(p) + ("/" if p.is_dir() else "") for p in rutas]
        if self.ui:
            self.ui.enviar(tipo="resultados", titulo="¿Cuál?", items=items)
        texto = f"He encontrado {len(rutas)}. ¿Cuál? Dime el primero, el segundo…"
        if self.es_telegram():
            texto += "\n" + "\n".join(f"{i + 1}. {x}" for i, x in enumerate(items))
        else:
            texto += " Te los enseño en la pantalla."
        return Respuesta(texto)

    def _encontrar(self, accion: str, nombre: str, tipo: str, extra: dict | None = None) -> Path | Respuesta:
        carpetas = True if tipo in ("carpeta", "directorio") else (False if tipo else None)
        nombre = re.sub(r"^(el|la|los|las|mi|mis)\s+", "", nombre.strip())
        exts = EXT_TIPO.get(tipo, ())
        rutas = buscar_en_casa(nombre, carpetas=carpetas, extensiones=exts)
        if not rutas:
            que = "ninguna carpeta" if carpetas else "nada"
            return Respuesta(f"No encuentro {que} que se llame {nombre}.")
        exactas = [p for p in rutas if normalizar(p.stem if p.is_file() else p.name) == normalizar(nombre)]
        if len(exactas) == 1:
            return exactas[0]
        if len(rutas) == 1:
            return rutas[0]
        return self._elegir(accion, rutas, extra)

    def _ejecutar(self, accion: str, ruta: Path, datos: dict) -> Respuesta:
        if accion == "borrar":
            return self._borrar(ruta)
        if accion == "enviar":
            return self._enviar(ruta)
        if accion == "pdf":
            return self._convertir(ruta)
        if accion in ("mover", "copiar"):
            return self._mover(ruta, Path(datos["destino"]), accion == "copiar")
        if accion == "renombrar":
            return self._renombrar(ruta, datos["nuevo"])
        return Respuesta("No sé qué hacer con eso.")

    # ---------- acciones
    def _borrar(self, ruta: Path) -> Respuesta:
        motivo = protegida(ruta)
        if motivo:
            return Respuesta(f"No puedo borrar {ruta.name}: {motivo}.")
        if ruta.is_dir():
            n = sum(1 for _ in ruta.rglob("*"))
            que = f"la carpeta {ruta.name}, con {n} elemento{'s' if n != 1 else ''} dentro"
        else:
            que = f"el archivo {ruta.name}"
        if not self.confirmar(f"mandar a la papelera {que}"):
            return Respuesta("Vale, no borro nada.")
        r = subprocess.run(["gio", "trash", str(ruta)], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return Respuesta(f"No he podido borrarlo: {r.stderr.strip()[:120]}")
        self.log(f"archivos: a la papelera {ruta}")
        return Respuesta(f"Hecho, {ruta.name} está en la papelera. Si te arrepientes, puedes recuperarlo de ahí.")

    def _enviar(self, ruta: Path) -> Respuesta:
        envio, temporal = ruta, None
        if ruta.is_dir():
            if tamano(ruta) > LIMITE_TELEGRAM * 2:
                return Respuesta(f"La carpeta {ruta.name} es demasiado grande para mandarla por Telegram.")
            temporal = Path(tempfile.gettempdir()) / "jarvis" / f"{ruta.name}.zip"
            temporal.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(temporal, "w", zipfile.ZIP_DEFLATED) as z:
                for f in ruta.rglob("*"):
                    if f.is_file():
                        z.write(f, f.relative_to(ruta.parent))
            envio = temporal
        if envio.stat().st_size > LIMITE_TELEGRAM:
            return Respuesta(f"{ruta.name} ocupa {mb(envio.stat().st_size)}: Telegram no deja mandar más de 50 megas.")
        if self.es_telegram():
            return Respuesta(f"Ahí va {ruta.name}.", archivo=str(envio))
        ok = self.enviar_documento(str(envio), f"📎 {ruta.name}")
        return Respuesta(f"Te he mandado {ruta.name} al móvil." if ok else
                         "No he podido mandarlo. ¿Está configurado Telegram?")

    def _convertir(self, ruta: Path) -> Respuesta:
        if ruta.suffix.lower() == ".pdf":
            return Respuesta(f"{ruta.name} ya es un PDF.")
        pdf = a_pdf(ruta, ruta.parent)
        if not pdf:
            return Respuesta(f"No he podido convertir {ruta.name} a PDF.")
        if not self.es_telegram():
            lanzar(["xdg-open", str(pdf)])
        return Respuesta(f"Convertido. El PDF está junto al original, en {pdf.parent.name}.", archivo=str(pdf))

    def _mover(self, ruta: Path, destino: Path, copiar: bool) -> Respuesta:
        motivo = protegida(ruta) if not copiar else None
        if motivo:
            return Respuesta(f"No puedo mover {ruta.name}: {motivo}.")
        if str(destino.resolve()).startswith(str(ruta.resolve()) + os.sep) or destino.resolve() == ruta.resolve():
            return Respuesta("No puedo meter una carpeta dentro de sí misma.")
        nuevo = sin_pisar(destino / ruta.name)
        if copiar:
            (shutil.copytree if ruta.is_dir() else shutil.copy2)(ruta, nuevo)
        else:
            shutil.move(str(ruta), str(nuevo))
        return Respuesta(f"{'Copiado' if copiar else 'Movido'}: {nuevo.name} ya está en {destino.name}.")

    def _renombrar(self, ruta: Path, nuevo_nombre: str) -> Respuesta:
        motivo = protegida(ruta)
        if motivo:
            return Respuesta(f"No puedo renombrar {ruta.name}: {motivo}.")
        nombre = limpiar_nombre(nuevo_nombre)
        nuevo = ruta.with_name(nombre + (ruta.suffix if ruta.is_file() and not Path(nombre).suffix else ""))
        if nuevo.exists():
            return Respuesta(f"Ya existe algo llamado {nuevo.name} ahí.")
        ruta.rename(nuevo)
        return Respuesta(f"Renombrado a {nuevo.name}.")

    # ---------- crear documentos
    def _crear_documento(self, formato: str, nombre: str | None, carpeta: Path, texto: str | None,
                         tema: str | None, peticion: str) -> Respuesta:
        carpeta.mkdir(parents=True, exist_ok=True)
        if texto is not None:
            return self._escribir(formato, nombre or texto[:40], carpeta, texto, por_telegram=self.es_telegram())
        if not tema:
            return Respuesta("¿Qué quieres que ponga? Dime por ejemplo: crea un word sobre las vacaciones, "
                             "o crea un pdf que diga, y el texto.")
        if not self.redactar:
            return Respuesta("Ahora mismo no puedo redactar documentos.")
        tg = self.es_telegram()
        threading.Thread(target=self._redactar_y_escribir, args=(formato, nombre, carpeta, tema, tg),
                         daemon=True).start()
        return Respuesta(f"Me pongo a redactarlo. Tardaré un par de minutos; te aviso cuando esté.")

    def _redactar_y_escribir(self, formato: str, nombre: str | None, carpeta: Path, tema: str, tg: bool) -> None:
        try:
            texto = self.redactar(tema)
        except Exception as e:
            self._contar(f"No he podido redactar el documento ({type(e).__name__}).", tg)
            return
        if not texto.strip():
            self._contar("La IA no ha devuelto nada. Prueba otra vez con otras palabras.", tg)
            return
        r = self._escribir(formato, nombre or " ".join(tema.split()[:6]), carpeta, texto, por_telegram=tg,
                           generado=True)
        if tg and r.archivo:
            self.enviar_documento(r.archivo, r.texto)
        else:
            self._contar(r.texto, tg)

    def _contar(self, texto: str, tg: bool) -> None:
        self.log(f"archivos: {texto}")
        (self.avisar if tg else self.decir)(texto)

    def _escribir(self, formato: str, nombre: str, carpeta: Path, texto: str, por_telegram: bool,
                  generado: bool = False) -> Respuesta:
        nombre = limpiar_nombre(nombre)
        titulo, cuerpo = separar_titulo(texto, nombre) if generado else (nombre, texto)
        if formato == "txt":
            ruta = sin_pisar(carpeta / f"{nombre}.txt")
            ruta.write_text(texto.strip() + "\n", encoding="utf-8")
        else:
            try:
                ruta_docx = sin_pisar(carpeta / f"{nombre}.docx")
                crear_docx(ruta_docx, titulo, cuerpo)
            except ImportError:
                return Respuesta("Me falta el programa para crear documentos de Word (python-docx).")
            ruta = ruta_docx
            if formato == "pdf":
                pdf = a_pdf(ruta_docx, Path(tempfile.gettempdir()))
                if not pdf:
                    return Respuesta("He creado el Word, pero no he podido convertirlo a PDF.", archivo=str(ruta_docx))
                ruta = sin_pisar(carpeta / f"{nombre}.pdf")
                shutil.move(str(pdf), ruta)
                ruta_docx.unlink(missing_ok=True)
        self.log(f"archivos: creado {ruta}")
        if not por_telegram:
            lanzar(["xdg-open", str(ruta)])
        from ultimos import apuntar
        apuntar(ruta, "documento", abierto=not por_telegram)
        tipo = {"txt": "El archivo de texto", "docx": "El Word", "pdf": "El PDF"}[formato]
        return Respuesta(f"{tipo} {ruta.name} está listo, en {carpeta.name}.", archivo=str(ruta))

    # ---------- órdenes
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion)
        t = re.sub(r"^(por favor|oye|venga)\s+", "", t)

        # Elegir entre varios ("el segundo", "borra el 2")
        if self._pendiente and time.time() - self._pendiente["t"] < 180:
            m = re.match(r"^(?:(?:borra|elimina|manda|mandame|envia|enviame|pasame|mueve|copia|renombra|convierte)\w*\s+)?"
                         r"(?:el |la |al |a la )?(?:numero |opcion )?(\w+)$", t)
            if m and (m.group(1) in NUMEROS or m.group(1).isdigit()):
                n = int(m.group(1)) if m.group(1).isdigit() else NUMEROS[m.group(1)]
                rutas = self._pendiente["rutas"]
                idx = len(rutas) - 1 if n == -1 else n - 1
                if not 0 <= idx < len(rutas):
                    return Respuesta(f"Solo hay {len(rutas)}.")
                pendiente, self._pendiente = self._pendiente, None
                return self._ejecutar(pendiente["accion"], rutas[idx], pendiente)

        # Crear documentos: "crea un pdf/word/archivo de texto ..."
        m = re.search(r"\b(?:crea|creame|haz|hazme|genera|generame|redacta|redactame|escribe|escribeme|prepara|preparame)\w*"
                      r"\s+(?:un |una )?(?:nuevo |nueva )?(?:documento |archivo |fichero )?(?:de |en )?"
                      r"(pdf|word|docx|texto|txt|documento)\b(.*)$", t)
        if m and m.group(1) in ("texto", "txt") and not re.search(r"\b(archivo|fichero|documento) (de )?(texto|txt)\b", t):
            m = None                                   # "escríbeme un texto bonito" es charla, no un archivo
        if m and not re.search(r"\bcarpeta\b", t[:m.start(1)]):
            formato = {"pdf": "pdf", "word": "docx", "docx": "docx", "documento": "docx"}.get(m.group(1), "txt")
            resto = m.group(2).strip(" ,.:")
            texto = None
            mt = re.search(r"\b(?:que (?:diga|ponga|contenga)|con (?:el|este) texto|diciendo|con el contenido)\s*:?\s*(.+)$", resto)
            if mt:
                texto = con_tildes(peticion, mt.group(1)).strip()
                texto = texto[:1].upper() + texto[1:]
                resto = resto[:mt.start()].strip(" ,")
            nombre = None
            mn = re.search(r"\b(?:llamad[oa]|que se llame|con (?:el )?nombre(?: de)?|titulad[oa])\s+(.+?)"
                           r"(?=\s+(?:sobre|acerca de|con|en)\s|$)", resto)
            if mn:
                nombre = con_tildes(peticion, mn.group(1))
                resto = (resto[:mn.start()] + " " + resto[mn.end():]).strip(" ,")
            resto, carpeta = separar_destino(resto)
            carpeta = carpeta or carpeta_usuario("DOCUMENTS")
            tema = re.sub(r"^(?:sobre|acerca de|con|de|para)\s+", "", resto).strip(" ,") or None
            if tema:
                tema = con_tildes(peticion, tema)
            return self._crear_documento(formato, nombre, carpeta, texto, tema, peticion)

        # Crear carpeta
        m = re.search(r"\b(?:crea|creame|haz|hazme|anade|nueva)\w*\s+(?:una\s+)?(?:nueva\s+)?carpeta\s+"
                      r"(?:llamada\s+|que se llame\s+|con (?:el )?nombre(?: de)?\s+|de nombre\s+)?(.+)$", t)
        if m:
            nombre, destino = separar_destino(m.group(1))
            destino = destino or carpeta_usuario("DOCUMENTS")
            nombre = limpiar_nombre(con_tildes(peticion, nombre))
            principales = {carpeta_usuario(c) for c in set(CARPETAS_CONOCIDAS.values())}
            if destino != HOME and destino not in principales and protegida(destino):
                return Respuesta(f"No puedo crear carpetas ahí: {protegida(destino)}.")
            nueva = destino / nombre
            if nueva.exists():
                return Respuesta(f"Ya existe una carpeta {nombre} en {destino.name}.")
            nueva.mkdir(parents=True)
            self.log(f"archivos: carpeta creada {nueva}")
            return Respuesta(f"Carpeta {nombre} creada en {destino.name}.")

        # Convertir a PDF
        m = re.search(r"\b(?:convierte|pasa|transforma|exporta)\w*\s+(?:el |la )?(?:archivo |documento |fichero )?(.+?)"
                      r"\s+(?:a|en) pdf$", t)
        if m:
            r = self._encontrar("pdf", m.group(1), "", None)
            return r if isinstance(r, Respuesta) else self._convertir(r)

        # Renombrar
        m = re.search(r"\b(?:renombra|cambia(?:le)? el nombre (?:a|de))\w*\s+(?:el |la )?(?:archivo |fichero |documento |carpeta )?"
                      r"(.+?)\s+(?:a|como|por)\s+(.+)$", t)
        if m:
            tipo = "carpeta" if re.search(r"\bcarpeta\b", t) else ""
            nuevo = con_tildes(peticion, m.group(2))
            r = self._encontrar("renombrar", m.group(1), tipo, {"nuevo": nuevo})
            return r if isinstance(r, Respuesta) else self._renombrar(r, nuevo)

        # Mover o copiar
        m = re.search(r"\b(mueve|muevelo|copia|copialo|lleva)\w*\s+(?:el |la |los |las )?(" + TIPOS + r")?\s*(.+?)"
                      r"\s+(?:a|al|en|dentro de)\s+(?:la carpeta\s+|el\s+|la\s+)?(.+)$", t)
        if m and (m.group(2) or re.search(r"\b(mueve|copia)", m.group(1))):
            destino = carpeta_destino(m.group(4))
            if destino is None:
                return Respuesta(f"No encuentro la carpeta {m.group(4)}.")
            copiar = m.group(1).startswith("copia")
            r = self._encontrar("copiar" if copiar else "mover", m.group(3), m.group(2) or "", {"destino": str(destino)})
            return r if isinstance(r, Respuesta) else self._mover(r, destino, copiar)

        # Mandar por Telegram
        m = re.search(r"\b(?:mandame|enviame|pasame|manda|envia|pasa)\w*\s+(?:al movil\s+|por telegram\s+)?"
                      r"(el |la |los |las |un |una |mi |mis )?(" + TIPOS + r")\s+(?:de |del |llamad[oa] )?(.+?)"
                      r"(?:\s+(?:al movil|por telegram|a mi movil|al telefono))?$", t)
        if m and not (m.group(2) in ("foto", "imagen") and (m.group(1) or "").strip() in ("un", "una", "")):
            tipo = m.group(2)
            r = self._encontrar("enviar", m.group(3), tipo)
            return r if isinstance(r, Respuesta) else self._enviar(r)

        # Borrar (siempre con confirmación y a la papelera)
        m = re.search(r"^(?:borra|borrar|elimina|eliminar|tira|suprime|manda a la papelera)\w*\s+"
                      r"(?:el |la |los |las |mi |mis )?(" + TIPOS + r")?\s*(?:de |del |llamad[oa] )?(.+)$", t)
        if m and not re.search(NO_SON_ARCHIVOS, t):
            tipo = m.group(1) or ""
            if not tipo:                               # sin decir "archivo" o "carpeta" solo si existe algo así
                if not buscar_en_casa(m.group(2), maximo=1):
                    return None
            r = self._encontrar("borrar", m.group(2), tipo)
            return r if isinstance(r, Respuesta) else self._borrar(r)
        return None
