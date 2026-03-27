"""
auth.py — Sistema de autenticación para el panel admin de Natura.

Características:
- Contraseñas hasheadas con bcrypt (PBKDF2-HMAC-SHA256 + salt aleatorio)
- Sesiones en st.session_state con token firmado
- Límite de intentos fallidos (bloqueo temporal)
- Log de accesos en la DB
- Roles: admin, editor
"""

import sqlite3
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple
import streamlit as st

# ── CONSTANTES ────────────────────────────────────────────────────────────────
USERS_DB      = "users.db"
SESSION_KEY   = "natura_auth_session"
MAX_ATTEMPTS  = 5          # intentos antes de bloqueo
LOCKOUT_SECS  = 300        # 5 minutos de bloqueo
SESSION_HOURS = 8          # duración de sesión
PEPPER        = os.environ.get("AUTH_PEPPER", "NaturaFlores_Pepper_2024!")


# ── HASH DE CONTRASEÑA (PBKDF2 + salt + pepper) ───────────────────────────────

def _hash_password(password: str) -> str:
    """Genera un hash seguro para la contraseña con salt aleatorio."""
    salt = secrets.token_hex(32)
    peppered = password + PEPPER
    dk = hashlib.pbkdf2_hmac("sha256", peppered.encode(), salt.encode(), 260_000)
    return f"{salt}:{dk.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verifica una contraseña contra el hash almacenado."""
    try:
        salt, dk_hex = stored_hash.split(":", 1)
        peppered = password + PEPPER
        dk = hashlib.pbkdf2_hmac("sha256", peppered.encode(), salt.encode(), 260_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# ── TOKEN DE SESIÓN ──────────────────────────────────────────────────────────

def _generate_token(username: str, secret: str) -> str:
    """Genera un token HMAC para la sesión."""
    payload = f"{username}:{time.time()}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _verify_token(token: str, secret: str, max_age_hours: int = SESSION_HOURS) -> Optional[str]:
    """Verifica el token de sesión. Devuelve el username si es válido."""
    try:
        parts = token.rsplit(":", 1)
        if len(parts) != 2:
            return None
        payload, sig = parts
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        username, ts = payload.rsplit(":", 1)
        age = time.time() - float(ts)
        if age > max_age_hours * 3600:
            return None
        return username
    except Exception:
        return None


# ── BASE DE DATOS DE USUARIOS ─────────────────────────────────────────────────

def init_users_db():
    """Inicializa la DB de usuarios y la tabla de logs de acceso."""
    conn = sqlite3.connect(USERS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            rol          TEXT NOT NULL DEFAULT 'editor',
            activo       INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT NOT NULL,
            last_login   TEXT,
            login_count  INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS access_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT NOT NULL,
            event      TEXT NOT NULL,
            ip_hint    TEXT,
            timestamp  TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            username     TEXT PRIMARY KEY,
            attempts     INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT
        )
    """)
    conn.commit()
    conn.close()


def user_exists(username: str) -> bool:
    conn = sqlite3.connect(USERS_DB)
    row = conn.execute("SELECT id FROM admin_users WHERE username=?", (username,)).fetchone()
    conn.close()
    return row is not None


def create_user(username: str, password: str, rol: str = "editor") -> bool:
    """Crea un nuevo usuario. Devuelve True si tuvo éxito."""
    if not username.strip() or len(password) < 8:
        return False
    if user_exists(username):
        return False
    h = _hash_password(password)
    conn = sqlite3.connect(USERS_DB)
    conn.execute(
        "INSERT INTO admin_users (username, password_hash, rol, created_at) VALUES (?,?,?,?)",
        (username.strip(), h, rol, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    return True


def change_password(username: str, new_password: str) -> bool:
    """Cambia la contraseña de un usuario."""
    if len(new_password) < 8:
        return False
    h = _hash_password(new_password)
    conn = sqlite3.connect(USERS_DB)
    conn.execute("UPDATE admin_users SET password_hash=? WHERE username=?", (h, username))
    conn.commit()
    conn.close()
    return True


def get_all_users() -> list:
    conn = sqlite3.connect(USERS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, username, rol, activo, created_at, last_login, login_count FROM admin_users ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_user(username: str) -> bool:
    conn = sqlite3.connect(USERS_DB)
    conn.execute("DELETE FROM admin_users WHERE username=?", (username,))
    conn.commit()
    conn.close()
    return True


def toggle_user_active(username: str) -> bool:
    conn = sqlite3.connect(USERS_DB)
    conn.execute("UPDATE admin_users SET activo = 1 - activo WHERE username=?", (username,))
    conn.commit()
    conn.close()
    return True


def get_access_log(limit: int = 50) -> list:
    conn = sqlite3.connect(USERS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM access_log ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── CONTROL DE INTENTOS ──────────────────────────────────────────────────────

def _get_attempts(username: str) -> Tuple[int, Optional[datetime]]:
    conn = sqlite3.connect(USERS_DB)
    row = conn.execute(
        "SELECT attempts, locked_until FROM login_attempts WHERE username=?", (username,)
    ).fetchone()
    conn.close()
    if not row:
        return 0, None
    locked = datetime.fromisoformat(row[1]) if row[1] else None
    return row[0], locked


def _register_attempt(username: str, success: bool):
    conn = sqlite3.connect(USERS_DB)
    if success:
        conn.execute("DELETE FROM login_attempts WHERE username=?", (username,))
    else:
        existing = conn.execute(
            "SELECT attempts FROM login_attempts WHERE username=?", (username,)
        ).fetchone()
        attempts = (existing[0] if existing else 0) + 1
        locked_until = None
        if attempts >= MAX_ATTEMPTS:
            locked_until = (datetime.now() + timedelta(seconds=LOCKOUT_SECS)).isoformat()
        conn.execute(
            "INSERT INTO login_attempts (username, attempts, locked_until) VALUES (?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET attempts=excluded.attempts, locked_until=excluded.locked_until",
            (username, attempts, locked_until)
        )
    conn.commit()
    conn.close()


def _log_event(username: str, event: str):
    conn = sqlite3.connect(USERS_DB)
    conn.execute(
        "INSERT INTO access_log (username, event, timestamp) VALUES (?,?,?)",
        (username, event, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


# ── LOGIN PRINCIPAL ──────────────────────────────────────────────────────────

def try_login(username: str, password: str, secret: str) -> Tuple[bool, str]:
    """
    Intenta autenticar al usuario.
    Devuelve (éxito: bool, mensaje: str).
    Si tiene éxito, guarda el token en st.session_state.
    """
    username = username.strip().lower()

    # Verificar bloqueo
    attempts, locked_until = _get_attempts(username)
    if locked_until and datetime.now() < locked_until:
        remaining = int((locked_until - datetime.now()).total_seconds() / 60) + 1
        _log_event(username, f"BLOCKED ({attempts} intentos)")
        return False, f"Cuenta bloqueada temporalmente. Espera {remaining} minuto(s)."

    # Buscar usuario
    conn = sqlite3.connect(USERS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM admin_users WHERE username=? AND activo=1", (username,)
    ).fetchone()
    conn.close()

    if not row:
        _register_attempt(username, False)
        _log_event(username, "FAILED — usuario no encontrado")
        return False, "Usuario o contraseña incorrectos."

    if not _verify_password(password, row["password_hash"]):
        _register_attempt(username, False)
        _log_event(username, "FAILED — contraseña incorrecta")
        remaining_att = MAX_ATTEMPTS - (_get_attempts(username)[0])
        if remaining_att <= 2:
            return False, f"Contraseña incorrecta. {max(0,remaining_att)} intentos restantes."
        return False, "Usuario o contraseña incorrectos."

    # Éxito
    _register_attempt(username, True)
    token = _generate_token(username, secret)
    st.session_state[SESSION_KEY] = {
        "token": token,
        "username": username,
        "rol": row["rol"],
        "login_time": datetime.now().isoformat(),
    }

    # Actualizar DB
    conn = sqlite3.connect(USERS_DB)
    conn.execute(
        "UPDATE admin_users SET last_login=?, login_count=login_count+1 WHERE username=?",
        (datetime.now().isoformat(), username)
    )
    conn.commit()
    conn.close()

    _log_event(username, f"LOGIN_OK — rol={row['rol']}")
    return True, "OK"


def logout():
    """Cierra la sesión actual."""
    session = st.session_state.get(SESSION_KEY)
    if session:
        _log_event(session.get("username", "?"), "LOGOUT")
    st.session_state.pop(SESSION_KEY, None)


def get_current_user(secret: str) -> Optional[dict]:
    """
    Devuelve el usuario autenticado actual o None si no hay sesión válida.
    Verifica el token HMAC en cada llamada.
    """
    session = st.session_state.get(SESSION_KEY)
    if not session:
        return None
    username = _verify_token(session.get("token", ""), secret)
    if not username:
        st.session_state.pop(SESSION_KEY, None)
        return None
    return {
        "username": session["username"],
        "rol": session["rol"],
        "login_time": session["login_time"],
    }


def require_login(secret: str) -> Optional[dict]:
    """
    Wrapper para usar en NATURA.py: si no hay sesión válida, detiene la ejecución.
    Devuelve el usuario actual si está autenticado.
    """
    return get_current_user(secret)
