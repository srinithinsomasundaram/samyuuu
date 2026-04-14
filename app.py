from flask import Flask, render_template, request, redirect, url_for, session, flash, g
import pickle
import os
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
try:
    from groq import Groq
except Exception:  # pragma: no cover
    Groq = None

app = Flask(__name__)
app.secret_key = 'your_secret_key'

def load_model():
    model_path = os.environ.get('CKD_MODEL_PATH', 'ckd_model.pkl')
    try:
        with open(model_path, 'rb') as f:
            return pickle.load(f)
    except ModuleNotFoundError as exc:
        # `ckd_model.pkl` is a scikit-learn model; unpickling requires sklearn installed.
        missing = str(getattr(exc, 'name', '') or '')
        if missing == 'sklearn' or missing.startswith('sklearn.'):
            raise RuntimeError(
                "Missing dependency: scikit-learn.\n\n"
                "This project includes a virtual environment in `.venv`.\n"
                "Run the app with:\n"
                "  .\\.venv\\Scripts\\python.exe app.py\n\n"
                "Or activate the venv and install deps:\n"
                "  .\\.venv\\Scripts\\Activate.ps1\n"
                "  python -m pip install -r requirements.txt\n"
            ) from exc
        raise


# Load model lazily to avoid importing scikit-learn/scipy at module import time.
model = None

def get_model():
    global model
    if model is None:
        model = load_model()
    return model

# Clinical CKD threshold logic using the user's normal value ranges.
def ckd_threshold_prediction(sc, al, hemo, bp, egfr):
    return int(
        sc > 1.3
        or al > 30
        or hemo < 12
        or bp > 130
        or egfr < 60
    )

# Groq client (optional; used for future doctor features)
groq_client = None
if Groq is not None:
    groq_client = Groq(api_key=os.environ.get('GROQ_API_KEY', 'your_groq_api_key'))

DB_FILE = os.environ.get('CKD_DB_PATH', 'ckd_app.db')


def get_db():
    if 'db' not in g:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop('db', None)
    if conn is not None:
        conn.close()


def init_db():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL CHECK(role IN ('patient', 'doctor')),
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            age INTEGER,
            gender TEXT CHECK(gender IN ('M','F')),
            department TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS patient_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sc REAL NOT NULL,
            al REAL NOT NULL,
            hemo REAL NOT NULL,
            bp REAL NOT NULL,
            egfr REAL NOT NULL,
            prediction INTEGER NOT NULL,
            risk REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS patient_inputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sc REAL NOT NULL,
            al REAL NOT NULL,
            hemo REAL NOT NULL,
            bp REAL NOT NULL,
            egfr REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    # Lightweight migrations for existing DBs
    columns = {row['name'] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    if 'department' not in columns:
        db.execute("ALTER TABLE users ADD COLUMN department TEXT")

    db.commit()


@app.before_request
def _ensure_db():
    init_db()


def current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def require_role(role: str):
    user = current_user()
    if not user or user['role'] != role:
        return False
    return True


def risk_level_from_percent(risk_percent: float) -> str:
    if risk_percent < 33:
        return 'Low'
    if risk_percent < 66:
        return 'Medium'
    return 'High'

@app.route('/')
def home():
    return render_template('home.html')


@app.route('/patient')
def patient_auth():
    return render_template('auth_patient.html')


@app.route('/doctor')
def doctor_auth():
    return render_template('auth_doctor.html')


@app.route('/patient/register', methods=['POST'])
def patient_register():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    age = request.form.get('age', '').strip()
    gender = request.form.get('gender', '').strip().upper()

    if not name or not email or not password:
        flash('Please fill all required fields.')
        return redirect(url_for('patient_auth'))
    if not age.isdigit() or int(age) <= 0:
        flash('Please enter a valid age.')
        return redirect(url_for('patient_auth'))
    if gender not in ('M', 'F'):
        flash('Please select a valid gender.')
        return redirect(url_for('patient_auth'))

    db = get_db()
    try:
        db.execute(
            """
            INSERT INTO users (role, name, email, password_hash, age, gender, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                'patient',
                name,
                email,
                generate_password_hash(password),
                int(age),
                gender,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        flash('Email already registered. Please login.')
        return redirect(url_for('patient_auth'))

    flash('Registration successful. Please login.')
    return redirect(url_for('patient_auth'))


@app.route('/patient/login', methods=['POST'])
def patient_login():
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    if not email or not password:
        flash('Please enter email and password.')
        return redirect(url_for('patient_auth'))

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE role = 'patient' AND email = ?", (email,)).fetchone()
    if not user or not check_password_hash(user['password_hash'], password):
        flash('Invalid email or password.')
        return redirect(url_for('patient_auth'))

    session.clear()
    session['user_id'] = user['id']
    session['role'] = 'patient'
    return redirect(url_for('patient_dashboard'))


@app.route('/doctor/register', methods=['POST'])
def doctor_register():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    department = request.form.get('department', '').strip()

    if not name or not email or not password or not department:
        flash('Please fill all required fields.')
        return redirect(url_for('doctor_auth'))

    db = get_db()
    try:
        db.execute(
            """
            INSERT INTO users (role, name, email, password_hash, department, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                'doctor',
                name,
                email,
                generate_password_hash(password),
                department,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        flash('Email already registered. Please login.')
        return redirect(url_for('doctor_auth'))

    flash('Registration successful. Please login.')
    return redirect(url_for('doctor_auth'))


@app.route('/doctor/login', methods=['POST'])
def doctor_login():
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    if not email or not password:
        flash('Please enter email and password.')
        return redirect(url_for('doctor_auth'))

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE role = 'doctor' AND email = ?", (email,)).fetchone()
    if not user or not check_password_hash(user['password_hash'], password):
        flash('Invalid email or password.')
        return redirect(url_for('doctor_auth'))

    session.clear()
    session['user_id'] = user['id']
    session['role'] = 'doctor'
    return redirect(url_for('doctor_dashboard'))

@app.route('/patient_dashboard')
def patient_dashboard():
    if not require_role('patient'):
        return redirect(url_for('patient_auth'))

    user = current_user()
    db = get_db()
    records = db.execute(
        """
        SELECT sc, al, hemo, bp, egfr, created_at
        FROM patient_inputs
        WHERE user_id = ?
        ORDER BY datetime(created_at) DESC, id DESC
        """,
        (user['id'],),
    ).fetchall()
    return render_template('patient_dashboard.html', user=user, records=records)

@app.route('/patient/submit', methods=['POST'])
def submit_details():
    if not require_role('patient'):
        return redirect(url_for('patient_auth'))

    user = current_user()
    try:
        sc = float(request.form['sc'])
        al = float(request.form['al'])
        hemo = float(request.form['hemo'])
        bp = float(request.form['bp'])
    except (TypeError, ValueError):
        flash('Please enter valid numeric values.')
        return redirect(url_for('patient_dashboard'))

    age = int(user['age'])
    gender = user['gender']
    try:
        egfr = calculate_egfr(sc, age, gender)
    except ValueError as e:
        flash(str(e))
        return redirect(url_for('patient_dashboard'))

    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db = get_db()
    db.execute(
        """
        INSERT INTO patient_inputs (user_id, sc, al, hemo, bp, egfr, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user['id'], sc, al, hemo, bp, egfr, created_at),
    )
    db.commit()

    flash("Details saved successfully. Prediction will be done by the doctor.")
    return redirect(url_for('patient_dashboard'))

@app.route('/doctor_dashboard')
def doctor_dashboard():
    if not require_role('doctor'):
        return redirect(url_for('doctor_auth'))

    db = get_db()
    last_result = session.pop('doctor_last_result', None)
    patients = db.execute(
        """
        SELECT u.id, u.name, u.email, u.created_at,
               (SELECT COUNT(*) FROM patient_records r WHERE r.user_id = u.id) AS record_count
        FROM users u
        WHERE u.role = 'patient'
        ORDER BY datetime(u.created_at) DESC, u.id DESC
        """
    ).fetchall()

    predictions = db.execute(
        """
        SELECT u.id AS patient_id, u.name AS patient_name, u.email AS patient_email,
               r.sc, r.al, r.hemo, r.bp, r.egfr, r.prediction, r.risk, r.created_at
        FROM patient_records r
        JOIN users u ON u.id = r.user_id
        WHERE u.role = 'patient'
        ORDER BY datetime(r.created_at) DESC, r.id DESC
        LIMIT 200
        """
    ).fetchall()

    return render_template(
        'doctor_dashboard.html',
        user=current_user(),
        patients=patients,
        predictions=predictions,
        last_result=last_result,
    )


@app.route('/doctor/patient/<int:patient_user_id>')
def doctor_view_patient(patient_user_id: int):
    if not require_role('doctor'):
        return redirect(url_for('doctor_auth'))

    db = get_db()
    patient = db.execute(
        "SELECT id, name, email, age, gender, created_at FROM users WHERE id = ? AND role = 'patient'",
        (patient_user_id,),
    ).fetchone()
    if not patient:
        flash('Patient not found.')
        return redirect(url_for('doctor_dashboard'))

    records = db.execute(
        """
        SELECT sc, al, hemo, bp, egfr, prediction, risk, created_at
        FROM patient_records
        WHERE user_id = ?
        ORDER BY datetime(created_at) DESC, id DESC
        """,
        (patient_user_id,),
    ).fetchall()

    return render_template('doctor_view_patient.html', user=current_user(), patient=patient, records=records)


@app.route('/doctor/check_ckd', methods=['POST'])
def doctor_check_ckd():
    if not require_role('doctor'):
        return redirect(url_for('doctor_auth'))

    patient_id_raw = request.form.get('patient_id', '').strip()
    if not patient_id_raw.isdigit():
        flash('Please enter a valid Patient ID.')
        return redirect(url_for('doctor_dashboard'))

    patient_user_id = int(patient_id_raw)

    try:
        sc = float(request.form['sc'])
        al = float(request.form['al'])
        hemo = float(request.form['hemo'])
        bp = float(request.form['bp'])
    except (TypeError, ValueError):
        flash('Please enter valid numeric values.')
        return redirect(url_for('doctor_dashboard'))

    db = get_db()
    patient = db.execute(
        "SELECT id, name, email, age, gender FROM users WHERE id = ? AND role = 'patient'",
        (patient_user_id,),
    ).fetchone()
    if not patient:
        flash('Patient not found.')
        return redirect(url_for('doctor_dashboard'))
    if patient['age'] is None or patient['gender'] is None:
        flash('Patient profile is incomplete (age/gender missing).')
        return redirect(url_for('doctor_dashboard'))

    try:
        egfr = calculate_egfr(sc, int(patient['age']), patient['gender'])
    except ValueError as e:
        flash(str(e))
        return redirect(url_for('doctor_dashboard'))
    prediction = ckd_threshold_prediction(sc, float(al), hemo, bp, egfr)
    risk = 100.0 if prediction == 1 else 0.0
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db.execute(
        """
        INSERT INTO patient_records (user_id, sc, al, hemo, bp, egfr, prediction, risk, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (patient_user_id, sc, al, hemo, bp, egfr, prediction, risk, created_at),
    )
    db.commit()

    session['doctor_last_result'] = {
        'patient_id': patient_user_id,
        'patient_name': patient['name'],
        'patient_email': patient['email'],
        'prediction': prediction,
        'risk': round(risk, 2),
        'risk_level': risk_level_from_percent(risk),
        'created_at': created_at,
    }

    return redirect(url_for('doctor_dashboard') + '#results')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

def calculate_egfr(sc, age, gender):
    if sc is None or sc <= 0:
        raise ValueError('Serum Creatinine must be greater than 0.')
    if age is None or int(age) <= 0:
        raise ValueError('Age must be greater than 0.')
    if gender not in ('M', 'F'):
        raise ValueError('Gender must be M or F.')
    if gender == 'F':
        kappa = 0.7
        alpha = -0.329
        sex_factor = 1.018
    else:
        kappa = 0.9
        alpha = -0.411
        sex_factor = 1.0
    if sc / kappa <= 1:
        egfr = 141 * (sc / kappa) ** alpha * (0.993 ** age) * sex_factor
    else:
        egfr = 141 * (sc / kappa) ** -1.209 * (0.993 ** age) * sex_factor
    return round(egfr, 2)

if __name__ == '__main__':
    app.run(debug=True)
