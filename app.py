from flask import Flask, render_template, request, redirect, url_for, session
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta
import random
import smtplib
from email.message import EmailMessage
from textblob import TextBlob
import matplotlib
import os

matplotlib.use("Agg")
import matplotlib.pyplot as plt

app = Flask(__name__)
app.secret_key = "secret123"

# ---------------- DB ----------------
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "admin",
    "database": "testdb1",
}

db = mysql.connector.connect(**DB_CONFIG)
cursor = db.cursor(dictionary=True)


def ensure_db_connection():
    global db, cursor
    try:
        if not db.is_connected():
            db.reconnect(attempts=3, delay=2)
            cursor = db.cursor(dictionary=True)
    except Error:
        db = mysql.connector.connect(**DB_CONFIG)
        cursor = db.cursor(dictionary=True)


# ---------------- EMAIL CONFIG ----------------
SENDER_EMAIL = "smartdiaryonline.app@gmail.com"
APP_PASSWORD = "lgtz ezel wfhb tifu"


def send_otp(email, otp):
    msg = EmailMessage()
    msg["Subject"] = "SmartDiary OTP Verification"
    msg["From"] = SENDER_EMAIL
    msg["To"] = email
    msg.set_content(f"Your OTP is {otp}. Valid for 10 minutes.")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.send_message(msg)


# ---------------- LOGIN ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    ensure_db_connection()

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        cursor.execute(
            "SELECT * FROM users WHERE username=%s AND password=%s AND verified=1",
            (username, password),
        )
        user = cursor.fetchone()

        if user:
            session["username"] = username
            return redirect(url_for("dashboard"))

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")


# ---------------- REGISTER EMAIL ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    ensure_db_connection()

    if request.method == "POST":
        email = request.form["email"]
        otp = str(random.randint(100000, 999999))

        cursor.execute("DELETE FROM email_otps WHERE email=%s", (email,))
        cursor.execute(
            "INSERT INTO email_otps (email, otp, created_at) VALUES (%s,%s,%s)",
            (email, otp, datetime.now()),
        )
        db.commit()

        try:
            send_otp(email, otp)
        except Exception:
            return render_template(
                "register.html",
                error="Unable to send OTP right now. Please try again.",
            )

        return redirect(url_for("verify_register", email=email))

    return render_template("register.html")


# ---------------- VERIFY OTP ----------------
@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    ensure_db_connection()
    email = request.args.get("email")

    if request.method == "POST":
        email = request.form["email"]
        otp = request.form["otp"]
        username = request.form["username"]
        password = request.form["password"]

        cursor.execute(
            "SELECT * FROM email_otps WHERE email=%s AND otp=%s",
            (email, otp),
        )
        record = cursor.fetchone()

        if not record:
            return render_template(
                "verify_register.html",
                email=email,
                error="Invalid or expired OTP",
            )

        if datetime.now() - record["created_at"] > timedelta(minutes=10):
            cursor.execute("DELETE FROM email_otps WHERE email=%s", (email,))
            db.commit()
            return render_template(
                "verify_register.html",
                email=email,
                error="OTP expired. Please request a new one.",
            )

        cursor.execute(
            "SELECT * FROM users WHERE username=%s OR email=%s",
            (username, email),
        )
        existing = cursor.fetchone()
        if existing:
            return render_template(
                "verify_register.html",
                email=email,
                error="Username or email already exists.",
            )

        cursor.execute(
            """
            INSERT INTO users (username,password,email,verified,created_at)
            VALUES (%s,%s,%s,1,%s)
            """,
            (username, password, email, datetime.now()),
        )
        cursor.execute("DELETE FROM email_otps WHERE email=%s", (email,))
        db.commit()

        return redirect(url_for("login"))

    return render_template("verify_register.html", email=email)


# ---------------- DASHBOARD ----------------
@app.route("/dashboard")
def dashboard():
    ensure_db_connection()
    if "username" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html")


# ---------------- NEW ENTRY ----------------
@app.route("/new_entry", methods=["GET", "POST"])
def new_entry():
    ensure_db_connection()
    if "username" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        text = request.form["entry_text"]
        polarity = TextBlob(text).sentiment.polarity

        if polarity > 0.15:
            mood = "Happy"
        elif polarity < -0.15:
            mood = "Sad"
        else:
            mood = "Neutral"

        cursor.execute(
            """
            INSERT INTO diary_entries (username,entry_text,mood,created_at)
            VALUES (%s,%s,%s,%s)
            """,
            (session["username"], text, mood, datetime.now()),
        )
        db.commit()

        return redirect(url_for("diary"))

    return render_template("new_entry.html")


# ---------------- DIARY ----------------
@app.route("/diary")
def diary():
    ensure_db_connection()
    if "username" not in session:
        return redirect(url_for("login"))

    cursor.execute(
        "SELECT * FROM diary_entries WHERE username=%s ORDER BY created_at DESC",
        (session["username"],),
    )
    entries = cursor.fetchall()

    return render_template("diary.html", entries=entries)


# ---------------- INSIGHTS (GRAPH + AI) ----------------
@app.route("/insights")
def insights():
    ensure_db_connection()
    if "username" not in session:
        return redirect(url_for("login"))

    cursor.execute(
        "SELECT created_at, mood FROM diary_entries WHERE username=%s ORDER BY created_at",
        (session["username"],),
    )
    data = cursor.fetchall()

    if not data:
        return render_template(
            "insights.html",
            dates=[],
            mood_values=[],
            advice="Start writing entries to unlock insights.",
        )

    dates = []
    values = []
    mood_map = {"Happy": 1, "Neutral": 0, "Sad": -1}

    for row in data:
        dates.append(row["created_at"].date().isoformat())
        values.append(mood_map.get(row["mood"], 0))

    # ----- Optional server-side graph image generation -----
    plt.figure(figsize=(6, 3))
    plt.plot(dates, values, marker="o")
    plt.yticks([-1, 0, 1], ["Sad", "Neutral", "Happy"])
    plt.xlabel("Date")
    plt.ylabel("Mood")
    plt.tight_layout()

    if not os.path.exists("static"):
        os.mkdir("static")

    plt.savefig("static/mood_graph.png")
    plt.close()

    avg = sum(values) / len(values)

    if avg > 0.3:
        advice = (
            "Your emotional trend shows consistent positivity. "
            "You are emotionally resilient and in a healthy mental phase. "
            "Keep journaling, practicing gratitude, and maintaining routines."
        )
    elif avg < -0.3:
        advice = (
            "Your recent emotional pattern suggests emotional strain. "
            "This is not a failure; it is a signal. Consider slowing down, "
            "talking to someone you trust, and doing grounding activities."
        )
    else:
        advice = (
            "Your emotions fluctuate naturally, indicating balance with moments "
            "of stress. Try mindfulness, better sleep routines, and self-reflection."
        )

    return render_template(
        "insights.html",
        dates=dates,
        mood_values=values,
        advice=advice,
    )


# ---------------- LOGOUT ----------------
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
