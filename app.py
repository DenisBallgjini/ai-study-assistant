from flask import Flask, render_template, request
from PyPDF2 import PdfReader
from collections import Counter
import os
import re

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


def generate_questions(text):

    words = re.findall(r'\b[a-zA-Z]{6,}\b', text)

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

def generate_flashcards(concepts):

    flashcards = []

    for concept in concepts:

        flashcards.append({

            "question":
            f"What is {concept}?",

            "answer":
            f"{concept} is an important concept detected in your notes."

        })

    return flashcards


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():

    file = request.files["pdf"]

    if file:

        filepath = os.path.join(
            app.config["UPLOAD_FOLDER"],
            file.filename
        )

        file.save(filepath)

        reader = PdfReader(filepath)

        text = ""

        for page in reader.pages:

            extracted = page.extract_text()

            if extracted:
                text += extracted

        summary = text[:700]

        quiz = generate_questions(text)

        concepts = extract_concepts(text)

        flashcards = generate_flashcards(
    concepts
)

        return render_template(
    "summary.html",
    summary=summary,
    quiz=quiz,
    concepts=concepts,
    flashcards=flashcards
)

    return "No file uploaded"


if __name__ == "__main__":
    app.run(debug=True)