from fastapi import FastAPI, HTTPException, Query, Request, Response, Depends, Header
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
import hmac
from pydantic import BaseModel, Field

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

def _tune_sqlite(conn: sqlite3.Connection) -> None:
    """Aplica pragmas que suben rendimiento y concurrencia en free-tier de Render."""
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 3000")

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
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=600,
)

def _client_ip(request: Request) -> str:
    """Extrae la IP real considerando proxies (Render, Cloudflare)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    ip = _client_ip(request)
    if not _check_rate_limit(ip):
        return JSONResponse(status_code=429, content={"detail": "Demasiadas peticiones. Intenta de nuevo en un minuto."})
    return await call_next(request)

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers.setdefault("X-Robots-Tag", "noindex")
    return response

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
    _tune_sqlite(conn)
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prod_categoria  ON productos(categoria)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prod_disponible ON productos(disponible)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prod_destacado  ON productos(destacado)")
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
    _tune_sqlite(conn)
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_equipo_status ON equipo(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_equipo_orden  ON equipo(orden)")
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
    _tune_sqlite(conn)
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_gallery_status    ON gallery_images(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_gallery_categoria ON gallery_images(categoria)")
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
    _tune_sqlite(conn)
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

def _row_to_producto(r: sqlite3.Row) -> ProductoResponse:
    etiquetas: List[str] = []
    try:
        etiquetas = json.loads(r["etiquetas"] or "[]")
    except Exception:
        pass
    img_url = r["imagen_url"]
    if img_url:
        img_url = img_url.replace("\\", "/")
    return ProductoResponse(
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
    )

@app.get("/api/productos", response_model=List[ProductoResponse])
async def get_productos(
    response: Response,
    categoria: Optional[str] = Query(None),
    disponible: Optional[bool] = Query(None),
    destacado: Optional[bool] = Query(None),
    q: Optional[str] = Query(None, description="Búsqueda por nombre, descripción o categoría"),
    limit: int = Query(120, ge=1, le=300),
    offset: int = Query(0, ge=0),
    etiqueta: Optional[str] = Query(None),
):
    try:
        conn = sqlite3.connect(PRODUCTOS_DB)
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM productos WHERE 1=1"
        params: list = []
        if categoria:
            sql += " AND categoria=?"
            params.append(categoria)
        if disponible is not None:
            sql += " AND disponible=?"
            params.append(1 if disponible else 0)
        if destacado is not None:
            sql += " AND destacado=?"
            params.append(1 if destacado else 0)
        if q:
            like = f"%{q.strip()}%"
            sql += " AND (nombre LIKE ? OR descripcion LIKE ? OR categoria LIKE ? OR etiquetas LIKE ?)"
            params.extend([like, like, like, like])
        if etiqueta:
            sql += " AND etiquetas LIKE ?"
            params.append(f"%{etiqueta.strip()}%")
        sql += " ORDER BY destacado DESC, created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        result = [_row_to_producto(r) for r in rows]
        response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
        return result
    except Exception as e:
        logger.error(f"Error obteniendo productos: {e}")
        raise HTTPException(status_code=500, detail="Error interno al obtener productos")

@app.get("/api/productos/{producto_id}", response_model=ProductoResponse)
async def get_producto(producto_id: int, response: "Response"):
    try:
        conn = sqlite3.connect(PRODUCTOS_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM productos WHERE id=? AND disponible=1", (producto_id,)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        response.headers["Cache-Control"] = "public, max-age=120"
        return _row_to_producto(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo producto {producto_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

# ── ENDPOINTS EQUIPO ────────────────────────────────────────────────────────

@app.get("/api/equipo", response_model=List[EquipoItemResponse])
async def get_equipo(response: Response):
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
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=600"
        return result
    except Exception as e:
        logger.error(f"Error obteniendo equipo: {e}")
        raise HTTPException(status_code=500, detail="Error interno al obtener el equipo")

# ── ENDPOINTS GALERÍA ─────────────────────────────────────────────────────────

@app.get("/api/gallery", response_model=List[GalleryImageResponse])
async def get_gallery(
    response: Response,
    categoria: Optional[str] = Query(None),
    limit: int = Query(60, ge=1, le=200),
):
    try:
        conn = sqlite3.connect(GALLERY_DB)
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM gallery_images WHERE status='publicado'"
        params: list = []
        if categoria:
            sql += " AND categoria=?"
            params.append(categoria)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("imagen_url"):
                d["imagen_url"] = d["imagen_url"].replace("\\", "/")
            result.append(GalleryImageResponse(**d))
        response.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=300"
        return result
    except Exception as e:
        logger.error(f"Error obteniendo galería: {e}")
        raise HTTPException(status_code=500, detail="Error interno al obtener la galería")

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
    if not hmac.compare_digest(config.secret, expected):
        raise HTTPException(status_code=403, detail="No autorizado")
    _set_config("maintenance_mode", "true" if config.maintenance_mode else "false")
    if config.maintenance_title:
        _set_config("maintenance_title", config.maintenance_title)
    if config.maintenance_message:
        _set_config("maintenance_message", config.maintenance_message)
    return {"success": True, "maintenance_mode": config.maintenance_mode}

# ── BÚSQUEDA UNIFICADA ───────────────────────────────────────────────────────

@app.get("/api/search")
async def search_all(
    response: Response,
    q: str = Query(..., min_length=2, description="Término de búsqueda"),
    limit: int = Query(20, ge=1, le=50),
):
    q_stripped = q.strip()
    like = f"%{q_stripped}%"
    results: list = []
    try:
        conn = sqlite3.connect(PRODUCTOS_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM productos WHERE disponible=1 AND (nombre LIKE ? OR descripcion LIKE ? OR etiquetas LIKE ?) ORDER BY destacado DESC LIMIT ?",
            (like, like, like, limit)
        ).fetchall()
        conn.close()
        for r in rows:
            p = _row_to_producto(r)
            results.append({"tipo": "producto", **p.model_dump()})
    except Exception as e:
        logger.warning(f"Error en búsqueda de productos: {e}")
    response.headers["Cache-Control"] = "public, max-age=30"
    return {"query": q_stripped, "total": len(results), "results": results}

# ── HEALTH CHECK ──────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check(response: Response):
    dbs = {
        "productos": os.path.exists(PRODUCTOS_DB),
        "gallery": os.path.exists(GALLERY_DB),
        "equipo": os.path.exists(EQUIPO_DB),
        "site_config": os.path.exists(SITE_CONFIG_DB),
    }
    all_ok = all(dbs.values())
    response.headers["Cache-Control"] = "no-cache"
    return {
        "status": "healthy" if all_ok else "degraded",
        "timestamp": datetime.now().isoformat(),
        "databases": dbs,
        "version": "2.0.0",
    }

# ── TESTIMONIOS DB ────────────────────────────────────────────────────────────

TESTIMONIOS_DB = os.path.join(DB_BASE, "testimonios.db")

def _init_testimonios_db():
    conn = sqlite3.connect(TESTIMONIOS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS testimonios (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre     TEXT NOT NULL,
            texto      TEXT NOT NULL,
            nota       INTEGER NOT NULL DEFAULT 5,
            ocasion    TEXT,
            avatar     TEXT,
            verificado INTEGER NOT NULL DEFAULT 1,
            orden      INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_test_orden ON testimonios(orden)")
    conn.commit()
    conn.close()

try:
    _init_testimonios_db()
except Exception as e:
    logger.warning(f"No se pudo inicializar testimonios_db: {e}")

class TestimonioResponse(BaseModel):
    id: int
    nombre: str
    texto: str
    nota: int = 5
    ocasion: Optional[str] = None
    avatar: Optional[str] = None
    verificado: bool = True
    orden: int = 0

@app.get("/api/testimonios", response_model=List[TestimonioResponse])
async def get_testimonios(response: Response):
    try:
        conn = sqlite3.connect(TESTIMONIOS_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM testimonios ORDER BY orden ASC, created_at DESC").fetchall()
        conn.close()
        result = [TestimonioResponse(
            id=r["id"], nombre=r["nombre"], texto=r["texto"], nota=r["nota"],
            ocasion=r["ocasion"], avatar=r["avatar"],
            verificado=bool(r["verificado"]), orden=r["orden"],
        ) for r in rows]
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=600"
        return result
    except Exception as e:
        logger.error(f"Error obteniendo testimonios: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

# ── ADMIN AUTH ────────────────────────────────────────────────────────────────

def _require_admin(authorization: Optional[str] = Header(None)):
    expected = os.environ.get("BBDD_SECRET", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Servidor no configurado")
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="No autorizado")

# ── ADMIN: PRODUCTOS ──────────────────────────────────────────────────────────

class AdminProductoCreate(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    categoria: str = Field(default="flores", max_length=64)
    descripcion: Optional[str] = Field(default=None, max_length=5000)
    precio: Optional[float] = Field(default=None, ge=0, le=100000)
    precio_oferta: Optional[float] = Field(default=None, ge=0, le=100000)
    disponible: bool = True
    destacado: bool = False
    imagen_url: Optional[str] = Field(default=None, max_length=1000)
    etiquetas: List[str] = Field(default_factory=list, max_length=20)

class AdminProductoUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=200)
    categoria: Optional[str] = Field(default=None, max_length=64)
    descripcion: Optional[str] = Field(default=None, max_length=5000)
    precio: Optional[float] = Field(default=None, ge=0, le=100000)
    precio_oferta: Optional[float] = Field(default=None, ge=0, le=100000)
    disponible: Optional[bool] = None
    destacado: Optional[bool] = None
    imagen_url: Optional[str] = Field(default=None, max_length=1000)
    etiquetas: Optional[List[str]] = Field(default=None, max_length=20)

@app.get("/api/admin/productos", dependencies=[Depends(_require_admin)])
async def admin_list_productos():
    try:
        conn = sqlite3.connect(PRODUCTOS_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM productos ORDER BY created_at DESC").fetchall()
        conn.close()
        return [_row_to_producto(r) for r in rows]
    except Exception as e:
        logger.error(f"Admin: error listando productos: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

@app.post("/api/admin/productos", dependencies=[Depends(_require_admin)], status_code=201)
async def admin_create_producto(data: AdminProductoCreate):
    try:
        now = datetime.now().isoformat()
        conn = sqlite3.connect(PRODUCTOS_DB)
        cur = conn.execute(
            "INSERT INTO productos (nombre,categoria,descripcion,precio,precio_oferta,disponible,destacado,imagen_url,etiquetas,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (data.nombre, data.categoria, data.descripcion, data.precio, data.precio_oferta,
             1 if data.disponible else 0, 1 if data.destacado else 0,
             data.imagen_url, json.dumps(data.etiquetas), now, now)
        )
        new_id = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM productos WHERE id=?", (new_id,)).fetchone()
        conn.close()
        return _row_to_producto(row)
    except Exception as e:
        logger.error(f"Admin: error creando producto: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

@app.put("/api/admin/productos/{producto_id}", dependencies=[Depends(_require_admin)])
async def admin_update_producto(producto_id: int, data: AdminProductoUpdate):
    try:
        now = datetime.now().isoformat()
        conn = sqlite3.connect(PRODUCTOS_DB)
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT id FROM productos WHERE id=?", (producto_id,)).fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        fields, params = [], []
        if data.nombre is not None:       fields.append("nombre=?");       params.append(data.nombre)
        if data.categoria is not None:    fields.append("categoria=?");    params.append(data.categoria)
        if data.descripcion is not None:  fields.append("descripcion=?");  params.append(data.descripcion)
        if data.precio is not None:       fields.append("precio=?");       params.append(data.precio)
        if data.precio_oferta is not None:fields.append("precio_oferta=?");params.append(data.precio_oferta)
        if data.disponible is not None:   fields.append("disponible=?");   params.append(1 if data.disponible else 0)
        if data.destacado is not None:    fields.append("destacado=?");    params.append(1 if data.destacado else 0)
        if data.imagen_url is not None:   fields.append("imagen_url=?");   params.append(data.imagen_url)
        if data.etiquetas is not None:    fields.append("etiquetas=?");    params.append(json.dumps(data.etiquetas))
        if fields:
            fields.append("updated_at=?"); params.append(now); params.append(producto_id)
            conn.execute(f"UPDATE productos SET {', '.join(fields)} WHERE id=?", params)
            conn.commit()
        row = conn.execute("SELECT * FROM productos WHERE id=?", (producto_id,)).fetchone()
        conn.close()
        return _row_to_producto(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin: error actualizando producto {producto_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

@app.delete("/api/admin/productos/{producto_id}", dependencies=[Depends(_require_admin)])
async def admin_delete_producto(producto_id: int):
    try:
        conn = sqlite3.connect(PRODUCTOS_DB)
        result = conn.execute("DELETE FROM productos WHERE id=?", (producto_id,))
        conn.commit()
        conn.close()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        return {"success": True, "deleted_id": producto_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin: error eliminando producto {producto_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

# ── ADMIN: GALERÍA ─────────────────────────────────────────────────────────────

class AdminGalleryCreate(BaseModel):
    imagen_url: str
    titulo: Optional[str] = None
    categoria: Optional[str] = None
    status: str = "publicado"

class AdminGalleryUpdate(BaseModel):
    imagen_url: Optional[str] = None
    titulo: Optional[str] = None
    categoria: Optional[str] = None
    status: Optional[str] = None

@app.get("/api/admin/gallery", dependencies=[Depends(_require_admin)])
async def admin_list_gallery():
    try:
        conn = sqlite3.connect(GALLERY_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM gallery_images ORDER BY created_at DESC").fetchall()
        conn.close()
        return [{"id": r["id"], "titulo": r["titulo"], "imagen_url": r["imagen_url"],
                 "categoria": r["categoria"], "status": r["status"], "created_at": r["created_at"]} for r in rows]
    except Exception as e:
        logger.error(f"Admin: error listando galería: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

@app.post("/api/admin/gallery", dependencies=[Depends(_require_admin)], status_code=201)
async def admin_create_gallery(data: AdminGalleryCreate):
    try:
        now = datetime.now().isoformat()
        conn = sqlite3.connect(GALLERY_DB)
        cur = conn.execute(
            "INSERT INTO gallery_images (titulo,imagen_url,categoria,status,created_at) VALUES (?,?,?,?,?)",
            (data.titulo, data.imagen_url, data.categoria, data.status, now)
        )
        new_id = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM gallery_images WHERE id=?", (new_id,)).fetchone()
        conn.close()
        return {"id": row["id"], "titulo": row["titulo"], "imagen_url": row["imagen_url"],
                "categoria": row["categoria"], "status": row["status"]}
    except Exception as e:
        logger.error(f"Admin: error añadiendo a galería: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

@app.put("/api/admin/gallery/{img_id}", dependencies=[Depends(_require_admin)])
async def admin_update_gallery(img_id: int, data: AdminGalleryUpdate):
    try:
        conn = sqlite3.connect(GALLERY_DB)
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT id FROM gallery_images WHERE id=?", (img_id,)).fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Imagen no encontrada")
        fields, params = [], []
        if data.imagen_url is not None: fields.append("imagen_url=?"); params.append(data.imagen_url)
        if data.titulo is not None:     fields.append("titulo=?");     params.append(data.titulo)
        if data.categoria is not None:  fields.append("categoria=?");  params.append(data.categoria)
        if data.status is not None:     fields.append("status=?");     params.append(data.status)
        if fields:
            params.append(img_id)
            conn.execute(f"UPDATE gallery_images SET {', '.join(fields)} WHERE id=?", params)
            conn.commit()
        row = conn.execute("SELECT * FROM gallery_images WHERE id=?", (img_id,)).fetchone()
        conn.close()
        return {"id": row["id"], "titulo": row["titulo"], "imagen_url": row["imagen_url"],
                "categoria": row["categoria"], "status": row["status"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin: error actualizando imagen {img_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

@app.delete("/api/admin/gallery/{img_id}", dependencies=[Depends(_require_admin)])
async def admin_delete_gallery(img_id: int):
    try:
        conn = sqlite3.connect(GALLERY_DB)
        result = conn.execute("DELETE FROM gallery_images WHERE id=?", (img_id,))
        conn.commit()
        conn.close()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Imagen no encontrada")
        return {"success": True, "deleted_id": img_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin: error eliminando imagen {img_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

# ── ADMIN: TESTIMONIOS ────────────────────────────────────────────────────────

class AdminTestimonioCreate(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=120)
    texto: str = Field(..., min_length=5, max_length=1500)
    nota: int = Field(default=5, ge=1, le=5)
    ocasion: Optional[str] = Field(default=None, max_length=80)
    verificado: bool = True
    orden: int = Field(default=0, ge=0, le=9999)

class AdminTestimonioUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=120)
    texto: Optional[str] = Field(default=None, min_length=5, max_length=1500)
    nota: Optional[int] = Field(default=None, ge=1, le=5)
    ocasion: Optional[str] = Field(default=None, max_length=80)
    verificado: Optional[bool] = None
    orden: Optional[int] = Field(default=None, ge=0, le=9999)

@app.get("/api/admin/testimonios", dependencies=[Depends(_require_admin)])
async def admin_list_testimonios():
    try:
        conn = sqlite3.connect(TESTIMONIOS_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM testimonios ORDER BY orden ASC, created_at DESC").fetchall()
        conn.close()
        return [{"id": r["id"], "nombre": r["nombre"], "texto": r["texto"], "nota": r["nota"],
                 "ocasion": r["ocasion"], "avatar": r["avatar"],
                 "verificado": bool(r["verificado"]), "orden": r["orden"]} for r in rows]
    except Exception as e:
        logger.error(f"Admin: error listando testimonios: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

@app.post("/api/admin/testimonios", dependencies=[Depends(_require_admin)], status_code=201)
async def admin_create_testimonio(data: AdminTestimonioCreate):
    try:
        now = datetime.now().isoformat()
        avatar = "".join(p[0].upper() for p in data.nombre.split()[:2] if p)
        conn = sqlite3.connect(TESTIMONIOS_DB)
        cur = conn.execute(
            "INSERT INTO testimonios (nombre,texto,nota,ocasion,avatar,verificado,orden,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (data.nombre, data.texto, data.nota, data.ocasion, avatar, 1 if data.verificado else 0, data.orden, now)
        )
        new_id = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM testimonios WHERE id=?", (new_id,)).fetchone()
        conn.close()
        return {"id": row["id"], "nombre": row["nombre"], "texto": row["texto"], "nota": row["nota"],
                "ocasion": row["ocasion"], "avatar": row["avatar"], "verificado": bool(row["verificado"])}
    except Exception as e:
        logger.error(f"Admin: error creando testimonio: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

@app.put("/api/admin/testimonios/{t_id}", dependencies=[Depends(_require_admin)])
async def admin_update_testimonio(t_id: int, data: AdminTestimonioUpdate):
    try:
        conn = sqlite3.connect(TESTIMONIOS_DB)
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT id FROM testimonios WHERE id=?", (t_id,)).fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail="Testimonio no encontrado")
        fields, params = [], []
        if data.nombre     is not None: fields.append("nombre=?");     params.append(data.nombre)
        if data.texto      is not None: fields.append("texto=?");      params.append(data.texto)
        if data.nota       is not None: fields.append("nota=?");       params.append(data.nota)
        if data.ocasion    is not None: fields.append("ocasion=?");    params.append(data.ocasion)
        if data.verificado is not None: fields.append("verificado=?"); params.append(1 if data.verificado else 0)
        if data.orden      is not None: fields.append("orden=?");      params.append(data.orden)
        if fields:
            params.append(t_id)
            conn.execute(f"UPDATE testimonios SET {', '.join(fields)} WHERE id=?", params)
            conn.commit()
        row = conn.execute("SELECT * FROM testimonios WHERE id=?", (t_id,)).fetchone()
        conn.close()
        return {"id": row["id"], "nombre": row["nombre"], "texto": row["texto"], "nota": row["nota"],
                "ocasion": row["ocasion"], "avatar": row["avatar"], "verificado": bool(row["verificado"]),
                "orden": row["orden"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin: error actualizando testimonio {t_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

@app.delete("/api/admin/testimonios/{t_id}", dependencies=[Depends(_require_admin)])
async def admin_delete_testimonio(t_id: int):
    try:
        conn = sqlite3.connect(TESTIMONIOS_DB)
        result = conn.execute("DELETE FROM testimonios WHERE id=?", (t_id,))
        conn.commit()
        conn.close()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Testimonio no encontrado")
        return {"success": True, "deleted_id": t_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin: error eliminando testimonio {t_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

# ── ADMIN: CONFIG ─────────────────────────────────────────────────────────────

@app.get("/api/admin/config", dependencies=[Depends(_require_admin)])
async def admin_get_config():
    return {
        "maintenance_mode": _get_config("maintenance_mode", "false") == "true",
        "maintenance_title": _get_config("maintenance_title", "Próximamente"),
        "maintenance_message": _get_config("maintenance_message", "Estamos preparando algo especial."),
    }

@app.post("/api/admin/config", dependencies=[Depends(_require_admin)])
async def admin_set_config(request: Request):
    try:
        body = await request.json()
        if "maintenance_mode" in body:
            _set_config("maintenance_mode", "true" if body["maintenance_mode"] else "false")
        if "maintenance_title" in body:
            _set_config("maintenance_title", str(body["maintenance_title"]))
        if "maintenance_message" in body:
            _set_config("maintenance_message", str(body["maintenance_message"]))
        return {"success": True}
    except Exception as e:
        logger.error(f"Admin: error actualizando config: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

if __name__ == "__main__":
    # reload solo en desarrollo local (APP_ENV=development). En Render el start
    # command usa `uvicorn api_server:app --host 0.0.0.0 --port $PORT` sin reload.
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8001)),
        reload=_DEBUG,
    )
