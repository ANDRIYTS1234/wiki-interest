"""DejaVu Sans from matplotlib's own data, registered for both matplotlib and reportlab.

System fonts are never used, so output looks the same on Windows, macOS and Linux.
"""

from __future__ import annotations

from pathlib import Path

FAMILY = "DejaVu Sans"
RL_REGULAR = "DejaVuSans"
RL_BOLD = "DejaVuSans-Bold"

# Characters the reports must render: Ukrainian, Polish, Czech, German, Spanish, Portuguese, signs.
SAMPLE_TEXT = "Ґґ Єє Її Іі Ąą Łł Źź Čč Řř Ůů Ěě ß ñ ã ç − – « » №"


def font_paths() -> dict[str, Path]:
    import matplotlib

    base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    return {"regular": base / "DejaVuSans.ttf", "bold": base / "DejaVuSans-Bold.ttf"}


def missing_glyphs(text: str = SAMPLE_TEXT) -> list[str]:
    """Characters of `text` absent from the regular font's character map."""
    from reportlab.pdfbase.ttfonts import TTFontFile

    face = TTFontFile(str(font_paths()["regular"]))
    return sorted({ch for ch in text if not ch.isspace() and ord(ch) not in face.charToGlyph})


def register_reportlab() -> None:
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if RL_REGULAR in pdfmetrics.getRegisteredFontNames():
        return
    paths = font_paths()
    pdfmetrics.registerFont(TTFont(RL_REGULAR, str(paths["regular"])))
    pdfmetrics.registerFont(TTFont(RL_BOLD, str(paths["bold"])))
    addMapping(RL_REGULAR, 0, 0, RL_REGULAR)
    addMapping(RL_REGULAR, 1, 0, RL_BOLD)
    addMapping(RL_REGULAR, 0, 1, RL_REGULAR)
    addMapping(RL_REGULAR, 1, 1, RL_BOLD)


def configure_matplotlib() -> None:
    import matplotlib
    from matplotlib import font_manager

    for path in font_paths().values():
        font_manager.fontManager.addfont(str(path))
    matplotlib.rcParams["font.family"] = FAMILY
