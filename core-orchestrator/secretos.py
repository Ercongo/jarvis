"""
Claves y perfil portátil.

  - Las claves (Groq, Telegram, Google, OpenRouter, herramientas de creación) viven en SECRETOS (perfil.py), solo
    legibles por la persona (600). Nunca van al repositorio ni a los paquetes.
  - Un perfil se puede llevar a otro PC en un archivo .jarvisperfil cifrado con contraseña (AES-256 de openssl,
    clave derivada con PBKDF2 de 600.000 vueltas): ajustes, memoria, aprendizajes, calendario, notas, lo
    investigado y, si se quiere, las claves.

  python3 secretos.py exportar ~/Escritorio/mi_asistente.jarvisperfil [--sin-claves]
  python3 secretos.py importar ~/Descargas/mi_asistente.jarvisperfil
  python3 secretos.py permisos        (deja las claves en 600)
  python3 secretos.py lista           (qué claves hay, sin enseñarlas)
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import platform
import shutil
import subprocess
import tarfile
from pathlib import Path

from perfil import DATOS, SECRETOS, nombre

CABECERA = b"JARVISPERFIL1\n"
VUELTAS = "600000"

ARCHIVOS_CLAVE = {      # archivo → para qué es
    "groq.json": "cerebro en la nube (Groq)",
    "telegram.json": "bot de Telegram",
    "google.json": "permiso de la cuenta de Google",
    "google_cliente.json": "app de Google Cloud",
    "openrouter.json": "Nex / OpenRouter",
    "estudio.json": "herramientas de creación (Hugging Face, Musicful, fal, Runway)",
}
CLAVES_EN_CONFIG = ("pollinations_token",)     # claves que viven dentro de config.json

DATOS_PERFIL = ["config.json", "memoria.json", "aprendido.json", "calendario.json", "calendario.ics",
                "recordatorios.json", "saber", "notas"]


class ErrorPerfil(Exception):
    pass


# ---------------------------------------------------------------- permisos
def asegurar_permisos() -> list[str]:
    """Claves en 600 y su carpeta sin permisos para otros. Devuelve las que se han corregido."""
    corregidas = []
    for nombre_ in ARCHIVOS_CLAVE:
        p = SECRETOS / nombre_
        if p.exists() and (p.stat().st_mode & 0o077):
            p.chmod(0o600)
            corregidas.append(nombre_)
    for p in (DATOS / "config.json",):           # lleva alguna clave (pollinations)
        if p.exists() and (p.stat().st_mode & 0o077):
            p.chmod(0o600)
            corregidas.append(p.name)
    return corregidas


def lista() -> list[tuple[str, str, bool]]:
    return [(n, para, (SECRETOS / n).exists()) for n, para in ARCHIVOS_CLAVE.items()]


# ---------------------------------------------------------------- cifrado (openssl)
def _openssl(datos: bytes, contrasena: str, descifrar: bool) -> bytes:
    if not shutil.which("openssl"):
        raise ErrorPerfil("falta openssl")
    leer, escribir = os.pipe()                    # la contraseña por un descriptor: no sale en la lista de procesos
    os.write(escribir, contrasena.encode())
    os.close(escribir)
    try:
        r = subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", VUELTAS, "-salt", "-md", "sha256",
                            *(["-d"] if descifrar else []), "-pass", f"fd:{leer}"],
                           input=datos, capture_output=True, pass_fds=(leer,), timeout=120)
    finally:
        os.close(leer)
    if r.returncode != 0:
        raise ErrorPerfil("contraseña incorrecta o archivo dañado" if descifrar else r.stderr.decode()[:200])
    return r.stdout


# ---------------------------------------------------------------- exportar / importar
def exportar(destino: Path, contrasena: str, con_claves: bool = True) -> Path:
    if len(contrasena) < 8:
        raise ErrorPerfil("la contraseña tiene que tener al menos 8 caracteres")
    buf = io.BytesIO()
    contenido = []
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in DATOS_PERFIL:
            p = DATOS / rel
            if p.exists():
                if rel == "config.json" and not con_claves:
                    c = json.loads(p.read_text(encoding="utf-8"))
                    for k in CLAVES_EN_CONFIG:
                        c.pop(k, None)
                    datos = json.dumps(c, ensure_ascii=False, indent=2).encode()
                    info = tarfile.TarInfo("datos/config.json")
                    info.size, info.mode = len(datos), 0o600
                    tar.addfile(info, io.BytesIO(datos))
                else:
                    tar.add(p, arcname=f"datos/{rel}")
                contenido.append(rel)
        if con_claves:
            for n in ARCHIVOS_CLAVE:
                p = SECRETOS / n
                if p.exists():
                    tar.add(p, arcname=f"secretos/{n}")
                    contenido.append(n)
        manifiesto = json.dumps({"version": 1, "asistente": nombre(), "fecha": dt.datetime.now().isoformat(),
                                 "equipo": platform.node(), "claves": con_claves, "contenido": contenido},
                                ensure_ascii=False).encode()
        info = tarfile.TarInfo("manifiesto.json")
        info.size = len(manifiesto)
        tar.addfile(info, io.BytesIO(manifiesto))
    cifrado = CABECERA + _openssl(buf.getvalue(), contrasena, descifrar=False)
    destino = Path(destino).expanduser()
    if destino.suffix != ".jarvisperfil":
        destino = destino.with_suffix(".jarvisperfil")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(cifrado)
    destino.chmod(0o600)
    return destino


def leer_manifiesto(origen: Path, contrasena: str) -> tuple[dict, bytes]:
    bruto = Path(origen).expanduser().read_bytes()
    if not bruto.startswith(CABECERA):
        raise ErrorPerfil("no es un perfil del asistente")
    claro = _openssl(bruto[len(CABECERA):], contrasena, descifrar=True)
    with tarfile.open(fileobj=io.BytesIO(claro), mode="r:gz") as tar:
        m = tar.extractfile("manifiesto.json")
        return json.loads(m.read()) if m else {}, claro


def importar(origen: Path, contrasena: str) -> dict:
    """Mete el perfil en este PC. Lo que ya hubiera se guarda antes en DATOS/copias_perfil/<fecha>/."""
    manifiesto, claro = leer_manifiesto(origen, contrasena)
    copia = DATOS / "copias_perfil" / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    permitidos = {f"datos/{r}" for r in DATOS_PERFIL} | {f"secretos/{n}" for n in ARCHIVOS_CLAVE}
    puestos = []
    with tarfile.open(fileobj=io.BytesIO(claro), mode="r:gz") as tar:
        for m in tar.getmembers():
            raiz = "/".join(m.name.split("/")[:2])
            if m.name == "manifiesto.json":
                continue
            if raiz not in permitidos or ".." in Path(m.name).parts or m.issym() or m.islnk() or m.isdev():
                continue                                          # nada fuera de lo esperado
            base, rel = (SECRETOS, m.name[len("secretos/"):]) if m.name.startswith("secretos/") else \
                (DATOS, m.name[len("datos/"):])
            destino = base / rel
            if m.isdir():
                destino.mkdir(parents=True, exist_ok=True)
                continue
            if destino.exists() and destino.is_file():
                (copia / m.name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destino, copia / m.name)
            destino.parent.mkdir(parents=True, exist_ok=True)
            f = tar.extractfile(m)
            if f is None:
                continue
            datos = f.read()
            if rel == "config.json" and m.name.startswith("datos/") and destino.exists():
                try:                                           # no perder las claves que ya tenía este PC
                    viejo, nuevo = json.loads(destino.read_text(encoding="utf-8")), json.loads(datos)
                    for k in CLAVES_EN_CONFIG:
                        if k in viejo and k not in nuevo:
                            nuevo[k] = viejo[k]
                    datos = json.dumps(nuevo, ensure_ascii=False, indent=2).encode()
                except ValueError:
                    pass
            destino.write_bytes(datos)
            if m.name.startswith("secretos/") or rel == "config.json":
                destino.chmod(0o600)
            puestos.append(m.name)
    manifiesto["puestos"] = puestos
    manifiesto["copia_de_lo_anterior"] = str(copia) if copia.exists() else ""
    return manifiesto


if __name__ == "__main__":
    import getpass
    import sys

    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    orden = args[0]
    try:
        if orden == "permisos":
            c = asegurar_permisos()
            print("Corregidas: " + ", ".join(c) if c else "Las claves ya estaban protegidas.")
        elif orden == "lista":
            for n, para, hay in lista():
                print(f"{'✔' if hay else '·'} {n:22} {para}")
        elif orden == "exportar" and len(args) >= 2:
            c1 = getpass.getpass("Contraseña para el perfil (mínimo 8): ")
            if getpass.getpass("Repítela: ") != c1:
                sys.exit("No coinciden.")
            p = exportar(Path(args[1]), c1, con_claves="--sin-claves" not in args)
            print(f"Perfil guardado en {p}. Sin la contraseña no se puede abrir; guárdala bien.")
        elif orden == "importar" and len(args) >= 2:
            m = importar(Path(args[1]), getpass.getpass("Contraseña del perfil: "))
            print(f"Perfil de {m.get('asistente')} ({m.get('equipo')}, {str(m.get('fecha', ''))[:16]}) importado: "
                  f"{len(m['puestos'])} archivos.")
            if m.get("copia_de_lo_anterior"):
                print(f"Lo que había antes está en {m['copia_de_lo_anterior']}.")
            if any(x.endswith("telegram.json") for x in m["puestos"]):
                print("Ojo: si el otro PC sigue encendido con el mismo bot de Telegram, los dos se pelearán por los "
                      "mensajes. Apaga el asistente allí o crea un bot nuevo para este PC.")
            print("Reinicia el asistente para que lo coja.")
        else:
            print(__doc__)
            sys.exit(1)
    except ErrorPerfil as e:
        sys.exit(f"No se ha podido: {e}.")
