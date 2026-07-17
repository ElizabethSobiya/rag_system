"""Document parsers: returns list of (text, page_number) tuples."""
from pathlib import Path


def parse_pdf(file_bytes: bytes) -> list[tuple[str, int]]:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text("text")
        if text.strip():
            pages.append((text, page_num))
    doc.close()
    return pages


def parse_docx(file_bytes: bytes) -> list[tuple[str, int]]:
    import io

    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    # DOCX has no page numbers; group all text as page 1
    text = "\n".join(paragraphs)
    return [(text, 1)] if text else []


def parse_html(file_bytes: bytes) -> list[tuple[str, int]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(file_bytes, "lxml")
    # Remove scripts and styles
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return [(text, 1)] if text else []


def parse_text(file_bytes: bytes) -> list[tuple[str, int]]:
    text = file_bytes.decode("utf-8", errors="replace")
    return [(text, 1)] if text.strip() else []


def parse_markdown(file_bytes: bytes) -> list[tuple[str, int]]:
    import markdown
    from bs4 import BeautifulSoup

    md_text = file_bytes.decode("utf-8", errors="replace")
    html = markdown.markdown(md_text)
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n", strip=True)
    return [(text, 1)] if text else []


def parse_document(file_bytes: bytes, filename: str) -> list[tuple[str, int]]:
    """Route to the correct parser based on file extension."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(file_bytes)
    elif suffix == ".docx":
        return parse_docx(file_bytes)
    elif suffix in (".html", ".htm"):
        return parse_html(file_bytes)
    elif suffix == ".md":
        return parse_markdown(file_bytes)
    else:  # .txt and anything else
        return parse_text(file_bytes)
