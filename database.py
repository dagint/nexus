import hashlib
import json
import secrets
import sqlite3
import logging
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

logger = logging.getLogger(__name__)


def get_db():
    conn = sqlite3.connect(Config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT,
            timezone TEXT DEFAULT 'UTC',
            max_commute_minutes INTEGER DEFAULT 60,
            seniority_tier TEXT,
            blocked_companies TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS saved_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            query TEXT NOT NULL,
            location TEXT,
            remote_only INTEGER DEFAULT 0,
            skills_json TEXT,
            frequency TEXT DEFAULT 'daily',
            seniority_filter TEXT,
            min_match_score INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_notified_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS seen_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_id INTEGER NOT NULL,
            job_key TEXT NOT NULL,
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (search_id) REFERENCES saved_searches(id) ON DELETE CASCADE,
            UNIQUE(search_id, job_key)
        );

        CREATE TABLE IF NOT EXISTS applied_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_key TEXT NOT NULL,
            title TEXT,
            company TEXT,
            location TEXT,
            apply_url TEXT,
            stage TEXT DEFAULT 'applied',
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, job_key)
        );

        CREATE TABLE IF NOT EXISTS company_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT UNIQUE NOT NULL,
            data_json TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS resumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT DEFAULT 'Default Resume',
            filename TEXT,
            raw_text TEXT NOT NULL,
            skills_json TEXT,
            is_default INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            query TEXT NOT NULL,
            location TEXT,
            remote_only INTEGER DEFAULT 0,
            resume_id INTEGER,
            result_count INTEGER DEFAULT 0,
            searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS resume_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resume_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            raw_text TEXT NOT NULL,
            skills_json TEXT,
            change_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS shared_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            share_token TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            job_key TEXT NOT NULL,
            title TEXT,
            company TEXT,
            location TEXT,
            description TEXT,
            apply_url TEXT,
            salary_min REAL,
            salary_max REAL,
            remote_status TEXT,
            source TEXT,
            match_score INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            link TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS bookmarked_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_key TEXT NOT NULL,
            title TEXT,
            company TEXT,
            location TEXT,
            apply_url TEXT,
            salary_min REAL,
            salary_max REAL,
            remote_status TEXT,
            source TEXT,
            description TEXT,
            match_score INTEGER,
            bookmarked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, job_key)
        );

        CREATE TABLE IF NOT EXISTS dismissed_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_key TEXT NOT NULL,
            title TEXT,
            company TEXT,
            dismissed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, job_key)
        );
    """)
    conn.commit()
    conn.close()
    logger.info("Database initialized at %s", Config.DB_PATH)


# --- Users ---

def create_user(email, password, name=""):
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
            (email.lower().strip(), generate_password_hash(password), name.strip()),
        )
        conn.commit()
        user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return None  # Email already exists
    conn.close()
    return user_id


def authenticate_user(email, password):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
    ).fetchone()
    conn.close()
    if row and check_password_hash(row["password_hash"], password):
        return dict(row)
    return None


def get_user_by_id(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_email(email):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_user_password(user_id, new_password):
    conn = get_db()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), user_id),
    )
    conn.commit()
    conn.close()


def create_password_reset_token(email):
    user = get_user_by_email(email)
    if not user:
        return None
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.utcnow() + timedelta(hours=1)
    conn = get_db()
    # Remove any existing tokens for this user
    conn.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user["id"],))
    conn.execute(
        "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
        (user["id"], token_hash, expires_at),
    )
    conn.commit()
    conn.close()
    return token


def validate_reset_token(token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM password_reset_tokens WHERE token_hash = ?", (token_hash,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    if datetime.utcnow() > datetime.fromisoformat(row["expires_at"]):
        return None
    return row["user_id"]


def consume_reset_token(token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    conn = get_db()
    conn.execute("DELETE FROM password_reset_tokens WHERE token_hash = ?", (token_hash,))
    conn.commit()
    conn.close()


# --- Saved Searches ---

def create_saved_search(user_id, query, location, remote_only, skills_json, frequency):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO saved_searches (user_id, query, location, remote_only, skills_json, frequency) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, query, location, int(remote_only), skills_json, frequency),
    )
    conn.commit()
    search_id = cursor.lastrowid
    conn.close()
    return search_id


def get_saved_searches(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM saved_searches WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


def get_all_saved_searches():
    """Get all saved searches across all users (for scheduler)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT ss.*, u.email FROM saved_searches ss JOIN users u ON ss.user_id = u.id ORDER BY ss.id"
    ).fetchall()
    conn.close()
    return rows


def delete_saved_search(search_id, user_id):
    conn = get_db()
    conn.execute(
        "DELETE FROM saved_searches WHERE id = ? AND user_id = ?",
        (search_id, user_id),
    )
    conn.commit()
    conn.close()


def update_last_notified(search_id):
    conn = get_db()
    conn.execute(
        "UPDATE saved_searches SET last_notified_at = CURRENT_TIMESTAMP WHERE id = ?",
        (search_id,),
    )
    conn.commit()
    conn.close()


# --- Seen Jobs ---

def add_seen_jobs(search_id, job_keys):
    conn = get_db()
    conn.executemany(
        "INSERT OR IGNORE INTO seen_jobs (search_id, job_key) VALUES (?, ?)",
        [(search_id, key) for key in job_keys],
    )
    conn.commit()
    conn.close()


def get_seen_job_keys(search_id):
    conn = get_db()
    rows = conn.execute("SELECT job_key FROM seen_jobs WHERE search_id = ?", (search_id,)).fetchall()
    conn.close()
    return {row["job_key"] for row in rows}


# --- Applied Jobs ---

PIPELINE_STAGES = ["applied", "screen", "interview", "offer", "rejected", "withdrawn"]


def mark_applied(user_id, job_key, title, company, notes="", location="", apply_url="", stage="applied"):
    conn = get_db()
    conn.execute(
        """INSERT INTO applied_jobs (user_id, job_key, title, company, location, apply_url, stage, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, job_key) DO UPDATE SET
               stage = excluded.stage, notes = excluded.notes, updated_at = CURRENT_TIMESTAMP""",
        (user_id, job_key, title, company, location, apply_url, stage, notes),
    )
    conn.commit()
    conn.close()


def update_applied_stage(user_id, job_key, stage, notes=None):
    conn = get_db()
    if notes is not None:
        conn.execute(
            "UPDATE applied_jobs SET stage = ?, notes = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND job_key = ?",
            (stage, notes, user_id, job_key),
        )
    else:
        conn.execute(
            "UPDATE applied_jobs SET stage = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND job_key = ?",
            (stage, user_id, job_key),
        )
    conn.commit()
    conn.close()


def update_applied_notes(user_id, job_key, notes):
    conn = get_db()
    conn.execute(
        "UPDATE applied_jobs SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND job_key = ?",
        (notes, user_id, job_key),
    )
    conn.commit()
    conn.close()


def unmark_applied(user_id, job_key):
    conn = get_db()
    conn.execute("DELETE FROM applied_jobs WHERE user_id = ? AND job_key = ?", (user_id, job_key))
    conn.commit()
    conn.close()


def get_applied_job_keys(user_id):
    conn = get_db()
    rows = conn.execute("SELECT job_key FROM applied_jobs WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    return {row["job_key"] for row in rows}


def get_applied_jobs(user_id, stage=None):
    conn = get_db()
    if stage:
        rows = conn.execute(
            "SELECT * FROM applied_jobs WHERE user_id = ? AND stage = ? ORDER BY updated_at DESC",
            (user_id, stage),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM applied_jobs WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    conn.close()
    return rows


def get_applied_stats(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT stage, COUNT(*) as count FROM applied_jobs WHERE user_id = ? GROUP BY stage",
        (user_id,),
    ).fetchall()
    conn.close()
    return {row["stage"]: row["count"] for row in rows}


# --- Company Cache ---

def get_cached_company(company_name):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM company_cache WHERE company_name = ? AND scraped_at > datetime('now', '-7 days')",
        (company_name,),
    ).fetchone()
    conn.close()
    if row:
        return json.loads(row["data_json"])
    return None


def cache_company(company_name, data):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO company_cache (company_name, data_json, scraped_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (company_name, json.dumps(data)),
    )
    conn.commit()
    conn.close()


# --- User Settings ---

def get_user_settings(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT timezone, max_commute_minutes, seniority_tier, blocked_companies FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


def update_user_settings(user_id, **kwargs):
    conn = get_db()
    allowed = {"timezone", "max_commute_minutes", "seniority_tier", "blocked_companies", "name"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [user_id]
    conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


# --- Resumes ---

def save_resume(user_id, raw_text, skills_json=None, name="Default Resume", filename=None):
    conn = get_db()
    # If this is the first resume, make it default
    existing = conn.execute("SELECT COUNT(*) as c FROM resumes WHERE user_id = ?", (user_id,)).fetchone()
    is_default = 1 if existing["c"] == 0 else 0

    cursor = conn.execute(
        "INSERT INTO resumes (user_id, name, filename, raw_text, skills_json, is_default) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, name, filename, raw_text, skills_json, is_default),
    )
    conn.commit()
    resume_id = cursor.lastrowid
    conn.close()
    return resume_id


def get_resumes(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM resumes WHERE user_id = ? ORDER BY is_default DESC, updated_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


def get_resume(resume_id, user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM resumes WHERE id = ? AND user_id = ?", (resume_id, user_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_default_resume(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM resumes WHERE user_id = ? AND is_default = 1", (user_id,)
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT * FROM resumes WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1", (user_id,)
        ).fetchone()
    conn.close()
    return dict(row) if row else None


def set_default_resume(resume_id, user_id):
    conn = get_db()
    conn.execute("UPDATE resumes SET is_default = 0 WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE resumes SET is_default = 1 WHERE id = ? AND user_id = ?", (resume_id, user_id))
    conn.commit()
    conn.close()


def delete_resume(resume_id, user_id):
    conn = get_db()
    conn.execute("DELETE FROM resumes WHERE id = ? AND user_id = ?", (resume_id, user_id))
    conn.commit()
    conn.close()


def update_resume(resume_id, user_id, raw_text, skills_json=None, name=None):
    conn = get_db()
    if name:
        conn.execute(
            "UPDATE resumes SET raw_text = ?, skills_json = ?, name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (raw_text, skills_json, name, resume_id, user_id),
        )
    else:
        conn.execute(
            "UPDATE resumes SET raw_text = ?, skills_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (raw_text, skills_json, resume_id, user_id),
        )
    conn.commit()
    conn.close()


# --- Search History ---

def add_search_history(user_id, query, location, remote_only, resume_id=None, result_count=0):
    conn = get_db()
    conn.execute(
        "INSERT INTO search_history (user_id, query, location, remote_only, resume_id, result_count) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, query, location, int(remote_only), resume_id, result_count),
    )
    conn.commit()
    conn.close()


def get_search_history(user_id, limit=20):
    conn = get_db()
    rows = conn.execute(
        """SELECT sh.*, r.name as resume_name FROM search_history sh
           LEFT JOIN resumes r ON sh.resume_id = r.id
           WHERE sh.user_id = ? ORDER BY sh.searched_at DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return rows


# --- Bookmarks ---

def bookmark_job(user_id, job_data):
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO bookmarked_jobs
           (user_id, job_key, title, company, location, apply_url, salary_min, salary_max, remote_status, source, description, match_score)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, job_data["job_key"], job_data.get("title", ""), job_data.get("company", ""),
         job_data.get("location", ""), job_data.get("apply_url", ""),
         job_data.get("salary_min"), job_data.get("salary_max"),
         job_data.get("remote_status", ""), job_data.get("source", ""),
         job_data.get("description", "")[:1000], job_data.get("match_score")),
    )
    conn.commit()
    conn.close()


def unbookmark_job(user_id, job_key):
    conn = get_db()
    conn.execute("DELETE FROM bookmarked_jobs WHERE user_id = ? AND job_key = ?", (user_id, job_key))
    conn.commit()
    conn.close()


def get_bookmarked_jobs(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM bookmarked_jobs WHERE user_id = ? ORDER BY bookmarked_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


def get_bookmarked_job_keys(user_id):
    conn = get_db()
    rows = conn.execute("SELECT job_key FROM bookmarked_jobs WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    return {row["job_key"] for row in rows}


# --- Resume Versions ---

def save_resume_version(resume_id, user_id, raw_text, skills_json=None, change_note=""):
    conn = get_db()
    row = conn.execute(
        "SELECT MAX(version_number) as max_v FROM resume_versions WHERE resume_id = ? AND user_id = ?",
        (resume_id, user_id),
    ).fetchone()
    next_version = (row["max_v"] or 0) + 1
    conn.execute(
        "INSERT INTO resume_versions (resume_id, user_id, version_number, raw_text, skills_json, change_note) VALUES (?, ?, ?, ?, ?, ?)",
        (resume_id, user_id, next_version, raw_text, skills_json, change_note),
    )
    conn.commit()
    conn.close()
    return next_version


def get_resume_versions(resume_id, user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM resume_versions WHERE resume_id = ? AND user_id = ? ORDER BY version_number DESC",
        (resume_id, user_id),
    ).fetchall()
    conn.close()
    return rows


def get_resume_version(version_id, user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM resume_versions WHERE id = ? AND user_id = ?",
        (version_id, user_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# --- Shared Jobs ---

def create_shared_job(user_id, job_data):
    token = secrets.token_urlsafe(16)
    conn = get_db()
    conn.execute(
        """INSERT INTO shared_jobs
           (share_token, user_id, job_key, title, company, location, description, apply_url, salary_min, salary_max, remote_status, source, match_score)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (token, user_id, job_data.get("job_key", ""), job_data.get("title", ""),
         job_data.get("company", ""), job_data.get("location", ""),
         job_data.get("description", "")[:2000], job_data.get("apply_url", ""),
         job_data.get("salary_min"), job_data.get("salary_max"),
         job_data.get("remote_status", ""), job_data.get("source", ""),
         job_data.get("match_score")),
    )
    conn.commit()
    conn.close()
    return token


def get_shared_job(token):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM shared_jobs WHERE share_token = ?", (token,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# --- Notifications ---

def create_notification(user_id, message, link=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)",
        (user_id, message, link),
    )
    conn.commit()
    conn.close()


def get_unread_notifications(user_id, limit=10):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return rows


def get_unread_count(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND is_read = 0",
        (user_id,),
    ).fetchone()
    conn.close()
    return row["count"] if row else 0


def mark_notifications_read(user_id, notification_ids=None):
    conn = get_db()
    if notification_ids:
        placeholders = ",".join("?" * len(notification_ids))
        conn.execute(
            f"UPDATE notifications SET is_read = 1 WHERE user_id = ? AND id IN ({placeholders})",
            [user_id] + list(notification_ids),
        )
    else:
        conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ?",
            (user_id,),
        )
    conn.commit()
    conn.close()


# --- Role Velocity ---

# --- Dismissed Jobs ---

def dismiss_job(user_id, job_key, title="", company=""):
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO dismissed_jobs (user_id, job_key, title, company)
           VALUES (?, ?, ?, ?)""",
        (user_id, job_key, title, company),
    )
    conn.commit()
    conn.close()


def undismiss_job(user_id, job_key):
    conn = get_db()
    conn.execute("DELETE FROM dismissed_jobs WHERE user_id = ? AND job_key = ?", (user_id, job_key))
    conn.commit()
    conn.close()


def get_dismissed_job_keys(user_id):
    conn = get_db()
    rows = conn.execute("SELECT job_key FROM dismissed_jobs WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    return {row["job_key"] for row in rows}


def get_dismissed_jobs(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM dismissed_jobs WHERE user_id = ? ORDER BY dismissed_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


# --- Role Velocity ---

def get_role_velocity(company, title, months=6):
    conn = get_db()
    row = conn.execute(
        """SELECT COUNT(DISTINCT sj.job_key) as count
           FROM seen_jobs sj
           WHERE sj.job_key LIKE ? AND sj.first_seen_at > datetime('now', ?)""",
        (f"%{company}%{title}%", f"-{months} months"),
    ).fetchone()
    conn.close()
    return row["count"] if row else 0
