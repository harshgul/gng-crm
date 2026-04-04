from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse
import pandas as pd

app = Flask(__name__)
app.secret_key = "supersecretkey"

# LOGIN SETUP
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

UNIVERSITIES = [
    "APIC","CQU","Flinders","Macquarie University","QUT","Swinburne",
    "UC , Sydney Hills","UNISc, Adelaide","UTAS (Melb/Sydney)",
    "VU (Brisbane/Sydney)","MIT","Curtin","Danford","Notre Dame","Other"
]

# ✅ DATABASE CONNECTION
def get_conn(dict_cursor=False):
    db_url = os.getenv("DATABASE_URL")
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
from flask_login import UserMixin

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

# 🔐 AUTH ROUTES
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
    c.execute("""
    SELECT leads.*, partners.name AS partner_name, partners.company AS partner_company
    FROM leads
    LEFT JOIN partners ON leads.partner_id = partners.id
    ORDER BY leads.id ASC
""")
    leads = c.fetchall()
    conn.close()

    return render_template("leads.html",
        leads=leads,
        universities=UNIVERSITIES,
        search_query="",
        selected_university="",
        selected_stage=""
    )

# ➕ ADD LEAD
@app.route("/add_lead", methods=["GET", "POST"])
@login_required
def add_lead():
    if request.method == "POST":
        data = request.form

        conn = get_conn()
        c = conn.cursor()

        c.execute("""
            INSERT INTO leads (name,email,phone,stage,notes,university,partner_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            data.get("name"),
            data.get("email"),
            data.get("phone"),
            data.get("stage"),
            data.get("notes"),
            data.get("university"),
            data.get("partner_id")
        ))

        conn.commit()
        conn.close()
        return redirect(url_for("leads"))

    return render_template("add_lead.html", universities=UNIVERSITIES,partners=partners)


# ✏️ EDIT LEAD
@app.route("/edit_lead/<int:id>", methods=["GET", "POST"])
@login_required
def edit_lead(id):
    conn = get_conn(dict_cursor=True)
    c = conn.cursor()

    if request.method == "POST":
        data = request.form

        c.execute("""
            UPDATE leads 
            SET name=%s,email=%s,phone=%s,stage=%s,notes=%s,university=%s, partner_id=%s
            WHERE id=%s
        """, (
            data.get("name"),
            data.get("email"),
            data.get("phone"),
            data.get("stage"),
            data.get("notes"),
            data.get("university"),
            data.get("partner_id"),
            id
        ))

        conn.commit()
        conn.close()
        return redirect(url_for("leads"))

    c.execute("SELECT * FROM leads WHERE id=%s", (id,))
    lead = c.fetchone()
    # fetch partners
    c.execute("SELECT id, name FROM partners ORDER BY name ASC")
    partners = c.fetchall()
    conn.close()

    return render_template("edit_lead.html", lead=lead, universities=UNIVERSITIES,partners=partners)

# ❌ DELETE LEAD
@app.route("/delete_lead/<int:id>")
@login_required
def delete_lead(id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM leads WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for("leads"))

# 🤝 PARTNERS
@app.route("/partners")
@login_required
def partners():
    conn = get_conn(dict_cursor=True)
    c = conn.cursor()

    c.execute("SELECT * FROM partners ORDER BY id ASC")
    partners = c.fetchall()

    conn.close()

    return render_template("partners.html", partners=partners)
#add partner
@app.route("/add-partner", methods=["GET", "POST"])
@login_required
def add_partner():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        phone = request.form.get("phone")
        company = request.form.get("company")
        location = request.form.get("location")

        conn = get_conn()
        c = conn.cursor()

        c.execute("""
            INSERT INTO partners (name, email, phone, company, location)
            VALUES (%s, %s, %s, %s, %s)
        """, (name, email, phone, company, location))

        conn.commit()
        conn.close()

        return redirect(url_for("partners"))

    return render_template("add_partner.html")

#edit partner
@app.route("/edit_partner/<int:id>", methods=["GET", "POST"])
@login_required
def edit_partner(id):
    conn = get_conn(dict_cursor=True)
    c = conn.cursor()

    if request.method == "POST":
        data = request.form

        c.execute("""
            UPDATE partners
            SET name=%s, email=%s, phone=%s, company=%s , location=%s 
            WHERE id=%s
        """, (
            data.get("name"),
            data.get("email"),
            data.get("phone"),
            data.get("company"),
            data.get("location"),
            id
        ))

        conn.commit()
        conn.close()
        return redirect(url_for("partners"))

    c.execute("SELECT * FROM partners WHERE id=%s", (id,))
    partner = c.fetchone()
    conn.close()

    return render_template("edit_partner.html", partner=partner)

#delete partner 
@app.route("/delete_partner/<int:id>")
@login_required
def delete_partner(id):
    conn = get_conn()
    c = conn.cursor()

    c.execute("DELETE FROM partners WHERE id = %s", (id,))
    conn.commit()
    conn.close()

    return redirect(url_for("partners"))

# 👥 TEAM / DEV
@app.route("/team")
@login_required
def team():
    return render_template("team.html")


# 📥 IMPORT LEADS
@app.route("/import_leads", methods=["POST"])
@login_required
def import_leads():
    file = request.files["file"]
    df = pd.read_excel(file)

    conn = get_conn()
    c = conn.cursor()

    for _, row in df.iterrows():
        c.execute("""
            INSERT INTO leads (name,email,phone,stage,notes,university)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (
            row.get("name"),
            row.get("email"),
            row.get("phone"),
            row.get("stage"),
            row.get("notes", ""),
            row.get("university", "")
        ))

    conn.commit()
    conn.close()
    return redirect(url_for("leads"))

# 🛠 CREATE TABLES
def create_tables():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT,
        full_name TEXT
    );
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id SERIAL PRIMARY KEY,
        name TEXT,
        email TEXT,
        phone TEXT,
        stage TEXT,
        notes TEXT,
        university TEXT
    );
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS partners (
        id SERIAL PRIMARY KEY,
        name TEXT,
        email TEXT,
        phone TEXT,
        company TEXT,
        location TEXT,
        added_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    c.execute("SELECT * FROM users WHERE username='admin'")
    if not c.fetchone():
        c.execute("""
            INSERT INTO users (username, password, role, full_name)
            VALUES ('admin', 'admin123', 'admin', 'Admin User')
        """)

    conn.commit()
    conn.close()

create_tables()

if __name__ == "__main__":
    app.run(debug=True)
