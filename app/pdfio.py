"""Работа с файлами документов: определение типа, текст и таблицы из PDF, картинка для просмотра."""

from dataclasses import dataclass, field
from pathlib import Path

MEDIA_TYPES = {"pdf": "application/pdf", "png": "image/png", "jpeg": "image/jpeg"}


def sniff(content: bytes) -> str | None:
    """Тип файла по сигнатуре, а не по расширению: имя файла приходит от пользователя."""
    if content.startswith(b"%PDF-"):
        return "pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return None


@dataclass
class PdfContent:
    text: str
    tables: list[list[list[str | None]]] = field(default_factory=list)
    pages: int = 0


def read_pdf(path: Path) -> PdfContent:
    """Текстовый слой и таблицы PDF. У сканов текстового слоя нет: text будет пустым."""
    import pdfplumber

    texts: list[str] = []
    tables: list[list[list[str | None]]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
            tables.extend(page.extract_tables())
        pages = len(pdf.pages)
    return PdfContent(text="\n".join(texts).replace(" ", " "), tables=tables, pages=pages)


def render_preview(path: Path, target: Path, resolution: int = 110) -> None:
    """Первая страница PDF в PNG: просмотр в интерфейсе не зависит от PDF-плагина браузера."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pdf.pages[0].to_image(resolution=resolution).save(target, format="PNG")
