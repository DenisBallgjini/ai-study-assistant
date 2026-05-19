from flask import Flask, render_template, request
from PyPDF2 import PdfReader
from collections import Counter
import os
import re

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

stored_text = ""


def create_summary(text):

    sentences = text.split(".")

    summary = "📌 Main Points\n\n"

    count = 0

    for sentence in sentences:

        sentence = sentence.strip()

        if len(sentence) > 40:

            summary += "• " + sentence + "\n\n"

            count += 1

        if count == 8:

            break

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

    global stored_text

    file = request.files["pdf"]

    if file:

        filepath = os.path.join(
            app.config["UPLOAD_FOLDER"],
            file.filename
        )

        file.save(filepath)

        reader = PdfReader(
            filepath
        )

        text = ""

        for page in reader.pages:

            extracted = page.extract_text()

            if extracted:

                text += extracted

        stored_text = text

        summary = create_summary(
            text[:3000]
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

    global stored_text

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