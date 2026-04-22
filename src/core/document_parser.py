from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


def extract_text_from_pdf(pdf_path: str) -> str:
    if PdfReader is None:
        return "PDF dependency missing. Install `pypdf`."

    path = Path(pdf_path)
    if not path.exists():
        return f"PDF not found: {pdf_path}"

    try:
        reader = PdfReader(str(path))
        pages_text = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        return f"Error while reading PDF: {exc}"

    full_text = "\n".join(pages_text).strip()
    return full_text if full_text else "No readable text found in PDF."
