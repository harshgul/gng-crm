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

    # ✅ Counts
    c.execute("SELECT COUNT(*) AS total FROM leads")
    leads_count = c.fetchone()["total"]

    c.execute("SELECT COUNT(*) AS total FROM leads WHERE stage IN ('offer','ucol','coe','visa-grant')")
    apps_count = c.fetchone()["total"]

    c.execute("SELECT COUNT(*) AS total FROM leads WHERE stage='coe'")
    coe_count = c.fetchone()["total"]

    c.execute("SELECT COUNT(*) AS total FROM leads WHERE stage='visa-grant'")
    visa_count = c.fetchone()["total"]

    # ✅ COE Summary
    c.execute("""
        SELECT university, COUNT(*) AS total
        FROM leads
        WHERE stage='coe'
        GROUP BY university
    """)
    coe_summary = c.fetchall()

    # ✅ PIPELINE (THIS IS THE IMPORTANT PART)
    stages = [
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('assessment', 'Assessment'),
        ('gs', 'GS'),
        ('on-hold', 'On Hold'),
        ('offer', 'Offer'),
        ('ucol', 'UCOL'),
        ('coe', 'COE'),
        ('visa-grant', 'Visa Grant')
    ]

    pipeline = []

    for key, label in stages:
        c.execute("""
            SELECT leads.*, partners.company AS partner_company
            FROM leads
            LEFT JOIN partners ON leads.partner_id = partners.id
            WHERE stage=%s
        """, (key,))
        items = c.fetchall()

        pipeline.append((key, label, items))

    conn.close()

    return render_template(
        "dashboard.html",
        leads_count=leads_count,
        apps_count=apps_count,
        coe_count=coe_count,
        visa_count=visa_count,
        coe_summary=coe_summary,
        pipeline=pipeline
    )
#about
@app.route("/about")
@login_required   # optional, remove if you want it public
def about():
    return render_template("about.html")

# 📋 LEADS
@app.route("/leads")
@login_required
def leads():
    search_query = request.args.get("q", "").strip()
    university = request.args.get("university", "").strip()
    stage = request.args.get("stage", "").strip()

    conn = get_conn(dict_cursor=True)
    c = conn.cursor()

    base_query = """
    SELECT 
        leads.*, 
        partners.name AS partner_name,
        partners.company AS partner_company
    FROM leads
    LEFT JOIN partners 
        ON leads.partner_id = partners.id
    WHERE 1=1
    """

    params = []

    if search_query:
        base_query += """
        AND (
            leads.name LIKE %s OR 
            leads.email LIKE %s OR 
            leads.phone LIKE %s OR 
            partners.company LIKE %s
        )
        """
        params.extend([f"%{search_query}%"] * 4)

    if university:
        base_query += " AND leads.university = %s"
        params.append(university)

    if stage:
        base_query += " AND leads.stage = %s"
        params.append(stage)

    base_query += " ORDER BY leads.id ASC"

    c.execute(base_query, params)
    leads = c.fetchall()
    conn.close()

    return render_template(
        "leads.html",
        leads=leads,
        search_query=search_query,
        universities=UNIVERSITIES,
        selected_university=university,
        selected_stage=stage
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
    c.execute("SELECT id, company FROM partners ORDER BY company ASC")
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



# 📥 IMPORT LEADS
@app.route("/import-leads", methods=["GET", "POST"])
@login_required
def import_leads():
    if request.method == "POST":
        file = request.files.get("file")

        if not file:
            flash("No file uploaded", "danger")
            return redirect(url_for("import_leads"))

        try:
            import pandas as pd
            df = pd.read_excel(file)

            conn = get_conn()
            c = conn.cursor()

            for _, row in df.iterrows():
                c.execute("""
                    INSERT INTO leads (name, email, phone, stage, notes)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    row.get("name"),
                    row.get("email"),
                    row.get("phone"),
                    row.get("stage"),
                    row.get("notes")
                ))

            conn.commit()
            conn.close()

            flash("Leads imported successfully!", "success")
            return redirect(url_for("leads"))

        except Exception as e:
            print("IMPORT ERROR:", e)
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for("import_leads"))

    # ✅ THIS FIXES YOUR ERROR
    return render_template("import_leads.html")

#team 
@app.route("/team")
@login_required
def team():
    team_members = [
        {
            "name": "Raj Guleria",
            "role": "CEO",
            "image": "team/raj.jpg",
            "bio": "Founder of Guleria & Guleria Consultants with over 10 years of experience in international education and student recruitment."
        },
        
        {
            "name": "Minakshi",
            "role": "Senior Counsellor (Mohali Office)",
            "image": "team/meenakshi.jpg",
            "bio": "Student counselor at the Mohali branch, dedicated to helping students choose the right courses and career paths."
        },
        {
            "name": "Harsh Guleria",
            "role": "Managing Director (Operations)",
            "image": "team/harsh.jpg",
            "bio": "Oversees day-to-day operations and ensures smooth functioning across all branches with a focus on student success."
        },
        {
            "name": "Saurabh",
            "role": "Regional Manager (UP)",
            "image": "team/saurabh.jpg",
            "bio": "Responsible for managing operations in Uttar Pradesh and guiding students through their admission journey."
        },
        
        {
            "name": "Devansh",
            "role": "GTE Compliance Officer (Kanpur)",
            "image": "team/devansh.jpg",
            "bio": "Ensures all applications meet Genuine Temporary Entrant (GTE) requirements and compliance standards."
        },
        {
            "name": "Ankita",
            "role": "Admissions Officer (Kanpur)",
            "image": "team/ankita.jpg",
            "bio": "Guides students in preparing strong applications and assists with admissions formalities."
        },
        {
            "name": "Parul",
            "role": "Admissions Officer (Lucknow)",
            "image": "team/parul.jpg",
            "bio": "Works closely with students to streamline the admissions process and provide accurate university guidance."
        },
       
    ]
    return render_template("team.html", team=team_members)


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
