import io
import logging
import os

logger = logging.getLogger(__name__)


def parse_resume(file=None, text=None):
    """Parse resume from file upload or pasted text. Returns extracted text."""
    if text and text.strip():
        logger.info("Parsing resume from pasted text (%d chars)", len(text))
        return text.strip()

    if file is None:
        return ""

    filename = getattr(file, "filename", "")
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".pdf":
        return _parse_pdf(file)
    elif ext == ".docx":
        return _parse_docx(file)
    else:
        raise ValueError(f"Unsupported file type: {ext}. Only .pdf and .docx are supported.")


def _parse_pdf(file):
    import pdfplumber

    logger.info("Parsing PDF resume")
    text_parts = []
    try:
        pdf = pdfplumber.open(io.BytesIO(file.read()))
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        pdf.close()
    except Exception as e:
        logger.error("Failed to parse PDF: %s", e)
        raise ValueError(f"Could not parse PDF file: {e}")

    result = "\n".join(text_parts)
    logger.info("Extracted %d chars from PDF", len(result))
    return result


def _parse_docx(file):
    from docx import Document

    logger.info("Parsing DOCX resume")
    try:
        doc = Document(io.BytesIO(file.read()))
        text_parts = [p.text for p in doc.paragraphs if p.text.strip()]
    except Exception as e:
        logger.error("Failed to parse DOCX: %s", e)
        raise ValueError(f"Could not parse DOCX file: {e}")

    result = "\n".join(text_parts)
    logger.info("Extracted %d chars from DOCX", len(result))
    return result
