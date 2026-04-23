import base64
import json
import mimetypes
from pathlib import Path
import re
from typing import Any

from huggingface_hub import InferenceClient

from config.settings import (
    DOCUMENT_QA_MAX_CONTEXT_CHARS,
    DOCUMENT_QA_TEXT_MODEL,
    HF_TOKEN,
    POLICY_NOT_FOUND_RESPONSE,
    VISION_MODEL,
)
from src.core.RAG import get_policy_rag_service
from src.core.document_parser import extract_text_from_pdf

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_SETUP_KEYWORDS = (
    "setup",
    "set up",
    "install",
    "configure",
    "connect",
    "how do i",
    "how can i",
    "manual",
    "guide",
    "instructions",
    "how do i use",
    "how to use",
    "turn on",
    "pair",
    "plug in",
    "dock",
    "headset",
    "headphone",
    "equipment",
)


_HF_CLIENT: InferenceClient | None = None


def _hf_client() -> InferenceClient:
    global _HF_CLIENT
    if _HF_CLIENT is None:
        _HF_CLIENT = InferenceClient(token=HF_TOKEN, provider="hf-inference")
    return _HF_CLIENT


def _response_text(response) -> str:
    try:
        return response.choices[0].message.content or ""
    except AttributeError:
        return response["choices"][0]["message"].get("content", "")


def _chat_text(messages: list[dict[str, Any]], model: str, max_tokens: int = 500) -> str:
    response = _hf_client().chat_completion(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.1,
    )
    return _response_text(response).strip()


def _image_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _chat_vision(prompt: str, image_path: Path, max_tokens: int = 500) -> str:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
            ],
        }
    ]
    return _chat_text(messages, model=VISION_MODEL, max_tokens=max_tokens)


def detect_document_modality(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in PDF_EXTENSIONS:
        return "pdf"
    return "unknown"


def answer_question_about_file(file_path: str, question: str) -> str:
    path = Path(file_path).expanduser()
    if not path.exists():
        return f"File not found: {file_path}"

    modality = detect_document_modality(str(path))
    if modality == "image":
        return _answer_question_about_image(path, question)
    if modality == "pdf":
        return _answer_question_about_pdf(path, question)
    return "Unsupported file type. Use a PDF or image file."


def _answer_question_about_image(path: Path, question: str) -> str:
    equipment = _identify_equipment_from_image(path, question)
    if equipment is not None and _should_use_training_docs(question):
        setup_answer = _answer_setup_question_from_training_docs(equipment, question)
        if setup_answer:
            return setup_answer

    prompt = f"Look at the provided document image and answer this question concisely: {question}"
    try:
        answer = _chat_vision(prompt, path, max_tokens=500)
    except Exception as exc:
        return f"Vision generation failed: {exc}"

    answer = answer.strip()
    if equipment is not None and equipment["equipment_name"] != "unknown":
        fallback_answer = answer if answer else "I don't know."
        return (
            f"Detected equipment: {equipment['equipment_name']} "
            f"(confidence: {equipment['confidence']}).\n"
            f"Image answer: {fallback_answer}"
        )
    return answer if answer else "I don't know."


def _answer_question_about_pdf(path: Path, question: str) -> str:
    content = extract_text_from_pdf(str(path))
    lowered = content.lower()
    if (
        not content.strip()
        or "not found:" in lowered
        or "error while" in lowered
        or "dependency missing" in lowered
        or "no readable text found" in lowered
    ):
        return content

    context = content[:DOCUMENT_QA_MAX_CONTEXT_CHARS]
    prompt = f"""
You are an onboarding assistant.
Answer the user's question using ONLY the provided document context.
If the answer is not clearly present in the context, say exactly: I don't know.
The context was extracted from a PDF. Ignore repetitive page numbers or broken sentences.

Context:
\"\"\"
{context}
\"\"\"

Question:
{question}

Answer:
""".strip()

    try:
        answer = _chat_text(
            [{"role": "user", "content": prompt}],
            model=DOCUMENT_QA_TEXT_MODEL,
            max_tokens=500,
        )
    except Exception as exc:
        return f"Document QA generation failed: {exc}"

    answer = answer.strip()
    return answer if answer else "I don't know."


def _should_use_training_docs(question: str) -> bool:
    lowered = question.lower()
    return any(keyword in lowered for keyword in IMAGE_SETUP_KEYWORDS)


def _identify_equipment_from_image(path: Path, question: str) -> dict | None:
    prompt = f"""
Look at this image and identify the primary equipment shown.
The user question is: {question}

Return JSON only with this exact schema:
{{
  "equipment_name": "<specific equipment name or unknown>",
  "brand_or_model": "<brand/model if visible, otherwise empty string>",
  "visible_text": "<important text visible on device if any>",
  "setup_keywords": ["<3 to 6 short search keywords>"],
  "confidence": "high|medium|low"
}}

If you are not confident, use "unknown" for equipment_name.
""".strip()
    try:
        content = _chat_vision(prompt, path, max_tokens=350)
    except Exception:
        return None

    content = content.strip()
    return _parse_equipment_json(content)


def _parse_equipment_json(content: str) -> dict | None:
    cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    if not isinstance(parsed, dict):
        return None

    equipment_name = str(parsed.get("equipment_name", "unknown")).strip() or "unknown"
    brand_or_model = str(parsed.get("brand_or_model", "")).strip()
    visible_text = str(parsed.get("visible_text", "")).strip()
    confidence = str(parsed.get("confidence", "low")).strip().lower()
    keywords = parsed.get("setup_keywords", [])
    if not isinstance(keywords, list):
        keywords = []

    return {
        "equipment_name": equipment_name,
        "brand_or_model": brand_or_model,
        "visible_text": visible_text,
        "setup_keywords": [str(keyword).strip() for keyword in keywords if str(keyword).strip()],
        "confidence": confidence if confidence in {"high", "medium", "low"} else "low",
    }


def _answer_setup_question_from_training_docs(equipment: dict, question: str) -> str | None:
    equipment_name = equipment["equipment_name"]
    if equipment_name == "unknown":
        return None

    search_parts = [equipment_name]
    search_parts.extend(_equipment_aliases(equipment_name))
    if equipment.get("brand_or_model"):
        search_parts.append(equipment["brand_or_model"])
    if equipment.get("visible_text"):
        search_parts.append(equipment["visible_text"])
    search_parts.extend(equipment.get("setup_keywords", []))

    query = (
        f"Equipment identified from uploaded image: {', '.join(search_parts)}. "
        f"User question: {question}. "
        "Find matching setup, connection, installation, or usage instructions in the training documents."
    )

    try:
        response = get_policy_rag_service().answer(query)
    except Exception as exc:
        return f"Detected equipment: {equipment_name} (confidence: {equipment['confidence']}).\nCould not search training documents: {exc}"

    if response.answer_text == POLICY_NOT_FOUND_RESPONSE:
        return (
            f"Detected equipment: {equipment_name} (confidence: {equipment['confidence']}).\n"
            "I could not find matching setup instructions for this equipment in the training documents."
        )

    lines = [f"Detected equipment: {equipment_name} (confidence: {equipment['confidence']})."]
    if equipment.get("brand_or_model"):
        lines.append(f"Detected model/brand: {equipment['brand_or_model']}")
    lines.append(response.answer_text)
    if response.sources:
        lines.append("Sources:")
        lines.extend(f"- {source}" for source in response.sources)
    return "\n".join(lines)


def _equipment_aliases(equipment_name: str) -> list[str]:
    lowered = equipment_name.lower()
    aliases: list[str] = []
    if "headphone" in lowered or "headset" in lowered:
        aliases.extend(["headphone setup", "headset setup", "audio setup"])
    if "dock" in lowered or "docking" in lowered:
        aliases.extend(["docking station setup", "dock setup"])
    if "monitor" in lowered:
        aliases.extend(["monitor setup", "display setup"])
    return aliases
