from flask import Flask, render_template, request, session
from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError
from collections import Counter
import os
import re
import uuid
from pathlib import Path

secret_file = Path(".flask_secret_key")
if not secret_file.exists():
    secret_file.write_text(os.urandom(32).hex())
    secret_file.chmod(0o600)

app = Flask(__name__)
app.secret_key = secret_file.read_text().strip()

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024



def create_summary(text):
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if len(sentence.strip()) > 40
    ]

    if not sentences:
        return "No sufficient text found to summarize."

    max_points = min(8, len(sentences))
    selected = []

    for i in range(max_points):
        index = i * len(sentences) // max_points
        selected.append(sentences[index])

    summary = "📌 Main Points\n\n"
    summary += "\n\n".join("• " + sentence for sentence in selected)

    return summary


def generate_questions(text):

    words = re.findall(
        r'\b[a-zA-Z]{6,}\b',
        text
    )

    common_words = Counter(words)

    topics = []

    for word, count in common_words.most_common(3):

        topics.append(word)

    questions = []

    for topic in topics:

        questions.append(
            f"What is {topic}?"
        )

        questions.append(
            f"Explain the role of {topic}."
        )

    return questions


def extract_concepts(text):

    words = re.findall(
        r'\b[a-zA-Z]{6,}\b',
        text
    )

    common_words = Counter(words)

    concepts = []

    for word, count in common_words.most_common(5):

        concepts.append(word)

    return concepts


def generate_flashcards(concepts, text):

    flashcards = []

    sentences = text.split(".")

    for concept in concepts:

        answer = "No definition found."

        for sentence in sentences:

            if concept.lower() in sentence.lower():

                answer = sentence.strip()

                break

        flashcards.append({

            "question":
            f"What is {concept}?",

            "answer":
            answer

        })

    return flashcards


@app.route("/")
def home():

    return render_template(
        "index.html"
    )


@app.route("/upload", methods=["POST"])
def upload():


    file = request.files.get("pdf")

    if not file or not file.filename:
        return "Please select a PDF file.", 400

    if not file.filename.lower().endswith(".pdf"):
        return "Only PDF files are allowed.", 400

    if file:

        filepath = os.path.join(
            app.config["UPLOAD_FOLDER"],
            f"{uuid.uuid4().hex}.pdf"
        )

        file.save(filepath)

        try:
            reader = PdfReader(filepath)
            text = ""

            for page in reader.pages:
                extracted = page.extract_text()

                if extracted:
                    text += extracted + "\n"

        except (PdfReadError, ValueError, OSError, KeyError):
            os.remove(filepath)
            return "Unable to read this PDF. Please upload a valid PDF file.", 400

        if not text.strip():
            os.remove(filepath)
            return "This PDF contains no extractable text.", 400

        session["document_id"] = os.path.basename(filepath)

        summary = create_summary(
            text
        )

        quiz = generate_questions(
            text
        )

        concepts = extract_concepts(
            text
        )

        flashcards = generate_flashcards(
            concepts,
            text
        )

        return render_template(
            "summary.html",
            summary=summary,
            quiz=quiz,
            concepts=concepts,
            flashcards=flashcards
        )

    return "No file uploaded"


@app.route("/ask", methods=["POST"])
def ask():

    document_id = session.get("document_id")

    if not document_id:
        return "Please upload a PDF before asking questions.", 400

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], document_id)

    if not os.path.isfile(filepath):
        return "Your uploaded PDF is no longer available. Please upload it again.", 400

    try:
        reader = PdfReader(filepath)
        stored_text = "\n".join(
            page.extract_text() or "" for page in reader.pages
        )
    except (PdfReadError, ValueError, OSError, KeyError):
        return "Unable to read your uploaded PDF.", 400

    question = request.form["question"]

    sentences = stored_text.split(".")

    question_words = set(
        re.findall(
            r'\w+',
            question.lower()
        )
    )

    stop_words = {

        "what",
        "is",
        "the",
        "a",
        "an",
        "how",
        "does",
        "do",
        "explain",
        "tell",
        "me"

    }

    question_words = {

        word

        for word in question_words

        if word not in stop_words

    }

    best_match = ""

    best_score = 0

    for sentence in sentences:

        sentence_words = set(

            re.findall(
                r'\w+',
                sentence.lower()
            )

        )

        score = len(

            question_words
            &
            sentence_words

        )

        if score > best_score:

            best_score = score

            best_match = sentence

    if best_score == 0:

        best_match = (
            "I couldn't find a relevant answer in your uploaded notes."
        )

    return f"""

    <h2>Answer</h2>

    <p>{best_match}</p>

    <br>

    <a href="/">

    Back Home

    </a>

    """


if __name__ == "__main__":

    app.run(debug=True)