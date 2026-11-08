"""
Fotos de perfil y portadas de cada red para el personaje de Nexus, hechas con sus propias fotos (las «verdes»).

  perfil (1080×1080, sirve para todas) · YouTube 2560×1440 (todo dentro de la zona segura central 1546×423)
  X 1500×500 · Facebook 1640×624 · Twitch 1200×480 · Pinterest 1920×1080

Se guardan en ~/jarvis/nexus/portadas/ y se ven y se descargan en la página de Asuka. Las redes no dejan cambiar la
foto ni la portada desde fuera sin su conexión oficial: se suben a mano (2 minutos por red) o, cuando la conexión
oficial esté puesta, las sube el asistente.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

FONDO, ROJO, CIAN, TINTA = (4, 7, 13), (255, 59, 92), (56, 232, 255), (236, 244, 250)
MEDIDAS = {   # nombre: (ancho, alto, zona segura (x, y, w, h) o None, dónde se cambia)
    "youtube": (2560, 1440, (507, 508, 1546, 423), "https://studio.youtube.com/ → Personalización → Marca"),
    "x": (1500, 500, (420, 0, 1080, 500), "https://x.com/settings/profile"),
    "facebook": (1640, 624, (0, 0, 1640, 624), "En la página: Editar → Foto de portada"),
    "twitch": (1200, 480, (0, 0, 1200, 480), "https://dashboard.twitch.tv/settings/channel → Marca"),
    "pinterest": (1920, 1080, (0, 0, 1920, 1080), "https://www.pinterest.es/settings/profile → Portada"),
}
CAMBIAR_PERFIL = {
    "tiktok": "App de TikTok → Perfil → Editar perfil → Cambiar foto",
    "instagram": "https://www.instagram.com/accounts/edit/ → Cambiar foto de perfil",
    "youtube": "https://studio.youtube.com/ → Personalización → Marca → Foto",
    "x": "https://x.com/settings/profile → foto",
    "twitch": "https://dashboard.twitch.tv/settings/channel → Foto de perfil",
    "pinterest": "https://www.pinterest.es/settings/profile → Foto",
    "facebook": "En la página: foto de perfil → Actualizar",
}


def _fuente(px: int, negrita: bool = True):
    for f in (("DejaVuSans-Bold.ttf" if negrita else "DejaVuSans.ttf"),
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, px)
        except OSError:
            continue
    return ImageFont.load_default()


# Cada red con su estilo, su tema de fotos y su lema (que no sean la misma portada recortada)
ESTILO = {   # red: (palabras de escena preferidas, nº de fotos, diseño, acento, lema)
    "youtube": (("gaming", "gamer", "headset", "controller", "setup", "tech", "anime"), 3, "tiras", (255, 59, 92),
                "GAMING · ANIME · VÍDEOS NUEVOS CADA SEMANA"),
    "x": (("cafe", "coffee", "terraza", "closeup", "selfie", "portrait"), 1, "foto_derecha", (56, 232, 255),
          "opiniones, memes y demasiado café"),
    "facebook": (("coria", "sevilla", "plaza", "rio", "river", "street", "paseo"), 1, "paisaje", (255, 196, 92),
                 "Desde Sevilla, con calma"),
    "twitch": (("gaming", "gamer", "headset", "controller", "setup", "night", "noche"), 2, "neon", (169, 112, 255),
               "DIRECTOS · CHARLA · PARTIDAS"),
    "pinterest": (("outfit", "jersey", "sweater", "street", "moto", "motorbike", "gym", "cafe", "paseo", "terraza"), 6,
                  "mosaico", (255, 130, 160), "outfits, rincones y mi día a día"),
}


def _tema(fotos: list[dict], palabras: tuple, n: int, usadas: set) -> list[Path]:
    """Fotos que encajan con el tema de la red, sin repetir las de otras redes mientras haya donde elegir."""
    def puntos(f):
        e = f.get("escena", "").lower()
        return sum(p in e for p in palabras)
    orden = sorted(fotos, key=lambda f: (-puntos(f), f["ruta"] in usadas))
    out, escenas = [], set()
    for f in orden:                                         # primero variadas (escena distinta)
        clave = f.get("escena", "").split()[0] if f.get("escena") else ""
        if f["ruta"] not in usadas and clave not in escenas and len(out) < n:
            out.append(f["ruta"]); escenas.add(clave)
    for f in orden:
        if len(out) >= n:
            break
        if f["ruta"] not in out:
            out.append(f["ruta"])
    usadas.update(out)
    return out


def _abrir(ruta: Path, w: int, h: int, centro=(0.5, 0.3)) -> Image.Image:
    with Image.open(ruta) as im:
        return ImageOps.fit(ImageOps.exif_transpose(im).convert("RGB"), (w, h), Image.LANCZOS, centering=centro)


def _degradado(w: int, h: int, desde_izq: bool = True) -> Image.Image:
    """Máscara horizontal: opaca a un lado, transparente al otro."""
    m = Image.linear_gradient("L").rotate(90 if desde_izq else -90, expand=True).resize((w, h))
    return m


def _textos(d, zona, nombre, lema, acento, hueco, alinear_abajo=False):
    zx, zy, zw, zh = zona
    partes = nombre.upper().split(" ", 1)
    l1, l2 = partes[0], (partes[1] if len(partes) > 1 else "")

    def ajustar(texto, tam, negrita=True):
        f = _fuente(tam, negrita)
        while tam > 14 and d.textlength(texto, font=f) > hueco:
            tam -= 2
            f = _fuente(tam, negrita)
        return f, tam
    f1, t1 = ajustar(l1, int(zh * 0.3))
    f2, t2 = ajustar(l2, int(t1 * 0.42)) if l2 else (None, 0)
    fl, tl = ajustar(lema, max(14, int(t1 * 0.24)), negrita=False)
    total = t1 + (t2 * 1.3 if l2 else 0) + t1 * 0.25 + tl * 1.4
    tx = zx + int(zh * 0.08)
    ty = int(zy + zh - total - zh * 0.1) if alinear_abajo else int(zy + (zh - total) / 2)
    sombra = (0, 0, 0)
    for txt, f, yy in [(l1, f1, ty)] + ([(l2, f2, ty + int(t1 * 1.05))] if l2 else []):
        d.text((tx + 3, yy + 3), txt, font=f, fill=sombra)
        d.text((tx, yy), txt, font=f, fill=TINTA)
    y = ty + int(t1 * 1.05) + (int(t2 * 1.3) if l2 else 0)
    d.rectangle([tx, y, tx + int(min(hueco, t1 * 3)), y + max(3, t1 // 18)], fill=acento)
    y += int(t1 * 0.25)
    d.text((tx + 2, y + 2), lema, font=fl, fill=sombra)
    d.text((tx, y), lema, font=fl, fill=acento)


def _portada(ancho, alto, zona, fotos, nombre, lema, diseno="tiras", acento=ROJO) -> Image.Image:
    zx, zy, zw, zh = zona
    base = Image.new("RGB", (ancho, alto), FONDO)
    if diseno == "paisaje" and fotos:                       # la foto entera a la derecha sobre ella misma difuminada
        fondo = _abrir(fotos[0], ancho, alto, (0.5, 0.3)).filter(ImageFilter.GaussianBlur(24))
        base = Image.blend(fondo, Image.new("RGB", (ancho, alto), (0, 0, 0)), 0.35)
        with Image.open(fotos[0]) as im:
            r = im.width / im.height
        fw = min(int(ancho * 0.6), int(alto * max(r, 0.8)))
        foto = _abrir(fotos[0], fw, alto, (0.5, 0.2))
        base.paste(foto, (ancho - fw, 0), _degradado(fw, alto, desde_izq=False).point(lambda v: min(255, v * 3)))
        _textos(ImageDraw.Draw(base), (zx, zy, int(zw * 0.5), zh), nombre, lema, acento, int(zw * 0.45))
        return base
    if diseno == "foto_derecha" and fotos:                  # una foto grande a la derecha que se funde con el fondo
        fw = int(ancho * 0.45)
        foto = _abrir(fotos[0], fw, alto, (0.5, 0.25))
        base.paste(foto, (ancho - fw, 0), _degradado(fw, alto, desde_izq=False).point(lambda v: min(255, v * 2)))
        hueco = ancho - fw - zx - int(zh * 0.12)
        _textos(ImageDraw.Draw(base), (zx, zy, hueco, zh), nombre, lema, acento, hueco)
        return base
    if diseno == "mosaico" and fotos:                       # cuadrícula de fotos y una franja con el nombre
        cols, filas = 3, 2
        cw, ch = ancho // cols, alto // filas
        for i, r in enumerate((fotos * 6)[: cols * filas]):
            base.paste(_abrir(r, cw - 6, ch - 6), ((i % cols) * cw + 3, (i // cols) * ch + 3))
        d = ImageDraw.Draw(base, "RGBA")
        fh = int(alto * 0.26)
        d.rectangle([0, alto - fh, ancho, alto], fill=(10, 8, 14, 215))
        _textos(d, (zx, alto - fh, zw, fh), nombre, lema, acento, int(zw * 0.7))
        return base
    # «tiras» (YouTube) y «neon» (Twitch): fondo difuminado + fotos verticales a la derecha
    if fotos:
        f = _abrir(fotos[0], ancho, alto).filter(ImageFilter.GaussianBlur(28))
        base = Image.blend(base, f, 0.35)
    if diseno == "neon":
        base = Image.blend(base, Image.new("RGB", (ancho, alto), (40, 10, 70)), 0.45)
    d = ImageDraw.Draw(base)
    n = len(fotos)
    hueco_f = int(zh * 0.04)
    ancho_f = int(min(zh * 0.92 * 0.62, (zw * 0.56 - (n + 1) * hueco_f) / max(n, 1)))
    alto_f = min(int(ancho_f / 0.62), int(zh * 0.92))
    x = zx + zw - n * (ancho_f + hueco_f)
    for i, ruta in enumerate(fotos):
        t = _abrir(ruta, ancho_f, alto_f)
        px, py = x + i * (ancho_f + hueco_f), zy + (zh - alto_f) // 2
        base.paste(t, (px, py))
        borde = acento if diseno == "neon" else (ROJO if i == 1 else CIAN)
        for g in range(3 if diseno == "neon" else 1):         # brillo «neón»
            d.rectangle([px - 2 - g * 4, py - 2 - g * 4, px + ancho_f + 1 + g * 4, py + alto_f + 1 + g * 4],
                        outline=borde, width=3)
    _textos(d, zona, nombre, lema, acento, x - zx - int(zh * 0.16))
    return base


def generar(nx: Path, fotos: list[dict], nombre: str, lema: str = "GAMING · ANIME · GYM · TECH",
            perfiles_red: dict | None = None) -> list[dict]:
    carpeta = nx / "portadas"
    carpeta.mkdir(parents=True, exist_ok=True)
    out = []
    perfil = nx / "perfil.jpg"
    origen = perfil if perfil.exists() else next((f["ruta"] for f in fotos if "portrait" in f["escena"]
                                                   or "closeup" in f["escena"]), fotos[0]["ruta"] if fotos else None)
    if origen:
        with Image.open(origen) as im:
            ImageOps.fit(im.convert("RGB"), (1080, 1080), Image.LANCZOS, centering=(0.5, 0.25)).save(
                carpeta / "perfil_1080.jpg", quality=94)
        out.append({"red": "todas", "tipo": "Foto de perfil", "archivo": "portadas/perfil_1080.jpg",
                    "medida": "1080×1080", "donde": CAMBIAR_PERFIL})
    for red, ruta in (perfiles_red or {}).items():          # foto de perfil distinta en alguna red
        if Path(ruta).exists():
            with Image.open(ruta) as im:
                ImageOps.fit(im.convert("RGB"), (1080, 1080), Image.LANCZOS, centering=(0.5, 0.25)).save(
                    carpeta / f"perfil_{red}_1080.jpg", quality=94)
            out.append({"red": red, "tipo": f"Foto de perfil de {red}", "archivo": f"portadas/perfil_{red}_1080.jpg",
                        "medida": "1080×1080", "donde": CAMBIAR_PERFIL.get(red, "")})
    import random
    fotos = list(fotos)
    random.shuffle(fotos)                                  # cada vez que se rehacen, otras fotos del tema
    usadas: set = set()
    for red, (w, h, zona, donde) in MEDIDAS.items():
        palabras, n, diseno, acento, lema_red = ESTILO[red]
        img = _portada(w, h, zona, _tema(fotos, palabras, n, usadas), nombre, lema_red, diseno, acento)
        nombre_arch = f"portadas/{red}_{w}x{h}.jpg"
        img.save(nx / nombre_arch, quality=92)
        out.append({"red": red, "tipo": "Portada", "archivo": nombre_arch, "medida": f"{w}×{h}", "donde": donde,
                    "lema": lema_red})
    return out
