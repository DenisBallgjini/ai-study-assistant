"""AI Study Assistant: PDF summaries, flashcards and quizzes with local Ollama."""
import json
import logging
import os
import re
import secrets
import uuid
from pathlib import Path

import bleach
import markdown
import ollama
from flask import Flask, render_template, request, session
from markupsafe import Markup, escape
from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError
from werkzeug.exceptions import RequestEntityTooLarge

ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / "uploads"
UPLOADS.mkdir(exist_ok=True)
KEY_FILE = ROOT / ".flask_secret_key"
if not KEY_FILE.exists():
    try:
        with KEY_FILE.open("x", encoding="utf-8") as handle:
            handle.write(secrets.token_hex(32))
        KEY_FILE.chmod(0o600)
    except FileExistsError:
        pass

app = Flask(__name__)
app.secret_key = KEY_FILE.read_text(encoding="utf-8").strip()
app.config.update(MAX_CONTENT_LENGTH=20 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
CHUNK_CHARS = 3400
MAX_CARDS = 15
log = logging.getLogger(__name__)


@app.template_filter("markdown")
def markdown_filter(value):
    html = markdown.markdown(value or "", extensions=["extra", "sane_lists"])
    return Markup(bleach.clean(html, tags=["p", "br", "h1", "h2", "h3", "h4", "strong", "em", "ul", "ol", "li", "blockquote", "code", "pre", "hr"], attributes={}, strip=True))


def extract_pages(path):
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError("Password-protected PDF")
    pages = []
    for number, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append((number, text))
    return pages


def lecture_chunks(pages, max_chars=CHUNK_CHARS):
    chunks, current = [], ""
    for number, text in pages:
        label = f"[PDF page {number}]\n"
        available = max_chars - len(label) - 2
        while text:
            if len(text) <= available:
                piece, text = text, ""
            else:
                cut = text.rfind(" ", available // 2, available)
                if cut < 1:
                    cut = available
                piece, text = text[:cut], text[cut:].lstrip()
            part = label + piece.strip() + "\n\n"
            if current and len(current) + len(part) > max_chars:
                chunks.append(current.strip())
                current = ""
            current += part
    if current:
        chunks.append(current.strip())
    return chunks


def parse_result(raw):
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("Model did not return valid JSON")
    if not isinstance(data, dict):
        raise ValueError("Model returned wrong JSON structure")
    summary = data.get("summary")
    if not isinstance(summary, str) or len(summary.strip()) < 30:
        raise ValueError("Model did not return a useful summary")
    result = {"summary": summary.strip()}
    for kind in ("flashcards", "quiz"):
        items = data.get(kind, [])
        if not isinstance(items, list):
            items = []
        valid = []
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("question"), str) and isinstance(item.get("answer"), str):
                question, answer = item["question"].strip(), item["answer"].strip()
                if question and answer:
                    valid.append({"question": question, "answer": answer})
        result[kind] = valid[:4]
    return result


SYSTEM_PROMPT = """You are a precise university lecture study-note writer. The SOURCE may be German; ALL OUTPUT MUST BE IN ENGLISH, including every heading, question and answer. Keep code identifiers, proper names and original technical terms when needed. Do not invent material, algorithms, steps, or facts absent from SOURCE. Do not add unrelated topics. Preserve the order of the lecture. Summarize every distinct definition, mechanism, distinction, and numbered procedure supported by SOURCE, including exact steps when given. If diagrams are not described in extracted text, do not guess their contents. Write clear detailed Markdown study notes, not vague generalities. Also produce 2-3 substantive flashcards and 2-3 exam-style quiz questions with explanatory answers based only on SOURCE. Return ONLY a JSON object of exactly this shape: {"summary":"Markdown notes in English", "flashcards":[{"question":"English question", "answer":"English answer"}], "quiz":[{"question":"English question", "answer":"English answer"}]}. No other text."""


def generate_chunk(source):
    # A single request per chunk is the main speed optimization.
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "SOURCE LECTURE EXCERPT:\n" + source}],
        format="json",
        options={"temperature": 0, "num_ctx": 6144, "num_predict": 1800},
    )
    return parse_result(response.message.content)


def evenly_select(items, limit=MAX_CARDS):
    if len(items) <= limit:
        return items
    return [items[round(i * (len(items) - 1) / (limit - 1))] for i in range(limit)]


def generate_study_material(pages):
    chunks = lecture_chunks(pages)
    summaries, flashcards, quiz = [], [], []
    for index, chunk in enumerate(chunks, 1):
        print(f"Processing lecture section {index}/{len(chunks)}...", flush=True)
        result = generate_chunk(chunk)
        summaries.append(f"## Lecture section {index}\n\n{result['summary']}")
        flashcards.extend(result["flashcards"])
        quiz.extend(result["quiz"])
    return "\n\n---\n\n".join(summaries), evenly_select(flashcards), evenly_select(quiz)


@app.errorhandler(RequestEntityTooLarge)
def too_large(_):
    return "PDF exceeds the 20 MB upload limit.", 413


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    uploaded = request.files.get("pdf")
    if not uploaded or not uploaded.filename:
        return "Please select a PDF file.", 400
    if not uploaded.filename.lower().endswith(".pdf"):
        return "Only PDF files are allowed.", 400
    if uploaded.mimetype not in ("application/pdf", "application/octet-stream", ""):
        return "Invalid PDF upload.", 400
    path = UPLOADS / f"{uuid.uuid4().hex}.pdf"
    uploaded.save(path)
    try:
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise ValueError("Not a PDF")
        pages = extract_pages(path)
    except (PdfReadError, ValueError, OSError, KeyError):
        path.unlink(missing_ok=True)
        return "Unable to read this PDF. Upload a valid, unencrypted PDF.", 400
    if not pages:
        path.unlink(missing_ok=True)
        return "This PDF has no extractable text. Scanned PDFs require OCR.", 400
    session["document_id"] = path.name
    try:
        summary, flashcards, quiz = generate_study_material(pages)
    except Exception:
        log.exception("Local AI generation failed")
        return "AI generation failed. Check the Flask terminal and that Ollama is running with the selected model.", 503
    return render_template("summary.html", summary=summary, flashcards=flashcards, quiz=quiz, concepts=[])


@app.route("/ask", methods=["POST"])
def ask():
    document_id = session.get("document_id", "")
    if not re.fullmatch(r"[0-9a-f]{32}\.pdf", document_id):
        return "Please upload a PDF first.", 400
    path = UPLOADS / document_id
    if not path.is_file():
        return "Your uploaded PDF is no longer available. Upload it again.", 400
    question = request.form.get("question", "").strip()[:1000]
    if not question:
        return "Please enter a question.", 400
    try:
        pages = extract_pages(path)
    except (PdfReadError, ValueError, OSError, KeyError):
        return "Unable to read the uploaded PDF.", 400
    terms = set(re.findall(r"\w+", question.lower())) - {"what", "is", "the", "a", "an", "how", "does", "do", "explain", "tell", "me"}
    best, best_score = "", 0
    for number, page in pages:
        for sentence in re.split(r"(?<=[.!?])\s+", page):
            overlap = len(terms & set(re.findall(r"\w+", sentence.lower())))
            if overlap > best_score:
                best, best_score = f"PDF page {number}: {sentence.strip()}", overlap
    if not best:
        best = "I couldn't find a relevant passage in your uploaded notes."
    return "<h2>Relevant passage from your PDF</h2><p>" + str(escape(best)) + '</p><p><a href="/">Back Home</a></p>'


if __name__ == "__main__":
    app.run(debug=False)
