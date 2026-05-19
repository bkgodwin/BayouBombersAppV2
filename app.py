import json
import string
import secrets
import sqlite3
import sys
from getpass import getpass
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config


app = Flask(__name__)
app.config.from_object(Config)
LIFT_PROJECTION_FACTOR = 0.03  # Epley-inspired burnout coefficient for suggestion-only projected max changes.


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = Path(app.config["DATABASE_PATH"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exception) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT UNIQUE,
            first_name TEXT,
            last_name TEXT,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('coach', 'athlete')),
            athlete_id INTEGER,
            coach_code TEXT,
            coach_user_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(athlete_id) REFERENCES athletes(id) ON DELETE SET NULL,
            FOREIGN KEY(coach_user_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS athletes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sex TEXT,
            event_groups TEXT NOT NULL,
            prs_json TEXT NOT NULL,
            lift_maxes_json TEXT NOT NULL,
            notes TEXT DEFAULT '',
            avatar TEXT DEFAULT '/static/images/default-athlete-avatar.svg',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS modules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            event_group TEXT NOT NULL,
            variation TEXT,
            reps TEXT,
            measured INTEGER NOT NULL DEFAULT 0,
            cues TEXT,
            info TEXT,
            demo_url TEXT,
            created_by INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS practice_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            practice_date TEXT NOT NULL,
            assigned_group TEXT,
            event_groups TEXT,
            notes TEXT,
            published INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS practice_plan_modules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            module_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            custom_variation TEXT,
            custom_reps TEXT,
            FOREIGN KEY(plan_id) REFERENCES practice_plans(id) ON DELETE CASCADE,
            FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS practice_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            athlete_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(plan_id, athlete_id),
            FOREIGN KEY(plan_id) REFERENCES practice_plans(id) ON DELETE CASCADE,
            FOREIGN KEY(athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS practice_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            module_id INTEGER NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            low_mark_inches REAL,
            typical_mark_inches REAL,
            best_mark_inches REAL,
            detailed_json TEXT DEFAULT '[]',
            note TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(assignment_id, module_id),
            FOREIGN KEY(assignment_id) REFERENCES practice_assignments(id) ON DELETE CASCADE,
            FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS lifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_id INTEGER NOT NULL,
            lift_name TEXT NOT NULL,
            week_no INTEGER,
            sets INTEGER,
            reps INTEGER,
            target_percent REAL,
            burnout_reps INTEGER,
            weight_used REAL,
            projected_max_increase REAL,
            approved INTEGER NOT NULL DEFAULT 0,
            entry_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS meet_performances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            distance_inches REAL NOT NULL,
            entry_date TEXT NOT NULL,
            location TEXT,
            notes TEXT,
            attempts_json TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            FOREIGN KEY(athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS coach_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_id INTEGER,
            practice_date TEXT,
            context TEXT NOT NULL,
            note TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(athlete_id) REFERENCES athletes(id) ON DELETE SET NULL,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    ensure_schema_updates()
    db.commit()


def ensure_schema_updates() -> None:
    db = get_db()
    columns = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}

    if "email" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "first_name" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
    if "last_name" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN last_name TEXT")
    if "coach_code" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN coach_code TEXT")
    if "coach_user_id" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN coach_user_id INTEGER")

    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email) WHERE email IS NOT NULL")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_coach_code_unique ON users(coach_code) WHERE coach_code IS NOT NULL")


def build_unique_username(db: sqlite3.Connection, email: str) -> str:
    base_raw = "".join(ch for ch in email.split("@", 1)[0].lower() if ch.isalnum())
    if not base_raw:
        base_raw = f"user{secrets.randbelow(10000):04d}"
    base = base_raw
    candidate = base
    suffix = 1
    while db.execute("SELECT id FROM users WHERE username = ?", (candidate,)).fetchone():
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate


def lookup_coach_id_by_code(db: sqlite3.Connection, coach_code: str) -> int | None:
    cleaned_code = "".join(ch for ch in (coach_code or "").upper() if ch.isalnum())
    if not cleaned_code:
        return None
    coach = db.execute(
        "SELECT id FROM users WHERE role = 'coach' AND coach_code = ?",
        (cleaned_code,),
    ).fetchone()
    return coach["id"] if coach else None


def generate_coach_code(db: sqlite3.Connection) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        exists = db.execute("SELECT id FROM users WHERE coach_code = ?", (code,)).fetchone()
        if not exists:
            return code


def prompt_initial_admin_credentials() -> tuple[str, str]:
    if app.config["ADMIN_DEFAULT_USERNAME"] and app.config["ADMIN_DEFAULT_PASSWORD"]:
        return app.config["ADMIN_DEFAULT_USERNAME"], app.config["ADMIN_DEFAULT_PASSWORD"]

    if not sys.stdin.isatty():
        raise RuntimeError(
            "No admin user exists yet. Start the app in an interactive terminal to set first-run admin credentials, "
            "or set BAYOU_ADMIN_USERNAME and BAYOU_ADMIN_PASSWORD."
        )

    print("\nFirst run setup: create the initial coach admin account.")
    while True:
        username = clean_text(input("Admin username: "), 64)
        if username:
            break
        print("Username is required.")

    while True:
        password = getpass("Admin password (8+ chars): ")
        confirm = getpass("Confirm admin password: ")
        if len(password) < 8:
            print("Password must be at least 8 characters.")
            continue
        if password != confirm:
            print("Passwords do not match.")
            continue
        break

    return username, password


def seed_data() -> None:
    db = get_db()
    now = datetime.utcnow().isoformat()

    athlete_count = db.execute("SELECT COUNT(*) AS c FROM athletes").fetchone()["c"]
    if athlete_count == 0:
        athletes = [
            ("Avery James", "F", "Shotput,Discus"),
            ("Mason Hall", "M", "Shotput"),
            ("Liam Ross", "M", "Javelin,Discus"),
        ]
        for name, sex, groups in athletes:
            db.execute(
                """
                INSERT INTO athletes(name, sex, event_groups, prs_json, lift_maxes_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    sex,
                    groups,
                    json.dumps(
                        {
                            "Shotput": {"Competition|Full": 520.0},
                            "Discus": {"Competition|Full": 430.0},
                            "Javelin": {"Competition|Full": 390.0},
                        }
                    ),
                    json.dumps({"Bench": 185, "Front Squat": 205, "Hang Clean": 165}),
                    now,
                ),
            )
        db.commit()

    admin_exists = db.execute("SELECT id FROM users WHERE role = 'coach' ORDER BY id LIMIT 1").fetchone()
    if not admin_exists:
        admin_username, admin_password = prompt_initial_admin_credentials()
        db.execute(
            "INSERT INTO users(username, password_hash, role, created_at) VALUES (?, ?, 'coach', ?)",
            (
                admin_username,
                generate_password_hash(admin_password),
                now,
            ),
        )
        db.commit()

    default_coach = db.execute("SELECT id FROM users WHERE role = 'coach' ORDER BY id LIMIT 1").fetchone()
    default_coach_id = default_coach["id"] if default_coach else None

    athlete_rows = db.execute("SELECT id, name FROM athletes ORDER BY id").fetchall()
    for athlete in athlete_rows:
        username = athlete["name"].lower().replace(" ", "")
        exists = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not exists:
            db.execute(
                """
                INSERT INTO users(username, password_hash, role, athlete_id, coach_user_id, created_at)
                VALUES (?, ?, 'athlete', ?, ?, ?)
                """,
                (
                    username,
                    generate_password_hash(app.config["ATHLETE_DEFAULT_PASSWORD"]),
                    athlete["id"],
                    default_coach_id,
                    now,
                ),
            )
    db.commit()

    module_count = db.execute("SELECT COUNT(*) AS c FROM modules").fetchone()["c"]
    if module_count == 0:
        starter_modules = [
            ("Daily Warmup", "Shotput,Discus,Javelin", "General", "10 min", 0, "Posture, rhythm, range", "Mobility + prep", ""),
            ("Stand Throws", "Shotput,Discus", "Stand", "8 throws", 1, "Stay long through finish", "Measured throws", ""),
            ("Approach Progression", "Javelin", "3-step", "6 reps", 1, "Carry speed into block", "Track each throw", ""),
        ]
        coach_id = db.execute("SELECT id FROM users WHERE role = 'coach' ORDER BY id LIMIT 1").fetchone()["id"]
        for m in starter_modules:
            db.execute(
                """
                INSERT INTO modules(name, event_group, variation, reps, measured, cues, info, demo_url, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*m, coach_id, now),
            )
        db.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def generate_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(24)
    return session["csrf_token"]


def validate_csrf() -> None:
    token = request.form.get("csrf_token", "")
    if not token or token != session.get("csrf_token"):
        abort(400, "Invalid CSRF token")


@app.context_processor
def template_context():
    return {
        "csrf_token": generate_csrf_token,
        "poll_seconds": app.config["POLL_SECONDS"],
    }


def clean_text(value: str, max_len: int = 255) -> str:
    value = (value or "").strip()
    if len(value) > max_len:
        value = value[:max_len]
    return value


def parse_mark_to_inches(mark: str) -> float | None:
    mark = (mark or "").strip()
    if not mark:
        return None
    cleaned = mark.replace('"', "")
    try:
        if "'" in cleaned:
            feet_part, inches_part = (cleaned.split("'", 1) + [""])[:2]
            feet = float(feet_part.strip() or 0)
            inches = float(inches_part.strip() or 0)
            return feet * 12 + inches
        return float(cleaned) * 12
    except ValueError as exc:
        raise ValueError("Invalid distance format.") from exc


def inches_to_display(inches: float | None) -> str:
    if inches is None:
        return ""
    feet = int(inches // 12)
    rem = round(inches - feet * 12, 1)
    meters = round(inches * 0.0254, 2)
    return f"{feet}' {rem}\" ({meters}m)"


def compute_alert(best_inches: float | None, pr_inches: float | None) -> str:
    if best_inches is None:
        return "Missing data"
    if not pr_inches or pr_inches <= 0:
        return "Needs baseline"
    ratio = best_inches / pr_inches
    if ratio >= 1.0:
        return "New PR pending review"
    if ratio >= 0.95:
        return "Strong session"
    if ratio < 0.70:
        return "Below normal range"
    return "On track"


@app.route("/")
def index():
    if session.get("role") == "coach":
        return redirect(url_for("coach_home"))
    if session.get("role") == "athlete":
        return redirect(url_for("athlete_today"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        validate_csrf()
        identifier = clean_text(request.form.get("username"), 120).lower()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE lower(username) = ? OR lower(COALESCE(email, '')) = ?",
            (identifier, identifier),
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["athlete_id"] = user["athlete_id"]
            generate_csrf_token()
            return redirect(url_for("index"))
        flash("Invalid credentials.", "error")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        validate_csrf()
        db = get_db()

        email = clean_text(request.form.get("email"), 120).lower()
        first_name = clean_text(request.form.get("first_name"), 80)
        last_name = clean_text(request.form.get("last_name"), 80)
        password = request.form.get("password", "")
        role = clean_text(request.form.get("role"), 20)
        coach_code = clean_text(request.form.get("coach_code"), 16)

        email_parts = email.split("@")
        email_local = email_parts[0] if len(email_parts) == 2 else ""
        email_domain = email_parts[1] if len(email_parts) == 2 else ""
        valid_email = (
            len(email_parts) == 2
            and bool(email_local)
            and "." in email_domain
            and not email_domain.startswith(".")
            and not email_domain.endswith(".")
        )

        if not valid_email or not first_name or not last_name or len(password) < 8 or role not in {"athlete", "coach"}:
            flash("Email, first name, last name, role, and 8+ char password are required.", "error")
            return render_template("register.html")

        coach_user_id = None
        if role == "athlete" and coach_code:
            coach_user_id = lookup_coach_id_by_code(db, coach_code)
            if not coach_user_id:
                flash("Coach code not found. Check the code or leave blank and add it later in account settings.", "error")
                return render_template("register.html")

        athlete_id = None
        if role == "athlete":
            athlete_name = f"{first_name} {last_name}".strip()
            cur = db.execute(
                """
                INSERT INTO athletes(name, sex, event_groups, prs_json, lift_maxes_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    athlete_name,
                    "",
                    "Shotput,Discus,Javelin",
                    json.dumps({}),
                    json.dumps({}),
                    datetime.utcnow().isoformat(),
                ),
            )
            athlete_id = cur.lastrowid

        username = build_unique_username(db, email)
        try:
            db.execute(
                """
                INSERT INTO users(username, email, first_name, last_name, password_hash, role, athlete_id, coach_user_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    email,
                    first_name,
                    last_name,
                    generate_password_hash(password),
                    role,
                    athlete_id,
                    coach_user_id,
                    datetime.utcnow().isoformat(),
                ),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            flash("That email already has an account.", "error")
            return render_template("register.html")

        flash("Registration complete. Sign in to continue.", "ok")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    validate_csrf()
    session.clear()
    return redirect(url_for("login"))


@app.route("/coach")
@login_required
@role_required("coach")
def coach_home():
    db = get_db()
    today = date.today().isoformat()
    coach = db.execute("SELECT coach_code FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    event_cards = {
        "Shotput": [],
        "Discus": [],
        "Javelin": [],
    }

    athletes = db.execute(
        """
        SELECT a.id, a.name, a.event_groups, a.avatar
        FROM athletes a
        JOIN users u ON u.athlete_id = a.id
        WHERE u.role = 'athlete' AND u.coach_user_id = ?
        ORDER BY a.name
        """,
        (session["user_id"],),
    ).fetchall()
    for athlete in athletes:
        groups = [g.strip() for g in athlete["event_groups"].split(",") if g.strip()]
        for group in groups:
            if group in event_cards:
                event_cards[group].append(dict(athlete))

    assignments = db.execute(
        """
        SELECT pa.id AS assignment_id, a.id AS athlete_id, a.name,
               COUNT(ppm.id) AS total_modules,
               SUM(CASE WHEN pr.completed = 1 THEN 1 ELSE 0 END) AS completed_modules,
               MAX(pr.best_mark_inches) AS best_mark_inches
        FROM practice_assignments pa
        JOIN practice_plans pp ON pp.id = pa.plan_id
        JOIN athletes a ON a.id = pa.athlete_id
        JOIN users u ON u.athlete_id = a.id AND u.role = 'athlete'
        LEFT JOIN practice_plan_modules ppm ON ppm.plan_id = pp.id
        LEFT JOIN practice_results pr ON pr.assignment_id = pa.id AND pr.module_id = ppm.module_id
        WHERE pp.practice_date = ? AND u.coach_user_id = ?
        GROUP BY pa.id, a.id, a.name
        ORDER BY a.name
        """,
        (today, session["user_id"]),
    ).fetchall()

    return render_template(
        "coach_home.html",
        event_cards=event_cards,
        today=today,
        assignments=assignments,
        coach_code=(coach["coach_code"] if coach else None),
    )


@app.route("/coach/modules", methods=["GET", "POST"])
@login_required
@role_required("coach")
def modules_page():
    db = get_db()
    if request.method == "POST":
        validate_csrf()
        name = clean_text(request.form.get("name"), 120)
        event_group = clean_text(request.form.get("event_group"), 120)
        variation = clean_text(request.form.get("variation"), 120)
        reps = clean_text(request.form.get("reps"), 120)
        cues = clean_text(request.form.get("cues"), app.config["MAX_FORM_TEXT"])
        info = clean_text(request.form.get("info"), app.config["MAX_FORM_TEXT"])
        demo_url = clean_text(request.form.get("demo_url"), 255)
        measured = 1 if request.form.get("measured") == "on" else 0

        if not name or not event_group:
            flash("Module name and event group are required.", "error")
        else:
            db.execute(
                """
                INSERT INTO modules(name, event_group, variation, reps, measured, cues, info, demo_url, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    event_group,
                    variation,
                    reps,
                    measured,
                    cues,
                    info,
                    demo_url,
                    session["user_id"],
                    datetime.utcnow().isoformat(),
                ),
            )
            db.commit()
            flash("Module created.", "ok")
            return redirect(url_for("modules_page"))

    modules = db.execute("SELECT * FROM modules ORDER BY created_at DESC").fetchall()
    return render_template("modules.html", modules=modules)


@app.route("/coach/athletes", methods=["GET", "POST"])
@login_required
@role_required("coach")
def athletes_page():
    db = get_db()
    if request.method == "POST":
        validate_csrf()
        name = clean_text(request.form.get("name"), 120)
        sex = clean_text(request.form.get("sex"), 20)
        event_groups = request.form.getlist("event_groups")
        username = clean_text(request.form.get("username"), 64)
        password = request.form.get("password", "")

        if not name or not event_groups or not username or len(password) < 8:
            flash("Name, event groups, username, and 8+ char password are required.", "error")
        else:
            try:
                cur = db.execute(
                    """
                    INSERT INTO athletes(name, sex, event_groups, prs_json, lift_maxes_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        sex,
                        ",".join(event_groups),
                        json.dumps({}),
                        json.dumps({}),
                        datetime.utcnow().isoformat(),
                    ),
                )
                athlete_id = cur.lastrowid
                db.execute(
                    """
                    INSERT INTO users(username, password_hash, role, athlete_id, coach_user_id, created_at)
                    VALUES (?, ?, 'athlete', ?, ?, ?)
                    """,
                    (
                        username,
                        generate_password_hash(password),
                        athlete_id,
                        session["user_id"],
                        datetime.utcnow().isoformat(),
                    ),
                )
                db.commit()
                flash("Athlete created.", "ok")
                return redirect(url_for("athletes_page"))
            except sqlite3.IntegrityError:
                db.rollback()
                flash("Username already exists.", "error")

    athletes = db.execute(
        """
        SELECT a.*
        FROM athletes a
        JOIN users u ON u.athlete_id = a.id
        WHERE u.role = 'athlete' AND u.coach_user_id = ?
        ORDER BY a.name
        """,
        (session["user_id"],),
    ).fetchall()
    return render_template("athletes.html", athletes=athletes)


@app.route("/coach/create-practice", methods=["GET", "POST"])
@login_required
@role_required("coach")
def create_practice():
    db = get_db()
    modules = db.execute("SELECT * FROM modules ORDER BY name").fetchall()
    athletes = db.execute(
        """
        SELECT a.id, a.name, a.event_groups
        FROM athletes a
        JOIN users u ON u.athlete_id = a.id
        WHERE u.role = 'athlete' AND u.coach_user_id = ?
        ORDER BY a.name
        """,
        (session["user_id"],),
    ).fetchall()

    if request.method == "POST":
        validate_csrf()
        title = clean_text(request.form.get("title"), 120)
        practice_date = clean_text(request.form.get("practice_date"), 10)
        assigned_group = clean_text(request.form.get("assigned_group"), 120)
        selected_events = request.form.getlist("event_groups")
        notes = clean_text(request.form.get("notes"), app.config["MAX_FORM_TEXT"])
        athlete_ids = [int(x) for x in request.form.getlist("athlete_ids") if x.isdigit()]
        module_order_raw = request.form.get("module_order", "[]")

        try:
            ordered_module_ids = [int(x) for x in json.loads(module_order_raw)]
        except (json.JSONDecodeError, TypeError, ValueError):
            flash("Invalid module list; please add modules again.", "error")
            ordered_module_ids = []

        if not title or not practice_date or not ordered_module_ids or not athlete_ids:
            flash("Title, date, athlete(s), and at least one module are required.", "error")
            return render_template("create_practice.html", modules=modules, athletes=athletes)

        cur = db.execute(
            """
            INSERT INTO practice_plans(title, practice_date, assigned_group, event_groups, notes, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                practice_date,
                assigned_group,
                ",".join(selected_events),
                notes,
                session["user_id"],
                datetime.utcnow().isoformat(),
            ),
        )
        plan_id = cur.lastrowid

        for idx, module_id in enumerate(ordered_module_ids, start=1):
            db.execute(
                "INSERT INTO practice_plan_modules(plan_id, module_id, position) VALUES (?, ?, ?)",
                (plan_id, module_id, idx),
            )

        for athlete_id in athlete_ids:
            db.execute(
                "INSERT OR IGNORE INTO practice_assignments(plan_id, athlete_id, created_at) VALUES (?, ?, ?)",
                (plan_id, athlete_id, datetime.utcnow().isoformat()),
            )

        db.commit()
        flash("Practice created and assigned.", "ok")
        return redirect(url_for("coach_home"))

    plans = db.execute(
        "SELECT id, title, practice_date, assigned_group FROM practice_plans ORDER BY practice_date DESC, id DESC LIMIT 10"
    ).fetchall()
    return render_template("create_practice.html", modules=modules, athletes=athletes, plans=plans)


@app.route("/athlete/today")
@login_required
@role_required("athlete")
def athlete_today():
    db = get_db()
    athlete_id = session.get("athlete_id")
    today = date.today().isoformat()

    assignment = db.execute(
        """
        SELECT pa.id AS assignment_id, pp.id AS plan_id, pp.title, pp.practice_date, pp.notes
        FROM practice_assignments pa
        JOIN practice_plans pp ON pp.id = pa.plan_id
        WHERE pa.athlete_id = ? AND pp.practice_date = ?
        ORDER BY pp.id DESC LIMIT 1
        """,
        (athlete_id, today),
    ).fetchone()

    modules = []
    if assignment:
        modules = db.execute(
            """
            SELECT ppm.module_id, ppm.position, m.name, m.variation, m.reps, m.measured, m.cues, m.info,
                   pr.completed, pr.low_mark_inches, pr.typical_mark_inches, pr.best_mark_inches, pr.note
            FROM practice_plan_modules ppm
            JOIN modules m ON m.id = ppm.module_id
            LEFT JOIN practice_results pr ON pr.assignment_id = ? AND pr.module_id = m.id
            WHERE ppm.plan_id = ?
            ORDER BY ppm.position ASC
            """,
            (assignment["assignment_id"], assignment["plan_id"]),
        ).fetchall()

    recent_meets = db.execute(
        """
        SELECT event, distance_inches, entry_date, location
        FROM meet_performances
        WHERE athlete_id = ?
        ORDER BY entry_date DESC, id DESC
        LIMIT 5
        """,
        (athlete_id,),
    ).fetchall()

    recent_lifts = db.execute(
        """
        SELECT id, lift_name, weight_used, reps, burnout_reps, projected_max_increase, approved, entry_date
        FROM lifts WHERE athlete_id = ?
        ORDER BY entry_date DESC, id DESC LIMIT 5
        """,
        (athlete_id,),
    ).fetchall()

    return render_template(
        "athlete_home.html",
        today=today,
        assignment=assignment,
        modules=modules,
        recent_meets=recent_meets,
        recent_lifts=recent_lifts,
        inches_to_display=inches_to_display,
    )


@app.route("/athlete/submit-result", methods=["POST"])
@login_required
@role_required("athlete")
def submit_result():
    validate_csrf()
    db = get_db()

    assignment_id = int(request.form.get("assignment_id", 0))
    module_id = int(request.form.get("module_id", 0))
    completed = 1 if request.form.get("completed") == "on" else 0
    note = clean_text(request.form.get("note"), app.config["MAX_FORM_TEXT"])

    try:
        low_mark = parse_mark_to_inches(request.form.get("low_mark")) if request.form.get("low_mark") else None
        typical_mark = parse_mark_to_inches(request.form.get("typical_mark")) if request.form.get("typical_mark") else None
        best_mark = parse_mark_to_inches(request.form.get("best_mark")) if request.form.get("best_mark") else None
    except ValueError:
        flash("Invalid throw mark format. Use feet or feet'inches (example: 44'6).", "error")
        return redirect(url_for("athlete_today"))

    valid_assignment = db.execute(
        "SELECT id FROM practice_assignments WHERE id = ? AND athlete_id = ?",
        (assignment_id, session.get("athlete_id")),
    ).fetchone()
    if not valid_assignment:
        abort(403)

    db.execute(
        """
        INSERT INTO practice_results(assignment_id, module_id, completed, low_mark_inches, typical_mark_inches, best_mark_inches, note, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(assignment_id, module_id)
        DO UPDATE SET
            completed=excluded.completed,
            low_mark_inches=excluded.low_mark_inches,
            typical_mark_inches=excluded.typical_mark_inches,
            best_mark_inches=excluded.best_mark_inches,
            note=excluded.note,
            updated_at=excluded.updated_at
        """,
        (assignment_id, module_id, completed, low_mark, typical_mark, best_mark, note, datetime.utcnow().isoformat()),
    )
    db.commit()
    flash("Result saved.", "ok")
    return redirect(url_for("athlete_today"))


@app.route("/athlete/submit-lift", methods=["POST"])
@login_required
@role_required("athlete")
def submit_lift():
    validate_csrf()
    db = get_db()

    lift_name = clean_text(request.form.get("lift_name"), 64)
    week_no = int(request.form.get("week_no", 0) or 0)
    sets = int(request.form.get("sets", 0) or 0)
    reps = int(request.form.get("reps", 0) or 0)
    target_percent = float(request.form.get("target_percent", 0) or 0)
    burnout_reps = int(request.form.get("burnout_reps", 0) or 0)
    weight_used = float(request.form.get("weight_used", 0) or 0)

    projected = round((burnout_reps * weight_used * LIFT_PROJECTION_FACTOR), 1) if burnout_reps and weight_used else 0.0

    if not lift_name:
        flash("Lift name is required.", "error")
        return redirect(url_for("athlete_today"))

    db.execute(
        """
        INSERT INTO lifts(athlete_id, lift_name, week_no, sets, reps, target_percent, burnout_reps, weight_used, projected_max_increase, entry_date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session.get("athlete_id"),
            lift_name,
            week_no,
            sets,
            reps,
            target_percent,
            burnout_reps,
            weight_used,
            projected,
            date.today().isoformat(),
            datetime.utcnow().isoformat(),
        ),
    )
    db.commit()
    flash("Lift entry saved. Coach approval required for projected max changes.", "ok")
    return redirect(url_for("athlete_today"))


@app.route("/athlete/submit-meet", methods=["POST"])
@login_required
@role_required("athlete")
def submit_meet():
    validate_csrf()
    db = get_db()

    event = clean_text(request.form.get("event"), 64)
    location = clean_text(request.form.get("location"), 120)
    notes = clean_text(request.form.get("notes"), app.config["MAX_FORM_TEXT"])
    entry_date = clean_text(request.form.get("entry_date"), 10) or date.today().isoformat()

    try:
        distance_inches = parse_mark_to_inches(request.form.get("distance"))
    except ValueError:
        flash("Invalid distance format. Use feet or feet'inches (example: 160'3).", "error")
        distance_inches = None

    if not event or distance_inches is None:
        flash("Event and distance are required for meet entries.", "error")
        return redirect(url_for("athlete_today"))

    attempts_raw = clean_text(request.form.get("attempts"), app.config["MAX_FORM_TEXT"])
    attempts = []
    if attempts_raw:
        for token in attempts_raw.split(","):
            token = token.strip()
            try:
                attempts.append(parse_mark_to_inches(token))
            except ValueError:
                continue

    db.execute(
        """
        INSERT INTO meet_performances(athlete_id, event, distance_inches, entry_date, location, notes, attempts_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session.get("athlete_id"),
            event,
            distance_inches,
            entry_date,
            location,
            notes,
            json.dumps(attempts),
            datetime.utcnow().isoformat(),
        ),
    )
    db.commit()
    flash("Meet result saved.", "ok")
    return redirect(url_for("athlete_today"))


@app.route("/athlete/account", methods=["GET", "POST"])
@login_required
@role_required("athlete")
def athlete_account():
    db = get_db()
    if request.method == "POST":
        validate_csrf()
        submitted_code = clean_text(request.form.get("coach_code"), 16)
        coach_user_id = lookup_coach_id_by_code(db, submitted_code) if submitted_code else None
        if submitted_code and not coach_user_id:
            flash("Coach code not found.", "error")
            return redirect(url_for("athlete_account"))

        db.execute("UPDATE users SET coach_user_id = ? WHERE id = ?", (coach_user_id, session["user_id"]))
        db.commit()
        flash("Account settings updated.", "ok")
        return redirect(url_for("athlete_account"))

    user = db.execute(
        """
        SELECT u.email, u.first_name, u.last_name, c.username AS coach_username, c.coach_code
        FROM users u
        LEFT JOIN users c ON c.id = u.coach_user_id
        WHERE u.id = ?
        """,
        (session["user_id"],),
    ).fetchone()
    return render_template("athlete_account.html", user=user)


@app.route("/coach/reports")
@login_required
@role_required("coach")
def reports_page():
    db = get_db()
    week_end = date.today()
    week_start = week_end - timedelta(days=6)

    athlete_rows = db.execute(
        """
        SELECT a.id, a.name, a.prs_json
        FROM athletes a
        JOIN users u ON u.athlete_id = a.id
        WHERE u.role = 'athlete' AND u.coach_user_id = ?
        ORDER BY a.name
        """,
        (session["user_id"],),
    ).fetchall()
    reports = []
    for athlete in athlete_rows:
        results = db.execute(
            """
            SELECT pr.best_mark_inches, pp.practice_date
            FROM practice_results pr
            JOIN practice_assignments pa ON pa.id = pr.assignment_id
            JOIN practice_plans pp ON pp.id = pa.plan_id
            WHERE pa.athlete_id = ? AND pp.practice_date BETWEEN ? AND ?
            """,
            (athlete["id"], week_start.isoformat(), week_end.isoformat()),
        ).fetchall()

        meets = db.execute(
            """
            SELECT event, distance_inches, entry_date
            FROM meet_performances
            WHERE athlete_id = ? AND entry_date BETWEEN ? AND ?
            ORDER BY entry_date DESC
            """,
            (athlete["id"], week_start.isoformat(), week_end.isoformat()),
        ).fetchall()

        notes = db.execute(
            """
            SELECT context, note, created_at
            FROM coach_notes
            WHERE athlete_id = ? AND date(created_at) BETWEEN ? AND ?
            ORDER BY created_at DESC
            """,
            (athlete["id"], week_start.isoformat(), week_end.isoformat()),
        ).fetchall()

        marks = [r["best_mark_inches"] for r in results if r["best_mark_inches"] is not None]
        best = max(marks) if marks else None
        worst = min(marks) if marks else None
        completion = db.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END) AS completed
            FROM practice_results pr
            JOIN practice_assignments pa ON pa.id = pr.assignment_id
            JOIN practice_plans pp ON pp.id = pa.plan_id
            WHERE pa.athlete_id = ? AND pp.practice_date BETWEEN ? AND ?
            """,
            (athlete["id"], week_start.isoformat(), week_end.isoformat()),
        ).fetchone()

        completion_pct = 0
        if completion["total"]:
            completion_pct = round((completion["completed"] or 0) / completion["total"] * 100)

        reports.append(
            {
                "athlete": athlete["name"],
                "best": inches_to_display(best),
                "worst": inches_to_display(worst),
                "completion_pct": completion_pct,
                "meets": meets,
                "notes": notes,
                "flag": "Needs review" if completion_pct < 60 else "On track",
            }
        )

    return render_template(
        "reports.html",
        week_start=week_start.isoformat(),
        week_end=week_end.isoformat(),
        reports=reports,
        inches_to_display=inches_to_display,
    )


@app.route("/coach/add-note", methods=["POST"])
@login_required
@role_required("coach")
def add_note():
    validate_csrf()
    db = get_db()
    athlete_id = request.form.get("athlete_id")
    practice_date = clean_text(request.form.get("practice_date"), 10)
    context = clean_text(request.form.get("context"), 64)
    note = clean_text(request.form.get("note"), app.config["MAX_FORM_TEXT"])

    if not context or not note:
        flash("Context and note are required.", "error")
        return redirect(url_for("coach_home"))

    db.execute(
        "INSERT INTO coach_notes(athlete_id, practice_date, context, note, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            int(athlete_id) if athlete_id and athlete_id.isdigit() else None,
            practice_date or None,
            context,
            note,
            session["user_id"],
            datetime.utcnow().isoformat(),
        ),
    )
    db.commit()
    flash("Coach note added.", "ok")
    return redirect(url_for("coach_home"))


@app.route("/coach/generate-code", methods=["POST"])
@login_required
@role_required("coach")
def generate_coach_code_route():
    validate_csrf()
    db = get_db()
    code = generate_coach_code(db)
    db.execute("UPDATE users SET coach_code = ? WHERE id = ?", (code, session["user_id"]))
    db.commit()
    flash(f"New coach code generated: {code}", "ok")
    return redirect(url_for("coach_home"))


@app.route("/coach/approve-lift/<int:lift_id>", methods=["POST"])
@login_required
@role_required("coach")
def approve_lift(lift_id: int):
    validate_csrf()
    db = get_db()
    db.execute("UPDATE lifts SET approved = 1 WHERE id = ?", (lift_id,))
    db.commit()
    flash("Lift projection approved.", "ok")
    return redirect(url_for("reports_page"))


@app.route("/api/live-status")
@login_required
@role_required("coach")
def live_status_api():
    db = get_db()
    today = date.today().isoformat()

    rows = db.execute(
        """
        SELECT a.name, a.prs_json,
               COUNT(ppm.id) AS total_modules,
               SUM(CASE WHEN pr.completed = 1 THEN 1 ELSE 0 END) AS completed_modules,
               MAX(pr.best_mark_inches) AS best_mark_inches
        FROM practice_assignments pa
        JOIN athletes a ON a.id = pa.athlete_id
        JOIN users u ON u.athlete_id = a.id AND u.role = 'athlete'
        JOIN practice_plans pp ON pp.id = pa.plan_id
        LEFT JOIN practice_plan_modules ppm ON ppm.plan_id = pp.id
        LEFT JOIN practice_results pr ON pr.assignment_id = pa.id AND pr.module_id = ppm.module_id
        WHERE pp.practice_date = ? AND u.coach_user_id = ?
        GROUP BY a.id
        ORDER BY a.name
        """,
        (today, session["user_id"]),
    ).fetchall()

    payload = []
    for row in rows:
        completion_pct = 0
        if row["total_modules"]:
            completion_pct = round((row["completed_modules"] or 0) / row["total_modules"] * 100)

        pr_lookup = json.loads(row["prs_json"] or "{}")
        baseline = None
        for event in ("Shotput", "Discus", "Javelin"):
            baseline = (pr_lookup.get(event) or {}).get("Competition|Full")
            if baseline:
                break

        payload.append(
            {
                "athlete": row["name"],
                "completion": completion_pct,
                "best_mark": inches_to_display(row["best_mark_inches"]),
                "alert": compute_alert(row["best_mark_inches"], baseline),
            }
        )

    return jsonify(payload)


@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, message=str(error)), 400


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="You do not have permission for this action."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="Page not found."), 404


@app.errorhandler(500)
def server_error(_error):
    return render_template("error.html", code=500, message="Unexpected server error."), 500


with app.app_context():
    if app.config["ENFORCE_DEFAULT_PASSWORD_CHANGE"] and not app.config["ADMIN_PASSWORD_FROM_ENV"]:
        raise RuntimeError("Set BAYOU_ADMIN_PASSWORD before startup when password-change enforcement is enabled.")
    init_db()
    seed_data()


if __name__ == "__main__":
    app.run(host=app.config["HOST"], port=app.config["PORT"], debug=app.config["DEBUG"])
