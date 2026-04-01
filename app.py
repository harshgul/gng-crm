from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
import pandas as pd

UNIVERSITIES = [
    "APIC","CQU","Flinders","Macquarie University","QUT","Swinburne",
    "UC , Sydney Hills","UNISc, Adelaide","UTAS (Melb/Sydney)",
    "VU (Brisbane/Sydney)","MIT","Curtin","Danford","Notre Dame","Other"
]

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"xlsx", "xls"}

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ✅ PostgreSQL Connection
def get_conn(dict_cursor=False):
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise Exception("DATABASE_URL not set")

    result = urlparse(db_url)

    return psycopg2.connect(
        database=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port,
        cursor_factory=RealDictCursor if dict_cursor else None
    )

# 👤 USER CLASS
class User(UserMixin):
    def __init__(self, id, username, role, full_name):
        self.id = id
        self.username = username
        self.role = role
        self.full_name = full_name

@login_manager.user_loader
def load_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, username, role, full_name FROM users WHERE id=%s", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return User(id=row[0], username=row[1], role=row[2], full_name=row[3])
    return None

@app.route("/")
def home():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT id, username, password, role, full_name FROM users WHERE username=%s", (username,))
        row = c.fetchone()
        conn.close()

        if row and row[2] == password:
            user = User(id=row[0], username=row[1], role=row[3], full_name=row[4])
            login_user(user)
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password", "danger")

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

# 📊 DASHBOARD
@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_conn(dict_cursor=True)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) as cnt FROM leads")
    leads_count = c.fetchone()["cnt"]

    c.execute("SELECT COUNT(*) as cnt FROM leads WHERE stage IN ('offer','coe','visa-grant')")
    apps_count = c.fetchone()["cnt"]

    c.execute("SELECT COUNT(*) as cnt FROM leads WHERE stage='coe'")
    coe_count = c.fetchone()["cnt"]

    c.execute("SELECT COUNT(*) as cnt FROM leads WHERE stage='visa-grant'")
    visa_count = c.fetchone()["cnt"]

    conn.close()

    return render_template("dashboard.html",
        leads_count=leads_count,
        apps_count=apps_count,
        coe_count=coe_count,
        visa_count=visa_count
    )

# 📋 LEADS
@app.route("/leads")
@login_required
def leads():
    conn = get_conn(dict_cursor=True)
    c = conn.cursor()
    c.execute("SELECT * FROM leads ORDER BY id ASC")
    leads = c.fetchall()
    conn.close()
    return render_template("leads.html", leads=leads)

# ➕ ADD LEAD
@app.route("/add_lead", methods=["POST"])
@login_required
def add_lead():
    data = request.form
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        INSERT INTO leads (name,email,phone,stage,notes,university)
        VALUES (%s,%s,%s,%s,%s,%s)
    """, (
        data.get("name"),
        data.get("email"),
        data.get("phone"),
        data.get("stage"),
        data.get("notes"),
        data.get("university")
    ))

    conn.commit()
    conn.close()
    return redirect(url_for("leads"))

# ✏️ EDIT LEAD
@app.route("/edit_lead/<int:id>", methods=["POST"])
@login_required
def edit_lead(id):
    data = request.form
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        UPDATE leads SET name=%s,email=%s,phone=%s,stage=%s,notes=%s,university=%s
        WHERE id=%s
    """, (
        data.get("name"),
        data.get("email"),
        data.get("phone"),
        data.get("stage"),
        data.get("notes"),
        data.get("university"),
        id
    ))

    conn.commit()
    conn.close()
    return redirect(url_for("leads"))

# ❌ DELETE
@app.route("/delete_lead/<int:id>")
@login_required
def delete_lead(id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM leads WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for("leads"))

# 📥 IMPORT
@app.route("/import_leads", methods=["POST"])
@login_required
def import_leads():
    file = request.files["file"]
    df = pd.read_excel(file)

    conn = get_conn()
    c = conn.cursor()

    for _, row in df.iterrows():
        c.execute("""
            INSERT INTO leads (name,email,phone,stage,notes)
            VALUES (%s,%s,%s,%s,%s)
        """, (
            row.get("name"),
            row.get("email"),
            row.get("phone"),
            row.get("stage"),
            row.get("notes", "")
        ))

    conn.commit()
    conn.close()
    return redirect(url_for("leads"))

if __name__ == "__main__":
    app.run()
