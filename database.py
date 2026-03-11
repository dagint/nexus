import hashlib
import json
import secrets
import sqlite3
import logging
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

logger = logging.getLogger(__name__)

# WAL mode only needs to be set once per database file; track it here.
_wal_initialized = False


def _new_conn():
    """Create a new SQLite connection with pragmas."""
    global _wal_initialized
    conn = sqlite3.connect(Config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    if not _wal_initialized:
        conn.execute("PRAGMA journal_mode=WAL")
        _wal_initialized = True
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_db():
    """Get a database connection.

    In Flask request context: reuses a per-request connection (closed by teardown).
    Outside Flask: returns a new connection that the caller must close.
    """
    try:
        from flask import g, has_app_context
        if has_app_context():
            if "db" not in g:
                g.db = _new_conn()
            return g.db
    except ImportError:
        pass
    return _new_conn()


def _is_request_conn(conn):
    """Check if this connection is the shared Flask per-request connection."""
    try:
        from flask import g, has_app_context
        if has_app_context():
            return getattr(g, "db", None) is conn
    except (ImportError, RuntimeError):
        pass
    return False


def _safe_close(conn):
    """Close a connection only if it's not the shared Flask request connection."""
    if not _is_request_conn(conn):
        conn.close()


def close_db(e=None):
    """Close the per-request DB connection (Flask teardown handler)."""
    try:
        from flask import g
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()
    except (ImportError, RuntimeError):
        pass


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
            is_active INTEGER DEFAULT 1,
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

        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            provider TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            model TEXT,
            tokens_input INTEGER DEFAULT 0,
            tokens_output INTEGER DEFAULT 0,
            estimated_cost_usd REAL DEFAULT 0.0,
            response_time_ms INTEGER DEFAULT 0,
            success INTEGER DEFAULT 1,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_api_usage_provider ON api_usage(provider);
        CREATE INDEX IF NOT EXISTS idx_api_usage_created_at ON api_usage(created_at);
        CREATE INDEX IF NOT EXISTS idx_api_usage_user_id ON api_usage(user_id);
        CREATE INDEX IF NOT EXISTS idx_bookmarked_jobs_user_id ON bookmarked_jobs(user_id);
        CREATE INDEX IF NOT EXISTS idx_applied_jobs_user_id ON applied_jobs(user_id);
        CREATE INDEX IF NOT EXISTS idx_applied_jobs_user_stage ON applied_jobs(user_id, stage);
        CREATE INDEX IF NOT EXISTS idx_dismissed_jobs_user_id ON dismissed_jobs(user_id);
        CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);
        CREATE INDEX IF NOT EXISTS idx_saved_searches_user_active ON saved_searches(user_id, is_active);
        CREATE INDEX IF NOT EXISTS idx_search_history_user_id ON search_history(user_id);

        CREATE TABLE IF NOT EXISTS search_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            query TEXT NOT NULL,
            location TEXT DEFAULT '',
            remote_only INTEGER DEFAULT 0,
            description TEXT,
            is_system INTEGER DEFAULT 1,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS job_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_key TEXT NOT NULL,
            name TEXT,
            email TEXT,
            phone TEXT,
            role TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_job_contacts_user_job ON job_contacts(user_id, job_key);

        CREATE TABLE IF NOT EXISTS interview_prep_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            job_title TEXT NOT NULL,
            job_key TEXT,
            prep_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_prep_cache_user ON interview_prep_cache(user_id);

        CREATE TABLE IF NOT EXISTS salary_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role_query TEXT NOT NULL,
            location TEXT,
            salary_min REAL,
            salary_max REAL,
            source TEXT,
            company TEXT,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_salary_data_user ON salary_data(user_id);
        CREATE INDEX IF NOT EXISTS idx_salary_data_role ON salary_data(role_query);

        CREATE TABLE IF NOT EXISTS job_description_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_key TEXT NOT NULL,
            description_hash TEXT NOT NULL,
            description TEXT NOT NULL,
            snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_jd_snapshots_user_job ON job_description_snapshots(user_id, job_key);

        CREATE TABLE IF NOT EXISTS webhooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            event_types TEXT DEFAULT '["new_matches"]',
            is_active INTEGER DEFAULT 1,
            secret TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_triggered_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_webhooks_user_id ON webhooks(user_id);

        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS team_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT DEFAULT 'member',
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(team_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_team_members_user ON team_members(user_id);
        CREATE INDEX IF NOT EXISTS idx_team_members_team ON team_members(team_id);

        CREATE TABLE IF NOT EXISTS team_shared_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            shared_by INTEGER NOT NULL,
            job_key TEXT NOT NULL,
            title TEXT,
            company TEXT,
            location TEXT,
            apply_url TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
            FOREIGN KEY (shared_by) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_team_shared_jobs_team ON team_shared_jobs(team_id);

        CREATE TABLE IF NOT EXISTS team_job_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_shared_job_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            comment TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (team_shared_job_id) REFERENCES team_shared_jobs(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_team_job_comments_job ON team_job_comments(team_shared_job_id);

        CREATE TABLE IF NOT EXISTS api_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            name TEXT DEFAULT 'API Token',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_api_tokens_user_id ON api_tokens(user_id);
        CREATE INDEX IF NOT EXISTS idx_api_tokens_hash ON api_tokens(token_hash);

        CREATE TABLE IF NOT EXISTS oauth_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            provider_user_id TEXT NOT NULL,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(provider, provider_user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_oauth_accounts_user ON oauth_accounts(user_id);

        CREATE TABLE IF NOT EXISTS merged_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_job_key TEXT NOT NULL,
            source_job_key TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_url TEXT,
            merged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_merged_jobs_canonical ON merged_jobs(canonical_job_key);

        CREATE TABLE IF NOT EXISTS stage_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_key TEXT NOT NULL,
            from_stage TEXT,
            to_stage TEXT NOT NULL,
            transitioned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_stage_transitions_user ON stage_transitions(user_id);

        CREATE TABLE IF NOT EXISTS salary_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role_query TEXT NOT NULL,
            location TEXT,
            salary_min REAL,
            salary_max REAL,
            source TEXT,
            observed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_salary_obs_user ON salary_observations(user_id);
    """)
    conn.commit()

    # Schema migrations for existing databases
    _migrate_add_column(conn, "saved_searches", "is_active", "INTEGER DEFAULT 1")
    _migrate_add_column(conn, "users", "blocked_keywords", "TEXT DEFAULT '[]'")
    _migrate_add_column(conn, "users", "blocked_locations", "TEXT DEFAULT '[]'")
    _migrate_add_column(conn, "applied_jobs", "follow_up_date", "TEXT")
    _migrate_add_column(conn, "users", "scoring_weights", "TEXT")
    _migrate_add_column(conn, "users", "user_autofill_data", "TEXT")
    _migrate_add_column(conn, "users", "is_admin", "INTEGER DEFAULT 0")
    _migrate_add_column(conn, "search_history", "avg_salary", "REAL")
    _migrate_add_column(conn, "applied_jobs", "resume_id", "INTEGER")
    _migrate_add_column(conn, "users", "weekly_report_enabled", "INTEGER DEFAULT 1")

    seed_search_templates(conn)
    bootstrap_admin(conn)

    _safe_close(conn)
    logger.info("Database initialized at %s", Config.DB_PATH)


def bootstrap_admin(conn=None):
    """Create or promote the admin user from ADMIN_EMAIL / ADMIN_PASSWORD env vars."""
    admin_email = Config.ADMIN_EMAIL
    if not admin_email:
        return
    admin_email = admin_email.lower().strip()
    own_conn = conn is None
    if own_conn:
        conn = get_db()

    row = conn.execute("SELECT id, is_admin FROM users WHERE email = ?", (admin_email,)).fetchone()
    if row:
        if not row["is_admin"]:
            conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (row["id"],))
            conn.commit()
            logger.info("Promoted existing user %s to admin", admin_email)
    else:
        admin_password = Config.ADMIN_PASSWORD
        if not admin_password:
            logger.warning("ADMIN_EMAIL is set but ADMIN_PASSWORD is not — cannot create admin account")
        else:
            conn.execute(
                "INSERT INTO users (email, password_hash, name, is_admin) VALUES (?, ?, ?, 1)",
                (admin_email, generate_password_hash(admin_password), "Admin"),
            )
            conn.commit()
            logger.info("Created admin account for %s", admin_email)

    if own_conn:
        _safe_close(conn)


def _migrate_add_column(conn, table, column, col_type):
    """Add a column to an existing table if it doesn't exist."""
    try:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            conn.commit()
            logger.info("Migrated: added %s.%s", table, column)
    except Exception as e:
        logger.warning("Migration failed for %s.%s: %s", table, column, e)


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
        _safe_close(conn)
        return None  # Email already exists
    _safe_close(conn)
    return user_id


def authenticate_user(email, password):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
    ).fetchone()
    _safe_close(conn)
    if row and check_password_hash(row["password_hash"], password):
        return dict(row)
    return None


def get_user_by_id(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    _safe_close(conn)
    return dict(row) if row else None


def get_user_by_email(email):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
    ).fetchone()
    _safe_close(conn)
    return dict(row) if row else None


def update_user_password(user_id, new_password):
    conn = get_db()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), user_id),
    )
    conn.commit()
    _safe_close(conn)


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
    _safe_close(conn)
    return token


def validate_reset_token(token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM password_reset_tokens WHERE token_hash = ?", (token_hash,)
    ).fetchone()
    _safe_close(conn)
    if not row:
        return None
    if datetime.utcnow() > datetime.fromisoformat(row["expires_at"]):
        return None
    return row["user_id"]


def consume_reset_token(token):
    """Atomically validate and consume a reset token. Returns user_id or None."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM password_reset_tokens WHERE token_hash = ?", (token_hash,)
    ).fetchone()
    if not row:
        _safe_close(conn)
        return None
    if datetime.utcnow() > datetime.fromisoformat(row["expires_at"]):
        conn.execute("DELETE FROM password_reset_tokens WHERE token_hash = ?", (token_hash,))
        conn.commit()
        _safe_close(conn)
        return None
    conn.execute("DELETE FROM password_reset_tokens WHERE token_hash = ?", (token_hash,))
    conn.commit()
    _safe_close(conn)
    return row["user_id"]


# --- Saved Searches ---

def create_saved_search(user_id, query, location, remote_only, skills_json, frequency):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO saved_searches (user_id, query, location, remote_only, skills_json, frequency) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, query, location, int(remote_only), skills_json, frequency),
    )
    conn.commit()
    search_id = cursor.lastrowid
    _safe_close(conn)
    return search_id


def get_saved_searches(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM saved_searches WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    _safe_close(conn)
    return rows


def get_all_saved_searches():
    """Get all active saved searches across all users (for scheduler)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT ss.*, u.email FROM saved_searches ss JOIN users u ON ss.user_id = u.id "
        "WHERE ss.is_active = 1 ORDER BY ss.id"
    ).fetchall()
    _safe_close(conn)
    return rows


def delete_saved_search(search_id, user_id):
    conn = get_db()
    conn.execute(
        "DELETE FROM saved_searches WHERE id = ? AND user_id = ?",
        (search_id, user_id),
    )
    conn.commit()
    _safe_close(conn)


def toggle_saved_search(search_id, user_id, is_active):
    """Enable or disable a single alert."""
    conn = get_db()
    conn.execute(
        "UPDATE saved_searches SET is_active = ? WHERE id = ? AND user_id = ?",
        (int(is_active), search_id, user_id),
    )
    conn.commit()
    _safe_close(conn)


def toggle_all_saved_searches(user_id, is_active):
    """Enable or disable all alerts for a user."""
    conn = get_db()
    conn.execute(
        "UPDATE saved_searches SET is_active = ? WHERE user_id = ?",
        (int(is_active), user_id),
    )
    conn.commit()
    _safe_close(conn)


def update_last_notified(search_id):
    conn = get_db()
    conn.execute(
        "UPDATE saved_searches SET last_notified_at = CURRENT_TIMESTAMP WHERE id = ?",
        (search_id,),
    )
    conn.commit()
    _safe_close(conn)


def get_user_email_count_today(user_id):
    """Count how many digest emails were sent to this user today."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM saved_searches "
        "WHERE user_id = ? AND last_notified_at >= datetime('now', '-24 hours')",
        (user_id,),
    ).fetchone()
    _safe_close(conn)
    return row["cnt"] if row else 0


# --- Seen Jobs ---

def add_seen_jobs(search_id, job_keys):
    conn = get_db()
    conn.executemany(
        "INSERT OR IGNORE INTO seen_jobs (search_id, job_key) VALUES (?, ?)",
        [(search_id, key) for key in job_keys],
    )
    conn.commit()
    _safe_close(conn)


def get_seen_job_keys(search_id):
    conn = get_db()
    rows = conn.execute("SELECT job_key FROM seen_jobs WHERE search_id = ?", (search_id,)).fetchall()
    _safe_close(conn)
    return {row["job_key"] for row in rows}


# --- Applied Jobs ---

PIPELINE_STAGES = ["applied", "screen", "interview", "offer", "rejected", "withdrawn"]


def mark_applied(user_id, job_key, title, company, notes="", location="", apply_url="", stage="applied"):
    conn = get_db()
    # Check if this is a new application or update
    existing = conn.execute(
        "SELECT stage FROM applied_jobs WHERE user_id = ? AND job_key = ?",
        (user_id, job_key),
    ).fetchone()

    conn.execute(
        """INSERT INTO applied_jobs (user_id, job_key, title, company, location, apply_url, stage, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, job_key) DO UPDATE SET
               stage = excluded.stage, notes = excluded.notes, updated_at = CURRENT_TIMESTAMP""",
        (user_id, job_key, title, company, location, apply_url, stage, notes),
    )

    # Record stage transition
    from_stage = existing["stage"] if existing else None
    if from_stage != stage:
        conn.execute(
            "INSERT INTO stage_transitions (user_id, job_key, from_stage, to_stage) VALUES (?, ?, ?, ?)",
            (user_id, job_key, from_stage, stage),
        )

    conn.commit()
    _safe_close(conn)


def update_applied_stage(user_id, job_key, stage, notes=None):
    conn = get_db()
    # Get current stage before updating (for transition tracking)
    current = conn.execute(
        "SELECT stage FROM applied_jobs WHERE user_id = ? AND job_key = ?",
        (user_id, job_key),
    ).fetchone()
    from_stage = current["stage"] if current else None

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

    # Record stage transition
    if from_stage != stage:
        conn.execute(
            "INSERT INTO stage_transitions (user_id, job_key, from_stage, to_stage) VALUES (?, ?, ?, ?)",
            (user_id, job_key, from_stage, stage),
        )

    conn.commit()
    _safe_close(conn)


def update_applied_notes(user_id, job_key, notes):
    conn = get_db()
    conn.execute(
        "UPDATE applied_jobs SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND job_key = ?",
        (notes, user_id, job_key),
    )
    conn.commit()
    _safe_close(conn)


def unmark_applied(user_id, job_key):
    conn = get_db()
    conn.execute("DELETE FROM applied_jobs WHERE user_id = ? AND job_key = ?", (user_id, job_key))
    conn.commit()
    _safe_close(conn)


def get_applied_job_keys(user_id):
    conn = get_db()
    rows = conn.execute("SELECT job_key FROM applied_jobs WHERE user_id = ?", (user_id,)).fetchall()
    _safe_close(conn)
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
    _safe_close(conn)
    return rows


def get_applied_stats(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT stage, COUNT(*) as count FROM applied_jobs WHERE user_id = ? GROUP BY stage",
        (user_id,),
    ).fetchall()
    _safe_close(conn)
    return {row["stage"]: row["count"] for row in rows}


# --- Company Cache ---

def get_cached_company(company_name):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM company_cache WHERE company_name = ? AND scraped_at > datetime('now', '-7 days')",
        (company_name,),
    ).fetchone()
    _safe_close(conn)
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
    _safe_close(conn)


# --- User Settings ---

def get_user_settings(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT timezone, max_commute_minutes, seniority_tier, blocked_companies, blocked_keywords, blocked_locations, scoring_weights, user_autofill_data, weekly_report_enabled FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    _safe_close(conn)
    return dict(row) if row else {}


def update_user_settings(user_id, **kwargs):
    conn = get_db()
    allowed = {"timezone", "max_commute_minutes", "seniority_tier", "blocked_companies", "blocked_keywords", "blocked_locations", "name", "scoring_weights", "user_autofill_data", "weekly_report_enabled"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    assert all(k in allowed for k in fields), f"Disallowed field(s) in SQL: {set(fields) - allowed}"
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [user_id]
    conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
    conn.commit()
    _safe_close(conn)


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
    _safe_close(conn)
    return resume_id


def get_resumes(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM resumes WHERE user_id = ? ORDER BY is_default DESC, updated_at DESC",
        (user_id,),
    ).fetchall()
    _safe_close(conn)
    return rows


def get_resume(resume_id, user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM resumes WHERE id = ? AND user_id = ?", (resume_id, user_id)
    ).fetchone()
    _safe_close(conn)
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
    _safe_close(conn)
    return dict(row) if row else None


def set_default_resume(resume_id, user_id):
    conn = get_db()
    conn.execute("UPDATE resumes SET is_default = 0 WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE resumes SET is_default = 1 WHERE id = ? AND user_id = ?", (resume_id, user_id))
    conn.commit()
    _safe_close(conn)


def delete_resume(resume_id, user_id):
    conn = get_db()
    conn.execute("DELETE FROM resumes WHERE id = ? AND user_id = ?", (resume_id, user_id))
    conn.commit()
    _safe_close(conn)


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
    _safe_close(conn)


# --- Search History ---

def add_search_history(user_id, query, location, remote_only, resume_id=None, result_count=0):
    conn = get_db()
    conn.execute(
        "INSERT INTO search_history (user_id, query, location, remote_only, resume_id, result_count) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, query, location, int(remote_only), resume_id, result_count),
    )
    conn.commit()
    _safe_close(conn)


def get_search_history(user_id, limit=20):
    conn = get_db()
    rows = conn.execute(
        """SELECT sh.*, r.name as resume_name FROM search_history sh
           LEFT JOIN resumes r ON sh.resume_id = r.id
           WHERE sh.user_id = ? ORDER BY sh.searched_at DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    _safe_close(conn)
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
    _safe_close(conn)


def unbookmark_job(user_id, job_key):
    conn = get_db()
    conn.execute("DELETE FROM bookmarked_jobs WHERE user_id = ? AND job_key = ?", (user_id, job_key))
    conn.commit()
    _safe_close(conn)


def get_bookmarked_jobs(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM bookmarked_jobs WHERE user_id = ? ORDER BY bookmarked_at DESC",
        (user_id,),
    ).fetchall()
    _safe_close(conn)
    return rows


def get_bookmarked_job_keys(user_id):
    conn = get_db()
    rows = conn.execute("SELECT job_key FROM bookmarked_jobs WHERE user_id = ?", (user_id,)).fetchall()
    _safe_close(conn)
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
    _safe_close(conn)
    return next_version


def get_resume_versions(resume_id, user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM resume_versions WHERE resume_id = ? AND user_id = ? ORDER BY version_number DESC",
        (resume_id, user_id),
    ).fetchall()
    _safe_close(conn)
    return rows


def get_resume_version(version_id, user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM resume_versions WHERE id = ? AND user_id = ?",
        (version_id, user_id),
    ).fetchone()
    _safe_close(conn)
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
    _safe_close(conn)
    return token


def get_shared_job(token):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM shared_jobs WHERE share_token = ?", (token,)
    ).fetchone()
    _safe_close(conn)
    return dict(row) if row else None


def purge_old_shared_jobs(days=30):
    """Delete shared_jobs older than the given number of days."""
    conn = get_db()
    conn.execute(
        "DELETE FROM shared_jobs WHERE created_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    conn.commit()
    _safe_close(conn)


# --- Notifications ---

def create_notification(user_id, message, link=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)",
        (user_id, message, link),
    )
    conn.commit()
    _safe_close(conn)


def get_unread_notifications(user_id, limit=10):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    _safe_close(conn)
    return rows


def get_unread_count(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND is_read = 0",
        (user_id,),
    ).fetchone()
    _safe_close(conn)
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
    _safe_close(conn)


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
    _safe_close(conn)


def undismiss_job(user_id, job_key):
    conn = get_db()
    conn.execute("DELETE FROM dismissed_jobs WHERE user_id = ? AND job_key = ?", (user_id, job_key))
    conn.commit()
    _safe_close(conn)


def get_dismissed_job_keys(user_id):
    conn = get_db()
    rows = conn.execute("SELECT job_key FROM dismissed_jobs WHERE user_id = ?", (user_id,)).fetchall()
    _safe_close(conn)
    return {row["job_key"] for row in rows}


def get_dismissed_jobs(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM dismissed_jobs WHERE user_id = ? ORDER BY dismissed_at DESC",
        (user_id,),
    ).fetchall()
    _safe_close(conn)
    return rows


# --- Role Velocity ---

# --- API Usage ---

def log_api_usage(user_id, provider, endpoint, model=None,
                  tokens_input=0, tokens_output=0, estimated_cost_usd=0.0,
                  response_time_ms=0, success=1, error_message=None):
    conn = get_db()
    conn.execute(
        """INSERT INTO api_usage
           (user_id, provider, endpoint, model, tokens_input, tokens_output,
            estimated_cost_usd, response_time_ms, success, error_message)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, provider, endpoint, model, tokens_input, tokens_output,
         estimated_cost_usd, response_time_ms, success, error_message),
    )
    conn.commit()
    _safe_close(conn)


def purge_old_api_usage(days=90):
    """Delete api_usage rows older than the given number of days."""
    conn = get_db()
    conn.execute(
        "DELETE FROM api_usage WHERE created_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    conn.commit()
    _safe_close(conn)


def _usage_where(user_id, days):
    """Build a WHERE clause for api_usage queries."""
    where = "WHERE created_at > datetime('now', ?)"
    params = [f"-{days} days"]
    if user_id is not None:
        where += " AND user_id = ?"
        params.append(user_id)
    return where, params


def get_api_usage_summary(user_id=None, days=30):
    """Aggregated cost and call count by provider."""
    conn = get_db()
    where, params = _usage_where(user_id, days)
    rows = conn.execute(
        f"""SELECT provider,
                   COUNT(*) as call_count,
                   COALESCE(SUM(tokens_input), 0) as total_input_tokens,
                   COALESCE(SUM(tokens_output), 0) as total_output_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as total_cost,
                   COALESCE(AVG(response_time_ms), 0) as avg_response_ms,
                   SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as error_count
            FROM api_usage {where}
            GROUP BY provider ORDER BY total_cost DESC""",
        params,
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def get_api_usage_daily(user_id=None, days=30):
    """Daily cost and call count totals."""
    conn = get_db()
    where, params = _usage_where(user_id, days)
    rows = conn.execute(
        f"""SELECT DATE(created_at) as date,
                   COUNT(*) as call_count,
                   COALESCE(SUM(estimated_cost_usd), 0) as total_cost,
                   COALESCE(SUM(COALESCE(tokens_input, 0) + COALESCE(tokens_output, 0)), 0) as total_tokens
            FROM api_usage {where}
            GROUP BY DATE(created_at) ORDER BY date""",
        params,
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def get_api_usage_recent(user_id=None, days=30, limit=50):
    """Recent API calls log."""
    conn = get_db()
    where, params = _usage_where(user_id, days)
    params.append(limit)
    rows = conn.execute(
        f"""SELECT * FROM api_usage {where}
            ORDER BY created_at DESC LIMIT ?""",
        params,
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def get_role_velocity(company, title, months=6):
    conn = get_db()
    row = conn.execute(
        """SELECT COUNT(DISTINCT sj.job_key) as count
           FROM seen_jobs sj
           WHERE sj.job_key LIKE ? AND sj.first_seen_at > datetime('now', ?)""",
        (f"%{company}%{title}%", f"-{months} months"),
    ).fetchone()
    _safe_close(conn)
    return row["count"] if row else 0


# --- Search Templates ---

def seed_search_templates(conn=None):
    """Insert system search templates, adding any missing ones by name."""
    own_conn = conn is None
    if own_conn:
        conn = get_db()
    templates = [
        ("Remote Python Backend Engineer", "Engineering", "python backend engineer", "", 1, "Python, Django/Flask, APIs, microservices"),
        ("Full-Stack React Developer", "Engineering", "full stack react developer", "", 0, "React, Node.js, full-stack web development"),
        ("Senior Data Engineer", "Data", "senior data engineer", "", 0, "ETL pipelines, Spark, SQL, data warehousing"),
        ("DevOps / SRE Engineer", "DevOps", "devops site reliability engineer", "", 0, "Kubernetes, Docker, CI/CD, cloud infrastructure"),
        ("Product Manager - Tech", "Product", "technical product manager", "", 0, "Product roadmap, Agile, stakeholder management"),
        ("UX/UI Designer", "Design", "ux ui designer", "", 0, "Figma, user research, design systems"),
        ("Machine Learning Engineer", "Data", "machine learning engineer", "", 0, "Python, PyTorch/TensorFlow, ML pipelines"),
        ("Cloud Solutions Architect", "DevOps", "cloud solutions architect AWS", "", 0, "AWS, system design, cloud migration"),
        ("Frontend Engineer (React/Vue)", "Engineering", "frontend engineer react vue", "", 0, "React, Vue, TypeScript, CSS"),
        ("Backend Java/Kotlin Developer", "Engineering", "backend java kotlin developer", "", 0, "Java, Spring Boot, Kotlin, microservices"),
        ("Data Analyst / BI", "Data", "data analyst business intelligence", "", 0, "SQL, Tableau/Power BI, Python, data visualization"),
        ("Mobile Developer (iOS/Android)", "Engineering", "mobile developer ios android", "", 0, "Swift, Kotlin, React Native, Flutter"),
        # Healthcare
        ("Registered Nurse (RN)", "Healthcare", "registered nurse RN", "", 0, "Bedside care, patient assessment, clinical nursing"),
        ("Travel Nurse", "Healthcare", "travel nurse contract", "", 0, "Travel nursing assignments, contract RN positions"),
        ("Nurse Practitioner (NP)", "Healthcare", "nurse practitioner NP", "", 0, "Advanced practice, primary care, prescriptive authority"),
        ("Medical Assistant", "Healthcare", "medical assistant", "", 0, "Clinical support, vitals, patient intake, EHR"),
        ("Healthcare Administrator", "Healthcare", "healthcare administrator manager", "", 0, "Hospital operations, compliance, staff management"),
        ("Physical Therapist", "Healthcare", "physical therapist PT", "", 0, "Rehabilitation, musculoskeletal, patient mobility"),
        ("Pharmacy Technician", "Healthcare", "pharmacy technician", "", 0, "Prescription processing, inventory, patient counseling support"),
        ("Medical Coder / Biller", "Healthcare", "medical coder biller", "", 1, "ICD-10, CPT coding, revenue cycle, claims processing"),
        ("Health Informatics", "Healthcare", "health informatics analyst", "", 0, "EHR systems, clinical data, healthcare IT"),
    ]
    existing = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM search_templates WHERE is_system = 1"
        ).fetchall()
    }
    new_templates = [t for t in templates if t[0] not in existing]
    if new_templates:
        conn.executemany(
            """INSERT INTO search_templates (name, category, query, location, remote_only, description, is_system, user_id)
               VALUES (?, ?, ?, ?, ?, ?, 1, NULL)""",
            new_templates,
        )
        conn.commit()
        logger.info("Seeded %d system search templates", len(new_templates))
    if own_conn:
        _safe_close(conn)


def get_search_templates(user_id=None):
    """Return system templates plus user's custom templates."""
    conn = get_db()
    if user_id:
        rows = conn.execute(
            "SELECT * FROM search_templates WHERE is_system = 1 OR user_id = ? ORDER BY category, name",
            (user_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM search_templates WHERE is_system = 1 ORDER BY category, name"
        ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def create_search_template(user_id, name, query, location="", remote_only=False, description="", category=""):
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO search_templates (name, category, query, location, remote_only, description, is_system, user_id)
           VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
        (name, category, query, location, int(remote_only), description, user_id),
    )
    conn.commit()
    tid = cursor.lastrowid
    _safe_close(conn)
    return tid


def delete_search_template(template_id, user_id):
    """Delete a user template. System templates cannot be deleted."""
    conn = get_db()
    conn.execute(
        "DELETE FROM search_templates WHERE id = ? AND user_id = ? AND is_system = 0",
        (template_id, user_id),
    )
    conn.commit()
    _safe_close(conn)


# --- Job Contacts ---

def add_job_contact(user_id, job_key, name="", email="", phone="", role="", notes=""):
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO job_contacts (user_id, job_key, name, email, phone, role, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, job_key, name, email, phone, role, notes),
    )
    conn.commit()
    cid = cursor.lastrowid
    _safe_close(conn)
    return cid


def get_job_contacts(user_id, job_key):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM job_contacts WHERE user_id = ? AND job_key = ? ORDER BY created_at DESC",
        (user_id, job_key),
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def update_job_contact(contact_id, user_id, **kwargs):
    conn = get_db()
    allowed = {"name", "email", "phone", "role", "notes"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        _safe_close(conn)
        return
    assert all(k in allowed for k in fields), f"Disallowed field(s) in SQL: {set(fields) - allowed}"
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [contact_id, user_id]
    conn.execute(f"UPDATE job_contacts SET {set_clause} WHERE id = ? AND user_id = ?", values)
    conn.commit()
    _safe_close(conn)


def delete_job_contact(contact_id, user_id):
    conn = get_db()
    conn.execute("DELETE FROM job_contacts WHERE id = ? AND user_id = ?", (contact_id, user_id))
    conn.commit()
    _safe_close(conn)


def update_follow_up_date(user_id, job_key, follow_up_date):
    conn = get_db()
    conn.execute(
        "UPDATE applied_jobs SET follow_up_date = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND job_key = ?",
        (follow_up_date, user_id, job_key),
    )
    conn.commit()
    _safe_close(conn)


# --- Interview Prep Cache ---

def get_cached_interview_prep(user_id, company, job_title):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM interview_prep_cache WHERE user_id = ? AND company = ? AND job_title = ? ORDER BY updated_at DESC LIMIT 1",
        (user_id, company, job_title),
    ).fetchone()
    _safe_close(conn)
    if row:
        result = dict(row)
        result["prep"] = json.loads(result["prep_json"])
        return result
    return None


def save_interview_prep(user_id, company, job_title, job_key, prep_json):
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM interview_prep_cache WHERE user_id = ? AND company = ? AND job_title = ?",
        (user_id, company, job_title),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE interview_prep_cache SET prep_json = ?, job_key = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (prep_json if isinstance(prep_json, str) else json.dumps(prep_json), job_key, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO interview_prep_cache (user_id, company, job_title, job_key, prep_json)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, company, job_title, job_key,
             prep_json if isinstance(prep_json, str) else json.dumps(prep_json)),
        )
    conn.commit()
    _safe_close(conn)


def get_all_interview_preps(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, company, job_title, job_key, created_at, updated_at FROM interview_prep_cache WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def get_interview_prep_by_id(prep_id, user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM interview_prep_cache WHERE id = ? AND user_id = ?",
        (prep_id, user_id),
    ).fetchone()
    _safe_close(conn)
    if row:
        result = dict(row)
        result["prep"] = json.loads(result["prep_json"])
        return result
    return None


def delete_interview_prep(prep_id, user_id):
    conn = get_db()
    conn.execute("DELETE FROM interview_prep_cache WHERE id = ? AND user_id = ?", (prep_id, user_id))
    conn.commit()
    _safe_close(conn)


def get_role_velocities_batch(company_title_pairs, months=6):
    """Batch role velocity lookup. Returns dict of (company, title) -> count."""
    if not company_title_pairs:
        return {}
    conn = get_db()
    cutoff = f"-{months} months"
    results = {}
    for company, title in company_title_pairs:
        row = conn.execute(
            """SELECT COUNT(DISTINCT job_key) as count FROM seen_jobs
               WHERE job_key LIKE ? AND first_seen_at > datetime('now', ?)""",
            (f"%{company}%{title}%", cutoff),
        ).fetchone()
        results[(company, title)] = row["count"] if row else 0
    _safe_close(conn)
    return results


# --- Job Description Snapshots ---

def snapshot_job_description(user_id, job_key, description):
    """Save a snapshot of a job description if it changed since the last snapshot.

    Returns True if a new snapshot was saved, False if unchanged.
    """
    desc_hash = hashlib.sha256((description or "").encode()).hexdigest()
    conn = get_db()

    # Check if we already have this exact version
    last = conn.execute(
        "SELECT description_hash FROM job_description_snapshots WHERE user_id = ? AND job_key = ? ORDER BY snapshot_at DESC LIMIT 1",
        (user_id, job_key),
    ).fetchone()

    if last and last["description_hash"] == desc_hash:
        _safe_close(conn)
        return False

    conn.execute(
        "INSERT INTO job_description_snapshots (user_id, job_key, description_hash, description) VALUES (?, ?, ?, ?)",
        (user_id, job_key, desc_hash, description),
    )
    conn.commit()
    _safe_close(conn)
    return True


def get_job_description_snapshots(user_id, job_key):
    """Return all snapshots for a job, ordered by date."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM job_description_snapshots WHERE user_id = ? AND job_key = ? ORDER BY snapshot_at ASC",
        (user_id, job_key),
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


# --- Follow-up Reminders ---

def get_due_follow_ups(days_ahead=7):
    """Get all follow-ups due within the next N days across all users.

    Returns rows with user_id, job_key, title, company, follow_up_date, stage, email.
    """
    conn = get_db()
    rows = conn.execute(
        """SELECT aj.user_id, aj.job_key, aj.title, aj.company, aj.follow_up_date, aj.stage,
                  u.email, u.name
           FROM applied_jobs aj
           JOIN users u ON u.id = aj.user_id
           WHERE aj.follow_up_date IS NOT NULL
             AND aj.follow_up_date <= date('now', '+' || ? || ' days')
             AND aj.stage NOT IN ('rejected', 'withdrawn')
           ORDER BY aj.follow_up_date ASC""",
        (days_ahead,),
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def get_user_due_follow_ups(user_id, days_ahead=7):
    """Get follow-ups due for a specific user within the next N days."""
    conn = get_db()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    future = (datetime.utcnow() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT * FROM applied_jobs
           WHERE user_id = ?
             AND follow_up_date IS NOT NULL
             AND follow_up_date <= ?
             AND stage NOT IN ('rejected', 'withdrawn')
           ORDER BY follow_up_date ASC""",
        (user_id, future),
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


# --- Webhooks ---

def create_webhook(user_id, url, event_types=None, secret=None):
    conn = get_db()
    et = json.dumps(event_types or ["new_matches"])
    cursor = conn.execute(
        "INSERT INTO webhooks (user_id, url, event_types, secret) VALUES (?, ?, ?, ?)",
        (user_id, url, et, secret),
    )
    conn.commit()
    wid = cursor.lastrowid
    _safe_close(conn)
    return wid


def get_webhooks(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM webhooks WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def delete_webhook(webhook_id, user_id):
    conn = get_db()
    conn.execute("DELETE FROM webhooks WHERE id = ? AND user_id = ?", (webhook_id, user_id))
    conn.commit()
    _safe_close(conn)


def update_webhook_triggered(webhook_id):
    conn = get_db()
    conn.execute(
        "UPDATE webhooks SET last_triggered_at = CURRENT_TIMESTAMP WHERE id = ?",
        (webhook_id,),
    )
    conn.commit()
    _safe_close(conn)


def get_active_webhooks(user_id, event_type="new_matches"):
    """Get active webhooks for a user that match the given event type."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM webhooks WHERE user_id = ? AND is_active = 1",
        (user_id,),
    ).fetchall()
    _safe_close(conn)
    result = []
    for r in rows:
        try:
            types = json.loads(r["event_types"])
        except (json.JSONDecodeError, TypeError):
            types = ["new_matches"]
        if event_type in types:
            result.append(dict(r))
    return result


# --- Teams ---

def create_team(name, created_by):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO teams (name, created_by) VALUES (?, ?)",
        (name.strip(), created_by),
    )
    team_id = cursor.lastrowid
    # Creator is automatically an admin member
    conn.execute(
        "INSERT INTO team_members (team_id, user_id, role) VALUES (?, ?, 'admin')",
        (team_id, created_by),
    )
    conn.commit()
    _safe_close(conn)
    return team_id


def get_user_teams(user_id):
    conn = get_db()
    rows = conn.execute(
        """SELECT t.*, tm.role, u.name as creator_name, u.email as creator_email,
                  (SELECT COUNT(*) FROM team_members WHERE team_id = t.id) as member_count
           FROM teams t
           JOIN team_members tm ON tm.team_id = t.id AND tm.user_id = ?
           JOIN users u ON u.id = t.created_by
           ORDER BY t.created_at DESC""",
        (user_id,),
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def get_team(team_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
    _safe_close(conn)
    return dict(row) if row else None


def get_team_members(team_id):
    conn = get_db()
    rows = conn.execute(
        """SELECT tm.*, u.name, u.email
           FROM team_members tm
           JOIN users u ON u.id = tm.user_id
           WHERE tm.team_id = ?
           ORDER BY tm.joined_at ASC""",
        (team_id,),
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def is_team_member(team_id, user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM team_members WHERE team_id = ? AND user_id = ?",
        (team_id, user_id),
    ).fetchone()
    _safe_close(conn)
    return row is not None


def get_team_member_role(team_id, user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT role FROM team_members WHERE team_id = ? AND user_id = ?",
        (team_id, user_id),
    ).fetchone()
    _safe_close(conn)
    return row["role"] if row else None


def add_team_member(team_id, user_id, role="member"):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO team_members (team_id, user_id, role) VALUES (?, ?, ?)",
            (team_id, user_id, role),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        _safe_close(conn)
        return False
    _safe_close(conn)
    return True


def remove_team_member(team_id, user_id):
    conn = get_db()
    conn.execute(
        "DELETE FROM team_members WHERE team_id = ? AND user_id = ?",
        (team_id, user_id),
    )
    conn.commit()
    _safe_close(conn)


def delete_team(team_id):
    conn = get_db()
    conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))
    conn.commit()
    _safe_close(conn)


def share_job_with_team(team_id, shared_by, job_key, title="", company="", location="", apply_url="", notes=""):
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO team_shared_jobs (team_id, shared_by, job_key, title, company, location, apply_url, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (team_id, shared_by, job_key, title, company, location, apply_url, notes),
    )
    conn.commit()
    jid = cursor.lastrowid
    _safe_close(conn)
    return jid


def get_team_shared_jobs(team_id):
    conn = get_db()
    rows = conn.execute(
        """SELECT tsj.*, u.name as shared_by_name, u.email as shared_by_email
           FROM team_shared_jobs tsj
           JOIN users u ON u.id = tsj.shared_by
           WHERE tsj.team_id = ?
           ORDER BY tsj.created_at DESC""",
        (team_id,),
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def get_team_shared_job(job_id):
    conn = get_db()
    row = conn.execute(
        """SELECT tsj.*, u.name as shared_by_name, u.email as shared_by_email
           FROM team_shared_jobs tsj
           JOIN users u ON u.id = tsj.shared_by
           WHERE tsj.id = ?""",
        (job_id,),
    ).fetchone()
    _safe_close(conn)
    return dict(row) if row else None


def add_team_job_comment(team_shared_job_id, user_id, comment):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO team_job_comments (team_shared_job_id, user_id, comment) VALUES (?, ?, ?)",
        (team_shared_job_id, user_id, comment),
    )
    conn.commit()
    cid = cursor.lastrowid
    _safe_close(conn)
    return cid


def get_team_job_comments(team_shared_job_id):
    conn = get_db()
    rows = conn.execute(
        """SELECT tjc.*, u.name, u.email
           FROM team_job_comments tjc
           JOIN users u ON u.id = tjc.user_id
           WHERE tjc.team_shared_job_id = ?
           ORDER BY tjc.created_at ASC""",
        (team_shared_job_id,),
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def get_team_activity(team_id, limit=20):
    """Get recent team activity (shares and comments)."""
    conn = get_db()
    # Get recent shared jobs
    shares = conn.execute(
        """SELECT 'share' as activity_type, tsj.created_at, u.name as user_name, u.email as user_email,
                  tsj.title as job_title, tsj.company as job_company, tsj.id as item_id
           FROM team_shared_jobs tsj
           JOIN users u ON u.id = tsj.shared_by
           WHERE tsj.team_id = ?
           ORDER BY tsj.created_at DESC LIMIT ?""",
        (team_id, limit),
    ).fetchall()

    # Get recent comments
    comments = conn.execute(
        """SELECT 'comment' as activity_type, tjc.created_at, u.name as user_name, u.email as user_email,
                  tsj.title as job_title, tsj.company as job_company, tjc.team_shared_job_id as item_id
           FROM team_job_comments tjc
           JOIN users u ON u.id = tjc.user_id
           JOIN team_shared_jobs tsj ON tsj.id = tjc.team_shared_job_id
           WHERE tsj.team_id = ?
           ORDER BY tjc.created_at DESC LIMIT ?""",
        (team_id, limit),
    ).fetchall()

    _safe_close(conn)

    activity = [dict(r) for r in shares] + [dict(r) for r in comments]
    activity.sort(key=lambda a: a["created_at"], reverse=True)
    return activity[:limit]


# --- Merged Jobs (Deduplication Provenance) ---

def record_merge(canonical_job_key, source_job_key, source_name, source_url=None):
    """Record that a duplicate job was merged into a canonical listing."""
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO merged_jobs (canonical_job_key, source_job_key, source_name, source_url)
           VALUES (?, ?, ?, ?)""",
        (canonical_job_key, source_job_key, source_name, source_url),
    )
    conn.commit()
    _safe_close(conn)


def record_merges_batch(merges):
    """Record multiple merges at once. merges is a list of (canonical_key, source_key, source_name, source_url)."""
    if not merges:
        return
    conn = get_db()
    conn.executemany(
        """INSERT OR IGNORE INTO merged_jobs (canonical_job_key, source_job_key, source_name, source_url)
           VALUES (?, ?, ?, ?)""",
        merges,
    )
    conn.commit()
    _safe_close(conn)


def get_merge_sources(canonical_job_key):
    """Get all alternate sources for a canonical job key."""
    conn = get_db()
    rows = conn.execute(
        "SELECT source_name, source_url, merged_at FROM merged_jobs WHERE canonical_job_key = ? ORDER BY merged_at DESC",
        (canonical_job_key,),
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def get_merge_sources_batch(job_keys):
    """Get alternate sources for multiple job keys at once. Returns dict of job_key -> list of sources."""
    if not job_keys:
        return {}
    conn = get_db()
    placeholders = ",".join("?" * len(job_keys))
    rows = conn.execute(
        f"SELECT canonical_job_key, source_name, source_url FROM merged_jobs WHERE canonical_job_key IN ({placeholders})",
        list(job_keys),
    ).fetchall()
    _safe_close(conn)

    result = {}
    for row in rows:
        key = row["canonical_job_key"]
        if key not in result:
            result[key] = []
        result[key].append({"source": row["source_name"], "url": row["source_url"]})
    return result


# --- Stage Transitions ---

def get_stage_transitions(user_id, job_key=None):
    """Get stage transitions for a user, optionally filtered by job key."""
    conn = get_db()
    if job_key:
        rows = conn.execute(
            "SELECT * FROM stage_transitions WHERE user_id = ? AND job_key = ? ORDER BY transitioned_at ASC",
            (user_id, job_key),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM stage_transitions WHERE user_id = ? ORDER BY transitioned_at ASC",
            (user_id,),
        ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


# --- Salary Observations ---

def record_salary_observation(user_id, role_query, location=None, salary_min=None, salary_max=None, source=None):
    """Record a salary observation from search results."""
    conn = get_db()
    conn.execute(
        """INSERT INTO salary_observations (user_id, role_query, location, salary_min, salary_max, source)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, role_query, location, salary_min, salary_max, source),
    )
    conn.commit()
    _safe_close(conn)


def record_salary_observations_batch(observations):
    """Record multiple salary observations. observations is list of (user_id, role_query, location, salary_min, salary_max, source)."""
    if not observations:
        return
    conn = get_db()
    conn.executemany(
        """INSERT INTO salary_observations (user_id, role_query, location, salary_min, salary_max, source)
           VALUES (?, ?, ?, ?, ?, ?)""",
        observations,
    )
    conn.commit()
    _safe_close(conn)


def get_salary_benchmarks(user_id, role_query=None):
    """Compute salary percentiles from salary_data (existing) and salary_observations tables.

    Returns dict with p25, median, p75, sample_size, by_role.
    """
    import statistics as _stats

    conn = get_db()
    params = [user_id]
    where_extra = ""
    if role_query:
        where_extra = " AND role_query LIKE ?"
        params.append(f"%{role_query}%")

    # Pull from both salary_data and salary_observations
    midpoints = []

    # From salary_data
    rows1 = conn.execute(
        f"SELECT salary_min, salary_max, role_query FROM salary_data WHERE user_id = ?{where_extra} ORDER BY recorded_at DESC LIMIT 500",
        params,
    ).fetchall()
    for r in rows1:
        s_min = r["salary_min"] or 0
        s_max = r["salary_max"] or 0
        if s_min > 0 or s_max > 0:
            mid = (s_min + s_max) / 2 if s_min > 0 and s_max > 0 else max(s_min, s_max)
            midpoints.append(mid)

    # From salary_observations
    params2 = [user_id]
    where2 = ""
    if role_query:
        where2 = " AND role_query LIKE ?"
        params2.append(f"%{role_query}%")

    rows2 = conn.execute(
        f"SELECT salary_min, salary_max FROM salary_observations WHERE user_id = ?{where2} ORDER BY observed_at DESC LIMIT 500",
        params2,
    ).fetchall()
    for r in rows2:
        s_min = r["salary_min"] or 0
        s_max = r["salary_max"] or 0
        if s_min > 0 or s_max > 0:
            mid = (s_min + s_max) / 2 if s_min > 0 and s_max > 0 else max(s_min, s_max)
            midpoints.append(mid)

    _safe_close(conn)

    if not midpoints:
        return {"p25": None, "median": None, "p75": None, "sample_size": 0}

    midpoints.sort()
    n = len(midpoints)
    return {
        "p25": round(midpoints[n // 4]) if n >= 4 else round(midpoints[0]),
        "median": round(_stats.median(midpoints)),
        "p75": round(midpoints[3 * n // 4]) if n >= 4 else round(midpoints[-1]),
        "sample_size": n,
    }


# --- Search History with avg_salary ---

def add_search_history_with_salary(user_id, query, location, remote_only, resume_id=None, result_count=0, avg_salary=None):
    """Add search history entry including optional average salary."""
    conn = get_db()
    conn.execute(
        "INSERT INTO search_history (user_id, query, location, remote_only, resume_id, result_count, avg_salary) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, query, location, int(remote_only), resume_id, result_count, avg_salary),
    )
    conn.commit()
    _safe_close(conn)


# --- Admin ---

def get_admin_stats():
    """Get aggregate system stats for admin dashboard."""
    conn = get_db()
    stats = {}
    stats["total_users"] = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    stats["total_searches"] = conn.execute("SELECT COUNT(*) as c FROM search_history").fetchone()["c"]
    stats["total_api_calls"] = conn.execute("SELECT COUNT(*) as c FROM api_usage").fetchone()["c"]
    stats["total_cost"] = conn.execute("SELECT COALESCE(SUM(estimated_cost_usd), 0) as c FROM api_usage").fetchone()["c"]
    stats["active_alerts"] = conn.execute("SELECT COUNT(*) as c FROM saved_searches WHERE is_active = 1").fetchone()["c"]
    stats["total_applied"] = conn.execute("SELECT COUNT(*) as c FROM applied_jobs").fetchone()["c"]
    stats["total_bookmarks"] = conn.execute("SELECT COUNT(*) as c FROM bookmarked_jobs").fetchone()["c"]
    stats["total_teams"] = conn.execute("SELECT COUNT(*) as c FROM teams").fetchone()["c"]
    stats["total_resumes"] = conn.execute("SELECT COUNT(*) as c FROM resumes").fetchone()["c"]
    _safe_close(conn)
    return stats


def get_admin_users():
    """Get all users with aggregate stats for admin view."""
    conn = get_db()
    rows = conn.execute(
        """SELECT u.id, u.email, u.name, u.is_admin, u.created_at,
                  (SELECT COUNT(*) FROM search_history WHERE user_id = u.id) as search_count,
                  (SELECT COUNT(*) FROM applied_jobs WHERE user_id = u.id) as applied_count,
                  (SELECT MAX(searched_at) FROM search_history WHERE user_id = u.id) as last_active
           FROM users u
           ORDER BY u.created_at DESC""",
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def is_user_admin(user_id):
    conn = get_db()
    row = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    _safe_close(conn)
    return bool(row and row["is_admin"])


# --- API Tokens ---

def create_api_token(user_id, name="API Token"):
    """Create a new API token. Returns the plain token (only shown once); stores the hash."""
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO api_tokens (user_id, token_hash, name) VALUES (?, ?, ?)",
        (user_id, token_hash, name),
    )
    conn.commit()
    _safe_close(conn)
    return token, cursor.lastrowid


def validate_api_token(token):
    """Validate an API token and return the user_id, or None if invalid."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    conn = get_db()
    row = conn.execute(
        "SELECT user_id FROM api_tokens WHERE token_hash = ?", (token_hash,)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE api_tokens SET last_used_at = CURRENT_TIMESTAMP WHERE token_hash = ?",
            (token_hash,),
        )
        conn.commit()
    _safe_close(conn)
    return row["user_id"] if row else None


def get_api_tokens(user_id):
    """Get all API tokens for a user (without hashes)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, created_at, last_used_at FROM api_tokens WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def delete_api_token(token_id, user_id):
    """Delete an API token."""
    conn = get_db()
    conn.execute(
        "DELETE FROM api_tokens WHERE id = ? AND user_id = ?",
        (token_id, user_id),
    )
    conn.commit()
    _safe_close(conn)


# --- OAuth Accounts ---

def create_oauth_account(user_id, provider, provider_user_id, email=None):
    """Link an OAuth account to a user."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO oauth_accounts (user_id, provider, provider_user_id, email) VALUES (?, ?, ?, ?)",
            (user_id, provider, provider_user_id, email),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        _safe_close(conn)
        return False
    _safe_close(conn)
    return True


def get_oauth_account(provider, provider_user_id):
    """Get a user by OAuth provider + ID."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM oauth_accounts WHERE provider = ? AND provider_user_id = ?",
        (provider, provider_user_id),
    ).fetchone()
    _safe_close(conn)
    return dict(row) if row else None


def link_oauth_account(user_id, provider, provider_user_id, email=None):
    """Link an OAuth account to an existing user (alias for create_oauth_account)."""
    return create_oauth_account(user_id, provider, provider_user_id, email)


def get_user_oauth_accounts(user_id):
    """Get all OAuth accounts linked to a user."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM oauth_accounts WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


# --- Weekly Report Data ---

def get_weekly_report_users():
    """Get all users who have weekly reports enabled."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, email, name FROM users WHERE weekly_report_enabled = 1"
    ).fetchall()
    _safe_close(conn)
    return [dict(r) for r in rows]


def get_user_weekly_stats(user_id, days=7):
    """Get job search stats for the past N days for a user."""
    conn = get_db()
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    # Applications this week
    apps_this_week = conn.execute(
        "SELECT COUNT(*) as c FROM applied_jobs WHERE user_id = ? AND applied_at >= ?",
        (user_id, cutoff),
    ).fetchone()["c"]

    # Stage changes this week
    stage_changes = conn.execute(
        """SELECT st.job_key, st.from_stage, st.to_stage, st.transitioned_at,
                  aj.title, aj.company
           FROM stage_transitions st
           LEFT JOIN applied_jobs aj ON aj.user_id = st.user_id AND aj.job_key = st.job_key
           WHERE st.user_id = ? AND st.transitioned_at >= ?
           ORDER BY st.transitioned_at DESC""",
        (user_id, cutoff),
    ).fetchall()

    # Total applications
    total_apps = conn.execute(
        "SELECT COUNT(*) as c FROM applied_jobs WHERE user_id = ?",
        (user_id,),
    ).fetchone()["c"]

    # Response rate (any stage change from 'applied')
    total_applied = conn.execute(
        "SELECT COUNT(*) as c FROM applied_jobs WHERE user_id = ? AND stage = 'applied'",
        (user_id,),
    ).fetchone()["c"]
    responded = conn.execute(
        "SELECT COUNT(*) as c FROM applied_jobs WHERE user_id = ? AND stage NOT IN ('applied', 'withdrawn')",
        (user_id,),
    ).fetchone()["c"]
    response_rate = round(responded / total_apps * 100) if total_apps > 0 else 0

    # Interviews scheduled
    interviews = conn.execute(
        "SELECT COUNT(*) as c FROM applied_jobs WHERE user_id = ? AND stage = 'interview'",
        (user_id,),
    ).fetchone()["c"]

    # Upcoming follow-ups (next 7 days)
    future = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    upcoming_followups = conn.execute(
        """SELECT title, company, follow_up_date FROM applied_jobs
           WHERE user_id = ? AND follow_up_date IS NOT NULL
             AND follow_up_date >= ? AND follow_up_date <= ?
             AND stage NOT IN ('rejected', 'withdrawn')
           ORDER BY follow_up_date ASC""",
        (user_id, today, future),
    ).fetchall()

    _safe_close(conn)

    return {
        "apps_this_week": apps_this_week,
        "total_apps": total_apps,
        "response_rate": response_rate,
        "interviews": interviews,
        "stage_changes": [dict(r) for r in stage_changes],
        "upcoming_followups": [dict(r) for r in upcoming_followups],
    }


# --- Extension: My Jobs ---

def get_user_applied_and_bookmarked_keys(user_id):
    """Get applied job keys and bookmarked job keys for API extension endpoint."""
    conn = get_db()
    applied = conn.execute(
        "SELECT job_key FROM applied_jobs WHERE user_id = ?", (user_id,)
    ).fetchall()
    bookmarked = conn.execute(
        "SELECT job_key FROM bookmarked_jobs WHERE user_id = ?", (user_id,)
    ).fetchall()
    _safe_close(conn)
    return {
        "applied_keys": [r["job_key"] for r in applied],
        "bookmarked_keys": [r["job_key"] for r in bookmarked],
    }


# --- User creation with OAuth (no password) ---

def create_user_oauth(email, name=""):
    """Create a user without a password (for OAuth login). Returns user_id or None."""
    conn = get_db()
    # Use a random unusable password hash
    unusable_hash = "oauth_" + secrets.token_hex(32)
    try:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
            (email.lower().strip(), unusable_hash, name.strip()),
        )
        conn.commit()
        user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        _safe_close(conn)
        return None
    _safe_close(conn)
    return user_id
