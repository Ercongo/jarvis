"""
Radio y pódcast, sin cuentas ni claves:
  - emisoras de todo el mundo con Radio Browser (https://www.radio-browser.info, ~50 000 emisoras, datos libres);
  - pódcast con el buscador de Apple Podcasts y su RSS (el último episodio, o el de un tema).

  «pon la radio» (la última que escuchaste, o la SER), «pon Cadena SER», «pon los 40», «pon radio Marca»,
  «sintoniza Rock FM», «pon la radio en el echo» (la pone Alexa en el Echo)
  «pon el pódcast La Ruina», «pon el último episodio de Nadie Sabe Nada», «busca pódcast de historia»
  «para la radio», «quita el pódcast», «qué estás poniendo»

Se oye con ffplay (sin ventana). «para la música» también la para (usa el mismo aviso que la música de arranque).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Callable

from herramientas import leer_config, guardar_config, normalizar
from sistema import PID_MUSICA, Respuesta, musica_sonando, parar_musica

UA = "Athena/1.0 (asistente personal)"
SERVIDORES = ["de1.api.radio-browser.info", "fi1.api.radio-browser.info", "all.api.radio-browser.info"]
# nombres como se dicen → como se buscan (las de España más pedidas)
ALIAS = {"la ser": "cadena ser", "ser": "cadena ser", "los cuarenta": "los40", "los 40": "los40", "40 principales": "los40",
         "cuarenta principales": "los40", "la cope": "cope", "rne": "radio nacional", "radio 1": "radio nacional",
         "radio nacional de espana": "radio nacional", "radio 3": "radio 3", "onda cero": "onda cero", "cadena dial": "cadena dial",
         "kiss": "kiss fm", "europa": "europa fm", "rock": "rock fm", "cadena 100": "cadena 100", "marca": "radio marca",
         "canal sur": "canal sur radio", "catalunya radio": "catalunya radio", "melodia": "melodia fm", "loca": "loca fm",
         "flaix": "flaix fm", "megastar": "megastar fm", "radio clasica": "radio clasica", "hit fm": "hit fm"}
CONOCIDAS = r"(?:cadena ser|la ser|los ?40|los cuarenta|40 principales|cuarenta principales|cope|la cope|onda cero|rne|" \
            r"radio nacional|radio 1|radio 3|radio clasica|cadena dial|kiss fm|europa fm|rock fm|cadena 100|radio marca|" \
            r"canal sur radio|catalunya radio|melodia fm|loca fm|flaix fm|megastar fm|hit fm|radio ole|esradio|" \
            r"radio euskadi|radio galega|a punt radio|onda madrid|radio maria)"


def _json(url: str, timeout: int = 12):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def buscar_emisoras(nombre: str, n: int = 5) -> list[dict]:
    nombre = ALIAS.get(nombre, nombre)
    for pais in ("ES", ""):
        q = {"name": nombre, "order": "clickcount", "reverse": "true", "hidebroken": "true", "limit": n}
        if pais:
            q["countrycode"] = pais
        for s in SERVIDORES:
            try:
                r = _json(f"https://{s}/json/stations/search?" + urllib.parse.urlencode(q))
                break
            except Exception:
                r = None
        if r:
            return [{"nombre": x.get("name", "").strip(), "url": x.get("url_resolved") or x.get("url"),
                     "pais": x.get("countrycode", ""), "tipo": x.get("codec", "")} for x in r if x.get("url_resolved") or x.get("url")]
    return []


def buscar_podcast(nombre: str, n: int = 3) -> list[dict]:
    r = _json("https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": nombre, "media": "podcast", "country": "ES", "limit": n, "lang": "es_es"}))
    return [{"nombre": x.get("collectionName", ""), "autor": x.get("artistName", ""), "rss": x.get("feedUrl", "")}
            for x in r.get("results", []) if x.get("feedUrl")]


def episodios(rss: str, n: int = 10) -> list[dict]:
    req = urllib.request.Request(rss, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        raiz = ET.fromstring(r.read())
    res = []
    for it in raiz.iter("item"):
        enc = it.find("enclosure")
        if enc is None or not enc.get("url"):
            continue
        res.append({"titulo": (it.findtext("title") or "").strip(), "url": enc.get("url"),
                    "fecha": (it.findtext("pubDate") or "")[:16]})
        if len(res) >= n:
            break
    return res


class Radio:
    def __init__(self, log: Callable[[str], None], alexa=None):
        self.log = log
        self.alexa = alexa                                # para «en el echo»
        self.sonando: dict | None = None
        self._proc: subprocess.Popen | None = None

    # ---------------------------------------------------------------- reproducir
    def _reproducir(self, url: str, que: dict) -> bool:
        jugador = shutil.which("ffplay")
        if not jugador:
            return False
        self._parar()
        parar_musica()
        try:
            self._proc = subprocess.Popen([jugador, "-nodisp", "-autoexit", "-loglevel", "error", "-infbuf", url],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                          stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            return False
        try:
            PID_MUSICA.parent.mkdir(parents=True, exist_ok=True)
            PID_MUSICA.write_text(str(self._proc.pid))          # «para la música» también la para
        except OSError:
            pass
        self.sonando = {**que, "desde": time.time()}
        return True

    def _parar(self) -> bool:
        p, self._proc = self._proc, None
        if p and p.poll() is None:
            p.terminate()
            self.sonando = None
            return True
        return False

    def _en_echo(self, frase: str) -> Respuesta:
        if not self.alexa:
            return Respuesta("No tengo Alexa conectada.")
        return self.alexa._texto(frase)

    # ---------------------------------------------------------------- órdenes
    def manejar(self, texto: str) -> Respuesta | None:
        t = normalizar(texto).strip(" .?¿!¡")
        t = re.sub(r"^(athena|atenea|jarvis)[, ]+", "", t)
        t = t.replace("podcasts", "podcast").replace("pódcast", "podcast")
        en_echo = re.search(r" en (?:el |la )?(echo|alexa|despertador)( \w+)?$", t)
        if en_echo:
            t = t[:en_echo.start()]

        # parar
        if re.search(r"^(para|quita|apaga|deten|corta|cierra)\w* (la |el )?(radio|emisora|podcast|episodio)$", t):
            if en_echo:
                return self._en_echo("para")
            if self._parar() or (self.sonando is None and musica_sonando() and parar_musica()):
                return Respuesta("Radio apagada." if "radio" in t or "emisora" in t else "Pódcast parado.")
            return Respuesta("No estaba sonando nada.")
        if re.search(r"^(que|quien) (esta sonando|suena|estas poniendo|emisora es)", t) and self.sonando and \
                self._proc and self._proc.poll() is None:
            s = self.sonando
            return Respuesta(f"Estás escuchando {s['nombre']}" + (f": {s['episodio']}." if s.get("episodio") else "."))

        # pódcast
        m = re.search(r"^(?:busca|buscame)\w* (?:un |algun |unos )?podcast (?:de|sobre) (.+)$", t)
        if m:
            return self._buscar_podcasts(m.group(1))
        m = re.search(r"^(?:pon|ponme|reproduce|quiero (?:oir|escuchar))\w* (?:el )?(ultimo |penultimo )?(?:episodio|capitulo|programa)"
                      r" (?:de|del) (?:podcast )?(.+)$", t) or \
            re.search(r"^(?:pon|ponme|reproduce|quiero (?:oir|escuchar))\w* (?:el |un )?podcast (?:de |del )?(ultimo |)(.+)$", t)
        if m:
            if en_echo:
                return self._en_echo(f"pon el podcast {m.group(2)}")
            return self._podcast(m.group(2).strip(), penultimo=(m.group(1) or "").startswith("pen"))

        # radio
        m = re.search(r"^(?:pon|ponme|sintoniza|quiero (?:oir|escuchar)|enciende)\w* (?:la )?(?:radio|emisora)(?: (?:de )?(.+))?$", t) \
            or re.search(rf"^(?:pon|ponme|sintoniza|quiero (?:oir|escuchar))\w* ({CONOCIDAS})$", t)
        if m:
            nombre = (m.group(1) or "").strip()
            if en_echo:
                return self._en_echo(f"pon {nombre or 'la radio'}")
            return self._radio(nombre)
        return None

    def _radio(self, nombre: str) -> Respuesta:
        if not nombre:
            ultima = leer_config().get("radio_ultima") or {}
            if ultima.get("url") and self._reproducir(ultima["url"], ultima):
                return Respuesta(f"Pongo {ultima['nombre']}.")
            nombre = "cadena ser"
        try:
            lista = buscar_emisoras(nombre)
        except Exception as e:
            self.log(f"radio: {e!r}")
            lista = []
        if not lista:
            return Respuesta(f"No encuentro la emisora {nombre}.")
        for e in lista[:3]:                               # la primera que arranque
            if self._reproducir(e["url"], e):
                time.sleep(2.5)
                if self._proc and self._proc.poll() is None:
                    guardar_config(radio_ultima={"nombre": e["nombre"], "url": e["url"]})
                    self.log(f"radio: {e['nombre']}")
                    return Respuesta(f"Pongo {e['nombre']}. Dime «para la radio» cuando quieras.")
        return Respuesta(f"He encontrado {lista[0]['nombre']}, pero ahora no emite. Prueba otra.")

    def _buscar_podcasts(self, tema: str) -> Respuesta:
        try:
            lista = buscar_podcast(tema, 5)
        except Exception as e:
            self.log(f"radio: podcast {e!r}")
            return Respuesta("No puedo buscar pódcast ahora mismo.")
        if not lista:
            return Respuesta(f"No encuentro pódcast sobre {tema}.")
        nombres = "; ".join(f"{p['nombre']}" for p in lista[:5])
        return Respuesta(f"Sobre {tema} hay: {nombres}. Dime «pon el pódcast …» con el que quieras.")

    def _podcast(self, nombre: str, penultimo: bool = False) -> Respuesta:
        try:
            lista = buscar_podcast(nombre)
            eps = episodios(lista[0]["rss"]) if lista else []
        except Exception as e:
            self.log(f"radio: podcast {e!r}")
            return Respuesta("No he podido traer ese pódcast ahora mismo.")
        if not eps:
            return Respuesta(f"No encuentro el pódcast {nombre}.")
        ep = eps[1] if penultimo and len(eps) > 1 else eps[0]
        if self._reproducir(ep["url"], {"nombre": lista[0]["nombre"], "episodio": ep["titulo"]}):
            self.log(f"radio: pódcast {lista[0]['nombre']} · {ep['titulo'][:60]}")
            return Respuesta(f"Pongo {lista[0]['nombre']}: {ep['titulo']}.")
        return Respuesta("No he podido reproducirlo.")
