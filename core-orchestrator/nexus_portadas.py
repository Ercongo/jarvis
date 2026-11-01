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


def _elegir(fotos: list[dict], n: int) -> list[Path]:
    """Fotos variadas: una de cada escena distinta (gaming, gimnasio, calle…)."""
    vistas, out = set(), []
    for f in fotos:
        clave = f["escena"].split()[0]
        if clave not in vistas:
            vistas.add(clave)
            out.append(f["ruta"])
    for f in fotos:
        if len(out) >= n:
            break
        if f["ruta"] not in out:
            out.append(f["ruta"])
    return out[:n]


def _portada(ancho: int, alto: int, zona: tuple, fotos: list[Path], nombre: str, lema: str) -> Image.Image:
    zx, zy, zw, zh = zona
    base = Image.new("RGB", (ancho, alto), FONDO)
    if fotos:     # fondo: la primera foto, enorme, difuminada y oscurecida
        with Image.open(fotos[0]) as im:
            f = ImageOps.fit(im.convert("RGB"), (ancho, alto), Image.LANCZOS).filter(ImageFilter.GaussianBlur(28))
        base = Image.blend(base, f, 0.35)
    d = ImageDraw.Draw(base)
    # tiras de fotos en la mitad derecha de la zona segura
    n = min(3, len(fotos))
    hueco_f = int(zh * 0.04)
    ancho_f = int(min(zh * 0.92 * 0.62, (zw * 0.56 - (n + 1) * hueco_f) / max(n, 1)))
    alto_f = min(int(ancho_f / 0.62), int(zh * 0.92))
    x = zx + zw - n * (ancho_f + hueco_f)
    for i, ruta in enumerate(fotos[:n]):
        with Image.open(ruta) as im:
            t = ImageOps.fit(im.convert("RGB"), (ancho_f, alto_f), Image.LANCZOS, centering=(0.5, 0.3))
        px, py = x + i * (ancho_f + hueco_f), zy + (zh - alto_f) // 2
        base.paste(t, (px, py))
        d.rectangle([px - 2, py - 2, px + ancho_f + 1, py + alto_f + 1], outline=ROJO if i == 1 else CIAN, width=3)
    # nombre en dos líneas (el primero, grande) y el lema, a la izquierda
    hueco = x - zx - int(zh * 0.16)
    partes = nombre.upper().split(" ", 1)
    l1, l2 = partes[0], (partes[1] if len(partes) > 1 else "")

    def ajustar(texto: str, tam: int, negrita: bool = True):
        f = _fuente(tam, negrita)
        while tam > 14 and d.textlength(texto, font=f) > hueco:
            tam -= 2
            f = _fuente(tam, negrita)
        return f, tam
    f1, t1 = ajustar(l1, int(zh * 0.3))
    f2, t2 = ajustar(l2, int(t1 * 0.42)) if l2 else (None, 0)
    fl, tl = ajustar(lema, max(14, int(t1 * 0.24)), negrita=False)
    total = t1 + (t2 * 1.3 if l2 else 0) + t1 * 0.25 + tl * 1.4
    tx, ty = zx + int(zh * 0.08), int(zy + (zh - total) / 2)
    d.text((tx, ty), l1, font=f1, fill=TINTA)
    y = ty + int(t1 * 1.05)
    if l2:
        d.text((tx, y), l2, font=f2, fill=TINTA)
        y += int(t2 * 1.3)
    d.rectangle([tx, y, tx + int(min(hueco, t1 * 3)), y + max(3, t1 // 18)], fill=ROJO)
    y += int(t1 * 0.25)
    d.text((tx, y), lema, font=fl, fill=CIAN)
    return base


def generar(nx: Path, fotos: list[dict], nombre: str, lema: str = "GAMING · ANIME · GYM · TECH") -> list[dict]:
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
    elegidas = _elegir(fotos, 3)
    for red, (w, h, zona, donde) in MEDIDAS.items():
        img = _portada(w, h, zona, elegidas, nombre, lema)
        nombre_arch = f"portadas/{red}_{w}x{h}.jpg"
        img.save(nx / nombre_arch, quality=92)
        out.append({"red": red, "tipo": "Portada", "archivo": nombre_arch, "medida": f"{w}×{h}", "donde": donde})
    return out
