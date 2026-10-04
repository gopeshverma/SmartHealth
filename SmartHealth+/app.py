from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from flask import Flask, render_template, request, redirect, session, url_for, send_file
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
import tempfile
import pickle
import sqlite3
import os

app=Flask(__name__)
app.secret_key="supersecretkey123"

model=pickle.load(open("model.pkl","rb"))

def init_db():
    conn=sqlite3.connect("database.db")
    c=conn.cursor()

    #Patient records table
    c.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            patient_id TEXT,
            contact TEXT,
            age INTEGER,
            bmi REAL,
            heart_rate INTEGER,
            sleep_hours REAL,
            activity_level INTEGER,
            risk TEXT
        )
    """)

    #Users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    """)

    #Check if role column exists, if not add it
    c.execute("PRAGMA table_info(users)")
    columns=[col[1] for col in c.fetchall()]
    if "role" not in columns:
        c.execute("ALTER TABLE users ADD COLUMN role TEXT")

    #Default users
    default_users=[
        ("admin", "admin123", "admin"),
        ("doctor1", "doctor123", "doctor"),
        ("staff1", "staff123", "staff")
    ]

    for username, raw_password, role in default_users:
        c.execute("SELECT * FROM users WHERE username=?", (username,))
        user=c.fetchone()

        if not user:
            hashed_password=generate_password_hash(raw_password)
            c.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (username, hashed_password, role)
            )
        else:
            if len(user) < 4 or user[3] is None:
                c.execute(
                    "UPDATE users SET role=? WHERE username=?",
                    (role, username)
                )

    conn.commit()
    conn.close()

init_db()

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        username=request.form["username"]
        password=request.form["password"]

        conn=sqlite3.connect("database.db")
        c=conn.cursor()
        c.execute("SELECT * FROM users WHERE username=?", (username,))
        user=c.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            session["user"]=username
            session["role"]=user[3]
            return redirect(url_for("admin"))
        else:
            return "Invalid Credentials"

    return render_template("login.html")

@app.route("/predict", methods=["POST"])
def predict():
    name=request.form["name"]
    patient_id=request.form["patient_id"]
    contact=request.form["contact"]

    age=int(request.form["age"])
    bmi=float(request.form["bmi"])
    heart_rate=int(request.form["heart_rate"])
    sleep=float(request.form["sleep"])
    activity=int(request.form["activity"])

    prediction=model.predict([[age,bmi,heart_rate,sleep,activity]])[0]

    risk_map={0:"Low Risk",1:"Medium Risk",2:"High Risk"}
    risk=risk_map[prediction]

    if risk=="Low Risk":
        advice="You are healthy! Maintain a balanced diet, regular exercise, and good sleep routine."
    elif risk=="Medium Risk":
        advice="You need to improve your lifestyle. Focus on healthy eating, regular physical activity, and proper sleep."
    else:
        advice="High health risk detected. Immediate medical consultation is recommended. Improve diet, reduce stress, and monitor health closely."

    conn=sqlite3.connect("database.db")
    c=conn.cursor()

    c.execute("""
        INSERT INTO records
        (name, patient_id, contact, age, bmi, heart_rate, sleep_hours, activity_level, risk)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,(name, patient_id, contact, age, bmi, heart_rate, sleep, activity, risk))

    conn.commit()
    conn.close()

    return render_template(
        "result.html",
        risk=risk,
        advice=advice,
        name=name,
        patient_id=patient_id,
        contact=contact,
        age=age,
        bmi=bmi,
        heart_rate=heart_rate,
        sleep=sleep,
        activity=activity
    )

@app.route("/download")
def download():
    name=request.args.get("name")
    patient_id=request.args.get("patient_id")
    contact=request.args.get("contact")
    age=request.args.get("age")
    bmi=request.args.get("bmi")
    heart_rate=request.args.get("heart_rate")
    sleep=request.args.get("sleep")
    activity=request.args.get("activity")
    risk=request.args.get("risk")

    temp_file=tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf_path=temp_file.name
    temp_file.close()

    doc=SimpleDocTemplate(pdf_path)
    styles=getSampleStyleSheet()

    story=[]
    story.append(Paragraph("SmartHealth+ Medical Report", styles["Title"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"Patient Name: {name}", styles["Normal"]))
    story.append(Paragraph(f"Patient ID: {patient_id}", styles["Normal"]))
    story.append(Paragraph(f"Contact: {contact}", styles["Normal"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Health Data", styles["Heading2"]))
    story.append(Paragraph(f"Age: {age}", styles["Normal"]))
    story.append(Paragraph(f"BMI: {bmi}", styles["Normal"]))
    story.append(Paragraph(f"Heart Rate: {heart_rate}", styles["Normal"]))
    story.append(Paragraph(f"Sleep Hours: {sleep}", styles["Normal"]))
    story.append(Paragraph(f"Activity Level: {activity}", styles["Normal"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"Risk Level: {risk}", styles["Heading2"]))

    if risk=="Low Risk":
        advice="You are healthy! Maintain a balanced diet, exercise regularly, and sleep well."
    elif risk=="Medium Risk":
        advice="Improve your lifestyle. Focus on diet, exercise, and sleep quality."
    else:
        advice="High risk detected. Immediate consultation with a doctor is strongly recommended."

    story.append(Paragraph("Recommendation:", styles["Heading2"]))
    story.append(Paragraph(advice, styles["Normal"]))

    doc.build(story)

    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=f"{patient_id}_report.pdf"
    )

@app.route("/admin")
def admin():
    if "user" not in session:
        return redirect(url_for("login"))

    search=request.args.get("search")
    filter_type=request.args.get("filter")

    conn=sqlite3.connect("database.db")
    c=conn.cursor()

    query="SELECT * FROM records WHERE 1=1"
    params=[]

    if search:
        query+=" AND (name LIKE ? OR patient_id LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    if filter_type=="high":
        query+=" AND risk='High Risk'"
    elif filter_type=="recent":
        query+=" ORDER BY id DESC LIMIT 5"

    c.execute(query, params)
    data=c.fetchall()

    c.execute("SELECT COUNT(*) FROM records WHERE risk='Low Risk'")
    low=c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM records WHERE risk='Medium Risk'")
    medium=c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM records WHERE risk='High Risk'")
    high=c.fetchone()[0]

    c.execute("SELECT AVG(bmi) FROM records")
    avg_bmi=c.fetchone()[0]
    if avg_bmi is None:
        avg_bmi=0

    conn.close()

    return render_template(
        "admin.html",
        data=data,
        low=low,
        medium=medium,
        high=high,
        avg_bmi=avg_bmi,
        username=session.get("user"),
        role=session.get("role")
    )

@app.route("/delete/<int:id>")
def delete(id):
    if "user" not in session:
        return redirect(url_for("login"))

    if session.get("role")!="admin":
        return "Access Denied: Only admin can delete records."

    conn=sqlite3.connect("database.db")
    c=conn.cursor()
    c.execute("DELETE FROM records WHERE id=?", (id,))
    conn.commit()
    conn.close()

    return redirect("/admin")

@app.route("/edit/<int:id>")
def edit(id):
    if "user" not in session:
        return redirect(url_for("login"))

    if session.get("role") not in ["admin","doctor"]:
        return "Access Denied: Only admin or doctor can edit records."

    conn=sqlite3.connect("database.db")
    c=conn.cursor()
    c.execute("SELECT * FROM records WHERE id=?", (id,))
    record=c.fetchone()
    conn.close()

    return render_template("edit.html", record=record)

@app.route("/update/<int:id>", methods=["POST"])
def update(id):
    if "user" not in session:
        return redirect(url_for("login"))

    if session.get("role") not in ["admin","doctor"]:
        return "Access Denied: Only admin or doctor can update records."

    name=request.form["name"]
    patient_id=request.form["patient_id"]
    contact=request.form["contact"]
    age=request.form["age"]
    bmi=request.form["bmi"]
    heart_rate=request.form["heart_rate"]
    sleep=request.form["sleep"]
    activity=request.form["activity"]

    conn=sqlite3.connect("database.db")
    c=conn.cursor()

    c.execute("""
        UPDATE records
        SET name=?, patient_id=?, contact=?, age=?, bmi=?, heart_rate=?, sleep_hours=?, activity_level=?
        WHERE id=?
    """,(name, patient_id, contact, age, bmi, heart_rate, sleep, activity, id))

    conn.commit()
    conn.close()

    return redirect("/admin")

@app.route("/logout")
def logout():
    session.pop("user", None)
    session.pop("role", None)
    return redirect(url_for("login"))

if __name__=="__main__":
    app.run(debug=True)
    #For deployment
    #app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))