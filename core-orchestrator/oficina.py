"""
Oficina para Jarvis: abrir archivos por su nombre, hojas de cálculo, presentaciones, planos (DWG/DXF) y PDF.

Órdenes (por voz o Telegram):
  Abrir
    "abre el excel presupuesto" / "abre el plano de la cocina" / "abre el pdf factura luz"
    "abre el último archivo descargado" / "abre el último word" / "¿cuáles son mis últimos documentos?"
  Hojas de cálculo
    "crea un excel de gastos del mes con fecha, concepto e importe"     → la IA diseña la tabla (con totales)
    "añade al excel gastos: 20 euros de gasolina"                      → la IA coloca cada dato en su columna
    "¿cuánto suma la columna importe del excel gastos?" / "resume el excel gastos"
    "en el excel gastos, ¿cuánto gasté en gasolina?" / "haz un gráfico del excel gastos"
  Presentaciones
    "crea una presentación sobre la energía solar"                     → PowerPoint redactado por la IA
  Planos
    "describe el plano casa" / "¿cuántas puertas tiene el plano casa?"  → lee capas, textos y cotas, y lo mira
    "convierte el plano casa a pdf"
    "dibuja un plano de una habitación de 4 por 3 metros con una puerta" → DXF (lo abre LibreCAD y AutoCAD)
  PDF y Word
    "une los pdf factura y contrato" / "convierte la foto ticket a pdf" / "convierte el pdf contrato a word"
    "escanea este documento" (con la cámara, o la foto que acabas de mandar por Telegram)
    "extrae el texto del pdf contrato" / "pasa a texto la foto ticket"   → también si es un escaneo (con la visión)
    "añade al word informe: texto…" / "añade al word informe un apartado sobre los costes"
    "convierte el documento X a word / a excel / a odt / a csv"

Solo toca archivos de tu carpeta personal; nunca sobrescribe: si el nombre existe, crea "nombre (2)".
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from archivos import (NUMEROS, anadir_markdown_docx, buscar_en_casa, limpiar_nombre, separar_destino, sin_pisar)
from herramientas import HOME, carpeta_usuario, corto, lanzar, leer_texto, normalizar
from sistema import Respuesta, con_tildes

TMP = Path(tempfile.gettempdir()) / "jarvis"
LIBRECAD = HOME / ".local" / "bin" / "librecad"          # el portátil original lo tiene aquí (AppImage)
if not LIBRECAD.exists() and shutil.which("librecad"):    # en el disco portátil e instalaciones nuevas: el de apt
    LIBRECAD = Path(shutil.which("librecad"))
DWG2DXF = HOME / ".local" / "bin" / "dwg2dxf"            # LibreDWG compilado en ~/.local

EXT = {
    "excel": (".xlsx", ".xlsm", ".xls", ".ods", ".csv"),
    "word": (".docx", ".doc", ".odt", ".rtf"),
    "pdf": (".pdf",),
    "presentacion": (".pptx", ".ppt", ".odp"),
    "plano": (".dwg", ".dxf"),
    "texto": (".txt", ".md"),
    "foto": (".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".gif"),
    "video": (".mp4", ".mkv", ".avi", ".mov", ".webm"),
    "audio": (".mp3", ".ogg", ".flac", ".m4a", ".wav"),
}
EXT["documento"] = EXT["word"] + EXT["pdf"] + EXT["texto"] + EXT["excel"] + EXT["presentacion"]
EXT["archivo"] = ()                                  # cualquiera
OFIMATICA = EXT["word"] + EXT["pdf"] + EXT["excel"] + EXT["presentacion"] + EXT["plano"] + EXT["texto"]

# palabra dicha → tipo
TIPO_DICHO = [
    (r"hojas? de calculos?|excels?|libros? de excel|calc", "excel"),
    (r"words?|documentos? de word|documentos? de texto", "word"),
    (r"pdfs?", "pdf"),
    (r"presentacion(?:es)?|powerpoints?|power points?|diapositivas", "presentacion"),
    (r"planos?|dwg|dxf|autocad|dibujos? de autocad", "plano"),
    (r"archivos? de texto|txt|notas de texto", "texto"),
    (r"fotos?|imagen(?:es)?|capturas?", "foto"),
    (r"videos?|peliculas?", "video"),
    (r"canciones?|audios?|grabacion(?:es)?", "audio"),
    (r"documentos?", "documento"),
    (r"archivos?|ficheros?", "archivo"),
]
RE_TIPO = "(?:" + "|".join(p for p, _ in TIPO_DICHO) + ")"


def tipo_de(palabra: str) -> str:
    for patron, tipo in TIPO_DICHO:
        if re.fullmatch(patron, palabra.strip()):
            return tipo
    return "archivo"


ARTICULOS = r"(?:el |la |los |las |mi |mis |un |una |este |esta |ese |esa )?"
DE_NOMBRE = r"(?:de |del |de la |llamad[oa] |que se llama |con (?:el )?nombre(?: de)? )?"


def palabras_utiles(texto: str) -> list[str]:
    return [w for w in re.split(r"\s+", texto.strip(" ,.:;¿?¡!")) if w]


def buscar_por_prefijo(texto: str, extensiones: tuple[str, ...], maximo_palabras: int = 5
                       ) -> tuple[list[Path], str, str]:
    """'gastos 20 euros de gasolina' → ([~/Documentos/Gastos.xlsx], 'gastos', '20 euros de gasolina').
    Prueba con las primeras palabras (de más a menos) hasta que alguna coincide con un archivo."""
    palabras = palabras_utiles(texto)
    for k in range(min(len(palabras), maximo_palabras), 0, -1):
        nombre = " ".join(palabras[:k])
        if nombre in ("de", "del", "la", "el"):
            continue
        rutas = [p for p in buscar_en_casa(nombre, carpetas=False, extensiones=extensiones) if p.is_file()]
        if rutas:
            return rutas, nombre, " ".join(palabras[k:])
    return [], "", texto


def recientes(extensiones: tuple[str, ...] = OFIMATICA, carpeta: Path | None = None, n: int = 8,
              dias: int = 120) -> list[Path]:
    """Los archivos más recientes de tu carpeta personal (o de una carpeta)."""
    base = carpeta or HOME
    try:
        r = subprocess.run(["find", str(base), "-maxdepth", "6", "(", "-name", ".*", "-o", "-path", f"{HOME}/snap",
                            "-o", "-path", f"{HOME}/jarvis", "-o", "-path", f"{HOME}/repos", ")", "-prune", "-o",
                            "-type", "f", "-mtime", f"-{dias}", "-printf", "%T@ %p\n"],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    filas = []
    for linea in r.stdout.splitlines():
        t, _, ruta = linea.partition(" ")
        p = Path(ruta)
        if extensiones and p.suffix.lower() not in extensiones:
            continue
        if p.name.startswith("~$") or p.name.startswith(".~lock"):
            continue
        try:
            filas.append((float(t), p))
        except ValueError:
            pass
    filas.sort(key=lambda x: -x[0])
    return [p for _, p in filas[:n]]


def json_de(texto: str) -> dict:
    texto = re.sub(r"(?s)<think>.*?</think>", "", texto or "").strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        m = re.search(r"(?s)\{.*\}", texto)
        if m:
            return json.loads(m.group(0))
        raise ValueError("la IA no ha devuelto JSON")


def hablar_numero(x: float) -> str:
    if abs(x - round(x)) < 0.005:
        return f"{int(round(x)):,}".replace(",", ".")
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# =============================================================== hojas de cálculo

ESTILO_NUM = {"euros": '#,##0.00 "€"', "numero": "#,##0.##", "entero": "0", "porcentaje": "0%",
              "fecha": "DD/MM/YYYY", "hora": "HH:MM"}


def _a_valor(v, tipo: str):
    if v is None or v == "":
        return None
    if tipo in ("euros", "numero", "entero", "porcentaje") and isinstance(v, str):
        s = v.replace("€", "").replace("%", "").strip()
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?|-?\d+,\d+", s):
            s = s.replace(".", "").replace(",", ".")
        try:
            n = float(s)
            if tipo == "porcentaje" and "%" in v:
                n /= 100
            return int(n) if tipo == "entero" else n
        except ValueError:
            return v
    if tipo == "fecha" and isinstance(v, str):
        for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
            try:
                return dt.datetime.strptime(v.strip(), formato)
            except ValueError:
                pass
    return v


def crear_xlsx(ruta: Path, spec: dict) -> None:
    """spec = {"hojas": [{"nombre", "columnas": [{"nombre", "tipo", "formula"?}], "filas": [[...]], "total": bool}]}"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    libro = Workbook()
    libro.remove(libro.active)
    cabecera = PatternFill("solid", fgColor="1F3A5F")
    zebra = PatternFill("solid", fgColor="EEF3F8")
    fina = Side(style="thin", color="C9D3DE")
    for h in (spec.get("hojas") or [])[:6]:
        hoja = libro.create_sheet(re.sub(r"[\[\]:*?/\\]", " ", str(h.get("nombre") or "Hoja"))[:31])
        columnas = [c if isinstance(c, dict) else {"nombre": str(c), "tipo": "texto"} for c in h.get("columnas") or []]
        if not columnas:
            continue
        letras = {normalizar(c["nombre"]): get_column_letter(i + 1) for i, c in enumerate(columnas)}
        for i, c in enumerate(columnas, start=1):
            celda = hoja.cell(row=1, column=i, value=c["nombre"])
            celda.font = Font(bold=True, color="FFFFFF")
            celda.fill = cabecera
            celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        filas = [f for f in (h.get("filas") or []) if isinstance(f, list)][:2000]
        for r, fila in enumerate(filas, start=2):
            for i, c in enumerate(columnas, start=1):
                tipo = c.get("tipo", "texto")
                if c.get("formula"):
                    valor = "=" + re.sub(r"\[([^\]]+)\]", lambda m: f"{letras.get(normalizar(m.group(1)), 'A')}{r}",
                                         str(c["formula"]).lstrip("="))
                else:
                    valor = _a_valor(fila[i - 1] if i - 1 < len(fila) else None, tipo)
                celda = hoja.cell(row=r, column=i, value=valor)
                if tipo in ESTILO_NUM:
                    celda.number_format = ESTILO_NUM[tipo]
                celda.border = Border(bottom=fina)
                if r % 2 == 1:
                    celda.fill = zebra
        ultima = max(1, len(filas) + 1)
        hoja.freeze_panes = "A2"
        hoja.auto_filter.ref = f"A1:{get_column_letter(len(columnas))}{ultima}"
        if h.get("total", True) and any(c.get("tipo") in ("euros", "numero", "entero") for c in columnas):
            poner_total(hoja, columnas_tipos=[c.get("tipo", "texto") for c in columnas], ultima_fila=ultima)
        for i, c in enumerate(columnas, start=1):
            largo = max([len(str(c["nombre"]))] + [len(str(f[i - 1])) for f in filas[:200] if i - 1 < len(f)])
            hoja.column_dimensions[get_column_letter(i)].width = min(48, max(10, largo + 3))
        hoja.row_dimensions[1].height = 22
        if not libro.sheetnames[1:]:                    # tipos y fórmulas, para poder añadir filas luego
            meta = libro.create_sheet("_jarvis")
            meta.append([c["nombre"] for c in columnas])
            meta.append([c.get("tipo", "texto") for c in columnas])
            meta.append([str(c.get("formula") or "") for c in columnas])
            meta.sheet_state = "hidden"
    if not libro.sheetnames:
        libro.create_sheet("Hoja1")
    libro.properties.title = str(spec.get("titulo") or "")
    libro.properties.creator = "Jarvis"
    libro.save(str(ruta))


def poner_total(hoja, columnas_tipos: list[str], ultima_fila: int) -> None:
    from openpyxl.styles import Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    fila = ultima_fila + 1
    hoja.cell(row=fila, column=1, value="TOTAL").font = Font(bold=True)
    for i, tipo in enumerate(columnas_tipos, start=1):
        celda = hoja.cell(row=fila, column=i)
        if tipo in ("euros", "numero", "entero") and i > 1:
            l = get_column_letter(i)
            celda.value = f"=SUM({l}2:{l}{max(2, ultima_fila)})"
            celda.number_format = ESTILO_NUM[tipo]
            celda.font = Font(bold=True)
        celda.fill = PatternFill("solid", fgColor="DCE6F0")
        celda.border = Border(top=Side(style="medium", color="1F3A5F"))


def _evaluar(formula: str, hoja, cache: dict, profundidad: int = 0):
    """Calcula fórmulas sencillas (SUMA, + - * /, referencias) para leer archivos que nadie ha abierto aún."""
    from openpyxl.utils import column_index_from_string, get_column_letter
    if profundidad > 20:
        return None
    f = formula.lstrip("=").upper().replace("SUMA(", "SUM(").replace(";", ",")

    def valor(ref: str):
        ref = ref.replace("$", "")
        if ref in cache:
            return cache[ref]
        v = hoja[ref].value
        if isinstance(v, str) and v.startswith("="):
            v = _evaluar(v, hoja, cache, profundidad + 1)
        cache[ref] = v
        return v

    def rango(m):
        a, b = m.group(1).replace("$", ""), m.group(2).replace("$", "")
        ca, fa = re.match(r"([A-Z]+)(\d+)", a).groups()
        cb, fb = re.match(r"([A-Z]+)(\d+)", b).groups()
        total = 0.0
        for c in range(column_index_from_string(ca), column_index_from_string(cb) + 1):
            for r in range(int(fa), int(fb) + 1):
                v = valor(f"{get_column_letter(c)}{r}")
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    total += v
        return repr(total)

    f = re.sub(r"(?:SUM|AVERAGE|PROMEDIO)\(\s*(\$?[A-Z]+\$?\d+)\s*:\s*(\$?[A-Z]+\$?\d+)\s*\)", rango, f)
    f = re.sub(r"\$?[A-Z]{1,3}\$?\d+", lambda m: repr(valor(m.group(0)) if isinstance(valor(m.group(0)), (int, float))
                                                       else 0), f)
    if not re.fullmatch(r"[\d\s.+\-*/()e]+", f):
        return None
    try:
        return eval(f, {"__builtins__": {}}, {})          # solo números y operadores (comprobado arriba)
    except Exception:
        return None


def leer_tabla(ruta: Path, max_filas: int = 400) -> list[tuple[str, list[list]]]:
    """[(nombre_hoja, filas)] con los valores ya calculados."""
    suf = ruta.suffix.lower()
    if suf == ".csv":
        import csv
        with open(ruta, encoding="utf-8-sig", errors="ignore", newline="") as f:
            muestra = f.read(4096)
            f.seek(0)
            try:
                dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t")
            except csv.Error:
                dialecto = csv.excel
            return [(ruta.stem, [fila for _, fila in zip(range(max_filas), csv.reader(f, dialecto))])]
    origen = ruta
    if suf in (".xls", ".ods"):                       # se pasa a xlsx con LibreOffice
        TMP.mkdir(parents=True, exist_ok=True)
        perfil = Path(tempfile.gettempdir()) / "jarvis_libreoffice"
        subprocess.run(["soffice", f"-env:UserInstallation=file://{perfil}", "--headless", "--convert-to", "xlsx",
                        "--outdir", str(TMP), str(ruta)], capture_output=True, timeout=120)
        origen = TMP / (ruta.stem + ".xlsx")
        if not origen.exists():
            return []
    from openpyxl import load_workbook
    con_formulas = load_workbook(str(origen), data_only=False, read_only=False)
    calculados = load_workbook(str(origen), data_only=True, read_only=False)
    salida = []
    for nombre in con_formulas.sheetnames:
        if nombre == "_jarvis":
            continue
        hf, hv = con_formulas[nombre], calculados[nombre]
        cache: dict = {}
        filas = []
        for r, (fila_f, fila_v) in enumerate(zip(hf.iter_rows(max_row=max_filas), hv.iter_rows(max_row=max_filas))):
            fila = []
            for cf, cv in zip(fila_f, fila_v):
                v = cv.value
                if v is None and isinstance(cf.value, str) and cf.value.startswith("="):
                    v = _evaluar(cf.value, hf, cache)
                if isinstance(v, dt.datetime):
                    v = v.strftime("%d/%m/%Y") if not (v.hour or v.minute) else v.strftime("%d/%m/%Y %H:%M")
                fila.append(v)
            while fila and fila[-1] is None:
                fila.pop()
            filas.append(fila)
        while filas and not filas[-1]:
            filas.pop()
        if filas:
            salida.append((nombre, filas))
    return salida


def es_numero(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def estadisticas(filas: list[list]) -> str:
    """Sumas y medias calculadas aquí (la IA no hace bien las cuentas largas)."""
    if len(filas) < 2:
        return ""
    cab = [str(c) if c is not None else f"col{i + 1}" for i, c in enumerate(filas[0])]
    datos = [f for f in filas[1:] if f and str(f[0]).strip().upper() not in ("TOTAL", "TOTALES", "SUMA")]
    partes = [f"{len(datos)} filas de datos"]
    for i, nombre in enumerate(cab):
        nums = [f[i] for f in datos if i < len(f) and es_numero(f[i])]
        if len(nums) >= 1 and len(nums) >= len(datos) * 0.5:
            partes.append(f"columna «{nombre}»: suma {hablar_numero(sum(nums))}, media "
                          f"{hablar_numero(sum(nums) / len(nums))}, mínimo {hablar_numero(min(nums))}, "
                          f"máximo {hablar_numero(max(nums))}")
    # importe total = cantidad × precio, si la hoja no tiene ya una columna de total o importe
    nc = [normalizar(c) for c in cab]
    i_cant = next((i for i, c in enumerate(nc) if re.search(r"cantidad|unidades|uds|kilos|kg", c)), None)
    i_prec = next((i for i, c in enumerate(nc) if re.search(r"precio|coste|importe unitario|pvp", c)), None)
    if i_cant is not None and i_prec is not None and not any(re.search(r"total|importe$|subtotal", c) for c in nc):
        importe = sum(f[i_cant] * f[i_prec] for f in datos
                      if max(i_cant, i_prec) < len(f) and es_numero(f[i_cant]) and es_numero(f[i_prec]))
        partes.append(f"importe total (cantidad × precio, la cuenta que suele querer la persona): "
                      f"{hablar_numero(importe)}")
    return "; ".join(partes)


def tabla_como_texto(hojas: list[tuple[str, list[list]]], limite: int = 9000) -> str:
    trozos = []
    for nombre, filas in hojas:
        trozos.append(f"## Hoja «{nombre}»\nCálculos exactos: {estadisticas(filas)}")
        for f in filas:
            trozos.append(" | ".join("" if v is None else (hablar_numero(v) if es_numero(v) else str(v)) for v in f))
    return "\n".join(trozos)[:limite]


def anadir_filas_xlsx(ruta: Path, filas_nuevas: list[list]) -> int:
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter
    libro = load_workbook(str(ruta))
    hoja = libro.worksheets[0]
    cab = [c.value for c in hoja[1]]
    meta = {}
    if "_jarvis" in libro.sheetnames:
        m = libro["_jarvis"]
        for i, nombre in enumerate(c.value for c in m[1]):
            meta[normalizar(str(nombre))] = (m.cell(row=2, column=i + 1).value or "texto",
                                             m.cell(row=3, column=i + 1).value or "")
    letras = {normalizar(str(c)): get_column_letter(i + 1) for i, c in enumerate(cab)}
    ultima = hoja.max_row
    while ultima > 1 and all(c.value is None for c in hoja[ultima]):
        ultima -= 1
    total = None
    if str(hoja.cell(row=ultima, column=1).value or "").strip().upper() in ("TOTAL", "TOTALES"):
        total = ultima
        hoja.delete_rows(total)
        ultima -= 1
    base = ultima                                      # la última fila con datos (o la cabecera)
    formatos = [hoja.cell(row=base, column=i + 1).number_format if base > 1 else "General" for i in range(len(cab))]
    formulas = [hoja.cell(row=base, column=i + 1).value if base > 1 else None for i in range(len(cab))]
    tipos = []
    for i, fmt in enumerate(formatos):
        tipo, formula = meta.get(normalizar(str(cab[i])), (None, ""))
        if not tipo:
            tipo = ("euros" if "€" in fmt else "fecha" if "YY" in fmt.upper() else "porcentaje" if "%" in fmt
                    else "numero" if fmt not in ("General", "@") else "texto")
        tipos.append(tipo)
        if tipo in ESTILO_NUM:
            formatos[i] = ESTILO_NUM[tipo]
        if formula and not (isinstance(formulas[i], str) and formulas[i].startswith("=")):
            formulas[i] = ("plantilla", formula)
    for fila in filas_nuevas:
        ultima += 1
        for i in range(len(cab)):
            f_ant = formulas[i]
            if isinstance(f_ant, tuple):                  # fórmula de la plantilla: [Cantidad]*[Precio]
                valor = "=" + re.sub(r"\[([^\]]+)\]", lambda m: f"{letras.get(normalizar(m.group(1)), 'A')}{ultima}",
                                     f_ant[1].lstrip("="))
            elif isinstance(f_ant, str) and f_ant.startswith("="):   # se copia la fórmula de la última fila
                valor = re.sub(r"(\$?[A-Z]{1,3})" + str(base) + r"\b", lambda m: m.group(1) + str(ultima), f_ant)
            else:
                valor = _a_valor(fila[i] if i < len(fila) else None, tipos[i])
                if tipos[i] == "texto" and isinstance(valor, str):
                    n = _a_valor(valor, "numero")
                    valor = n if es_numero(n) else valor
            celda = hoja.cell(row=ultima, column=i + 1, value=valor)
            celda.number_format = formatos[i]
    if total is not None:
        poner_total(hoja, columnas_tipos=tipos, ultima_fila=ultima)
    if hoja.auto_filter.ref:
        hoja.auto_filter.ref = f"A1:{get_column_letter(len(cab))}{ultima}"
    libro.save(str(ruta))
    return len(filas_nuevas)


def grafico_xlsx(ruta: Path, circular: bool = False) -> str:
    """Añade una hoja «Gráfico» con un resumen por la primera columna de texto y la primera numérica."""
    from openpyxl import load_workbook
    from openpyxl.chart import BarChart, PieChart, Reference
    hojas = leer_tabla(ruta, max_filas=3000)
    if not hojas:
        raise ValueError("vacío")
    nombre_hoja, filas = hojas[0]
    cab = [str(c) if c is not None else "" for c in filas[0]]
    datos = [f for f in filas[1:] if f and str(f[0]).strip().upper() not in ("TOTAL", "TOTALES")]
    numericas = [i for i in range(len(cab)) if sum(1 for f in datos if i < len(f) and es_numero(f[i]))
                 >= max(1, len(datos) * 0.6)]
    preferidas = [i for i in numericas if re.search(r"importe|total|euros|coste|gasto|precio|valor|venta|cantidad|"
                                                     r"horas|puntos", normalizar(cab[i]))]
    col_num = (preferidas or numericas or [None])[0]
    if preferidas and len(preferidas) > 1:            # "Total" o "Importe" antes que "Precio" o "Cantidad"
        col_num = next((i for i in preferidas if re.search(r"importe|total|gasto|venta|valor", normalizar(cab[i]))),
                       preferidas[0])
    if col_num is None:
        raise ValueError("no hay columnas con números")
    col_txt = next((i for i in range(len(cab)) if i != col_num and sum(
        1 for f in datos if i < len(f) and isinstance(f[i], str) and not re.match(r"\d{2}/\d{2}/\d{4}", f[i]))
        >= len(datos) * 0.6), None)
    if col_txt is None:
        col_txt = 0
    grupos: dict[str, float] = {}
    for f in datos:
        if col_num < len(f) and es_numero(f[col_num]):
            clave = str(f[col_txt] if col_txt < len(f) and f[col_txt] is not None else "—")[:30]
            grupos[clave] = grupos.get(clave, 0) + f[col_num]
    orden = sorted(grupos.items(), key=lambda x: -x[1])[:20]
    libro = load_workbook(str(ruta))
    if "Gráfico" in libro.sheetnames:
        del libro["Gráfico"]
    hoja = libro.create_sheet("Gráfico")
    hoja.append([cab[col_txt] or "Concepto", cab[col_num] or "Valor"])
    for k, v in orden:
        hoja.append([k, round(v, 2)])
    grafico = PieChart() if circular else BarChart()
    grafico.title = f"{cab[col_num]} por {cab[col_txt]}".strip()
    datos_ref = Reference(hoja, min_col=2, min_row=1, max_row=len(orden) + 1)
    etiquetas = Reference(hoja, min_col=1, min_row=2, max_row=len(orden) + 1)
    grafico.add_data(datos_ref, titles_from_data=True)
    grafico.set_categories(etiquetas)
    grafico.width, grafico.height = 22, 12
    hoja.add_chart(grafico, f"A{len(orden) + 3}")
    hoja.column_dimensions["A"].width = 28
    libro.save(str(ruta))
    return f"{cab[col_num]} por {cab[col_txt]}"


# =============================================================== presentaciones

def crear_pptx(ruta: Path, spec: dict) -> int:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Emu, Pt

    azul, acento, claro = RGBColor(0x1F, 0x3A, 0x5F), RGBColor(0xE8, 0x9F, 0x2B), RGBColor(0xF5, 0xF7, 0xFA)
    p = Presentation()
    p.slide_width, p.slide_height = Emu(12192000), Emu(6858000)          # 16:9
    W, H = p.slide_width, p.slide_height
    vacia = p.slide_layouts[6]

    def caja(diapo, x, y, w, h, texto, tam, color, negrita=False):
        tb = diapo.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        tf.text = texto
        for par in tf.paragraphs:
            for run in par.runs:
                run.font.size, run.font.bold, run.font.color.rgb, run.font.name = Pt(tam), negrita, color, "Calibri"
        return tf

    def fondo(diapo, color):
        f = diapo.background.fill
        f.solid()
        f.fore_color.rgb = color

    portada = p.slides.add_slide(vacia)
    fondo(portada, azul)
    barra = portada.shapes.add_shape(MSO_SHAPE.RECTANGLE, int(W * 0.08), int(H * 0.60), int(W * 0.12), Emu(60000))
    barra.fill.solid()
    barra.fill.fore_color.rgb = acento
    barra.line.fill.background()
    caja(portada, int(W * 0.08), int(H * 0.28), int(W * 0.84), int(H * 0.3), str(spec.get("titulo") or "Presentación"),
         44, RGBColor(0xFF, 0xFF, 0xFF), True)
    if spec.get("subtitulo"):
        caja(portada, int(W * 0.08), int(H * 0.64), int(W * 0.84), int(H * 0.2), str(spec["subtitulo"]), 20,
             RGBColor(0xD6, 0xE0, 0xEA))
    diapos = [d for d in spec.get("diapositivas") or [] if isinstance(d, dict)][:20]
    for n, d in enumerate(diapos, start=2):
        s = p.slides.add_slide(vacia)
        fondo(s, claro)
        franja = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Emu(140000), H)
        franja.fill.solid()
        franja.fill.fore_color.rgb = acento
        franja.line.fill.background()
        caja(s, int(W * 0.06), int(H * 0.06), int(W * 0.88), int(H * 0.16), str(d.get("titulo") or ""), 32, azul, True)
        puntos = [str(x) for x in (d.get("puntos") or []) if str(x).strip()][:7]
        if puntos:
            tf = s.shapes.add_textbox(int(W * 0.07), int(H * 0.26), int(W * 0.86), int(H * 0.64)).text_frame
            tf.word_wrap = True
            for i, punto in enumerate(puntos):
                par = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                par.text = "•  " + punto
                par.space_after = Pt(12)
                for run in par.runs:
                    run.font.size = Pt(22 if len(puntos) <= 5 else 18)
                    run.font.color.rgb = RGBColor(0x33, 0x3D, 0x4A)
                    run.font.name = "Calibri"
        caja(s, int(W * 0.88), int(H * 0.92), int(W * 0.1), int(H * 0.06), str(n), 12, RGBColor(0x8A, 0x96, 0xA3))
        if d.get("notas"):
            s.notes_slide.notes_text_frame.text = str(d["notas"])
    p.core_properties.author = "Jarvis"
    p.core_properties.title = str(spec.get("titulo") or "")
    p.save(str(ruta))
    return len(diapos) + 1


# =============================================================== planos

UNIDADES_DXF = {0: "sin unidades", 1: "pulgadas", 2: "pies", 4: "milímetros", 5: "centímetros", 6: "metros"}


def dwg_a_dxf(ruta: Path) -> Path | None:
    """LibreCAD abre los DWG en pantalla; para leerlos por dentro los pasamos a DXF con LibreDWG."""
    conversor = str(DWG2DXF) if DWG2DXF.exists() else shutil.which("dwg2dxf")
    if not conversor:
        return None
    TMP.mkdir(parents=True, exist_ok=True)
    destino = TMP / f"{ruta.stem}_{int(time.time())}.dxf"
    try:
        subprocess.run([conversor, "-y", "-o", str(destino), str(ruta)], capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return destino if destino.exists() and destino.stat().st_size > 0 else None


def plano_a_pdf_librecad(ruta: Path, carpeta: Path) -> Path | None:
    if not LIBRECAD.exists() or ruta.suffix.lower() != ".dxf":     # su línea de órdenes solo acepta DXF
        return None
    destino = carpeta / (ruta.stem + ".pdf")
    try:
        subprocess.run([str(LIBRECAD), "dxf2pdf", "-a", "-k", "-o", str(destino), str(ruta)],
                       capture_output=True, timeout=180, env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return destino if destino.exists() and destino.stat().st_size > 0 else None


def resumen_dxf(ruta: Path) -> tuple[str, object]:
    import ezdxf
    from ezdxf import bbox
    doc = ezdxf.readfile(str(ruta))
    msp = doc.modelspace()
    unidades = UNIDADES_DXF.get(doc.header.get("$INSUNITS", 0), "sin unidades")
    tipos: dict[str, int] = {}
    capas: dict[str, int] = {}
    bloques: dict[str, int] = {}
    textos, cotas = [], []
    for e in msp:
        t = e.dxftype()
        tipos[t] = tipos.get(t, 0) + 1
        capas[e.dxf.layer] = capas.get(e.dxf.layer, 0) + 1
        if t == "INSERT":
            bloques[e.dxf.name] = bloques.get(e.dxf.name, 0) + 1
        elif t == "TEXT" and len(textos) < 80:
            textos.append(e.dxf.text.strip())
        elif t == "MTEXT" and len(textos) < 80:
            textos.append(e.plain_text().strip())
        elif t == "DIMENSION" and len(cotas) < 60:
            try:
                cotas.append(hablar_numero(e.get_measurement()) if not isinstance(e.get_measurement(), tuple)
                             else str(e.get_measurement()))
            except Exception:
                pass
    try:
        caja = bbox.extents(msp, fast=True)
        tam = f"{hablar_numero(caja.size.x)} por {hablar_numero(caja.size.y)} {unidades}" if caja.has_data else "?"
    except Exception:
        tam = "?"
    partes = [f"Plano {ruta.name} (versión {doc.dxfversion}), unidades: {unidades}, tamaño total del dibujo: {tam}.",
              "Elementos: " + ", ".join(f"{n} {t}" for t, n in sorted(tipos.items(), key=lambda x: -x[1])[:12]) + ".",
              "Capas: " + ", ".join(f"{c} ({n})" for c, n in sorted(capas.items(), key=lambda x: -x[1])[:20]) + "."]
    if bloques:
        partes.append("Bloques insertados (puertas, ventanas, muebles…): " +
                      ", ".join(f"{b} ×{n}" for b, n in sorted(bloques.items(), key=lambda x: -x[1])[:25]) + ".")
    if textos:
        partes.append("Textos del plano: " + " · ".join(t for t in textos if t)[:1500])
    if cotas:
        partes.append("Cotas: " + ", ".join(cotas))
    return "\n".join(partes), doc


def dxf_a_imagen(doc, destino: Path, pdf: bool = False) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    fig = plt.figure(figsize=(16.5, 11.7) if pdf else (12, 9))
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    ax.set_axis_off()
    config = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.BLACK)
    Frontend(RenderContext(doc), MatplotlibBackend(ax), config=config).draw_layout(doc.modelspace(), finalize=True)
    fig.savefig(str(destino), dpi=150 if pdf else 110, facecolor="white")
    plt.close(fig)
    return destino


COLORES_CAPA = {"MUROS": 7, "TABIQUES": 8, "PUERTAS": 3, "VENTANAS": 5, "MOBILIARIO": 30, "COTAS": 1, "TEXTOS": 2,
                "EJES": 9}


def crear_dxf(ruta: Path, spec: dict) -> int:
    import ezdxf
    from ezdxf.enums import TextEntityAlignment
    doc = ezdxf.new("R2010", setup=True, units=6)          # metros
    doc.header["$MEASUREMENT"] = 1
    msp = doc.modelspace()
    estilo_cota = doc.dimstyles.get("EZ_M_100_H25_CM") if "EZ_M_100_H25_CM" in doc.dimstyles else None

    def capa(nombre: str) -> str:
        nombre = re.sub(r"[<>/\\\":;?*|=`]", "_", (nombre or "0").upper())[:30] or "0"
        if nombre not in doc.layers:
            doc.layers.add(nombre, color=COLORES_CAPA.get(nombre, 7))
        return nombre

    def p(v) -> tuple[float, float]:
        return float(v[0]), float(v[1])

    n = 0
    for e in (spec.get("elementos") or [])[:600]:
        if not isinstance(e, dict):
            continue
        t = e.get("tipo")
        attrs = {"layer": capa(e.get("capa", "0"))}
        try:
            if t == "linea":
                msp.add_line(p(e["de"]), p(e["a"]), dxfattribs=attrs)
            elif t == "polilinea":
                msp.add_lwpolyline([p(q) for q in e["puntos"]], close=bool(e.get("cerrada")), dxfattribs=attrs)
            elif t == "rectangulo":
                x, y, w, h = (float(e[k]) for k in ("x", "y", "ancho", "alto"))
                msp.add_lwpolyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=True, dxfattribs=attrs)
            elif t == "circulo":
                msp.add_circle(p(e["centro"]), float(e["radio"]), dxfattribs=attrs)
            elif t == "arco":
                msp.add_arc(p(e["centro"]), float(e["radio"]), float(e.get("inicio", 0)), float(e.get("fin", 90)),
                            dxfattribs=attrs)
            elif t == "texto":
                txt = msp.add_text(str(e.get("texto", "")), height=float(e.get("altura", 0.2)), dxfattribs=attrs)
                txt.set_placement(p(e["pos"]), align=TextEntityAlignment.MIDDLE_CENTER)
            elif t == "cota":
                a, b = p(e["de"]), p(e["a"])
                d = float(e.get("desplazamiento", 0.5))
                horizontal = abs(b[0] - a[0]) >= abs(b[1] - a[1])
                base = ((a[0] + b[0]) / 2, max(a[1], b[1]) + d) if horizontal else (max(a[0], b[0]) + d, (a[1] + b[1]) / 2)
                kw = {"dimstyle": "EZ_M_100_H25_CM"} if estilo_cota else {}
                dim = msp.add_linear_dim(base=base, p1=a, p2=b, angle=0 if horizontal else 90,
                                         dxfattribs={"layer": capa("COTAS")}, **kw)
                dim.render()
            elif t == "estancia":                         # nombre y superficie (calculada aquí, no por la IA)
                x, y, w, h = (float(e[k]) for k in ("x", "y", "ancho", "alto"))
                altura = float(e.get("altura", max(0.15, min(w, h) / 14)))
                nombre = str(e.get("nombre") or "").upper()
                cx, cy = x + w / 2, y + h / 2
                for texto, dy in ((nombre, altura * 0.8), (f"{hablar_numero(w * h)} m²", -altura * 0.8)):
                    if texto.strip():
                        txt = msp.add_text(texto, height=altura, dxfattribs={"layer": capa("TEXTOS")})
                        txt.set_placement((cx, cy + dy), align=TextEntityAlignment.MIDDLE_CENTER)
            elif t == "ventana":                          # tres líneas paralelas en el hueco del muro
                import math
                a, b = p(e["de"]), p(e["a"])
                grueso = float(e.get("grueso", 0.25))
                largo = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
                nx, ny = -(b[1] - a[1]) / largo, (b[0] - a[0]) / largo
                at = {"layer": capa("VENTANAS")}
                for f in (-0.5, 0, 0.5):
                    d = f * grueso
                    msp.add_line((a[0] + nx * d, a[1] + ny * d), (b[0] + nx * d, b[1] + ny * d), dxfattribs=at)
                for q in (a, b):
                    msp.add_line((q[0] - nx * grueso / 2, q[1] - ny * grueso / 2),
                                 (q[0] + nx * grueso / 2, q[1] + ny * grueso / 2), dxfattribs=at)
            elif t == "puerta":                           # hoja + arco de apertura
                x, y = p(e["pos"])
                w = float(e.get("ancho", 0.8))
                ang = float(e.get("angulo", 0))
                import math
                r = math.radians(ang)
                fin = (x + w * math.cos(r), y + w * math.sin(r))
                hoja_ = (x + w * math.cos(r + math.pi / 2), y + w * math.sin(r + math.pi / 2))
                at = {"layer": capa("PUERTAS")}
                msp.add_line((x, y), hoja_, dxfattribs=at)
                msp.add_arc((x, y), w, ang, ang + 90, dxfattribs=at)
                msp.add_line((x, y), fin, dxfattribs={**at, "linetype": "DASHED"} if "DASHED" in doc.linetypes else at)
            else:
                continue
            n += 1
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    if spec.get("titulo"):
        try:
            from ezdxf import bbox
            caja = bbox.extents(msp)
            if caja.has_data:
                txt = msp.add_text(str(spec["titulo"]), height=max(0.25, caja.size.x / 30),
                                   dxfattribs={"layer": capa("TEXTOS")})
                txt.set_placement((caja.extmin.x, caja.extmin.y - max(0.6, caja.size.y / 12)))
        except Exception:
            pass
    doc.saveas(str(ruta))
    return n


# =============================================================== PDF

def unir_pdfs(rutas: list[Path], destino: Path) -> int:
    from pypdf import PdfWriter
    escritor = PdfWriter()
    for r in rutas:
        escritor.append(str(r))
    with open(destino, "wb") as f:
        escritor.write(f)
    return len(escritor.pages)


def imagenes_a_pdf(imagenes: list[Path], destino: Path) -> None:
    from PIL import Image, ImageOps
    paginas = []
    for im in imagenes:
        img = ImageOps.exif_transpose(Image.open(im)).convert("RGB")
        img.thumbnail((2480, 3508))                     # A4 a 300 ppp como máximo
        paginas.append(img)
    paginas[0].save(str(destino), "PDF", resolution=200.0, save_all=True, append_images=paginas[1:])


def paginas_como_imagen(pdf: Path, n: int = 3, dpi: int = 110) -> list[Path]:
    TMP.mkdir(parents=True, exist_ok=True)
    base = TMP / f"pag_{int(time.time())}"
    subprocess.run(["pdftoppm", "-r", str(dpi), "-jpeg", "-l", str(n), str(pdf), str(base)],
                   capture_output=True, timeout=120)
    return sorted(TMP.glob(base.name + "*.jpg"))


# =============================================================== el módulo

INSTR_EXCEL = """Diseñas hojas de cálculo para Jarvis. Hoy es {hoy}. Devuelve SOLO JSON:
{{"titulo": "título corto", "hojas": [{{"nombre": "Nombre de la hoja", "columnas": [{{"nombre": "Fecha", "tipo": "fecha"}}, \
{{"nombre": "Concepto", "tipo": "texto"}}, {{"nombre": "Importe", "tipo": "euros"}}], "filas": [["2026-10-19", "Gasolina", 45.5]], \
"total": true}}]}}
Tipos de columna: texto, numero, entero, euros, porcentaje (0.21 = 21 %), fecha (AAAA-MM-DD), hora.
Una columna calculada lleva "formula" con los nombres de otras columnas entre corchetes, p. ej. \
{{"nombre": "Total", "tipo": "euros", "formula": "[Cantidad]*[Precio]"}} (sus celdas en "filas" van vacías: null).
Reglas: usa exactamente los datos y columnas que diga el usuario. Si solo nombra columnas ("con concepto, cantidad y \
precio") o pide una plantilla o un control (gastos, inventario, horarios…) sin datos, "filas": [] (NUNCA inventes \
filas de ejemplo): pon columnas útiles y 0 filas, salvo que el contenido sea conocido (tabla de \
multiplicar, días del mes, provincias, un presupuesto de ejemplo que pida…), que sí rellenas. "total": true solo si \
sumar las columnas numéricas tiene sentido. Nombres en español de España, sin abreviaturas raras."""

INSTR_FILAS = """Añades filas a una hoja de cálculo. Columnas: {cab}. Últimas filas (para imitar el formato): {ultimas}.
Hoy es {hoy}. Convierte lo que dice el usuario en filas (una por cada cosa). Fechas AAAA-MM-DD ("hoy", "ayer" → \
la fecha real). Números sin símbolos ni unidades (20 euros → 20; "1.20" es uno con veinte). Si hay columna de cantidad o unidades y no se \
dice, pon 1. Deja null lo que no se sepa y las columnas calculadas o de total. Devuelve SOLO JSON: {{"filas": [[...], ...]}} con tantos valores como columnas, en orden."""

INSTR_PPTX = """Preparas presentaciones para Jarvis en español de España. Devuelve SOLO JSON:
{"titulo": "...", "subtitulo": "...", "diapositivas": [{"titulo": "...", "puntos": ["frase corta", "..."], \
"notas": "lo que diría el ponente"}]}
Entre 6 y 10 diapositivas (o las que pida el usuario), 3-5 puntos de máximo 14 palabras cada uno, con datos \
concretos y una diapositiva final de conclusiones. Sin markdown ni emojis."""

INSTR_DXF = """Dibujas planos técnicos sencillos para Jarvis, en METROS, origen (0,0) abajo a la izquierda, eje Y hacia \
arriba. Devuelve SOLO JSON: {"titulo": "...", "elementos": [...]}. Tipos de elemento:
{"tipo":"rectangulo","x":0,"y":0,"ancho":4,"alto":3,"capa":"MUROS"}
{"tipo":"linea","de":[0,0],"a":[4,0],"capa":"MUROS"}
{"tipo":"polilinea","puntos":[[0,0],[4,0],[4,3]],"cerrada":true,"capa":"MUROS"}
{"tipo":"circulo","centro":[2,1.5],"radio":0.4,"capa":"MOBILIARIO"}
{"tipo":"arco","centro":[0,0],"radio":1,"inicio":0,"fin":90,"capa":"0"}
{"tipo":"puerta","pos":[1,0],"ancho":0.8,"angulo":0}   (bisagra en pos; angulo = dirección de la hoja cerrada)
{"tipo":"ventana","de":[1.5,3],"a":[2.7,3],"grueso":0.25}   (sobre el eje del muro; Jarvis dibuja el símbolo)
{"tipo":"estancia","nombre":"Dormitorio","x":0,"y":0,"ancho":3,"alto":3.5}   (el interior libre de la estancia: \
Jarvis escribe el nombre y calcula él los m²; NO pongas tú la superficie en ningún texto)
{"tipo":"texto","pos":[2,1.5],"texto":"Norte","altura":0.2,"capa":"TEXTOS"}
{"tipo":"cota","de":[0,0],"a":[4,0],"desplazamiento":-0.6}
Capas: MUROS, TABIQUES, PUERTAS, VENTANAS, MOBILIARIO, COTAS, TEXTOS. Muros exteriores de 0.25 m de grueso \
(dos rectángulos, exterior e interior) y tabiques de 0.10 si es una vivienda. Pon cotas generales y el nombre y \
superficie de cada estancia (con el tipo estancia). Dibuja TODAS las puertas y ventanas que pida el usuario. \
Medidas realistas (puertas 0.8, ventanas 1.2…). Máximo 250 elementos."""

INSTR_PLANO = ("Eres Jarvis y explicas planos técnicos a alguien sin formación técnica, en español de España. "
               "Te doy los datos extraídos del archivo y, si hay, la imagen del plano. Responde a lo que pregunta "
               "usando los datos (los textos y cotas del plano son fiables; no inventes medidas). {formato}")

INSTR_TABLA = ("Eres Jarvis. Respondes preguntas sobre una hoja de cálculo en español de España. Las sumas y medias "
               "de «Cálculos exactos» son correctas: úsalas en vez de sumar tú. Si hay que filtrar (por ejemplo, solo "
               "la gasolina), suma con cuidado las filas que toquen. {formato}")

FORMATO_VOZ = "Máximo tres frases, sin listas ni símbolos: se leerá en voz alta. Los números, como se dicen."
FORMATO_TG = "Puede ser algo más largo y con alguna lista corta: se leerá en el móvil."


class Oficina:
    def __init__(self, cerebro, decir: Callable[..., None], confirmar: Callable[[str], bool], log=print, ui=None,
                 enviar_documento: Callable[[str, str], bool] | None = None,
                 es_telegram: Callable[[], bool] | None = None, avisar: Callable[[str], None] | None = None,
                 camara=None, vision=None, redactar: Callable[[str], str] | None = None):
        self.cerebro = cerebro
        self.decir = decir
        self.confirmar = confirmar
        self.log = log
        self.ui = ui
        self.enviar_documento = enviar_documento or (lambda ruta, pie: False)
        self.es_telegram = es_telegram or (lambda: False)
        self.avisar = avisar or (lambda t: None)
        self.camara = camara
        self.vision = vision
        self._creando = 0                  # trabajos en segundo plano (hojas, presentaciones, planos…)
        self.redactar = redactar
        self._pendiente: dict | None = None
        self.ultimo: Path | None = None                    # el último archivo con el que hemos trabajado

    # ---------- utilidades
    @property
    def ia(self) -> bool:
        return bool(self.cerebro and getattr(self.cerebro, "activo", False))

    def _ia_json(self, sistema: str, usuario: str, max_tokens: int = 3000, timeout: float = 90) -> dict:
        texto = self.cerebro.chat([{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
                                  formato_json=True, max_tokens=max_tokens, temperatura=0.4, timeout=timeout)
        return json_de(texto)

    def _ia_texto(self, sistema: str, usuario: str, max_tokens: int = 600) -> str:
        return self.cerebro.chat([{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
                                 max_tokens=max_tokens, temperatura=0.3, timeout=60).strip()

    def _formato(self) -> str:
        return FORMATO_TG if self.es_telegram() else FORMATO_VOZ

    def _contar(self, texto: str, tg: bool, archivo: Path | None = None) -> None:
        self.log(f"oficina: {texto}")
        if tg:
            if archivo and archivo.exists():
                if len(texto) > 900:                       # el pie de un archivo en Telegram es corto
                    self.avisar(texto)
                    texto = archivo.name
                self.enviar_documento(str(archivo), texto)
            else:
                self.avisar(texto)
        else:
            self.decir(texto)

    def _en_segundo_plano(self, trabajo: Callable[[], tuple[str, Path | None]], aviso: str) -> Respuesta:
        tg = self.es_telegram()

        def hilo():
            try:
                texto, archivo = trabajo()
            except Exception as e:
                self.log(f"oficina: error {e!r}")
                texto, archivo = f"No he podido terminarlo ({type(e).__name__}). Prueba otra vez.", None
            finally:
                self._creando -= 1
            if archivo and not tg:
                self.abrir_ruta(archivo, silencioso=True)
            self._contar(texto, tg, archivo)
            if archivo:
                from ultimos import apuntar
                apuntar(archivo, abierto=not tg)
        self._creando += 1
        threading.Thread(target=hilo, daemon=True).start()
        return Respuesta(aviso)

    def _elegir(self, accion: str, rutas: list[Path], **datos) -> Respuesta:
        self._pendiente = {"accion": accion, "rutas": rutas, "t": time.time(), **datos}
        items = [corto(p) for p in rutas]
        if self.ui:
            self.ui.enviar(tipo="resultados", titulo="¿Cuál?", items=items)
        texto = f"Hay {len(rutas)} que encajan. ¿Cuál? Dime el primero, el segundo…"
        if self.es_telegram():
            texto += "\n" + "\n".join(f"{i + 1}. {x}" for i, x in enumerate(items))
        else:
            texto += " Te los enseño en la pantalla."
        return Respuesta(texto)

    def _uno(self, rutas: list[Path], nombre: str, accion: str, **datos) -> Path | Respuesta:
        if not rutas and self._creando:
            # «crea un excel de compras» y enseguida «añade al excel compras…»: todavía se está haciendo; se espera
            self.log(f"oficina: espero a que termine lo que estoy creando para buscar «{nombre}»")
            fin = time.time() + 120
            while self._creando and time.time() < fin:
                time.sleep(1)
            extensiones = tuple({e for grupo in EXT.values() for e in grupo})
            rutas = [p for p in buscar_en_casa(nombre, carpetas=False, extensiones=extensiones) if p.is_file()]
        if not rutas:
            return Respuesta(f"No encuentro ningún archivo que se llame {nombre}.")
        exactas = [p for p in rutas if normalizar(p.stem) == normalizar(nombre)]
        if len(exactas) == 1 or len(rutas) == 1:
            return (exactas or rutas)[0]
        if len(exactas) > 1:
            rutas = exactas
        return self._elegir(accion, rutas, **datos)

    def _resolver(self, accion: str, ruta: Path, d: dict) -> Respuesta:
        self.ultimo = ruta
        metodo = getattr(self, "_hacer_" + accion)
        return metodo(ruta, **{k: v for k, v in d.items() if k not in ("accion", "rutas", "t")})

    def _buscar(self, accion: str, texto: str, tipo: str, **datos) -> Path | Respuesta:
        texto = re.sub(r"^(?:el |la |los |las |mi |mis |de |del )+", "", texto.strip())
        if re.fullmatch(r"(ese|eso|este|esto|el mismo|lo|la|el ultimo|la ultima|ultimo|ultima)", texto) and self.ultimo:
            return self.ultimo
        rutas = [p for p in buscar_en_casa(texto, carpetas=False, extensiones=EXT.get(tipo, ())) if p.is_file()]
        return self._uno(rutas, texto, accion, **datos)

    # ---------- abrir
    def abrir_ruta(self, ruta: Path, silencioso: bool = False) -> Respuesta:
        self.ultimo = ruta
        if self.es_telegram() and not silencioso:          # desde el móvil: te lo manda (y lo abre en el portátil)
            abierto = self._abrir_en_pantalla(ruta)
            return Respuesta(f"Aquí tienes {ruta.name}." + (" También te lo he abierto en el portátil." if abierto
                                                                 else ""), archivo=str(ruta))
        if not self._abrir_en_pantalla(ruta):
            return Respuesta(f"No tengo ningún programa para abrir {ruta.name}.")
        return Respuesta(f"Abriendo {ruta.name}.")

    def _abrir_en_pantalla(self, ruta: Path) -> bool:
        suf = ruta.suffix.lower()
        try:
            if suf in (".dwg", ".dxf"):
                if LIBRECAD.exists():
                    lanzar([str(LIBRECAD), str(ruta)])
                    return True
                pdf = plano_a_pdf(ruta, TMP)
                if pdf:
                    lanzar(["xdg-open", str(pdf)])
                    return True
                return False
            lanzar(["xdg-open", str(ruta)])
            return True
        except OSError:
            return False

    def _hacer_abrir(self, ruta: Path) -> Respuesta:
        return self.abrir_ruta(ruta)

    # ---------- hojas de cálculo
    def _crear_excel(self, tema: str, nombre: str | None, carpeta: Path, peticion: str) -> Respuesta:
        if not self.ia:
            ruta = sin_pisar(carpeta / f"{limpiar_nombre(nombre or tema or 'Hoja de cálculo')}.xlsx")
            crear_xlsx(ruta, {"hojas": [{"nombre": "Hoja1", "columnas": [{"nombre": "Columna A"}], "filas": []}]})
            self.abrir_ruta(ruta, silencioso=True)
            return Respuesta(f"Sin la IA solo puedo crearla vacía: {ruta.name}, en {carpeta.name}.", archivo=str(ruta))

        def trabajo():
            spec = self._ia_json(INSTR_EXCEL.format(hoy=dt.date.today().isoformat()), peticion, max_tokens=6000)
            titulo = nombre or spec.get("titulo") or tema or "Hoja de cálculo"
            ruta = sin_pisar(carpeta / f"{limpiar_nombre(titulo)}.xlsx")
            crear_xlsx(ruta, spec)
            self.ultimo = ruta
            hojas = spec.get("hojas") or []
            cols = ", ".join(str(c.get("nombre") if isinstance(c, dict) else c) for c in (hojas[0].get("columnas") or [])[:8]) if hojas else ""
            filas = sum(len(h.get("filas") or []) for h in hojas)
            return (f"Hoja de cálculo {ruta.name} lista, en {carpeta.name}. Columnas: {cols}" +
                    (f"; con {filas} filas." if filas else ". Está vacía para que la rellenes; dime añade al excel "
                     f"{ruta.stem}, y los datos, y lo apunto yo.")), ruta
        return self._en_segundo_plano(trabajo, "Diseño la hoja de cálculo; en unos segundos la tienes.")

    def _hacer_anadir_excel(self, ruta: Path, datos: str) -> Respuesta:
        if ruta.suffix.lower() not in (".xlsx", ".xlsm", ".csv"):
            return Respuesta(f"Solo sé añadir filas a archivos xlsx o csv, y {ruta.name} es {ruta.suffix}. "
                             "Dime convierte el archivo a excel y luego lo añado.")
        if not datos.strip():
            return Respuesta("¿Qué quieres que añada? Dime por ejemplo: añade al excel gastos, 20 euros de gasolina.")
        hojas = leer_tabla(ruta, max_filas=5000)
        cab = [str(c) for c in hojas[0][1][0]] if hojas and hojas[0][1] else []
        if not cab:
            return Respuesta(f"{ruta.name} no tiene cabeceras: no sé en qué columnas poner cada cosa.")
        # «1,20» (coma decimal española, sin espacio) es un solo número: así no se parte en «1» y «20»
        datos = re.sub(r"(?<=\d),(?=\d)", ".", datos)
        if self.ia:
            ultimas = [f for f in hojas[0][1][1:] if f and str(f[0]).upper() != "TOTAL"][-3:]
            spec = self._ia_json(INSTR_FILAS.format(cab=json.dumps(cab, ensure_ascii=False), hoy=dt.date.today(),
                                                    ultimas=json.dumps(ultimas, ensure_ascii=False, default=str)),
                                 datos, max_tokens=1500, timeout=45)
            filas = [f for f in spec.get("filas") or [] if isinstance(f, list)]
        else:
            filas = [[x.strip() for x in re.split(r"[;,]", datos)]]
        if not filas:
            return Respuesta("No he entendido qué añadir.")
        if ruta.suffix.lower() == ".csv":
            import csv
            with open(ruta, "a", encoding="utf-8", newline="") as f:
                csv.writer(f).writerows([["" if v is None else v for v in fila] for fila in filas])
        else:
            try:
                anadir_filas_xlsx(ruta, filas)
            except PermissionError:
                return Respuesta(f"No puedo guardar {ruta.name}: ciérralo antes en LibreOffice.")
        self.ultimo = ruta
        resumen = "; ".join(", ".join(str(v) for v in fila if v not in (None, "")) for fila in filas[:3])
        n = len(filas)
        return Respuesta(f"Añadid{'a' if n == 1 else 'as'} {n} fila{'s' if n != 1 else ''} a {ruta.stem}: {resumen}.")

    def _hacer_consultar_excel(self, ruta: Path, pregunta: str) -> Respuesta:
        hojas = leer_tabla(ruta)
        if not hojas:
            return Respuesta(f"{ruta.name} está vacío o no lo puedo leer.")
        self.ultimo = ruta
        texto = tabla_como_texto(hojas)
        if not self.ia:
            return Respuesta(f"{ruta.stem}: {estadisticas(hojas[0][1])}.")
        respuesta = self._ia_texto(INSTR_TABLA.format(formato=self._formato()),
                                   f"Pregunta: {pregunta}\n\nArchivo {ruta.name}:\n{texto}", max_tokens=700)
        return Respuesta(respuesta or estadisticas(hojas[0][1]))

    def _hacer_grafico(self, ruta: Path, circular: bool = False) -> Respuesta:
        if ruta.suffix.lower() not in (".xlsx", ".xlsm"):
            return Respuesta(f"Los gráficos los hago en archivos xlsx, y {ruta.name} no lo es.")
        try:
            titulo = grafico_xlsx(ruta, circular)
        except ValueError as e:
            return Respuesta(f"No puedo hacer un gráfico de {ruta.stem}: {e}.")
        except PermissionError:
            return Respuesta(f"No puedo guardar {ruta.name}: ciérralo antes en LibreOffice.")
        self.abrir_ruta(ruta, silencioso=True)
        return Respuesta(f"Gráfico hecho en la hoja Gráfico de {ruta.stem}: {titulo}.", archivo=str(ruta))

    # ---------- presentaciones
    def _crear_presentacion(self, tema: str, nombre: str | None, carpeta: Path) -> Respuesta:
        if not self.ia:
            return Respuesta("Para preparar una presentación necesito la IA en la nube, y ahora no está disponible.")
        if not tema:
            return Respuesta("¿Sobre qué? Dime por ejemplo: crea una presentación sobre el reciclaje.")

        def trabajo():
            spec = self._ia_json(INSTR_PPTX, f"Tema: {tema}", max_tokens=5000, timeout=120)
            ruta = sin_pisar(carpeta / f"{limpiar_nombre(nombre or spec.get('titulo') or tema)}.pptx")
            n = crear_pptx(ruta, spec)
            self.ultimo = ruta
            return f"La presentación {ruta.name} está lista, con {n} diapositivas, en {carpeta.name}.", ruta
        return self._en_segundo_plano(trabajo, "Me pongo con la presentación. Tardo menos de un minuto; te aviso.")

    # ---------- planos
    def _datos_plano(self, ruta: Path) -> tuple[str, Path | None]:
        """(texto con los datos del plano, imagen del plano) para la IA."""
        TMP.mkdir(parents=True, exist_ok=True)
        dxf = ruta if ruta.suffix.lower() == ".dxf" else dwg_a_dxf(ruta)
        if dxf:
            resumen, doc = resumen_dxf(dxf)
            try:
                imagen = dxf_a_imagen(doc, TMP / f"plano_{int(time.time())}.png")
            except Exception as e:
                self.log(f"oficina: no pude dibujar el plano: {e!r}")
                imagen = None
            return resumen, imagen
        return "", None

    def _hacer_describir_plano(self, ruta: Path, pregunta: str = "") -> Respuesta:
        tg = self.es_telegram()

        def trabajo():
            datos, imagen = self._datos_plano(ruta)
            if not datos:
                return (f"No he podido leer {ruta.name} por dentro (puede ser una versión de DWG muy nueva). "
                        f"Dime abre el plano {ruta.stem} y lo ves en LibreCAD.", None)
            if not self.ia:
                return datos[:600], None
            pregunta_ = pregunta or "Describe el plano: qué representa, estancias o piezas, medidas principales."
            sistema = INSTR_PLANO.format(formato=FORMATO_TG if tg else FORMATO_VOZ)
            texto = ""
            if imagen and getattr(self.cerebro, "vision_activa", False):
                try:
                    datos_img = base64.b64encode(imagen.read_bytes()).decode()
                    texto = self.cerebro.ver(f"data:image/png;base64,{datos_img}", sistema,
                                             f"{pregunta_}\n\nDatos del archivo:\n{datos[:6000]}",
                                             max_tokens=800 if tg else 350)
                except Exception as e:
                    self.log(f"oficina: visión del plano: {e!r}")
            if not texto:
                texto = self._ia_texto(sistema, f"{pregunta_}\n\nDatos del archivo:\n{datos[:8000]}")
            return texto, (imagen if tg else None)
        return self._en_segundo_plano(trabajo, f"Miro el plano {ruta.stem}…")

    def _hacer_plano_pdf(self, ruta: Path) -> Respuesta:
        pdf = plano_a_pdf(ruta, ruta.parent)
        if not pdf:
            return Respuesta(f"No he podido pasar {ruta.name} a PDF.")
        if not self.es_telegram():
            lanzar(["xdg-open", str(pdf)])
        return Respuesta(f"Hecho: {pdf.name}, junto al plano.", archivo=str(pdf))

    def _dibujar_plano(self, descripcion: str, nombre: str | None, carpeta: Path) -> Respuesta:
        if not self.ia:
            return Respuesta("Para dibujar un plano necesito la IA en la nube, y ahora no está disponible.")

        def trabajo():
            spec = self._ia_json(INSTR_DXF, descripcion, max_tokens=8000, timeout=150)
            ruta = sin_pisar(carpeta / f"{limpiar_nombre(nombre or spec.get('titulo') or 'Plano')}.dxf")
            n = crear_dxf(ruta, spec)
            if n == 0:
                ruta.unlink(missing_ok=True)
                return "La IA no me ha dado un dibujo válido. Descríbemelo con más detalle.", None
            self.ultimo = ruta
            pdf = None
            try:
                import ezdxf
                pdf = dxf_a_imagen(ezdxf.readfile(str(ruta)), ruta.with_suffix(".pdf"), pdf=True)
            except Exception as e:
                self.log(f"oficina: PDF del plano: {e!r}")
            extra = " y una copia en PDF" if pdf else ""
            return (f"Plano dibujado: {ruta.name}{extra}, en {carpeta.name}. Es un DXF, que abren LibreCAD y "
                    "AutoCAD; si lo necesitas en DWG, guárdalo como DWG desde AutoCAD.", ruta)
        return self._en_segundo_plano(trabajo, "Dibujo el plano. Dame un minuto.")

    # ---------- PDF y conversiones
    def _hacer_texto(self, ruta: Path) -> Respuesta:
        """Extrae el texto (si es un escaneo o una foto, con la visión) y lo guarda en un .txt al lado."""
        def trabajo():
            texto = ""
            suf = ruta.suffix.lower()
            if suf == ".pdf":
                texto = subprocess.run(["pdftotext", "-layout", str(ruta), "-"], capture_output=True, text=True,
                                       timeout=60).stdout.strip()
            elif suf not in EXT["foto"]:
                texto = leer_texto(ruta, limite=200000).strip()
            if len(texto) < 40:                          # escaneo o foto
                imagenes = paginas_como_imagen(ruta, 4, dpi=150) if suf == ".pdf" else [ruta]
                texto = self._transcribir(imagenes)
            if not texto:
                return f"No he sacado texto de {ruta.name}.", None
            destino = sin_pisar(ruta.with_name(ruta.stem + " (texto).txt"))
            destino.write_text(texto + "\n", encoding="utf-8")
            self.ultimo = destino
            palabras = len(texto.split())
            return f"Texto de {ruta.name} guardado en {destino.name}: unas {palabras} palabras.", destino
        return self._en_segundo_plano(trabajo, f"Saco el texto de {ruta.name}…")

    def _transcribir(self, imagenes: list[Path]) -> str:
        if not getattr(self.cerebro, "vision_activa", False):
            return ""
        partes = []
        for im in imagenes[:6]:
            datos = base64.b64encode(im.read_bytes()).decode()
            mime = "image/png" if im.suffix.lower() == ".png" else "image/jpeg"
            try:
                partes.append(self.cerebro.ver(
                    f"data:{mime};base64,{datos}", "Eres un OCR exacto. Transcribe TODO el texto de la imagen tal cual, "
                    "respetando párrafos, tablas (con | entre columnas) y números. No añadas comentarios.",
                    "Transcribe el texto.", max_tokens=2500))
            except Exception as e:
                self.log(f"oficina: OCR: {e!r}")
        return "\n\n".join(p for p in partes if p).strip()

    def _escanear(self) -> Respuesta:
        """Foto (la de Telegram reciente, o la cámara) → PDF en Documentos/Escaneos + su texto."""
        imagen = None
        if self.vision is not None and self.vision._foto_tg_reciente():
            imagen = self.vision._foto_tg_reciente()
        elif self.es_telegram():
            return Respuesta("Mándame una foto del documento y luego dime escanéalo.")
        elif self.camara is not None:
            TMP.mkdir(parents=True, exist_ok=True)
            self.decir("Pon el documento delante de la cámara. Tres, dos, uno.")
            time.sleep(1.5)
            imagen = self.camara.foto(destino=TMP)
        if not imagen:
            return Respuesta("No he podido hacer la foto del documento.")
        carpeta = carpeta_usuario("DOCUMENTS") / "Escaneos"
        carpeta.mkdir(parents=True, exist_ok=True)
        pdf = sin_pisar(carpeta / f"Escaneo {dt.datetime.now():%Y-%m-%d %H.%M}.pdf")
        imagenes_a_pdf([Path(imagen)], pdf)
        self.ultimo = pdf
        tg = self.es_telegram()

        def trabajo():
            texto = self._transcribir([Path(imagen)])
            if texto:
                pdf.with_suffix(".txt").write_text(texto + "\n", encoding="utf-8")
                resumen = self._ia_texto("Eres Jarvis. En una o dos frases, en español de España, di qué documento "
                                         "es y lo más importante (importes, fechas, plazos).", texto[:6000],
                                         max_tokens=200) if self.ia else ""
                return f"Escaneado en {pdf.name}, carpeta Escaneos, con su texto al lado. {resumen}".strip(), pdf
            return f"Escaneado en {pdf.name}, en la carpeta Escaneos.", pdf
        return self._en_segundo_plano(trabajo, "Escaneando…" if not tg else "Lo paso a PDF y leo el texto…")

    def _hacer_convertir(self, ruta: Path, formato: str) -> Respuesta:
        destino_ext = {"word": "docx", "docx": "docx", "excel": "xlsx", "xlsx": "xlsx", "odt": "odt",
                       "ods": "ods", "csv": "csv", "texto": "txt", "txt": "txt", "powerpoint": "pptx",
                       "pptx": "pptx", "dxf": "dxf"}[formato]
        suf = ruta.suffix.lower()
        if suf == "." + destino_ext:
            return Respuesta(f"{ruta.name} ya es {destino_ext}.")
        if suf == ".pdf" and destino_ext == "docx":
            try:
                from pdf2docx import Converter
            except ImportError:
                return Respuesta("Me falta el conversor de PDF a Word (pdf2docx).")
            destino = sin_pisar(ruta.with_suffix(".docx"))

            def trabajo():
                conv = Converter(str(ruta))
                try:
                    conv.convert(str(destino))
                finally:
                    conv.close()
                self.ultimo = destino
                return f"Convertido: {destino.name}, junto al PDF. Revisa el formato, que en los PDF complicados " \
                       "puede moverse algo.", destino
            return self._en_segundo_plano(trabajo, "Convierto el PDF a Word…")
        if suf in EXT["plano"] and destino_ext == "dxf":
            dxf = dwg_a_dxf(ruta)
            if not dxf:
                return Respuesta("Para pasar DWG a DXF ábrelo en LibreCAD y guárdalo como DXF; no tengo conversor automático.")
            destino = sin_pisar(ruta.with_suffix(".dxf"))
            shutil.move(str(dxf), destino)
            return Respuesta(f"Convertido: {destino.name}.", archivo=str(destino))
        if destino_ext == "txt":
            return self._hacer_texto(ruta)
        perfil = Path(tempfile.gettempdir()) / "jarvis_libreoffice"
        TMP.mkdir(parents=True, exist_ok=True)
        filtro = destino_ext + (":Text - txt - csv (StarCalc):44,34,76" if destino_ext == "csv" else "")
        try:
            subprocess.run(["soffice", f"-env:UserInstallation=file://{perfil}", "--headless", "--convert-to",
                            filtro, "--outdir", str(TMP), str(ruta)], capture_output=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired):
            return Respuesta(f"No he podido convertir {ruta.name}.")
        hecho = TMP / f"{ruta.stem}.{destino_ext}"
        if not hecho.exists():
            return Respuesta(f"LibreOffice no ha sabido pasar {ruta.name} a {destino_ext}.")
        destino = sin_pisar(ruta.with_suffix("." + destino_ext))
        shutil.move(str(hecho), destino)
        self.ultimo = destino
        if not self.es_telegram():
            lanzar(["xdg-open", str(destino)])
        return Respuesta(f"Convertido: {destino.name}, junto al original.", archivo=str(destino))

    # ---------- Word
    def _hacer_anadir_word(self, ruta: Path, contenido: str, redactar: bool = False) -> Respuesta:
        suf = ruta.suffix.lower()
        if suf not in (".docx", ".txt", ".md"):
            return Respuesta(f"Solo sé añadir texto a archivos docx o txt, y {ruta.name} es {suf}.")
        if not contenido.strip():
            return Respuesta("¿Qué añado? Dime: añade al word informe, y el texto.")

        def escribir(texto: str) -> None:
            if suf in (".txt", ".md"):
                with open(ruta, "a", encoding="utf-8") as f:
                    f.write("\n" + texto.strip() + "\n")
                return
            from docx import Document
            doc = Document(str(ruta))
            anadir_markdown_docx(doc, texto)
            doc.save(str(ruta))

        if redactar:
            if not self.redactar:
                return Respuesta("Ahora no puedo redactar.")
            actual = leer_texto(ruta, 4000)

            def trabajo():
                texto = self.redactar(f"un apartado nuevo para añadir al final de este documento: {contenido}. "
                                      f"Sigue su tono. No repitas el título del documento. Documento actual:\n{actual}")
                escribir(texto)
                self.ultimo = ruta
                return f"He añadido el apartado a {ruta.name}.", ruta
            return self._en_segundo_plano(trabajo, "Lo redacto y lo añado al final del documento.")
        try:
            escribir(contenido[:1].upper() + contenido[1:])
        except PermissionError:
            return Respuesta(f"No puedo guardar {ruta.name}: ciérralo antes.")
        self.ultimo = ruta
        return Respuesta(f"Añadido al final de {ruta.name}.")

    # ---------- órdenes
    def manejar(self, peticion: str) -> Respuesta | None:
        t = normalizar(peticion).strip(" .¿?¡!")
        t = re.sub(r"^(?:por favor|oye|venga|jarvis)[ ,]+", "", t)

        # elegir entre varios
        if self._pendiente and time.time() - self._pendiente["t"] < 180:
            m = re.fullmatch(r"(?:abre(?:me)?\s+)?(?:el |la |al |a la )?(?:numero |opcion )?(\w+)", t)
            if m and (m.group(1) in NUMEROS or m.group(1).isdigit()):
                n = int(m.group(1)) if m.group(1).isdigit() else NUMEROS[m.group(1)]
                rutas = self._pendiente["rutas"]
                idx = len(rutas) - 1 if n == -1 else n - 1
                if not 0 <= idx < len(rutas):
                    return Respuesta(f"Solo hay {len(rutas)}.")
                pendiente, self._pendiente = self._pendiente, None
                return self._resolver(pendiente["accion"], rutas[idx], pendiente)

        # "describe este plano", "resume este excel", "pásalo a pdf"… sobre el último archivo (p. ej. el de Telegram)
        m = re.search(r"\b(?:de |del |a |al |en )?(?:este|ese|esta|esa|el ultimo|la ultima)\s+(" + RE_TIPO +
                      r")(?:\s+(?:a|en) (?:pdf|texto))?$", t)
        if m and self.ultimo and self.ultimo.exists():
            r = self._sobre_el_ultimo(t.split()[0], tipo_de(m.group(1)), peticion)
            if r is not None:
                return r

        # últimos documentos
        if re.search(r"\b(cuales son |dime |ensename |muestrame )?(mis |los )?(ultimos|recientes) (documentos|archivos)"
                     r"|\bque (documentos|archivos) (he|has) (creado|usado|abierto|descargado|modificado)", t):
            rutas = recientes(n=8, dias=60)
            if not rutas:
                return Respuesta("No veo documentos recientes en tu carpeta.")
            self._pendiente = {"accion": "abrir", "rutas": rutas, "t": time.time()}
            items = [f"{corto(p)}  ·  {dt.datetime.fromtimestamp(p.stat().st_mtime):%d/%m %H:%M}" for p in rutas]
            if self.ui:
                self.ui.enviar(tipo="resultados", titulo="Últimos documentos", items=items)
            texto = (f"Los más recientes: {', '.join(p.stem for p in rutas[:3])}. Dime abre el primero, o el que quieras.")
            if self.es_telegram():
                texto += "\n" + "\n".join(f"{i + 1}. {x}" for i, x in enumerate(items))
            return Respuesta(texto)

        # abrir lo último descargado
        m = re.search(r"\babre(?:me)?\s+(?:el |la |lo )?(ultim[oa]s?|mas reciente)\s*(" + RE_TIPO + r")?\s*"
                      r"(?:que (?:he|has) (?:descargado|bajado|creado|guardado)|descargad[oa]|de (?:las )?descargas|"
                      r"descarga|que me (?:has|han) mandado)?\s*$", t)
        if m and (m.group(2) or re.search(r"descarg|bajado|creado|guardado|mandado", t)):
            tipo = tipo_de(m.group(2)) if m.group(2) else "archivo"
            carpeta = carpeta_usuario("DOWNLOAD") if re.search(r"descarg|bajado", t) else None
            exts = EXT.get(tipo) or ()
            rutas = recientes(exts if exts else (), carpeta=carpeta, n=1, dias=365)
            if not rutas:
                return Respuesta("No encuentro nada reciente de ese tipo.")
            return self.abrir_ruta(rutas[0])

        # abrir por nombre: "abre el excel presupuesto", "abre el plano de la cocina"
        m = re.match(r"^(?:abre|abreme|abrir|ensename|muestrame|carga)\s+" + ARTICULOS + r"(" + RE_TIPO + r")\s+"
                     + DE_NOMBRE + r"(.+)$", t)
        if m and not re.match(r"^(carpeta|navegador|terminal)", m.group(2)):
            tipo = tipo_de(m.group(1))
            r = self._buscar("abrir", m.group(2), tipo)
            return r if isinstance(r, Respuesta) else self.abrir_ruta(r)

        # crear hoja de cálculo
        m = re.search(r"\b(?:crea|creame|haz|hazme|genera|generame|prepara|preparame|monta|montame|disena)\w*\s+"
                      r"(?:un |una )?(?:nuevo |nueva )?(?:archivo |documento |fichero |libro )?(?:de |en )?"
                      r"(excel|hoja de calculos?|hoja excel|libro de excel|tabla de excel|xlsx)"
                      r"\b(.*)$", t)
        if m:
            resto = m.group(2).strip(" ,.:")
            nombre = None
            mn = re.search(r"\b(?:llamad[oa]|que se llame|con (?:el )?nombre(?: de)?|titulad[oa])\s+(.+?)"
                           r"(?=\s+(?:sobre|para|con|de|en|y|que)\s|[,;]|$)", resto)
            if mn:
                nombre = con_tildes(peticion, mn.group(1))
                nombre = re.sub(r"(?i)\.(xlsx?|ods|csv)$", "", nombre.strip()).replace("_", " ").strip() or None
                resto = (resto[:mn.start()] + " " + resto[mn.end():]).strip(" ,")
            resto, carpeta = separar_destino(resto)
            resto = re.sub(r"^y\s+(?:anade|pon|mete|incluye|crea)\w*\s+(?:una |la )?(?:hoja|pestana)?\s*", "", resto)
            tema = re.sub(r"^(?:sobre|para|de|del|con)\s+", "", resto).strip(" ,") or "hoja de cálculo"
            return self._crear_excel(con_tildes(peticion, tema) or tema, nombre, carpeta or carpeta_usuario("DOCUMENTS"),
                                     peticion)

        # añadir filas: "añade al excel gastos: 20 euros de gasolina"
        m = re.search(r"^(?:anade|anademe|apunta|apuntame|mete|agrega|incluye|pon|registra)\w*\s+(?:en |a |al |a la )"
                      r"(?:el |la |mi )?(excel|hoja de calculos?|hoja|tabla)\s+" + DE_NOMBRE + r"(.+)$", t)
        if m:
            resto = m.group(2)
            if ":" in peticion:                          # "añade al excel gastos: …" → el nombre va antes de los dos puntos
                nombre_dicho, _, datos = resto.partition(":")
                rutas = [p for p in buscar_en_casa(nombre_dicho, carpetas=False, extensiones=EXT["excel"]) if p.is_file()]
            else:
                rutas, nombre_dicho, datos = buscar_por_prefijo(resto, EXT["excel"])
            datos_orig = con_tildes(peticion, datos.strip(" ,:")) or datos
            r = self._uno(rutas, nombre_dicho or resto, "anadir_excel", datos=datos_orig)
            return r if isinstance(r, Respuesta) else self._hacer_anadir_excel(r, datos_orig)

        # gráfico
        m = re.search(r"\b(?:haz|hazme|crea|creame|genera|pon|anade)\w*\s+(?:un |una )?(grafico|grafica|tarta|quesito)"
                      r"\s+(?:circular\s+|de tarta\s+|de barras\s+)?(?:con |de |del |en el |para el )(?:el |la )?"
                      r"(?:excel|hoja de calculos?|hoja|tabla)\s+" + DE_NOMBRE + r"(.+)$", t)
        if m:
            circular = bool(re.search(r"tarta|quesito|circular", t))
            r = self._buscar("grafico", m.group(2), "excel", circular=circular)
            return r if isinstance(r, Respuesta) else self._hacer_grafico(r, circular)

        # preguntas sobre una hoja de cálculo
        m = re.search(r"\b(excel|hoja de calculos?|libro de excel)\s+" + DE_NOMBRE + r"(.+)$", t)
        if m and re.search(r"\b(lee|leeme|resume|resumeme|que hay|que pone|que dice|cuanto|cuanta|cuantos|cuantas|"
                           r"cual|cuales|dime|analiza|explicame|total|suma|media|promedio|quien|cuando|revisa)\b", t):
            rutas, nombre_dicho, extra = buscar_por_prefijo(m.group(2), EXT["excel"])
            pregunta = peticion if not re.search(r"^(lee|leeme|resume|resumeme|analiza|revisa)\b", t) else \
                "Resume qué contiene esta hoja de cálculo y los totales más importantes."
            r = self._uno(rutas, nombre_dicho or m.group(2), "consultar_excel", pregunta=pregunta)
            return r if isinstance(r, Respuesta) else self._hacer_consultar_excel(r, pregunta)

        # presentación
        m = re.search(r"\b(?:crea|creame|haz|hazme|genera|generame|prepara|preparame|monta|montame)\w*\s+"
                      r"(?:un |una )?(?:nuevo |nueva )?(presentacion|powerpoint|power point|diapositivas)\b(.*)$", t)
        if m:
            resto = m.group(2).strip(" ,.:")
            nombre = None
            mn = re.search(r"\b(?:llamad[oa]|que se llame|titulad[oa])\s+(.+?)(?=\s+(?:sobre|de|acerca de)\s|$)", resto)
            if mn:
                nombre = con_tildes(peticion, mn.group(1))
                resto = (resto[:mn.start()] + " " + resto[mn.end():]).strip(" ,")
            resto, carpeta = separar_destino(resto)
            tema = re.sub(r"^(?:sobre|de|acerca de|para|con)\s+", "", resto).strip(" ,")
            return self._crear_presentacion(con_tildes(peticion, tema) if tema else "", nombre,
                                            carpeta or carpeta_usuario("DOCUMENTS"))

        # dibujar un plano
        m = re.search(r"\b(?:dibuja|dibujame|crea|creame|haz|hazme|disena|disename|genera)\w*\s+(?:un |una )?"
                      r"(?:nuevo |nueva )?(?:plano|dxf|dwg|croquis|dibujo de autocad|planta)\b(.*)$", t)
        if m and m.group(1).strip():
            resto = m.group(1).strip(" ,.:")
            nombre = None
            mn = re.search(r"\b(?:llamad[oa]|que se llame|titulad[oa])\s+(.+?)(?=\s+(?:de|con)\s|$)", resto)
            if mn:
                nombre = con_tildes(peticion, mn.group(1))
            _, carpeta = separar_destino(resto)
            return self._dibujar_plano(peticion, nombre, carpeta or carpeta_usuario("DOCUMENTS"))

        # planos: describir / preguntar / a pdf
        m = re.search(r"\bplano\s+" + DE_NOMBRE + r"(.+?)(?:\s+(?:a|en) pdf)?$", t)
        if m and re.search(r"\b(convierte|pasa|exporta|imprime)\w*\b.*\bpdf$", t):
            r = self._buscar("plano_pdf", m.group(1), "plano")
            return r if isinstance(r, Respuesta) else self._hacer_plano_pdf(r)
        if m and re.search(r"\b(describe\w*|explica\w*|que|cuant\w+|mide|miden|analiza|lee|leeme|resume\w*|como|"
                           r"dime|cual\w*|donde|tiene|hay)\b", t):
            rutas, nombre_dicho, _ = buscar_por_prefijo(m.group(1), EXT["plano"])
            if not rutas and self.ultimo and self.ultimo.suffix.lower() in EXT["plano"] and \
                    re.fullmatch(r"(ese|este|el ultimo)", m.group(1)):
                rutas = [self.ultimo]
            r = self._uno(rutas, nombre_dicho or m.group(1), "describir_plano", pregunta=peticion)
            return r if isinstance(r, Respuesta) else self._hacer_describir_plano(r, peticion)

        # unir pdf
        m = re.search(r"\b(?:une|unir|junta|combina|fusiona)\w*\s+(?:los |las )?(?:pdf|pdfs|documentos)\s+(.+)$", t)
        if m:
            nombres = [n.strip(" ,") for n in re.split(r",|\s+y\s+|\s+con\s+", m.group(1)) if n.strip(" ,")]
            if len(nombres) < 2:
                return Respuesta("Dime al menos dos: une los pdf factura y contrato.")
            rutas = []
            for n in nombres[:10]:
                encontrados = [p for p in buscar_en_casa(n, carpetas=False, extensiones=(".pdf",)) if p.is_file()]
                if not encontrados:
                    return Respuesta(f"No encuentro ningún PDF que se llame {n}.")
                exacto = [p for p in encontrados if normalizar(p.stem) == normalizar(n)]
                rutas.append((exacto or encontrados)[0])
            destino = sin_pisar(rutas[0].parent / limpiar_nombre(" + ".join(p.stem for p in rutas))[:70]
                                .__add__(".pdf"))
            paginas = unir_pdfs(rutas, destino)
            self.ultimo = destino
            if not self.es_telegram():
                lanzar(["xdg-open", str(destino)])
            return Respuesta(f"Unidos en {destino.name}: {paginas} páginas.", archivo=str(destino))

        # imágenes a PDF: "convierte la foto ticket a pdf", "junta las fotos de la carpeta recibos en un pdf"
        m = re.search(r"\b(?:junta|une|pasa|convierte|mete)\w*\s+(?:todas )?las (?:fotos|imagenes) de (?:la carpeta )?(.+?)"
                      r"\s+(?:a|en) (?:un )?pdf$", t)
        if m:
            from archivos import carpeta_destino
            carpeta = carpeta_destino(m.group(1))
            if not carpeta:
                return Respuesta(f"No encuentro la carpeta {m.group(1)}.")
            fotos = sorted(p for p in carpeta.iterdir() if p.suffix.lower() in EXT["foto"])
            if not fotos:
                return Respuesta(f"No hay fotos en {carpeta.name}.")
            destino = sin_pisar(carpeta / f"{carpeta.name}.pdf")
            imagenes_a_pdf(fotos[:200], destino)
            return Respuesta(f"Hecho: {destino.name}, con {len(fotos)} páginas.", archivo=str(destino))
        m = re.search(r"\b(?:convierte|pasa|transforma)\w*\s+(?:la |el )?(?:foto|imagen|captura)\s+" + DE_NOMBRE +
                      r"(.+?)\s+(?:a|en) pdf$", t)
        if m:
            r = self._buscar("foto_pdf", m.group(1), "foto")
            return r if isinstance(r, Respuesta) else self._hacer_foto_pdf(r)

        # escanear
        if re.search(r"\b(escanea|escaneame|escanear|digitaliza)\w*\b", t):
            return self._escanear()

        # extraer texto / OCR
        m = re.search(r"\b(?:extrae|sacame|saca|copia|pasa|transcribe)\w*\s+(?:el texto|a texto|el contenido)\s+"
                      r"(?:de |del |de la )?(?:el |la )?(" + RE_TIPO + r")?\s*" + DE_NOMBRE + r"(.+)$", t)
        if not m:
            m = re.search(r"\b(?:pasa|convierte)\w*\s+a texto\s+(?:el |la )?(" + RE_TIPO + r")?\s*" + DE_NOMBRE +
                          r"(.+)$", t)
        if m:
            tipo = tipo_de(m.group(1)) if m.group(1) else "archivo"
            r = self._buscar("texto", m.group(2), tipo)
            return r if isinstance(r, Respuesta) else self._hacer_texto(r)

        # convertir a word/excel/odt/csv/txt/dxf (a pdf lo hace el módulo de archivos)
        m = re.search(r"\b(?:convierte|pasa|transforma|exporta|guarda)\w*\s+(?:el |la )?(" + RE_TIPO + r")?\s*"
                      + DE_NOMBRE + r"(.+?)\s+(?:a|en|como)\s+(?:un |una |formato )?"
                      r"(word|docx|excel|xlsx|odt|ods|csv|txt|texto|powerpoint|pptx|dxf)$", t)
        if m:
            tipo = tipo_de(m.group(1)) if m.group(1) else "archivo"
            r = self._buscar("convertir", m.group(2), tipo, formato=m.group(3))
            return r if isinstance(r, Respuesta) else self._hacer_convertir(r, m.group(3))

        # añadir a un Word
        m = re.search(r"^(?:anade|agrega|escribe|pon|mete|incluye)\w*\s+(?:en |a |al |a la )(?:el |la |mi )?"
                      r"(word|documento|archivo de texto|txt|nota)\s+" + DE_NOMBRE + r"(.+)$", t)
        if m:
            resto = m.group(2)
            redactar = False
            mt = re.search(r"\s*(?::|\bque diga\b|\bel texto\b|\besto\b)\s*", resto)
            ma = re.search(r"\s+(?:un |una |otro |otra )(apartado|parrafo|seccion|capitulo|conclusion|resumen|"
                           r"introduccion)\b", resto)
            if mt and (not ma or mt.start() < ma.start()):
                nombre_dicho, contenido = resto[:mt.start()], resto[mt.end():]
                rutas = [p for p in buscar_en_casa(nombre_dicho, carpetas=False, extensiones=(".docx", ".txt", ".md"))
                         if p.is_file()]
            elif ma:
                nombre_dicho, contenido, redactar = resto[:ma.start()], resto[ma.start():], True
                rutas = [p for p in buscar_en_casa(nombre_dicho, carpetas=False, extensiones=(".docx", ".txt", ".md"))
                         if p.is_file()]
            else:
                rutas, nombre_dicho, contenido = buscar_por_prefijo(resto, (".docx", ".txt", ".md"))
            contenido = con_tildes(peticion, contenido.strip()) or contenido
            r = self._uno(rutas, nombre_dicho, "anadir_word", contenido=contenido, redactar=redactar)
            return r if isinstance(r, Respuesta) else self._hacer_anadir_word(r, contenido, redactar)

        # resumir una presentación
        m = re.search(r"\b(?:resume|resumeme|lee|leeme|de que va|que dice|que pone)\w*\s+(?:la |el )?(presentacion|"
                      r"powerpoint|power point)\s+" + DE_NOMBRE + r"(.+)$", t)
        if m:
            r = self._buscar("resumir", m.group(2), "presentacion")
            return r if isinstance(r, Respuesta) else self._hacer_resumir(r)
        return None

    def recibido(self, ruta: Path) -> str:
        """Un archivo que llega por Telegram: se abre en el portátil y queda como «este»."""
        self.ultimo = ruta
        self._abrir_en_pantalla(ruta)
        suf = ruta.suffix.lower()
        ideas = {"plano": "«describe este plano» o «convierte este plano a pdf»",
                 "excel": "«resume este excel» o «haz un gráfico de este excel»",
                 "pdf": "«resume este pdf» o «extrae el texto de este pdf»",
                 "presentacion": "«resume esta presentación»", "word": "«resume este documento»"}
        tipo = next((k for k in ideas if suf in EXT[k]), None)
        return "Abierto en el portátil." + (f" Si quieres, dime {ideas[tipo]}." if tipo else "")

    def _sobre_el_ultimo(self, verbo: str, tipo: str, peticion: str) -> Respuesta | None:
        ruta, suf = self.ultimo, self.ultimo.suffix.lower()
        if tipo not in ("archivo", "documento") and EXT.get(tipo) and suf not in EXT[tipo]:
            return None
        if re.match(r"abre", verbo):
            return self.abrir_ruta(ruta)
        if re.match(r"(convierte|pasa|exporta)", verbo) and re.search(r"\bpdf$", normalizar(peticion)):
            if suf in EXT["plano"]:
                return self._hacer_plano_pdf(ruta)
            if suf in EXT["foto"]:
                return self._hacer_foto_pdf(ruta)
            return None                                  # lo hace el módulo de archivos
        if re.match(r"(extrae|saca|transcribe)", verbo):
            return self._hacer_texto(ruta)
        if suf in EXT["plano"]:
            return self._hacer_describir_plano(ruta, peticion)
        if suf in EXT["excel"]:
            if re.match(r"(haz|crea|pon)", verbo) and re.search(r"grafic|tarta|quesito", normalizar(peticion)):
                return self._hacer_grafico(ruta, bool(re.search(r"tarta|quesito|circular", normalizar(peticion))))
            return self._hacer_consultar_excel(ruta, peticion)
        if re.match(r"(resume|lee|explica|analiza|describe|que)", verbo):
            return self._hacer_resumir(ruta)
        return None

    def _hacer_foto_pdf(self, ruta: Path) -> Respuesta:
        destino = sin_pisar(ruta.with_suffix(".pdf"))
        imagenes_a_pdf([ruta], destino)
        self.ultimo = destino
        return Respuesta(f"Hecho: {destino.name}, junto a la foto.", archivo=str(destino))

    def _hacer_resumir(self, ruta: Path) -> Respuesta:
        texto = leer_pptx(ruta) if ruta.suffix.lower() == ".pptx" else leer_texto(ruta, 12000)
        if not texto.strip():
            return Respuesta(f"No puedo leer {ruta.name}.")
        self.ultimo = ruta
        if not self.ia:
            return Respuesta(texto[:400])
        return Respuesta(self._ia_texto(f"Eres Jarvis. Resume este documento en español de España. {self._formato()}",
                                        texto[:12000]))


def leer_pptx(ruta: Path) -> str:
    from pptx import Presentation
    partes = []
    for i, s in enumerate(Presentation(str(ruta)).slides, start=1):
        textos = [sh.text_frame.text for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
        partes.append(f"Diapositiva {i}: " + " / ".join(textos))
    return "\n".join(partes)


def plano_a_pdf(ruta: Path, carpeta: Path) -> Path | None:
    """DXF → PDF con ezdxf; DWG → PDF con LibreCAD (o vía DXF si hay conversor)."""
    carpeta.mkdir(parents=True, exist_ok=True)
    dxf = ruta if ruta.suffix.lower() == ".dxf" else dwg_a_dxf(ruta)
    if dxf:
        try:
            import ezdxf
            destino = sin_pisar(carpeta / (ruta.stem + ".pdf"))
            return dxf_a_imagen(ezdxf.readfile(str(dxf)), destino, pdf=True)
        except Exception:
            pass
    return plano_a_pdf_librecad(ruta, carpeta)
