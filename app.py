from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
from functools import wraps
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "studybuddy_change_this_secret"

# Keep the database in the same folder as app.py so it is not accidentally
# created in a different working directory when Flask is started elsewhere.
DB = str(Path(__file__).resolve().parent / "studybuddy.db")


def connect_db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = connect_db()

    con.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            subject TEXT,
            due_date TEXT,
            completed INTEGER DEFAULT 0
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            total INTEGER DEFAULT 0,
            attended INTEGER DEFAULT 0,
            UNIQUE(user_id, subject)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS timetable(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            subject TEXT NOT NULL,
            class_time TEXT NOT NULL
        )
    """)

    con.commit()
    con.close()


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/")
        return function(*args, **kwargs)
    return wrapper


@app.route("/", methods=["GET", "POST"])
def index():
    if "user_id" in session:
        return redirect("/dashboard")

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        con = connect_db()

        if action == "signup":
            name = request.form.get("name", "").strip()

            if not name or not email or len(password) < 6:
                flash("Enter all details. Password must have at least 6 characters.")
            else:
                try:
                    con.execute(
                        "INSERT INTO users(name, email, password) VALUES(?,?,?)",
                        (name, email, generate_password_hash(password))
                    )
                    con.commit()

                    user = con.execute(
                        "SELECT * FROM users WHERE email = ?", (email,)
                    ).fetchone()

                    session["user_id"] = user["id"]
                    session["name"] = user["name"]
                    session["user_name"] = user["name"]

                    con.close()
                    return redirect("/dashboard")
                except sqlite3.IntegrityError:
                    flash("Email already registered. Please login.")

        elif action == "login":
            user = con.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()

            if user and check_password_hash(user["password"], password):
                session["user_id"] = user["id"]
                session["name"] = user["name"]
                session["user_name"] = user["name"]
                con.close()
                return redirect("/dashboard")
            else:
                flash("Invalid email or password.")
        else:
            flash("Please choose Login or Sign Up.")

        con.close()

    return render_template("index.html")


@app.route("/dashboard")
@login_required
def dashboard():
    con = connect_db()
    uid = session["user_id"]

    tasks = con.execute(
        "SELECT * FROM tasks WHERE user_id = ? ORDER BY completed, id DESC",
        (uid,)
    ).fetchall()

    notes = con.execute(
        "SELECT * FROM notes WHERE user_id = ? ORDER BY id DESC",
        (uid,)
    ).fetchall()

    attendance = con.execute(
        "SELECT * FROM attendance WHERE user_id = ? ORDER BY subject",
        (uid,)
    ).fetchall()

    timetable = con.execute(
        """SELECT * FROM timetable
           WHERE user_id = ?
           ORDER BY CASE day
             WHEN 'Monday' THEN 1
             WHEN 'Tuesday' THEN 2
             WHEN 'Wednesday' THEN 3
             WHEN 'Thursday' THEN 4
             WHEN 'Friday' THEN 5
             WHEN 'Saturday' THEN 6
             ELSE 7 END, class_time""",
        (uid,)
    ).fetchall()

    con.close()

    pending = sum(1 for task in tasks if not task["completed"])
    total_classes = sum(row["total"] for row in attendance)
    attended_classes = sum(row["attended"] for row in attendance)
    percentage = round(attended_classes / total_classes * 100, 1) if total_classes else 0

    return render_template(
        "index.html",
        page="dashboard",
        name=session.get("name", session.get("user_name", "Student")),
        tasks=tasks,
        notes=notes,
        attendance=attendance,
        timetable=timetable,
        pending=pending,
        total_classes=total_classes,
        attended_classes=attended_classes,
        percentage=percentage
    )


# Add task: accept both "task" (current HTML) and "title" (older HTML).
@app.route("/add-task", methods=["POST"])
@login_required
def add_task():
    title = (request.form.get("task") or request.form.get("title") or "").strip()
    subject = request.form.get("subject", "").strip()
    due_date = request.form.get("due_date", "").strip()

    if not title:
        flash("Please enter a task before adding it.")
        return redirect("/dashboard#tasks")

    con = connect_db()
    con.execute(
        "INSERT INTO tasks(user_id, title, subject, due_date) VALUES(?,?,?,?)",
        (session["user_id"], title, subject, due_date)
    )
    con.commit()
    con.close()
    flash("Task saved.")
    return redirect("/dashboard#tasks")


# Accept GET because the current HTML uses clickable links; POST is also supported.
@app.route("/complete-task/<int:task_id>", methods=["GET", "POST"])
@login_required
def complete_task(task_id):
    con = connect_db()
    con.execute(
        """UPDATE tasks SET completed = 1 - completed
           WHERE id = ? AND user_id = ?""",
        (task_id, session["user_id"])
    )
    con.commit()
    con.close()
    return redirect("/dashboard#tasks")


@app.route("/delete-task/<int:task_id>", methods=["GET", "POST"])
@login_required
def delete_task(task_id):
    con = connect_db()
    con.execute(
        "DELETE FROM tasks WHERE id = ? AND user_id = ?",
        (task_id, session["user_id"])
    )
    con.commit()
    con.close()
    return redirect("/dashboard#tasks")


@app.route("/add-attendance", methods=["POST"])
@login_required
def add_attendance():
    subject = request.form.get("subject", "").strip()

    try:
        total = int(request.form.get("total", 0))
        attended = int(request.form.get("attended", 0))
    except (TypeError, ValueError):
        flash("Enter valid attendance numbers.")
        return redirect("/dashboard#attendance")

    if not subject or total <= 0 or attended < 0 or attended > total:
        flash("Check attendance: attended classes must be between 0 and total classes.")
        return redirect("/dashboard#attendance")

    con = connect_db()
    con.execute("""
        INSERT INTO attendance(user_id, subject, total, attended)
        VALUES(?,?,?,?)
        ON CONFLICT(user_id, subject)
        DO UPDATE SET total = excluded.total, attended = excluded.attended
    """, (session["user_id"], subject, total, attended))
    con.commit()
    con.close()
    flash("Attendance saved.")
    return redirect("/dashboard#attendance")


@app.route("/delete-attendance/<int:item_id>", methods=["GET", "POST"])
@login_required
def delete_attendance(item_id):
    con = connect_db()
    con.execute(
        "DELETE FROM attendance WHERE id = ? AND user_id = ?",
        (item_id, session["user_id"])
    )
    con.commit()
    con.close()
    return redirect("/dashboard#attendance")


@app.route("/add-note", methods=["POST"])
@login_required
def add_note():
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()

    if title and content:
        con = connect_db()
        con.execute(
            "INSERT INTO notes(user_id, title, content) VALUES(?,?,?)",
            (session["user_id"], title, content)
        )
        con.commit()
        con.close()
        flash("Note saved.")
    else:
        flash("Enter both a note title and note content.")

    return redirect("/dashboard#notes")


@app.route("/delete-note/<int:note_id>", methods=["GET", "POST"])
@login_required
def delete_note(note_id):
    con = connect_db()
    con.execute(
        "DELETE FROM notes WHERE id = ? AND user_id = ?",
        (note_id, session["user_id"])
    )
    con.commit()
    con.close()
    return redirect("/dashboard#notes")


# Accept both "start_time" (current HTML) and "class_time" (older HTML).
@app.route("/add-timetable", methods=["POST"])
@login_required
def add_timetable():
    day = request.form.get("day", "").strip()
    subject = request.form.get("subject", "").strip()
    class_time = (
        request.form.get("start_time")
        or request.form.get("class_time")
        or ""
    ).strip()

    valid_days = [
        "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday"
    ]

    if day not in valid_days or not subject or not class_time:
        flash("Please select a day, enter a subject, and choose a start time.")
        return redirect("/dashboard#timetable")

    con = connect_db()
    con.execute(
        "INSERT INTO timetable(user_id, day, subject, class_time) VALUES(?,?,?,?)",
        (session["user_id"], day, subject, class_time)
    )
    con.commit()
    con.close()
    flash("Timetable entry saved.")
    return redirect("/dashboard#timetable")


@app.route("/delete-timetable/<int:item_id>", methods=["GET", "POST"])
@login_required
def delete_timetable(item_id):
    con = connect_db()
    con.execute(
        "DELETE FROM timetable WHERE id = ? AND user_id = ?",
        (item_id, session["user_id"])
    )
    con.commit()
    con.close()
    return redirect("/dashboard#timetable")


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect("/")


# Forgot-password page route is not included here because a secure password reset
# requires a real verification flow; keep your existing route if you already have one.
init_db()

if __name__ == "__main__":
    app.run(debug=True)
