from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import os
from pathlib import Path
from typing import List, Optional
import json
import sqlite3
from datetime import datetime
import logging
import re
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── RATE LIMITING (in-memory, por IP) ────────────────────────────────────────
from collections import defaultdict
import time as _time

_rate_store: dict = defaultdict(list)
_RATE_LIMIT   = 60   # peticiones
_RATE_WINDOW  = 60   # segundos

def _check_rate_limit(ip: str) -> bool:
    now = _time.time()
    window_start = now - _RATE_WINDOW
    _rate_store[ip] = [t for t in _rate_store[ip] if t > window_start]
    if len(_rate_store[ip]) >= _RATE_LIMIT:
        return False
    _rate_store[ip].append(now)
    return True

_db_base_env = os.environ.get("DB_BASE_PATH", ".")
DB_BASE = _db_base_env if os.path.isdir(_db_base_env) else "."
MEDIA_BASE = os.environ.get("MEDIA_BASE_PATH", os.path.join(DB_BASE, "media"))

_DEBUG = os.environ.get("APP_ENV", "production").lower() == "development"

app = FastAPI(
    title="Natura API",
    description="API para Natura — Flores y Plantas",
    version="1.0.0",
    docs_url="/docs" if _DEBUG else None,
    redoc_url="/redoc" if _DEBUG else None,
    openapi_url="/openapi.json" if _DEBUG else None,
)

FRONTEND_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
]
_prod_origin = os.environ.get("FRONTEND_ORIGIN", "")
if _prod_origin:
    FRONTEND_ORIGINS.append(_prod_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(ip):
        return JSONResponse(status_code=429, content={"detail": "Demasiadas peticiones. Intenta de nuevo en un minuto."})
    return await call_next(request)

# ── MODELOS ──────────────────────────────────────────────────────────────────

class ProductoResponse(BaseModel):
    id: int
    nombre: str
    categoria: str
    descripcion: Optional[str] = None
    precio: Optional[float] = None
    precio_oferta: Optional[float] = None
    disponible: bool = True
    destacado: bool = False
    imagen_url: Optional[str] = None
    etiquetas: List[str] = []

class GalleryImageResponse(BaseModel):
    id: int
    titulo: Optional[str] = None
    imagen_url: str
    categoria: Optional[str] = None
    status: str = "publicado"

class EquipoItemResponse(BaseModel):
    id: int
    nombre: str
    rol: Optional[str] = None
    descripcion: Optional[str] = None
    imagen_url: Optional[str] = None
    orden: int = 0
    status: str = "publicado"

class SiteConfigUpdate(BaseModel):
    secret: str
    maintenance_mode: bool
    maintenance_title: Optional[str] = None
    maintenance_message: Optional[str] = None

# ── BASE DE DATOS PRODUCTOS ───────────────────────────────────────────────────

PRODUCTOS_DB = os.path.join(DB_BASE, "productos.db")

def _init_productos_db():
    os.makedirs(os.path.dirname(PRODUCTOS_DB) if os.path.dirname(PRODUCTOS_DB) else ".", exist_ok=True)
    conn = sqlite3.connect(PRODUCTOS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS productos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre      TEXT NOT NULL,
            categoria   TEXT NOT NULL DEFAULT 'flores',
            descripcion TEXT,
            precio      REAL,
            precio_oferta REAL,
            disponible  INTEGER NOT NULL DEFAULT 1,
            destacado   INTEGER NOT NULL DEFAULT 0,
            imagen_url  TEXT,
            etiquetas   TEXT DEFAULT '[]',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

try:
    _init_productos_db()
except Exception as e:
    logger.warning(f"No se pudo inicializar productos_db: {e}")

# ── BASE DE DATOS EQUIPO ────────────────────────────────────────────────────

EQUIPO_DB = os.path.join(DB_BASE, "equipo.db")

def _init_equipo_db():
    conn = sqlite3.connect(EQUIPO_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipo (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre     TEXT NOT NULL,
            rol        TEXT,
            descripcion TEXT,
            imagen_url TEXT NOT NULL,
            orden      INTEGER NOT NULL DEFAULT 0,
            status     TEXT NOT NULL DEFAULT 'publicado',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

try:
    _init_equipo_db()
except Exception as e:
    logger.warning(f"No se pudo inicializar equipo_db: {e}")

# ── BASE DE DATOS GALERÍA ─────────────────────────────────────────────────────

GALLERY_DB = os.path.join(DB_BASE, "gallery.db")

def _init_gallery_db():
    conn = sqlite3.connect(GALLERY_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gallery_images (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo     TEXT,
            imagen_url TEXT NOT NULL,
            categoria  TEXT,
            status     TEXT NOT NULL DEFAULT 'publicado',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

try:
    _init_gallery_db()
except Exception as e:
    logger.warning(f"No se pudo inicializar gallery_db: {e}")

# ── BASE DE DATOS SITE CONFIG ─────────────────────────────────────────────────

SITE_CONFIG_DB = os.path.join(DB_BASE, "site_config.db")

def _init_site_config_db():
    conn = sqlite3.connect(SITE_CONFIG_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS site_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO site_config (key, value, updated_at) VALUES ('maintenance_mode','false',?)",
        (datetime.now().isoformat(),)
    )
    conn.commit()
    conn.close()

try:
    _init_site_config_db()
except Exception as e:
    logger.warning(f"No se pudo inicializar site_config_db: {e}")

def _get_config(key: str, default: str = "") -> str:
    try:
        conn = sqlite3.connect(SITE_CONFIG_DB)
        row = conn.execute("SELECT value FROM site_config WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default

def _set_config(key: str, value: str):
    try:
        conn = sqlite3.connect(SITE_CONFIG_DB)
        conn.execute(
            "INSERT INTO site_config (key,value,updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error guardando config {key}: {e}")

# ── MEDIA ESTÁTICA ────────────────────────────────────────────────────────────

media_path = Path(MEDIA_BASE)
if media_path.exists():
    app.mount("/media", StaticFiles(directory=str(media_path)), name="media")

# ── ENDPOINTS PRODUCTOS ───────────────────────────────────────────────────────

@app.get("/api/productos", response_model=List[ProductoResponse])
async def get_productos(
    categoria: Optional[str] = Query(None),
    disponible: Optional[bool] = Query(None),
    destacado: Optional[bool] = Query(None),
):
    try:
        conn = sqlite3.connect(PRODUCTOS_DB)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM productos WHERE 1=1"
        params = []
        if categoria:
            query += " AND categoria=?"
            params.append(categoria)
        if disponible is not None:
            query += " AND disponible=?"
            params.append(1 if disponible else 0)
        if destacado is not None:
            query += " AND destacado=?"
            params.append(1 if destacado else 0)
        query += " ORDER BY destacado DESC, created_at DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        result = []
        for r in rows:
            etiquetas = []
            try:
                etiquetas = json.loads(r["etiquetas"] or "[]")
            except Exception:
                pass
            img_url = r["imagen_url"]
            if img_url:
                img_url = img_url.replace("\\", "/")
            result.append(ProductoResponse(
                id=r["id"],
                nombre=r["nombre"],
                categoria=r["categoria"],
                descripcion=r["descripcion"],
                precio=r["precio"],
                precio_oferta=r["precio_oferta"],
                disponible=bool(r["disponible"]),
                destacado=bool(r["destacado"]),
                imagen_url=img_url,
                etiquetas=etiquetas,
            ))
        return result
    except Exception as e:
        logger.error(f"Error obteniendo productos: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ── ENDPOINTS EQUIPO ────────────────────────────────────────────────────────

@app.get("/api/equipo", response_model=List[EquipoItemResponse])
async def get_equipo():
    try:
        conn = sqlite3.connect(EQUIPO_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM equipo WHERE status='publicado' ORDER BY orden ASC, created_at ASC"
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("imagen_url"):
                d["imagen_url"] = d["imagen_url"].replace("\\", "/")
            result.append(EquipoItemResponse(**d))
        return result
    except Exception as e:
        logger.error(f"Error obteniendo equipo: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ── ENDPOINTS GALERÍA ─────────────────────────────────────────────────────────

@app.get("/api/gallery", response_model=List[GalleryImageResponse])
async def get_gallery():
    try:
        conn = sqlite3.connect(GALLERY_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM gallery_images WHERE status='publicado' ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("imagen_url"):
                d["imagen_url"] = d["imagen_url"].replace("\\", "/")
            result.append(GalleryImageResponse(**d))
        return result
    except Exception as e:
        logger.error(f"Error obteniendo galería: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ── ENDPOINTS STATUS / MANTENIMIENTO ──────────────────────────────────────────

@app.get("/api/status")
async def get_site_status():
    return {
        "maintenance_mode": _get_config("maintenance_mode", "false") == "true",
        "maintenance_title": _get_config("maintenance_title", "Próximamente"),
        "maintenance_message": _get_config("maintenance_message", "Estamos preparando algo especial. Vuelve pronto."),
        "timestamp": datetime.now().isoformat(),
    }

@app.post("/api/status")
async def set_site_status(config: SiteConfigUpdate):
    expected = os.environ.get("BBDD_SECRET", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Servidor no configurado correctamente")
    if config.secret != expected:
        raise HTTPException(status_code=403, detail="No autorizado")
    _set_config("maintenance_mode", "true" if config.maintenance_mode else "false")
    if config.maintenance_title:
        _set_config("maintenance_title", config.maintenance_title)
    if config.maintenance_message:
        _set_config("maintenance_message", config.maintenance_message)
    return {"success": True, "maintenance_mode": config.maintenance_mode}

# ── HEALTH CHECK ──────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    dbs = {
        "productos": os.path.exists(PRODUCTOS_DB),
        "gallery": os.path.exists(GALLERY_DB),
        "equipo": os.path.exists(EQUIPO_DB),
        "site_config": os.path.exists(SITE_CONFIG_DB),
    }
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "databases": dbs,
    }

if __name__ == "__main__":
    uvicorn.run("api_server:app", host="0.0.0.0", port=8001, reload=True)
