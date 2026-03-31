from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3, os
from werkzeug.utils import secure_filename
import pandas as pd

UNIVERSITIES = [
    "APIC",
    "CQU",
    "Flinders",
    "Macquarie University",
    "QUT",
    "Swinburne",
    "UC , Sydney Hills",
    "UNISc, Adelaide",
    "UTAS (Melb/Sydney)",
    "VU (Brisbane/Sydney)",
    "MIT",
    "Curtin",
    "Danford",
    "Notre Dame",
    "Other"
]


DB_NAME = "gng_crm.db"
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"xlsx", "xls"}

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

def get_conn(row_factory=False):
    conn = sqlite3.connect(DB_NAME)
    if row_factory:
        conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'admin',
        full_name TEXT DEFAULT ''
    );""")
    c.execute("""CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        stage TEXT DEFAULT 'new',
        notes TEXT,
        partner_id INTEGER,
        added_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""")
    c.execute("""CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER,
        stage TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""")
    c.execute("""CREATE TABLE IF NOT EXISTS channel_partners (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        company TEXT,
        location TEXT,
        added_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""")
    try:
        c.execute("ALTER TABLE leads ADD COLUMN partner_id INTEGER;")
    except sqlite3.OperationalError:
        pass
   
    c.execute("SELECT COUNT(*) FROM users;")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO users (username, password, role, full_name) VALUES (?,?,?,?)",
                  ("admin", "admin123", "admin", "Administrator"))
    conn.commit()
    conn.close()

init_db()

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
    c.execute("SELECT id, username, role, full_name FROM users WHERE id=?", (user_id,))
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
        c.execute("SELECT id, username, password, role, full_name FROM users WHERE username=?", (username,))
        row = c.fetchone()
        conn.close()
        if row and row[2] == password:
            user = User(id=row[0], username=row[1], role=row[3], full_name=row[4])
            login_user(user)
            flash("Login successful!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))
    
    



@app.route("/dashboard", endpoint="dashboard")
@login_required
def dashboard():
    with get_conn(row_factory=True) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM leads")
        leads_count = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM leads WHERE stage IN ('offer','coe','visa-grant')")
        apps_count = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM leads WHERE stage='coe'")
        coe_count = c.fetchone()["cnt"]

        c.execute("SELECT COUNT(*) as cnt FROM leads WHERE stage='visa-grant'")
        visa_count = c.fetchone()["cnt"]
        
        # Count total leads per university
        c.execute("""
        SELECT university, COUNT(*) as total
        FROM leads
        WHERE stage='coe' AND university IS NOT NULL AND university != ''
        GROUP BY university
        """)
        
        coe_summary = c.fetchall()
        
        # Build pipeline view
        stages = [
            ('new', 'New'),
            ('contacted', 'Contacted'),
            ('assessment', 'Assessment'),
            ('gs', 'GS'),
            ('on-hold', 'On Hold'),
            ('offer', 'Offer'),
            ('ucol', 'Ucol'),
            ('coe', 'COE'),
            ('visa-grant', 'Visa Grant'),
            
        ]
        pipeline = []
        for key, label in stages:
            c.execute("""
                SELECT leads.id, leads.name, leads.email, leads.phone, leads.stage,leads.university, 
                       leads.notes, leads.added_on, channel_partners.company AS partner_company
                FROM leads
                LEFT JOIN channel_partners ON leads.partner_id = channel_partners.id
                WHERE leads.stage=?
            """, (key,))
            stage_leads = c.fetchall()
            pipeline.append((key, label, stage_leads))

    return render_template(
        "dashboard.html",
        leads_count=leads_count,
        apps_count=apps_count,
        coe_count=coe_count,
        visa_count=visa_count,
        pipeline=pipeline,
        coe_summary=coe_summary
    )
    


@app.route("/about")
@login_required   # optional, remove if you want it public
def about():
    return render_template("about.html")


@app.route("/leads")
@login_required
def leads():
    search_query = request.args.get("q", "").strip()
    university = request.args.get("university", "").strip()
    stage = request.args.get("stage", "").strip()

    conn = get_conn(row_factory=True)
    c = conn.cursor()

    base_query = """
    SELECT leads.*, channel_partners.company AS partner_company
    FROM leads
    LEFT JOIN channel_partners ON leads.partner_id = channel_partners.id
    WHERE 1=1
    """

    params = []

    # Search filter
    if search_query:
        base_query += """
        AND (
            leads.name LIKE ? OR 
            leads.email LIKE ? OR 
            leads.phone LIKE ? OR 
            channel_partners.company LIKE ?
        )
        """
        params.extend([f"%{search_query}%"] * 4)

    # University filter
    if university:
        base_query += " AND leads.university = ?"
        params.append(university)

    # Stage filter ✅ NEW
    if stage:
        base_query += " AND leads.stage = ?"
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
        selected_stage=stage   # 👈 important
    )


@app.route("/add_lead", methods=["GET", "POST"])
@login_required
def add_lead():
    conn = get_conn(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM channel_partners ORDER BY added_on DESC")
    partners = c.fetchall()

    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        phone = request.form.get("phone")
        stage = request.form.get("stage")
        notes = request.form.get("notes")
        partner_id = request.form.get("partner_id") or None
        university = request.form.get("university")
        c.execute(
            "INSERT INTO leads (name, email, phone, stage, notes, partner_id, added_on,university) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP,?)",
            (name, email, phone, stage, notes, partner_id,university)
        )
        conn.commit()
        conn.close()
        flash("Lead added successfully!", "success")
        return redirect(url_for("leads"))

    conn.close()
    return render_template("add_lead.html", partners=partners,universities=UNIVERSITIES)


@app.route("/edit_lead/<int:lead_id>", methods=["GET", "POST"])
@login_required
def edit_lead(lead_id):
    conn = get_conn(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM leads WHERE id=?", (lead_id,))
    lead = c.fetchone()

    # Fetch all channel partners to show in the dropdown
    c.execute("SELECT * FROM channel_partners ORDER BY added_on DESC")
    partners = c.fetchall()

    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        phone = request.form.get("phone")
        stage = request.form.get("stage")
        notes = request.form.get("notes")
        partner_id = request.form.get("partner_id") or None
        university = request.form.get("university")  # <-- add this line

        c.execute(
            "UPDATE leads SET name=?, email=?, phone=?, stage=?, notes=?,university=?, partner_id=? WHERE id=?",
            (name, email, phone, stage, notes, university, partner_id, lead_id)
        )
        conn.commit()
        conn.close()
        flash("Lead updated successfully!", "success")
        return redirect(url_for("leads") + f"#lead-{lead_id}")

    conn.close()
    return render_template("edit_lead.html", lead=lead, partners=partners, universities=UNIVERSITIES)  # <-- pass partners to template

@app.route("/delete_lead/<int:lead_id>")
@login_required
def delete_lead(lead_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()
    flash("Lead deleted successfully!", "info")
    return redirect(url_for("leads") + f"#lead-{lead_id}")

@app.route("/import_leads", methods=["GET", "POST"])
@login_required
def import_leads():
    if request.method == "POST":
        if "file" not in request.files:
            flash("No file part", "danger"); return redirect(request.url)
        file = request.files["file"]
        if file.filename == "":
            flash("No selected file", "danger"); return redirect(request.url)
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
        ext = filename.rsplit('.', 1)[-1].lower()
        try:
            if ext == 'xlsx':
                df = pd.read_excel(filepath, engine='openpyxl')
            elif ext == 'xls':
                df = pd.read_excel(filepath, engine='xlrd')
            else:
                flash("Invalid file type. Upload .xlsx or .xls only.", "danger")
                return redirect(request.url)
        except Exception as e:
            flash(f"Error reading Excel file: {e}", "danger")
            return redirect(request.url)

        required_cols = {'name', 'email', 'phone', 'stage'}
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            flash(f"Missing required columns in Excel: {', '.join(missing)}", "danger")
            return redirect(request.url)
        if 'notes' not in df.columns:
            df['notes'] = ''

        conn = get_conn()
        c = conn.cursor()
        for _, row in df.iterrows():
            c.execute(
                "INSERT INTO leads (name, email, phone, stage, notes, added_on) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (str(row['name']) if pd.notna(row['name']) else '',
                 str(row['email']) if pd.notna(row['email']) else '',
                 str(row['phone']) if pd.notna(row['phone']) else '',
                 str(row['stage']) if pd.notna(row['stage']) else 'new',
                 str(row['notes']) if pd.notna(row['notes']) else '')
            )
        conn.commit()
        conn.close()
        flash("Leads imported successfully!", "success")
        return redirect(url_for("leads"))
    return render_template("import_leads.html")

@app.route('/partners')
@login_required
def partners():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM channel_partners ORDER BY added_on DESC")
    partners = c.fetchall()
    conn.close()
    return render_template('partners.html', partners=partners)

@app.route('/add_partner', methods=['GET', 'POST'])
@login_required
def add_partner():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        company = request.form['company']
        location = request.form['location']
        conn = get_conn()
        c = conn.cursor()
        c.execute("INSERT INTO channel_partners (name, email, phone, company, location, added_on) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                  (name, email, phone, company, location))
        conn.commit()
        conn.close()
        flash("Partner added successfully!", "success")
        return redirect(url_for('partners'))
    return render_template('add_partner.html')

@app.route("/edit_partner/<int:partner_id>", methods=["GET", "POST"])
@login_required
def edit_partner(partner_id):
    conn = get_conn(row_factory=True)
    c = conn.cursor()
    c.execute("SELECT * FROM channel_partners WHERE id=?", (partner_id,))
    partner = c.fetchone()
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        phone = request.form["phone"]
        company = request.form["company"]
        location = request.form["location"]
        c.execute("UPDATE channel_partners SET name=?, email=?, phone=?, company=?, location=? WHERE id=?",
                  (name, email, phone, company, location, partner_id))
        conn.commit()
        conn.close()
        flash("Partner updated successfully!", "success")
        return redirect(url_for("partners"))
    conn.close()
    return render_template("edit_partner.html", partner=partner)

@app.route("/delete_partner/<int:partner_id>")
@login_required
def delete_partner(partner_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM channel_partners WHERE id=?", (partner_id,))
    conn.commit()
    conn.close()
    flash("Partner deleted successfully!", "info")
    return redirect(url_for("partners"))


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


if __name__ == "__main__":
    app.run()
