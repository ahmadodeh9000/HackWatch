"""The weekly digest as a 1080x1350 image (Instagram portrait, WhatsApp status), docs/digest.png.

Same events as digest.txt: Jordan, no club life, the next 7 days, then registrations
closing in that window. Headings in English and Arabic.

Arabic needs Pillow's raqm layout (libraqm + FriBiDi) to join letters and run
right to left; without it Arabic comes out as separate letters, so render() says so in
its warnings. The deploy job installs libraqm and the Noto/DejaVu fonts from Ubuntu.
"""
import re
from pathlib import Path
from typing import List, Optional, Sequence

from hackwatch.digest import Digest, _day, _short, _where
from hackwatch.tidy import shown_organizer, shown_title

WIDTH, HEIGHT = 1080, 1350
MARGIN = 72
BG, SURFACE, TEXT, MUTED, BORDER = "#faf8f5", "#ffffff", "#1f2430", "#555c6d", "#e4dfd6"
ACCENT, ACCENT_INK, SOON_BG, SOON_FG = "#4338ca", "#ffffff", "#fdecc8", "#7a4a00"
TYPE_COLORS = {"hackathon": ("#e0f2fe", "#075985"), "competition": ("#fce7f3", "#9d174d"),
               "conference": ("#f3e8ff", "#6b21a8"), "workshop": ("#dcfce7", "#166534"),
               "meetup": ("#ffedd5", "#9a3412"), "other": ("#ece9e3", "#4d5260")}
SITE_LABEL = "ahmadodeh9000.github.io/HackWatch"
# Emoji and pictographs: the fonts have no glyphs for them (they'd show as boxes).
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+")
ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")

# First font that exists wins. Linux paths are what the deploy job installs (fonts-noto-core,
# fonts-dejavu-core); the macOS ones are for running it locally.
LATIN_BOLD = ["/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Unicode.ttf"]
LATIN_REGULAR = ["/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial Unicode.ttf"]
# Arabic lines may mix in Latin words (club names), so these fonts must cover both.
ARABIC_BOLD = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
               "/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/GeezaPro.ttc"]
ARABIC_REGULAR = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                  "/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/GeezaPro.ttc"]


def _font(candidates: Sequence[str], size: int):
    from PIL import ImageFont
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


class Fonts:
    def __init__(self):
        self.cache = {}

    def get(self, text: str, size: int, bold: bool = False):
        arabic = bool(ARABIC.search(text or ""))
        key = (arabic, size, bold)
        if key not in self.cache:
            names = (ARABIC_BOLD if bold else ARABIC_REGULAR) if arabic else (LATIN_BOLD if bold else LATIN_REGULAR)
            self.cache[key] = _font(names, size)
        return self.cache[key]


def raqm_available() -> bool:
    from PIL import features
    return bool(features.check("raqm"))


def _wrap(draw, text: str, font, width: int, max_lines: int) -> List[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = word
        if len(lines) == max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1].rstrip()
        lines[-1] = last + "…"
    return lines or [""]


def is_rtl(text: str) -> bool:
    """Direction of a line from its first letter, like dir="auto" on the site."""
    for ch in text or "":
        if ch.isalpha():
            return bool(ARABIC.match(ch))
    return False


def _text(draw, xy, text, font, fill, width: Optional[int] = None):
    """Draw text; lines starting in Arabic are right-aligned inside `width` and laid out RTL."""
    x, y = xy
    rtl = is_rtl(text)
    kwargs = {"direction": "rtl" if rtl else "ltr"} if raqm_available() else {}
    if rtl and width:
        x = x + width - draw.textlength(text, font=font, **kwargs)
    draw.text((x, y), text, font=font, fill=fill, **kwargs)


def _pill(draw, x, y, text, font, bg, fg, pad_x=16, height=44) -> int:
    w = draw.textlength(text, font=font) + 2 * pad_x
    draw.rounded_rectangle((x, y, x + w, y + height), radius=height // 2, fill=bg)
    box = font.getbbox(text)
    draw.text((x + pad_x, y + (height - (box[3] - box[1])) / 2 - box[1]), text, font=font, fill=fg)
    return int(w)


def _when(e) -> str:
    d = _day(e.start_date)
    text = d.strftime("%a %-d %b").upper() if d else "TBA"
    return f"{text} · {e.start_time}" if e.start_time else text


def render(digest: Digest, path: Path) -> List[str]:
    """Write the PNG; returns warnings (missing fonts or Arabic shaping)."""
    from PIL import Image, ImageDraw

    warnings = []
    if not raqm_available():
        warnings.append("Pillow has no raqm layout here: Arabic text won't be joined or right-to-left.")
    fonts = Fonts()
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    inner = WIDTH - 2 * MARGIN

    # Header band
    draw.rectangle((0, 0, WIDTH, 280), fill=ACCENT)
    en, ar = "This week in Jordan tech", "هذا الأسبوع في فعاليات التقنية بالأردن"
    _text(draw, (MARGIN, 56), en, fonts.get(en, 64, True), ACCENT_INK)
    _text(draw, (MARGIN, 142), ar, fonts.get(ar, 46, True), ACCENT_INK, inner)
    span = f"{digest.start.strftime('%-d %b')} – {digest.end.strftime('%-d %b %Y')}"
    _text(draw, (MARGIN, 212), span, fonts.get(span, 34), "#dcd9ff")

    y = 316
    bottom = HEIGHT - 128  # the footer line
    # Keep room for up to 2 closing registrations and the "+ N more" line.
    reserved = (64 + 54 * min(2, len(digest.closing)) if digest.closing else 0) + 56
    shown = 0
    for e in digest.this_week:
        title = EMOJI.sub("", shown_title(e)).strip()
        title_font = fonts.get(title, 38, True)
        lines = _wrap(draw, _short(title, 90), title_font, inner - 48, 2)
        block = 40 + 10 + len(lines) * 48 + 40 + 38
        if y + block > bottom - reserved:
            break
        draw.rounded_rectangle((MARGIN - 8, y - 8, WIDTH - MARGIN + 8, y + block - 20), radius=24,
                               fill=SURFACE, outline=BORDER, width=2)
        x = MARGIN + 16
        x += _pill(draw, x, y + 10, _when(e), fonts.get("A", 25, True), ACCENT, ACCENT_INK, height=40) + 12
        bg, fg = TYPE_COLORS.get(e.type or "other", TYPE_COLORS["other"])
        _pill(draw, x, y + 10, (e.type or "other").capitalize(), fonts.get("A", 25, True), bg, fg, height=40)
        ty = y + 10 + 40 + 10
        for line in lines:
            _text(draw, (MARGIN + 24, ty), line, title_font, TEXT, inner - 48)
            ty += 48
        where = EMOJI.sub("", _where(e) + (f" · {shown_organizer(e)}" if e.organizer else "")).strip()
        where = _wrap(draw, where, fonts.get(where, 29), inner - 48, 1)[0]
        _text(draw, (MARGIN + 24, ty + 2), where, fonts.get(where, 29), MUTED, inner - 48)
        y += block
        shown += 1

    if not digest.this_week:
        msg, msg_ar = "No events listed for this week yet.", "لا توجد فعاليات مدرجة لهذا الأسبوع بعد."
        _text(draw, (MARGIN, y + 40), msg, fonts.get(msg, 40, True), TEXT)
        _text(draw, (MARGIN, y + 100), msg_ar, fonts.get(msg_ar, 36), MUTED, inner)
        y += 180

    more = len(digest.this_week) - shown
    if more > 0:
        note = f"+ {more} more on the site"
        _text(draw, (MARGIN, y), note, fonts.get(note, 32, True), ACCENT)
        y += 56

    # Registrations closing, as long as there's room
    if digest.closing:
        en_head, ar_head = "Registration closing soon", "التسجيل يُغلق قريباً"
        _text(draw, (MARGIN, y + 8), en_head, fonts.get(en_head, 34, True), TEXT)
        _text(draw, (MARGIN, y + 8), ar_head, fonts.get(ar_head, 30, True), MUTED, inner)
        y += 64
        for e in digest.closing:
            if y + 50 > bottom:
                break
            closes = _day(e.registration_deadline).strftime("%a %-d %b").upper()
            x = MARGIN + _pill(draw, MARGIN, y, closes, fonts.get("A", 24, True), SOON_BG, SOON_FG, height=40) + 14
            title = EMOJI.sub("", shown_title(e)).strip()
            title = _wrap(draw, title, fonts.get(title, 30), WIDTH - MARGIN - x, 1)[0]
            _text(draw, (x, y + 2), title, fonts.get(title, 30), TEXT, WIDTH - MARGIN - x)
            y += 54

    # Footer
    draw.line((MARGIN, HEIGHT - 128, WIDTH - MARGIN, HEIGHT - 128), fill=BORDER, width=2)
    brand_font = fonts.get("A", 40, True)
    draw.text((MARGIN, HEIGHT - 100), "Hack", font=brand_font, fill=TEXT)
    draw.text((MARGIN + draw.textlength("Hack", font=brand_font), HEIGHT - 100), "Watch", font=brand_font, fill=ACCENT)
    site_font = fonts.get(SITE_LABEL, 28)
    draw.text((WIDTH - MARGIN - draw.textlength(SITE_LABEL, font=site_font), HEIGHT - 92), SITE_LABEL,
              font=site_font, fill=MUTED)
    add = "Add your event · أضف فعاليتك"
    add_font = fonts.get(add, 24)
    draw.text((WIDTH - MARGIN - draw.textlength(add, font=add_font), HEIGHT - 52), add, font=add_font, fill=MUTED)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)
    return warnings
