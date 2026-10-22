#!/usr/bin/env python3
"""Prueba de todo lo que sabe hacer el asistente, sin hablarle: manda cada orden por escrito al asistente en
marcha (POST /orden en 127.0.0.1:8765, solo desde este equipo) y apunta qué módulo la ha atendido, cuánto ha tardado
y qué ha respondido. Al final dice qué archivos nuevos se han creado.

    python3 ~/jarvis/prueba_todo.py              # todo (las canciones y vídeos tardan: 10-20 min)
    python3 ~/jarvis/prueba_todo.py --rapida     # sin canciones, vídeos ni imágenes

No borra nada ni manda mensajes a nadie. Lo que crea va a las carpetas de siempre con «prueba» en el nombre.
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:8765/orden"
H = Path.home()

# (grupo, orden, palabras que deberían salir en la respuesta (cualquiera vale), rápida)
PRUEBAS = [
    ("básico", "qué hora es", ["son las", "es la", ":"], True),
    ("básico", "qué día es hoy", ["hoy es", "es "], True),
    ("básico", "cómo va el ordenador", ["cpu", "procesador", "memoria", "ram", "%"], True),
    ("básico", "qué tiempo hace", ["grados", "º", "°", "temperatura", "lluvia", "nubes", "sol"], True),
    ("memoria", "qué sabes de mí", ["sé", "sabes", "apuntado", "te llamas"], True),
    ("memoria", "cómo me llamo", ["llamas", "nombre"], True),
    ("calendario", "qué tengo esta semana", ["tienes", "nada", "no hay", "semana", "calendario"], True),
    ("programas", "abre la terminal", ["terminal", "abro", "abriendo", "abierto"], True),
    ("programas", "cierra la terminal", ["cierro", "cerrad", "terminal"], True),
    ("programas", "abre la carpeta documentos", ["document", "abro", "carpeta"], True),
    ("programas", "abre la calculadora", ["calculadora", "abro"], True),
    ("programas", "cierra la calculadora", ["calculadora", "cierro", "cerrad"], True),
    ("programas", "qué programas me has instalado", ["instalado", "ninguno", "programa"], True),
    ("internet", "busca en internet la población de Sevilla", ["sevilla", "habitantes", "resultado"], True),
    ("internet", "dime las noticias", ["notic", "titular"], True),
    ("vídeo y música", "busca en youtube despacito", ["youtube", "despacito", "resultado", "vídeo"], True),
    ("vídeo y música", "busca en tiktok recetas", ["tiktok", "recetas"], True),
    ("archivos", "crea un word sobre la historia de la Giralda llamado prueba giralda", ["word", "giralda", "document"], True),
    ("oficina", "crea un excel de gastos prueba con concepto, cantidad y precio", ["excel", "hoja", "gastos"], True),
    ("oficina", "añade al excel gastos prueba: pan, 2, 1,20 y leche, 6, 0,95", ["añad", "fila", "excel", "apunt"], True),
    ("oficina", "cuánto suma el excel gastos prueba", ["€", "suma", "total", "euros"], True),
    ("oficina", "haz un gráfico del excel gastos prueba", ["gráfico", "grafico"], True),
    ("oficina", "crea una presentación sobre la energía solar llamada prueba solar", ["presentaci", "diapositiva"], True),
    ("oficina", "dibuja un plano de una habitación de 3 por 4 metros con una puerta y una ventana llamado prueba habitacion",
     ["plano", "m²", "metros", "dxf"], True),
    ("visión", "qué ves en la pantalla", ["pantalla", "veo", "ventana", "escritorio"], True),
    ("visión", "qué ves por la cámara", ["veo", "cámara", "camara", "persona", "habitación"], True),
    ("cámara", "hazme una foto", ["foto"], True),
    ("cámara", "haz una captura", ["captura"], True),
    ("correo", "cuántos correos tengo sin leer", ["correo", "leer", "bandeja"], True),
    ("saber", "qué has investigado", ["investig", "nota", "nada"], True),
    ("creación", "qué herramientas de creación tienes", ["herramienta", "gratis", "hugging", "pollinations"], True),
    ("móvil", "dónde está mi móvil", ["móvil", "movil", "kde connect", "empareja"], True),
    ("nex", "cuánto llevo gastado en nex", ["nex", "$", "gast", "clave"], True),
    ("creación", "crea una imagen de un gato astronauta flotando sobre Sevilla", ["imagen", "pint", "listo", "gato"], False),
    ("creación", "compón una canción pop sobre el verano en Sevilla", ["canción", "cancion", "compon", "música"], False),
    ("creación", "crea un vídeo corto sobre la Giralda", ["vídeo", "video", "guion", "escena"], False),
]


def ordenar(texto: str, espera: float = 600) -> dict:
    datos = json.dumps({"texto": texto}).encode()
    req = urllib.request.Request(URL, datos, {"Content-Type": "application/json", "X-Jarvis": "1"})
    with urllib.request.urlopen(req, timeout=espera) as r:
        return json.loads(r.read())


def archivos_nuevos(desde: float) -> list[str]:
    nuevos = []
    for carpeta in ("Documentos", "Imágenes", "Vídeos", "Música", "Escritorio", "Documents", "Pictures", "Videos",
                    "Music"):
        base = H / carpeta
        if not base.is_dir():
            continue
        for raiz, dirs, nombres in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for n in nombres:
                f = Path(raiz) / n
                try:
                    if f.stat().st_mtime >= desde:
                        nuevos.append(f"{f.relative_to(H)}  ({f.stat().st_size // 1024} KB)")
                except OSError:
                    pass
    return sorted(nuevos)


def main() -> None:
    rapida = "--rapida" in sys.argv
    inicio = time.time()
    try:
        ordenar("qué hora es", espera=30)
    except OSError as e:
        sys.exit(f"El asistente no responde en {URL}: {e}")
    bien = mal = 0
    for grupo, orden, esperado, es_rapida in PRUEBAS:
        if rapida and not es_rapida:
            continue
        t0 = time.time()
        try:
            r = ordenar(orden)
        except OSError as e:
            r = {"texto": f"(sin respuesta: {e})", "origen": "error"}
        texto = (r.get("texto") or "").replace("\n", " ")
        bajo = texto.lower()
        ok = r.get("origen") not in ("error", "llm") and "todavía no lo sé" not in bajo and \
            "no he podido" not in bajo and "error" not in bajo and any(p in bajo for p in esperado)
        bien += ok
        mal += not ok
        print(f"{'✔' if ok else '✖'} [{grupo}] {orden}\n    {r.get('origen', '?')} · {time.time() - t0:.0f} s · "
              f"{texto[:260]}", flush=True)
        time.sleep(15)          # sin agotar el cupo por minuto del cerebro (Groq gratis)
    if not rapida:
        print("\nEsperando a que terminen las creaciones en segundo plano (hasta 20 min)…", flush=True)
        time.sleep(60)
        for _ in range(19):
            if any(x.split("  ")[0].lower().endswith((".mp4",)) for x in archivos_nuevos(inicio)):
                break
            time.sleep(60)
    print(f"\nResultado: {bien} bien, {mal} mal, en {(time.time() - inicio) / 60:.0f} min")
    print("Archivos nuevos:")
    for f in archivos_nuevos(inicio):
        print("  " + f)


if __name__ == "__main__":
    main()
