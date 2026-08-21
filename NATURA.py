import streamlit as st
import sqlite3
import os
import json
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path
import cloudinary
import cloudinary.uploader
from auth import (
    init_users_db, create_user, user_exists, get_all_users,
    delete_user, toggle_user_active, change_password,
    get_access_log, try_login, logout, require_login,
    SESSION_KEY,
)

st.set_page_config(
    page_title="Natura — Panel de Gestión",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CLOUDINARY ───────────────────────────────────────────────────────────────
_CLD_NAME   = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
_CLD_KEY    = os.environ.get("CLOUDINARY_API_KEY", "")
_CLD_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")
_USE_CLOUDINARY = bool(_CLD_NAME and _CLD_KEY and _CLD_SECRET)
if _USE_CLOUDINARY:
    cloudinary.config(cloud_name=_CLD_NAME, api_key=_CLD_KEY, api_secret=_CLD_SECRET, secure=True)

# ── CONSTANTES ────────────────────────────────────────────────────────────────
PRODUCTOS_DB = "productos.db"
GALLERY_DB = "gallery.db"
SITE_CONFIG_DB = "site_config.db"
MEDIA_DIR = Path("media")
MEDIA_PRODUCTOS = MEDIA_DIR / "productos"
MEDIA_GALLERY = MEDIA_DIR / "gallery"
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8001")
BBDD_SECRET = os.environ.get("BBDD_SECRET", "NaturaAdmin2024")

CATEGORIAS_PRODUCTOS = ["flores", "plantas", "macetas", "accesorios", "ramos", "coronas", "otros"]
EQUIPO_DB = "equipo.db"
MEDIA_EQUIPO = MEDIA_DIR / "equipo"

# ── CSS GLOBAL ────────────────────────────────────────────────────────────────
def inject_css():
    st.markdown("""
    <style>
        .stApp { background-color: #0A0A0A; color: #F5F0E8; }
        section[data-testid="stSidebar"] { background-color: #111111 !important; border-right: 1px solid #C9A84C33; }
        h1, h2, h3 { color: #C9A84C !important; }
        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #C9A84C, #A8863A) !important;
            color: #0A0A0A !important; font-weight: 700 !important;
            border: none !important; border-radius: 8px !important;
        }
        .stButton > button {
            border-radius: 8px !important;
            border: 1px solid #C9A84C55 !important;
            color: #C9A84C !important;
        }
        .stTextInput > div > div > input,
        .stTextArea > div > div > textarea,
        .stSelectbox > div > div {
            background-color: #1A1A1A !important;
            color: #F5F0E8 !important;
            border: 1px solid #C9A84C44 !important;
            border-radius: 8px !important;
        }
        .stTabs [data-baseweb="tab"] { color: #C9A84C99 !important; }
        .stTabs [aria-selected="true"] { color: #C9A84C !important; border-bottom: 2px solid #C9A84C !important; }
        [data-testid="metric-container"] {
            background: #1A1A1A; border: 1px solid #C9A84C33;
            border-radius: 12px; padding: 16px;
        }
        [data-testid="metric-container"] label { color: #C9A84C99 !important; }
        [data-testid="metric-container"] [data-testid="stMetricValue"] { color: #C9A84C !important; }
        .stDataFrame { border: 1px solid #C9A84C22 !important; border-radius: 8px !important; }
        hr { border-color: #C9A84C22 !important; }
        .img-card {
            background: #1A1A1A;
            border: 1px solid #C9A84C22;
            border-radius: 10px;
            padding: 8px;
            margin-bottom: 8px;
        }
        .badge-pub { background:#1A3A1A; color:#6ABF6A; padding:2px 8px; border-radius:12px; font-size:0.75rem; }
        .badge-oculto { background:#3A1A1A; color:#BF6A6A; padding:2px 8px; border-radius:12px; font-size:0.75rem; }
    </style>
    """, unsafe_allow_html=True)

# ── INICIALIZACIÓN DE BASES DE DATOS ─────────────────────────────────────────

def init_dbs():
    MEDIA_PRODUCTOS.mkdir(parents=True, exist_ok=True)
    MEDIA_GALLERY.mkdir(parents=True, exist_ok=True)
    MEDIA_EQUIPO.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(PRODUCTOS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS productos (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre        TEXT NOT NULL,
            categoria     TEXT NOT NULL DEFAULT 'flores',
            descripcion   TEXT,
            precio        REAL,
            precio_oferta REAL,
            disponible    INTEGER NOT NULL DEFAULT 1,
            destacado     INTEGER NOT NULL DEFAULT 0,
            imagen_url    TEXT,
            etiquetas     TEXT DEFAULT '[]',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

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

    conn = sqlite3.connect(EQUIPO_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipo (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre      TEXT NOT NULL,
            rol         TEXT,
            descripcion TEXT,
            imagen_url  TEXT NOT NULL,
            orden       INTEGER NOT NULL DEFAULT 0,
            status      TEXT NOT NULL DEFAULT 'publicado',
            created_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(SITE_CONFIG_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS site_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO site_config (key,value,updated_at) VALUES ('maintenance_mode','false',?)",
        (datetime.now().isoformat(),)
    )
    conn.commit()
    conn.close()

init_dbs()
init_users_db()

# Crear admin por defecto si no existe ningún usuario
_existing_users = get_all_users()
if not _existing_users:
    _default_pwd = os.environ.get("ADMIN_DEFAULT_PASSWORD", "NaturaAdmin2024!")
    create_user("admin", _default_pwd, rol="admin")

# ── HELPERS ───────────────────────────────────────────────────────────────────

# Todas las lecturas y escrituras van al backend por HTTP.
# Así el panel gestiona la BD del entorno definido por BACKEND_URL:
#   - localhost → BD local (dev).
#   - natura-api.onrender.com → BD de producción (visible en la web).
# Antes escribíamos directamente a SQLite local, lo que causaba que los
# productos añadidos desde el panel jamás llegaran a la web pública.

_AUTH_HEADERS = {"Authorization": f"Bearer {BBDD_SECRET}", "Content-Type": "application/json"}
_HTTP_TIMEOUT = 20  # generoso para cold-start de Render free tier

def _api_get(path: str, params: dict | None = None, admin: bool = False, timeout: int = _HTTP_TIMEOUT):
    headers = _AUTH_HEADERS if admin else None
    return requests.get(f"{BACKEND_URL}{path}", params=params, headers=headers, timeout=timeout)

def _api_post(path: str, data: dict, timeout: int = _HTTP_TIMEOUT):
    return requests.post(f"{BACKEND_URL}{path}", json=data, headers=_AUTH_HEADERS, timeout=timeout)

def _api_put(path: str, data: dict, timeout: int = _HTTP_TIMEOUT):
    return requests.put(f"{BACKEND_URL}{path}", json=data, headers=_AUTH_HEADERS, timeout=timeout)

def _api_delete(path: str, timeout: int = _HTTP_TIMEOUT):
    return requests.delete(f"{BACKEND_URL}{path}", headers=_AUTH_HEADERS, timeout=timeout)

@st.cache_data(ttl=60, show_spinner=False)
def get_productos() -> pd.DataFrame:
    """Lista todos los productos (incluidos no-disponibles) vía admin API."""
    try:
        r = _api_get("/api/admin/productos", admin=True)
        if not r.ok:
            return pd.DataFrame()
        return pd.DataFrame(r.json())
    except Exception as e:
        st.error(f"⚠️ Backend no responde: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60, show_spinner=False)
def get_gallery() -> pd.DataFrame:
    try:
        r = _api_get("/api/admin/gallery", admin=True)
        if not r.ok:
            return pd.DataFrame()
        return pd.DataFrame(r.json())
    except Exception as e:
        st.error(f"⚠️ Backend no responde: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60, show_spinner=False)
def get_equipo() -> pd.DataFrame:
    try:
        r = _api_get("/api/admin/equipo", admin=True)
        if not r.ok:
            return pd.DataFrame()
        return pd.DataFrame(r.json())
    except Exception as e:
        st.error(f"⚠️ Backend no responde: {e}")
        return pd.DataFrame()

def _invalidate_data_caches():
    """Llamar tras cualquier write: invalida los caches de lectura."""
    get_productos.clear()
    get_gallery.clear()
    get_equipo.clear()

@st.cache_data(ttl=30, show_spinner=False)
def get_maintenance_status(backend_url: str) -> dict:
    """Cachea 30s el estado de mantenimiento — antes bloqueaba 8s por rerun."""
    try:
        r = requests.get(f"{backend_url}/api/status", timeout=4)
        return r.json() if r.ok else {"maintenance_mode": False}
    except Exception:
        return {"maintenance_mode": False, "_offline": True}

def save_image(uploaded_file, folder: Path, prefix: str = "") -> str:
    if _USE_CLOUDINARY:
        try:
            folder_name = str(folder).replace("\\", "/").strip("/").split("/")[-1]
            public_id = f"natura/{folder_name}/{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            result = cloudinary.uploader.upload(
                uploaded_file.getbuffer().tobytes(),
                public_id=public_id,
                overwrite=True,
                resource_type="image",
                quality="auto",
                fetch_format="auto",
            )
            return result["secure_url"]
        except Exception as e:
            st.warning(f"Cloudinary error: {e} — guardando localmente")
    # Fallback: guardar en disco local
    ext = Path(uploaded_file.name).suffix.lower()
    fname = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
    dest = folder / fname
    folder.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return "/" + str(folder / fname).replace("\\", "/")

# ── SIDEBAR ───────────────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.markdown("""
            <div style="text-align:center; padding: 20px 0 10px 0;">
                <div style="font-size: 2.5rem;">🌿</div>
                <h1 style="font-size:1.4rem; margin:0; color:#C9A84C !important; letter-spacing:2px;">NATURA</h1>
                <p style="color:#C9A84C88; font-size:0.75rem; margin:4px 0 0 0; letter-spacing:1px;">FLORES & PLANTAS</p>
            </div>
        """, unsafe_allow_html=True)
        st.divider()

        menu_items = {
            "🏠 Dashboard": "dashboard",
            "🌸 Productos": "productos",
            "🖼️ Galería": "galeria",
            "👥 Equipo": "equipo",
            "🌐 Web Pública": "web",
        }

        if "menu" not in st.session_state:
            st.session_state["menu"] = "dashboard"

        for label, key in menu_items.items():
            is_active = st.session_state["menu"] == key
            btn_type = "primary" if is_active else "secondary"
            if st.button(label, key=f"menu_{key}", use_container_width=True, type=btn_type):
                st.session_state["menu"] = key
                st.rerun()

        st.divider()

        # ── Modo mantenimiento ─────────────────────────────────────────────
        st.markdown("### 🌐 Web Pública")
        _status = get_maintenance_status(BACKEND_URL)
        _maint_active = bool(_status.get("maintenance_mode"))
        if _status.get("_offline"):
            st.caption("⚠️ Backend no responde — estado desconocido")

        _label = "🔴 Mantenimiento ACTIVO" if _maint_active else "🟢 Web visible"
        st.markdown(f"**Estado:** {_label}")

        _title = st.text_input("Título", value="Próximamente", key="maint_title")
        _msg = st.text_area("Mensaje", value="Estamos preparando algo especial. Vuelve pronto.", key="maint_msg", height=70)

        def _set_maintenance(active: bool):
            resp = requests.post(
                f"{BACKEND_URL}/api/status",
                json={"maintenance_mode": active, "maintenance_title": _title, "maintenance_message": _msg, "secret": BBDD_SECRET},
                timeout=15,
            )
            if not resp.ok:
                raise RuntimeError(f"Error {resp.status_code}: {resp.text}")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔴 Activar", key="maint_on", use_container_width=True, type="primary", disabled=_maint_active):
                try:
                    _set_maintenance(True)
                    get_maintenance_status.clear()
                    st.toast("✅ Mantenimiento activado", icon="🔴")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ {e}")
        with col2:
            if st.button("🟢 Desact.", key="maint_off", use_container_width=True, disabled=not _maint_active):
                try:
                    _set_maintenance(False)
                    get_maintenance_status.clear()
                    st.toast("✅ Mantenimiento desactivado", icon="🟢")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ {e}")

        st.divider()
        st.markdown(f"<small style='color:#C9A84C44;'>⏰ {datetime.now().strftime('%H:%M:%S')}</small>", unsafe_allow_html=True)

# ── DASHBOARD ─────────────────────────────────────────────────────────────────

def render_dashboard():
    st.title("🌿 Dashboard — Natura")

    df_prod = get_productos()
    df_gal = get_gallery()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Productos", len(df_prod))
    c2.metric("Disponibles", int(df_prod["disponible"].sum()) if not df_prod.empty else 0)
    c3.metric("Destacados", int(df_prod["destacado"].sum()) if not df_prod.empty else 0)
    c4.metric("Imágenes galería", len(df_gal))

    st.divider()

    if not df_prod.empty:
        st.markdown("### 📊 Productos por categoría")
        cat_count = df_prod.groupby("categoria").size().reset_index(name="cantidad")
        import plotly.express as px
        fig = px.bar(
            cat_count, x="categoria", y="cantidad",
            color_discrete_sequence=["#C9A84C"],
            template="plotly_dark",
        )
        fig.update_layout(
            plot_bgcolor="#1A1A1A", paper_bgcolor="#1A1A1A",
            font_color="#F5F0E8", xaxis_title="", yaxis_title="Cantidad",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### 🌸 Últimos productos añadidos")
    if not df_prod.empty:
        cols_show = ["nombre", "categoria", "precio", "disponible", "destacado", "created_at"]
        cols_show = [c for c in cols_show if c in df_prod.columns]
        st.dataframe(df_prod[cols_show].head(10), use_container_width=True, hide_index=True)
    else:
        st.info("Aún no hay productos. Ve a **🌸 Productos** para añadir el primero.")

# ── GESTIÓN PRODUCTOS ─────────────────────────────────────────────────────────

def render_productos():
    st.title("🌸 Gestión de Productos")
    tab_ver, tab_nuevo, tab_editar = st.tabs(["📋 Ver todos", "➕ Nuevo producto", "✏️ Editar / Eliminar"])

    with tab_ver:
        df = get_productos()
        if df.empty:
            st.info("No hay productos todavía.")
        else:
            # Filtros
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                cat_filter = st.selectbox("Filtrar por categoría", ["Todas"] + CATEGORIAS_PRODUCTOS, key="filter_cat")
            with col_f2:
                disp_filter = st.selectbox("Disponibilidad", ["Todos", "Disponible", "No disponible"], key="filter_disp")

            if cat_filter != "Todas":
                df = df[df["categoria"] == cat_filter]
            if disp_filter == "Disponible":
                df = df[df["disponible"] == 1]
            elif disp_filter == "No disponible":
                df = df[df["disponible"] == 0]

            st.markdown(f"**{len(df)} productos**")
            cols_show = ["id", "nombre", "categoria", "precio", "precio_oferta", "disponible", "destacado"]
            cols_show = [c for c in cols_show if c in df.columns]
            st.dataframe(df[cols_show], use_container_width=True, hide_index=True)

    with tab_nuevo:
        st.markdown("### Añadir nuevo producto")
        with st.form("form_nuevo_producto"):
            n_nombre = st.text_input("Nombre *", placeholder="Ej: Rosa Roja Premium")
            n_cat = st.selectbox("Categoría *", CATEGORIAS_PRODUCTOS)
            n_desc = st.text_area("Descripción", placeholder="Describe el producto...")
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                n_precio = st.number_input("Precio (€)", min_value=0.0, step=0.5, format="%.2f")
            with col_p2:
                n_precio_oferta = st.number_input("Precio oferta (€, 0 = sin oferta)", min_value=0.0, step=0.5, format="%.2f")
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                n_disponible = st.checkbox("Disponible", value=True)
            with col_d2:
                n_destacado = st.checkbox("Destacado en web", value=False)
            n_etiquetas = st.text_input("Etiquetas (separadas por coma)", placeholder="oferta, temporada, nuevo")
            n_imagen = st.file_uploader("Imagen del producto", type=["jpg", "jpeg", "png", "webp"])
            submitted = st.form_submit_button("💾 Guardar producto", type="primary")

            if submitted:
                if not n_nombre.strip():
                    st.error("El nombre es obligatorio.")
                else:
                    imagen_url = None
                    if n_imagen:
                        imagen_url = save_image(n_imagen, MEDIA_PRODUCTOS, prefix=n_nombre.replace(" ", "_").lower())
                    etiquetas = json.dumps([e.strip() for e in n_etiquetas.split(",") if e.strip()])
                    now = datetime.now().isoformat()
                    payload = {
                        "nombre": n_nombre.strip(),
                        "categoria": n_cat,
                        "descripcion": n_desc.strip() or None,
                        "precio": n_precio or None,
                        "precio_oferta": n_precio_oferta or None,
                        "disponible": bool(n_disponible),
                        "destacado": bool(n_destacado),
                        "imagen_url": imagen_url,
                        "etiquetas": [e.strip() for e in n_etiquetas.split(",") if e.strip()],
                    }
                    with st.spinner("Guardando en el servidor..."):
                        r = _api_post("/api/admin/productos", payload)
                    if r.ok:
                        _invalidate_data_caches()
                        st.toast(f"✅ Producto '{n_nombre}' añadido", icon="🌿")
                        st.rerun()
                    else:
                        st.error(f"❌ Error {r.status_code}: {r.text[:200]}")

    with tab_editar:
        df = get_productos()
        if df.empty:
            st.info("No hay productos para editar.")
            return

        producto_opciones = {f"[{r['id']}] {r['nombre']}": r['id'] for _, r in df.iterrows()}
        seleccion = st.selectbox("Selecciona un producto", list(producto_opciones.keys()), key="sel_producto_edit")
        prod_id = producto_opciones[seleccion]
        prod = df[df["id"] == prod_id].iloc[0]

        with st.form("form_editar_producto"):
            e_nombre = st.text_input("Nombre", value=prod["nombre"])
            e_cat = st.selectbox("Categoría", CATEGORIAS_PRODUCTOS, index=CATEGORIAS_PRODUCTOS.index(prod["categoria"]) if prod["categoria"] in CATEGORIAS_PRODUCTOS else 0)
            e_desc = st.text_area("Descripción", value=prod["descripcion"] or "")
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                e_precio = st.number_input("Precio (€)", value=float(prod["precio"] or 0), min_value=0.0, step=0.5, format="%.2f")
            with col_p2:
                e_precio_oferta = st.number_input("Precio oferta (€)", value=float(prod["precio_oferta"] or 0), min_value=0.0, step=0.5, format="%.2f")
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                e_disponible = st.checkbox("Disponible", value=bool(prod["disponible"]))
            with col_d2:
                e_destacado = st.checkbox("Destacado", value=bool(prod["destacado"]))
            try:
                tags_actual = ", ".join(json.loads(prod["etiquetas"] or "[]"))
            except Exception:
                tags_actual = ""
            e_etiquetas = st.text_input("Etiquetas", value=tags_actual)
            e_imagen = st.file_uploader("Nueva imagen (opcional)", type=["jpg", "jpeg", "png", "webp"], key="edit_img")

            col_save, col_del = st.columns(2)
            with col_save:
                save_btn = st.form_submit_button("💾 Guardar cambios", type="primary")
            with col_del:
                del_btn = st.form_submit_button("🗑️ Eliminar producto")

            if save_btn:
                imagen_url = prod["imagen_url"]
                if e_imagen:
                    imagen_url = save_image(e_imagen, MEDIA_PRODUCTOS, prefix=e_nombre.replace(" ", "_").lower())
                payload = {
                    "nombre": e_nombre,
                    "categoria": e_cat,
                    "descripcion": e_desc or None,
                    "precio": e_precio or None,
                    "precio_oferta": e_precio_oferta or None,
                    "disponible": bool(e_disponible),
                    "destacado": bool(e_destacado),
                    "imagen_url": imagen_url,
                    "etiquetas": [e.strip() for e in e_etiquetas.split(",") if e.strip()],
                }
                with st.spinner("Actualizando..."):
                    r = _api_put(f"/api/admin/productos/{prod_id}", payload)
                if r.ok:
                    _invalidate_data_caches()
                    st.toast("✅ Producto actualizado", icon="✏️")
                    st.rerun()
                else:
                    st.error(f"❌ Error {r.status_code}: {r.text[:200]}")

            if del_btn:
                confirm_prod_key = f"confirm_del_prod_{prod_id}"
                st.session_state[confirm_prod_key] = True
                st.rerun()

        confirm_prod_key = f"confirm_del_prod_{prod_id}"
        if st.session_state.get(confirm_prod_key):
            st.warning(f"⚠️ ¿Seguro que quieres eliminar **{prod['nombre']}**? Esta acción no se puede deshacer.")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🗑️ Sí, eliminar", key="confirm_del_prod_yes", type="primary"):
                    delete_producto(prod_id, prod.get("imagen_url"))
                    st.session_state.pop(confirm_prod_key, None)
                    st.success("✅ Producto eliminado.")
                    st.rerun()
            with c2:
                if st.button("Cancelar", key="confirm_del_prod_no"):
                    st.session_state.pop(confirm_prod_key, None)
                    st.rerun()

# ── HELPERS EXTRA ─────────────────────────────────────────────────────────────

def toggle_gallery_status(img_id: int, current_status: str) -> bool:
    new_status = "oculto" if current_status == "publicado" else "publicado"
    try:
        r = _api_put(f"/api/admin/gallery/{img_id}", {"status": new_status})
        _invalidate_data_caches()
        return r.ok
    except Exception as e:
        st.error(f"❌ {e}")
        return False

def delete_gallery_image(img_id: int, imagen_url: str = "") -> bool:
    # Nota: la imagen queda en Cloudinary. Streamlit no tiene sesión Cloudinary
    # dedicada aquí — el user puede purgar orphans desde el dashboard Cloudinary.
    try:
        r = _api_delete(f"/api/admin/gallery/{img_id}")
        _invalidate_data_caches()
        return r.ok
    except Exception as e:
        st.error(f"❌ {e}")
        return False

def delete_producto(prod_id: int, imagen_url: str = "") -> bool:
    try:
        r = _api_delete(f"/api/admin/productos/{prod_id}")
        _invalidate_data_caches()
        return r.ok
    except Exception as e:
        st.error(f"❌ {e}")
        return False

# ── GESTIÓN GALERÍA ───────────────────────────────────────────────────────────

def render_galeria():
    st.title("🖼️ Gestión de Galería")
    tab_ver, tab_subir = st.tabs(["� Ver & Gestionar", "➕ Subir imágenes"])

    with tab_ver:
        df = get_gallery()
        if df.empty:
            st.info("No hay imágenes en la galería. Sube la primera en la pestaña ➕")
        else:
            # Filtros
            col_f1, col_f2 = st.columns([2, 1])
            with col_f1:
                filtro_cat = st.selectbox("Filtrar por categoría", ["Todas"] + ["general"] + CATEGORIAS_PRODUCTOS, key="gal_filter_cat")
            with col_f2:
                filtro_status = st.selectbox("Estado", ["Todos", "publicado", "oculto"], key="gal_filter_status")

            df_show = df.copy()
            if filtro_cat != "Todas":
                df_show = df_show[df_show["categoria"] == filtro_cat]
            if filtro_status != "Todos":
                df_show = df_show[df_show["status"] == filtro_status]

            st.markdown(f"**{len(df_show)} imágenes** · Publicadas: {len(df_show[df_show['status']=='publicado'])} · Ocultas: {len(df_show[df_show['status']=='oculto'])}")
            st.divider()

            # Grid 4 columnas
            COLS = 4
            rows = [df_show.iloc[i:i+COLS] for i in range(0, len(df_show), COLS)]
            for row_df in rows:
                cols = st.columns(COLS)
                for col, (_, img) in zip(cols, row_df.iterrows()):
                    with col:
                        # Preview imagen
                        img_path = img["imagen_url"].lstrip("/")
                        if os.path.exists(img_path):
                            st.image(img_path, use_column_width=True)
                        else:
                            st.markdown(
                                "<div style='background:#1A1A1A;height:120px;display:flex;align-items:center;justify-content:center;border-radius:8px;color:#555;font-size:2rem;'>🖼️</div>",
                                unsafe_allow_html=True
                            )

                        # Info
                        titulo = img['titulo'] or 'Sin título'
                        st.markdown(f"**{titulo[:25]}{'...' if len(titulo)>25 else ''}**")
                        badge = "publicado" if img['status'] == "publicado" else "oculto"
                        badge_class = "badge-pub" if badge == "publicado" else "badge-oculto"
                        st.markdown(f"<span class='{badge_class}'>{badge}</span>", unsafe_allow_html=True)
                        st.caption(f"#{img['id']} · {img['categoria'] or '—'}")

                        # Botones
                        btn_toggle_label = "👁️ Ocultar" if img['status'] == "publicado" else "✅ Publicar"
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button(btn_toggle_label, key=f"tog_{img['id']}", use_container_width=True):
                                toggle_gallery_status(img['id'], img['status'])
                                st.rerun()
                        with c2:
                            # Confirmación de eliminación
                            confirm_key = f"confirm_del_gal_{img['id']}"
                            if st.session_state.get(confirm_key):
                                if st.button("⚠️ Confirmar", key=f"confirm_yes_{img['id']}", use_container_width=True, type="primary"):
                                    delete_gallery_image(img['id'], img['imagen_url'])
                                    st.session_state.pop(confirm_key, None)
                                    st.success("Eliminada.")
                                    st.rerun()
                            else:
                                if st.button("🗑️ Borrar", key=f"del_{img['id']}", use_container_width=True):
                                    st.session_state[confirm_key] = True
                                    st.rerun()

    with tab_subir:
        st.markdown("### Subir imágenes a la galería")

        # Subida múltiple
        g_files = st.file_uploader(
            "Selecciona una o varias imágenes",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            key="gal_upload"
        )

        if g_files:
            st.markdown(f"**{len(g_files)} imagen(es) seleccionada(s)**")

            # Preview de las imágenes a subir
            preview_cols = st.columns(min(len(g_files), 4))
            for i, f in enumerate(g_files[:4]):
                with preview_cols[i]:
                    st.image(f, use_column_width=True, caption=f.name)
            if len(g_files) > 4:
                st.caption(f"... y {len(g_files)-4} más")

            st.divider()

        with st.form("form_subir_imagen"):
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                g_titulo = st.text_input("Título (se aplica a todas)", placeholder="Ej: Ramo primaveral")
                g_categoria = st.selectbox("Categoría", ["general"] + CATEGORIAS_PRODUCTOS)
            with col_m2:
                g_status = st.selectbox("Estado inicial", ["publicado", "oculto"])
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown("ℹ️ Puedes cambiar el estado después desde 📸 Ver & Gestionar")

            submitted = st.form_submit_button("📤 Subir imagen(es)", type="primary", use_container_width=True)

            if submitted:
                if not g_files:
                    st.error("Selecciona al menos una imagen antes de subir.")
                else:
                    subidas, fallidas = 0, 0
                    with st.spinner(f"Subiendo {len(g_files)} imagen(es)..."):
                        for f in g_files:
                            url = save_image(f, MEDIA_GALLERY, prefix="gallery")
                            payload = {
                                "titulo": g_titulo or None,
                                "imagen_url": url,
                                "categoria": g_categoria,
                                "status": g_status,
                            }
                            r = _api_post("/api/admin/gallery", payload)
                            if r.ok:
                                subidas += 1
                            else:
                                fallidas += 1
                    _invalidate_data_caches()
                    if subidas:
                        st.toast(f"✅ {subidas} imagen(es) subida(s)", icon="🖼️")
                    if fallidas:
                        st.error(f"❌ {fallidas} fallaron al guardarse en el servidor.")
                    st.rerun()

# ── GESTIÓN EQUIPO ─────────────────────────────────────────────────────────────────────────────────

def render_equipo():
    st.title("👥 Gestión del Equipo / Fotos de la Tienda")
    tab_ver, tab_nuevo, tab_editar = st.tabs(["📸 Ver fotos", "➕ Añadir foto", "✏️ Editar / Eliminar"])

    with tab_ver:
        df = get_equipo()
        if df.empty:
            st.info("No hay fotos del equipo aún. Añade la primera desde ➕ Añadir foto.")
        else:
            st.markdown(f"**{len(df)} fotos** publicadas en la web")
            for _, row in df.iterrows():
                with st.container():
                    col_img, col_info, col_acc = st.columns([1, 3, 1])
                    with col_img:
                        img_url = str(row.get("imagen_url", ""))
                        if img_url:
                            full = f"{BACKEND_URL}{img_url}" if img_url.startswith("/") else img_url
                            try:
                                st.image(full, width=120)
                            except Exception:
                                st.markdown("📷")
                    with col_info:
                        status_badge = "🟢 Publicado" if row.get("status") == "publicado" else "🔴 Oculto"
                        st.markdown(f"**{row['nombre']}** — *{row.get('rol', '')}*")
                        if row.get("descripcion"):
                            st.caption(row["descripcion"])
                        st.caption(f"Orden: {row.get('orden', 0)} · {status_badge}")
                    with col_acc:
                        if st.button("🔴 Ocultar" if row.get("status") == "publicado" else "🟢 Publicar",
                                     key=f"eq_toggle_{row['id']}"):
                            new_status = "oculto" if row.get("status") == "publicado" else "publicado"
                            r = _api_put(f"/api/admin/equipo/{row['id']}", {"status": new_status})
                            if r.ok:
                                _invalidate_data_caches()
                                st.rerun()
                            else:
                                st.error(f"❌ Error {r.status_code}: {r.text[:200]}")
                    st.divider()

    with tab_nuevo:
        st.markdown("### Añadir nueva foto")
        with st.form("form_nuevo_equipo"):
            col1, col2 = st.columns(2)
            with col1:
                eq_nombre = st.text_input("Nombre / Título *", placeholder="Ej: Tere, La tienda, Flores del día")
                eq_rol = st.text_input("Rol / Pie de foto", placeholder="Ej: Florista principal, C. Peligros 2")
                eq_orden = st.number_input("Orden de aparición", min_value=0, max_value=99, value=0, step=1)
            with col2:
                eq_desc = st.text_area("Descripción (opcional)", height=80, placeholder="Breve descripción...")
                eq_status = st.selectbox("Estado", ["publicado", "oculto"])
            eq_img = st.file_uploader("📸 Foto *", type=["jpg", "jpeg", "png", "webp"])
            submitted = st.form_submit_button("➕ Guardar foto", type="primary", use_container_width=True)

            if submitted:
                if not eq_nombre.strip():
                    st.error("El nombre es obligatorio.")
                elif not eq_img:
                    st.error("Debes subir una foto.")
                else:
                    with st.spinner("Subiendo foto..."):
                        url = save_image(eq_img, MEDIA_EQUIPO, prefix=eq_nombre.strip().replace(" ", "_")[:20].lower())
                        payload = {
                            "nombre": eq_nombre.strip(),
                            "rol": eq_rol.strip() or None,
                            "descripcion": eq_desc.strip() or None,
                            "imagen_url": url,
                            "orden": int(eq_orden),
                            "status": eq_status,
                        }
                        r = _api_post("/api/admin/equipo", payload)
                    if r.ok:
                        _invalidate_data_caches()
                        st.toast(f"✅ Foto '{eq_nombre}' añadida", icon="👥")
                        st.rerun()
                    else:
                        st.error(f"❌ Error {r.status_code}: {r.text[:200]}")

    with tab_editar:
        df = get_equipo()
        if df.empty:
            st.info("No hay fotos aún.")
        else:
            ids = df["id"].tolist()
            nombres = df["nombre"].tolist()
            sel_id = st.selectbox("Seleccionar foto", ids, format_func=lambda x: nombres[ids.index(x)])
            row = df[df["id"] == sel_id].iloc[0]

            with st.form("form_editar_equipo"):
                col1, col2 = st.columns(2)
                with col1:
                    e_nombre = st.text_input("Nombre / Título", value=row["nombre"])
                    e_rol = st.text_input("Rol / Pie de foto", value=row.get("rol") or "")
                    e_orden = st.number_input("Orden", min_value=0, max_value=99,
                                              value=int(row.get("orden", 0)), step=1)
                with col2:
                    e_desc = st.text_area("Descripción", value=row.get("descripcion") or "", height=80)
                    e_status = st.selectbox("Estado", ["publicado", "oculto"],
                                            index=0 if row.get("status") == "publicado" else 1)
                e_img = st.file_uploader("📸 Nueva foto (opcional — deja vacío para mantener la actual)",
                                         type=["jpg", "jpeg", "png", "webp"])

                col_save, col_del = st.columns(2)
                with col_save:
                    if st.form_submit_button("💾 Guardar cambios", type="primary", use_container_width=True):
                        new_url = row["imagen_url"]
                        if e_img:
                            with st.spinner("Subiendo nueva foto..."):
                                new_url = save_image(e_img, MEDIA_EQUIPO,
                                                     prefix=e_nombre.strip().replace(" ", "_")[:20].lower())
                        payload = {
                            "nombre": e_nombre.strip(),
                            "rol": e_rol.strip() or None,
                            "descripcion": e_desc.strip() or None,
                            "imagen_url": new_url,
                            "orden": int(e_orden),
                            "status": e_status,
                        }
                        r = _api_put(f"/api/admin/equipo/{sel_id}", payload)
                        if r.ok:
                            _invalidate_data_caches()
                            st.toast("✅ Actualizado", icon="✏️")
                            st.rerun()
                        else:
                            st.error(f"❌ Error {r.status_code}: {r.text[:200]}")
                with col_del:
                    if st.form_submit_button("🗑️ Eliminar", use_container_width=True):
                        r = _api_delete(f"/api/admin/equipo/{sel_id}")
                        if r.ok:
                            _invalidate_data_caches()
                            st.toast("✅ Eliminado", icon="🗑️")
                            st.rerun()
                        else:
                            st.error(f"❌ Error {r.status_code}: {r.text[:200]}")

# ── ADMINISTRACIÓN AVANZADA ──────────────────────────────────────────────────

def render_administracion():
    import shutil, zipfile, time, io as _io
    import pandas as pd
    st.title("⚙️ Administración del Sistema")

    tab_monitor, tab_integridad, tab_config, tab_backup, tab_logs = st.tabs([
        "📡 Monitorización",
        "🔍 Integridad",
        "🌐 Config. Web",
        "💾 Backups",
        "📋 Logs del Sistema",
    ])

    # ── TAB 1: MONITORIZACIÓN ─────────────────────────────────────────────────
    with tab_monitor:
        st.markdown("### Estado general del sistema")

        if st.button("🔄 Actualizar estado", key="btn_refresh_monitor"):
            st.rerun()

        # Estado API
        col_api, col_web, col_disk = st.columns(3)

        with col_api:
            st.markdown("#### 🔌 API Backend")
            try:
                t0 = time.time()
                r = requests.get(f"{BACKEND_URL}/api/health", timeout=6)
                latency = round((time.time() - t0) * 1000)
                if r.ok:
                    data = r.json()
                    st.success(f"✅ Online · {latency}ms")
                    dbs = data.get("databases", {})
                    for db_name, exists in dbs.items():
                        icon = "🟢" if exists else "🔴"
                        st.markdown(f"{icon} `{db_name}.db`")
                else:
                    st.error(f"❌ Error {r.status_code}")
            except requests.exceptions.ConnectionError:
                st.error("🔴 Sin conexión con la API")
            except requests.exceptions.Timeout:
                st.warning("⏱️ Timeout — API lenta o inactiva")
            except Exception as e:
                st.error(f"❌ {e}")

        with col_web:
            st.markdown("#### 🌐 Estado Web Pública")
            try:
                t0 = time.time()
                r_status = requests.get(f"{BACKEND_URL}/api/status", timeout=6)
                latency2 = round((time.time() - t0) * 1000)
                if r_status.ok:
                    s = r_status.json()
                    maint = s.get("maintenance_mode", False)
                    st.warning("🔴 MANTENIMIENTO ACTIVO" if maint else "🟢 Web visible")
                    st.caption(f"Latencia: {latency2}ms")
                    st.caption(f"Última comprobación: {datetime.now().strftime('%H:%M:%S')}")
                else:
                    st.error(f"❌ Error {r_status.status_code}")
            except Exception as e:
                st.error(f"❌ {e}")

        with col_disk:
            st.markdown("#### 💽 Almacenamiento local")
            try:
                total, used, free = shutil.disk_usage(".")
                pct = round(used / total * 100, 1)
                st.metric("Usado", f"{used // (1024**3):.1f} GB", f"{pct}%")
                st.metric("Libre", f"{free // (1024**2):.0f} MB")
                # Tamaño de media
                media_size = sum(
                    f.stat().st_size for f in MEDIA_DIR.rglob("*") if f.is_file()
                ) if MEDIA_DIR.exists() else 0
                st.caption(f"📁 Media: {media_size // (1024**2):.1f} MB")
            except Exception as e:
                st.caption(f"No disponible: {e}")

        st.divider()
        st.markdown("### 📊 Resumen de datos")
        c1, c2, c3, c4, c5 = st.columns(5)
        try:
            df_p = get_productos()
            df_g = get_gallery()
            df_e = get_equipo()
            from auth import get_all_users as _gu
            users = _gu()
            c1.metric("Productos", len(df_p))
            c2.metric("Disponibles", int(df_p["disponible"].sum()) if not df_p.empty else 0)
            c3.metric("En galería", len(df_g[df_g["status"] == "publicado"]) if not df_g.empty else 0)
            c4.metric("Equipo", len(df_e))
            c5.metric("Usuarios", len(users))
        except Exception as e:
            st.error(f"Error cargando datos: {e}")

        st.divider()
        st.markdown("### 🔗 Comprobación de endpoints API")
        endpoints = [
            ("GET /api/health",    f"{BACKEND_URL}/api/health"),
            ("GET /api/status",    f"{BACKEND_URL}/api/status"),
            ("GET /api/productos", f"{BACKEND_URL}/api/productos"),
            ("GET /api/gallery",   f"{BACKEND_URL}/api/gallery"),
            ("GET /api/equipo",    f"{BACKEND_URL}/api/equipo"),
        ]
        if st.button("▶️ Comprobar todos los endpoints", key="btn_check_ep"):
            results = []
            for name, url in endpoints:
                try:
                    t0 = time.time()
                    r = requests.get(url, timeout=8)
                    ms = round((time.time() - t0) * 1000)
                    icon = "✅" if r.ok else "❌"
                    results.append({"Endpoint": name, "Estado": f"{icon} {r.status_code}", "Latencia": f"{ms}ms", "Tamaño resp.": f"{len(r.content)} bytes"})
                except Exception as ex:
                    results.append({"Endpoint": name, "Estado": f"❌ Error", "Latencia": "—", "Tamaño resp.": str(ex)[:40]})
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

    # ── TAB 2: INTEGRIDAD ─────────────────────────────────────────────────────
    with tab_integridad:
        st.markdown("### 🔍 Verificación de integridad de datos")
        st.caption("Detecta inconsistencias, imágenes rotas y datos faltantes.")

        if st.button("▶️ Ejecutar verificación completa", key="btn_check_integrity", type="primary"):
            errores = []
            avisos = []
            ok_count = 0

            with st.spinner("Analizando..."):

                # 1. Productos sin imagen
                df_p = get_productos()
                sin_img = df_p[df_p["imagen_url"].isna() | (df_p["imagen_url"] == "")]
                if not sin_img.empty:
                    avisos.append(f"⚠️ {len(sin_img)} producto(s) sin imagen: {', '.join(sin_img['nombre'].tolist()[:5])}")
                else:
                    ok_count += 1

                # 2. Archivos de imagen de productos que no existen en disco
                rotos_prod = []
                for _, row in df_p.iterrows():
                    if row.get("imagen_url"):
                        path = row["imagen_url"].lstrip("/")
                        if not os.path.exists(path):
                            rotos_prod.append(row["nombre"])
                if rotos_prod:
                    errores.append(f"🔴 {len(rotos_prod)} imagen(s) de producto no encontrada(s) en disco: {', '.join(rotos_prod[:5])}")
                else:
                    ok_count += 1

                # 3. Imágenes de galería rotas en disco
                df_g = get_gallery()
                rotos_gal = []
                for _, row in df_g.iterrows():
                    path = row["imagen_url"].lstrip("/")
                    if not os.path.exists(path):
                        rotos_gal.append(str(row.get("titulo", row["id"])))
                if rotos_gal:
                    errores.append(f"🔴 {len(rotos_gal)} imagen(s) de galería no encontrada(s) en disco: {', '.join(rotos_gal[:5])}")
                else:
                    ok_count += 1

                # 4. Productos con precio_oferta > precio (lógica incorrecta)
                if not df_p.empty:
                    df_bad_price = df_p[
                        df_p["precio_oferta"].notna() &
                        df_p["precio"].notna() &
                        (df_p["precio_oferta"] >= df_p["precio"])
                    ]
                    if not df_bad_price.empty:
                        avisos.append(f"⚠️ {len(df_bad_price)} producto(s) con precio_oferta ≥ precio normal: {', '.join(df_bad_price['nombre'].tolist())}")
                    else:
                        ok_count += 1

                # 5. Productos sin categoría válida
                invalidos = df_p[~df_p["categoria"].isin(CATEGORIAS_PRODUCTOS)] if not df_p.empty else []
                if len(invalidos):
                    avisos.append(f"⚠️ {len(invalidos)} producto(s) con categoría no reconocida")
                else:
                    ok_count += 1

                # 6. DBs accesibles
                for db_path in [PRODUCTOS_DB, GALLERY_DB, EQUIPO_DB, SITE_CONFIG_DB]:
                    if not os.path.exists(db_path):
                        errores.append(f"🔴 Base de datos no encontrada: {db_path}")
                    else:
                        ok_count += 1

                # 7. Archivos huérfanos en media/productos (sin registro en DB)
                if MEDIA_PRODUCTOS.exists():
                    files_disk = {f.name for f in MEDIA_PRODUCTOS.iterdir() if f.is_file()}
                    if not df_p.empty:
                        files_db = set()
                        for url in df_p["imagen_url"].dropna():
                            files_db.add(Path(url).name)
                        huerfanos = files_disk - files_db
                        if huerfanos:
                            avisos.append(f"⚠️ {len(huerfanos)} archivo(s) huérfano(s) en media/productos (sin producto asociado)")
                        else:
                            ok_count += 1

            # Mostrar resultados
            st.markdown(f"#### Resultado: {ok_count} ✅ · {len(avisos)} ⚠️ · {len(errores)} 🔴")
            if errores:
                st.markdown("**Errores críticos:**")
                for e in errores:
                    st.error(e)
            if avisos:
                st.markdown("**Avisos:**")
                for a in avisos:
                    st.warning(a)
            if not errores and not avisos:
                st.success("✅ Todo correcto. No se detectaron problemas.")

        st.divider()
        st.markdown("### 🗂️ Archivos huérfanos en disco")
        st.caption("Archivos en la carpeta media/ que no están referenciados en ninguna base de datos.")
        if st.button("🔎 Buscar archivos huérfanos", key="btn_orphans"):
            huerfanos_total = []
            df_p = get_productos()
            df_g = get_gallery()
            df_e = get_equipo()
            all_urls = set()
            for df in [df_p, df_g, df_e]:
                col = "imagen_url"
                if col in df.columns:
                    for url in df[col].dropna():
                        all_urls.add(Path(url.lstrip("/")).name)
            for folder in [MEDIA_PRODUCTOS, MEDIA_GALLERY, MEDIA_EQUIPO]:
                if folder.exists():
                    for f in folder.iterdir():
                        if f.is_file() and f.name not in all_urls:
                            huerfanos_total.append({"Archivo": f.name, "Carpeta": str(folder), "Tamaño": f"{f.stat().st_size // 1024} KB"})
            if huerfanos_total:
                st.warning(f"Se encontraron {len(huerfanos_total)} archivo(s) huérfano(s):")
                st.dataframe(pd.DataFrame(huerfanos_total), use_container_width=True, hide_index=True)
            else:
                st.success("✅ No hay archivos huérfanos.")

    # ── TAB 3: CONFIG. WEB ────────────────────────────────────────────────────
    with tab_config:
        st.markdown("### 🌐 Configuración de la Web Pública")

        def _get_cfg(key, default=""):
            try:
                conn = sqlite3.connect(SITE_CONFIG_DB)
                row = conn.execute("SELECT value FROM site_config WHERE key=?", (key,)).fetchone()
                conn.close()
                return row[0] if row else default
            except Exception:
                return default

        def _set_cfg(key, value):
            try:
                conn = sqlite3.connect(SITE_CONFIG_DB)
                conn.execute(
                    "INSERT INTO site_config (key,value,updated_at) VALUES (?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, value, datetime.now().isoformat())
                )
                conn.commit()
                conn.close()
            except Exception as e:
                st.error(f"Error guardando: {e}")

        st.markdown("#### 🔧 Modo mantenimiento")
        maint_on = _get_cfg("maintenance_mode", "false") == "true"
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.markdown(f"**Estado actual:** {'🔴 ACTIVO' if maint_on else '🟢 Desactivado'}")
        with col_s2:
            if maint_on:
                if st.button("🟢 Desactivar mantenimiento", key="cfg_maint_off", type="primary"):
                    try:
                        requests.post(f"{BACKEND_URL}/api/status",
                            json={"maintenance_mode": False, "secret": BBDD_SECRET,
                                  "maintenance_title": _get_cfg("maintenance_title"),
                                  "maintenance_message": _get_cfg("maintenance_message")}, timeout=10)
                        get_maintenance_status.clear()
                        st.toast("✅ Web visible", icon="🟢"); st.rerun()
                    except Exception as e:
                        st.error(f"❌ {e}")
            else:
                if st.button("🔴 Activar mantenimiento", key="cfg_maint_on"):
                    try:
                        requests.post(f"{BACKEND_URL}/api/status",
                            json={"maintenance_mode": True, "secret": BBDD_SECRET,
                                  "maintenance_title": _get_cfg("maintenance_title", "Próximamente"),
                                  "maintenance_message": _get_cfg("maintenance_message", "Estamos preparando algo especial.")}, timeout=10)
                        get_maintenance_status.clear()
                        st.toast("✅ Mantenimiento activado", icon="🔴"); st.rerun()
                    except Exception as e:
                        st.error(f"❌ {e}")

        st.divider()
        st.markdown("#### 📝 Textos de la página de mantenimiento")
        with st.form("form_maint_texts"):
            m_title = st.text_input("Título", value=_get_cfg("maintenance_title", "Próximamente"))
            m_msg = st.text_area("Mensaje", value=_get_cfg("maintenance_message", "Estamos preparando algo especial. Vuelve pronto."), height=80)
            if st.form_submit_button("💾 Guardar textos", type="primary"):
                _set_cfg("maintenance_title", m_title)
                _set_cfg("maintenance_message", m_msg)
                st.success("✅ Textos guardados.")

        st.divider()
        st.markdown("#### 🔑 Variables de entorno activas")
        env_vars = {
            "BACKEND_URL": BACKEND_URL,
            "BBDD_SECRET": "●●●●●●●●" if BBDD_SECRET else "⚠️ No configurado",
            "AUTH_PEPPER": "●●●●●●●●" if os.environ.get("AUTH_PEPPER") else "⚠️ Usando valor por defecto",
            "ADMIN_DEFAULT_PASSWORD": "●●●●●●●●" if os.environ.get("ADMIN_DEFAULT_PASSWORD") else "Usando valor por defecto",
        }
        for k, v in env_vars.items():
            col_k, col_v = st.columns([2, 3])
            with col_k:
                st.markdown(f"`{k}`")
            with col_v:
                st.markdown(v)

        st.divider()
        st.markdown("#### 📊 Todos los valores en site_config.db")
        try:
            conn = sqlite3.connect(SITE_CONFIG_DB)
            df_cfg = pd.read_sql_query("SELECT key, value, updated_at FROM site_config ORDER BY key", conn)
            conn.close()
            if not df_cfg.empty:
                st.dataframe(df_cfg, use_container_width=True, hide_index=True)
            else:
                st.info("Sin configuración guardada.")
        except Exception as e:
            st.error(f"Error: {e}")

    # ── TAB 4: BACKUPS ────────────────────────────────────────────────────────
    with tab_backup:
        st.markdown("### 💾 Copia de seguridad")
        st.caption("Genera un ZIP con todas las bases de datos y las imágenes del servidor.")

        col_b1, col_b2 = st.columns(2)

        with col_b1:
            st.markdown("#### 📦 Solo bases de datos")
            st.caption("Incluye: productos.db, gallery.db, equipo.db, site_config.db, users.db")
            if st.button("⬇️ Descargar backup DBs", key="btn_backup_dbs", use_container_width=True, type="primary"):
                buf = _io.BytesIO()
                dbs_to_backup = ["productos.db", "gallery.db", "equipo.db", "site_config.db", "users.db"]
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for db in dbs_to_backup:
                        if os.path.exists(db):
                            zf.write(db, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}/{db}")
                buf.seek(0)
                st.download_button(
                    label="📥 Guardar ZIP",
                    data=buf,
                    file_name=f"natura_dbs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                    mime="application/zip",
                    key="dl_dbs"
                )

        with col_b2:
            st.markdown("#### 🖼️ Bases de datos + Imágenes")
            st.caption("Incluye todo lo anterior más la carpeta media/")
            if st.button("⬇️ Descargar backup completo", key="btn_backup_full", use_container_width=True):
                with st.spinner("Generando ZIP completo..."):
                    buf2 = _io.BytesIO()
                    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                    with zipfile.ZipFile(buf2, "w", zipfile.ZIP_DEFLATED) as zf:
                        for db in ["productos.db", "gallery.db", "equipo.db", "site_config.db", "users.db"]:
                            if os.path.exists(db):
                                zf.write(db, f"backup_{ts}/{db}")
                        if MEDIA_DIR.exists():
                            for f in MEDIA_DIR.rglob("*"):
                                if f.is_file():
                                    zf.write(f, f"backup_{ts}/{f}")
                    buf2.seek(0)
                    size_mb = buf2.getbuffer().nbytes / (1024 * 1024)
                    st.download_button(
                        label=f"📥 Guardar ZIP ({size_mb:.1f} MB)",
                        data=buf2,
                        file_name=f"natura_completo_{ts}.zip",
                        mime="application/zip",
                        key="dl_full"
                    )

        st.divider()
        st.markdown("#### 📋 Estado actual de las bases de datos")
        db_info = []
        for db_path in ["productos.db", "gallery.db", "equipo.db", "site_config.db", "users.db"]:
            if os.path.exists(db_path):
                size = os.path.getsize(db_path)
                mtime = datetime.fromtimestamp(os.path.getmtime(db_path)).strftime("%d/%m/%Y %H:%M")
                db_info.append({"Base de datos": db_path, "Tamaño": f"{size // 1024} KB", "Última modificación": mtime, "Estado": "✅ OK"})
            else:
                db_info.append({"Base de datos": db_path, "Tamaño": "—", "Última modificación": "—", "Estado": "🔴 No encontrada"})
        st.dataframe(pd.DataFrame(db_info), use_container_width=True, hide_index=True)

    # ── TAB 5: LOGS DEL SISTEMA ───────────────────────────────────────────────
    with tab_logs:
        st.markdown("### 📋 Logs y actividad reciente")

        col_l1, col_l2 = st.columns(2)

        with col_l1:
            st.markdown("#### 🔐 Log de accesos al panel")
            from auth import get_access_log as _gal
            logs = _gal(100)
            if logs:
                df_log = pd.DataFrame(logs)[["timestamp", "username", "event"]]
                df_log["timestamp"] = pd.to_datetime(df_log["timestamp"]).dt.strftime("%d/%m %H:%M:%S")
                df_log.columns = ["Fecha", "Usuario", "Evento"]
                # Colorear eventos
                st.dataframe(df_log, use_container_width=True, hide_index=True, height=400)
            else:
                st.info("Sin registros aún.")

        with col_l2:
            st.markdown("#### 📦 Actividad reciente en productos")
            try:
                conn = sqlite3.connect(PRODUCTOS_DB)
                df_recent = pd.read_sql_query(
                    "SELECT nombre, categoria, disponible, updated_at FROM productos ORDER BY updated_at DESC LIMIT 20",
                    conn
                )
                conn.close()
                if not df_recent.empty:
                    df_recent["updated_at"] = pd.to_datetime(df_recent["updated_at"]).dt.strftime("%d/%m %H:%M")
                    df_recent["disponible"] = df_recent["disponible"].map({1: "✅", 0: "❌"})
                    df_recent.columns = ["Producto", "Categoría", "Disp.", "Actualizado"]
                    st.dataframe(df_recent, use_container_width=True, hide_index=True, height=400)
                else:
                    st.info("Sin productos.")
            except Exception as e:
                st.error(f"Error: {e}")

        st.divider()
        st.markdown("#### 🌐 Test de conectividad API en tiempo real")
        if st.button("📡 Hacer ping a la API ahora", key="btn_ping"):
            endpoints_ping = [
                f"{BACKEND_URL}/api/health",
                f"{BACKEND_URL}/api/status",
                f"{BACKEND_URL}/api/productos",
            ]
            for url in endpoints_ping:
                try:
                    t0 = time.time()
                    r = requests.get(url, timeout=8)
                    ms = round((time.time() - t0) * 1000)
                    if r.ok:
                        st.success(f"✅ `{url.replace(BACKEND_URL,'')}` → {r.status_code} · {ms}ms")
                    else:
                        st.error(f"❌ `{url.replace(BACKEND_URL,'')}` → {r.status_code}")
                except Exception as ex:
                    st.error(f"🔴 `{url.replace(BACKEND_URL,'')}` → {str(ex)[:60]}")

        st.divider()
        st.markdown("#### ℹ️ Información del servidor")
        import platform, sys
        info = {
            "Python": sys.version.split(" ")[0],
            "Sistema": platform.system(),
            "Hostname": platform.node(),
            "Arquitectura": platform.machine(),
            "Streamlit": st.__version__,
            "Directorio trabajo": os.getcwd(),
        }
        col_i1, col_i2 = st.columns(2)
        items = list(info.items())
        for i, (k, v) in enumerate(items):
            with (col_i1 if i < len(items)//2 else col_i2):
                st.markdown(f"**{k}:** `{v}`")


# ── MAIN ─────────────────────────────────────────────────────────────────────────────────

# ── PANTALLA DE LOGIN ────────────────────────────────────────────────────────

def render_login():
    """Pantalla de login con diseño premium."""
    inject_css()
    st.markdown("""
    <style>
        .login-wrap {
            max-width: 420px;
            margin: 6vh auto 0 auto;
            padding: 48px 40px 40px 40px;
            background: #111111;
            border: 1px solid #C9A84C33;
            border-radius: 16px;
            box-shadow: 0 8px 48px rgba(0,0,0,0.6);
        }
        .login-logo {
            text-align: center;
            margin-bottom: 32px;
        }
        .login-logo .icon { font-size: 3rem; display:block; margin-bottom:8px; }
        .login-logo h1 {
            font-size: 1.6rem !important;
            letter-spacing: 4px;
            margin: 0 0 4px 0;
            color: #C9A84C !important;
        }
        .login-logo p {
            color: #C9A84C66;
            font-size: 0.7rem;
            letter-spacing: 2px;
            margin: 0;
        }
        .login-footer {
            text-align: center;
            margin-top: 24px;
            color: #C9A84C33;
            font-size: 0.7rem;
            letter-spacing: 1px;
        }
    </style>
    """, unsafe_allow_html=True)

    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.markdown("""
        <div class="login-wrap">
            <div class="login-logo">
                <span class="icon">🌿</span>
                <h1>NATURA</h1>
                <p>PANEL DE GESTIÓN</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=False):
            username = st.text_input(
                "Usuario",
                placeholder="usuario",
                label_visibility="collapsed",
            )
            password = st.text_input(
                "Contraseña",
                type="password",
                placeholder="contraseña",
                label_visibility="collapsed",
            )
            submitted = st.form_submit_button(
                "Acceder →",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            if not username.strip() or not password:
                st.error("Introduce usuario y contraseña.")
            else:
                ok, msg = try_login(username, password, BBDD_SECRET)
                if ok:
                    st.rerun()
                else:
                    st.error(f"🔒 {msg}")

        st.markdown(
            "<div class='login-footer'>Floristería Natura · Acceso restringido</div>",
            unsafe_allow_html=True
        )


# ── GESTIÓN DE USUARIOS (solo admin) ─────────────────────────────────────────

def render_usuarios(current_user: dict):
    st.title("👤 Gestión de Usuarios")

    if current_user["rol"] != "admin":
        st.warning("Solo los administradores pueden gestionar usuarios.")
        return

    tab_lista, tab_nuevo, tab_log = st.tabs(["👥 Usuarios", "➕ Nuevo usuario", "📋 Log de accesos"])

    with tab_lista:
        users = get_all_users()
        if not users:
            st.info("No hay usuarios.")
        else:
            for u in users:
                with st.container():
                    c1, c2, c3, c4 = st.columns([3, 2, 1, 2])
                    with c1:
                        is_me = u["username"] == current_user["username"]
                        badge = "🟢" if u["activo"] else "🔴"
                        you = " *(tú)*" if is_me else ""
                        st.markdown(f"{badge} **{u['username']}**{you}")
                        st.caption(f"Último acceso: {u['last_login'][:16] if u['last_login'] else 'Nunca'} · {u['login_count']} sesiones")
                    with c2:
                        rol_icon = "👑" if u["rol"] == "admin" else "✏️"
                        st.markdown(f"{rol_icon} `{u['rol']}`")
                        st.caption(f"Creado: {u['created_at'][:10]}")
                    with c3:
                        if not is_me:
                            label = "🔴 Desact." if u["activo"] else "🟢 Activar"
                            if st.button(label, key=f"tog_u_{u['id']}", use_container_width=True):
                                toggle_user_active(u["username"])
                                st.rerun()
                    with c4:
                        if not is_me:
                            if st.button("🗑️ Eliminar", key=f"del_u_{u['id']}", use_container_width=True):
                                st.session_state[f"confirm_del_user_{u['id']}"] = True
                                st.rerun()
                    # Confirmación de borrado
                    ck = f"confirm_del_user_{u['id']}"
                    if st.session_state.get(ck):
                        st.warning(f"⚠️ ¿Eliminar a **{u['username']}**? Esta acción no se puede deshacer.")
                        ca, cb = st.columns(2)
                        with ca:
                            if st.button("Sí, eliminar", key=f"yes_del_u_{u['id']}", type="primary"):
                                delete_user(u["username"])
                                st.session_state.pop(ck, None)
                                st.success("✅ Usuario eliminado.")
                                st.rerun()
                        with cb:
                            if st.button("Cancelar", key=f"no_del_u_{u['id']}"):
                                st.session_state.pop(ck, None)
                                st.rerun()
                    st.divider()

    with tab_nuevo:
        st.markdown("### Crear nuevo usuario")
        with st.form("form_nuevo_user"):
            nu_user = st.text_input("Nombre de usuario *", placeholder="ej: tere")
            nu_rol  = st.selectbox("Rol", ["editor", "admin"],
                                   help="Admin: acceso total. Editor: solo productos y galería.")
            nu_pwd1 = st.text_input("Contraseña *", type="password", placeholder="Mínimo 8 caracteres")
            nu_pwd2 = st.text_input("Repetir contraseña *", type="password")
            nu_sub  = st.form_submit_button("➕ Crear usuario", type="primary")

            if nu_sub:
                if not nu_user.strip():
                    st.error("El nombre de usuario es obligatorio.")
                elif len(nu_pwd1) < 8:
                    st.error("La contraseña debe tener al menos 8 caracteres.")
                elif nu_pwd1 != nu_pwd2:
                    st.error("Las contraseñas no coinciden.")
                elif user_exists(nu_user.strip().lower()):
                    st.error(f"El usuario '{nu_user}' ya existe.")
                else:
                    if create_user(nu_user.strip().lower(), nu_pwd1, rol=nu_rol):
                        st.success(f"✅ Usuario '{nu_user}' creado con rol '{nu_rol}'.")
                        st.rerun()
                    else:
                        st.error("Error al crear el usuario.")

        st.divider()
        st.markdown("### Cambiar mi contraseña")
        with st.form("form_cambiar_pwd"):
            cp_old  = st.text_input("Contraseña actual", type="password")
            cp_new1 = st.text_input("Nueva contraseña", type="password")
            cp_new2 = st.text_input("Repetir nueva", type="password")
            cp_sub  = st.form_submit_button("💾 Cambiar contraseña", type="primary")

            if cp_sub:
                from auth import try_login as _tl
                ok, _ = _tl(current_user["username"], cp_old, BBDD_SECRET)
                if not ok:
                    st.error("La contraseña actual es incorrecta.")
                elif len(cp_new1) < 8:
                    st.error("La nueva contraseña debe tener al menos 8 caracteres.")
                elif cp_new1 != cp_new2:
                    st.error("Las contraseñas no coinciden.")
                else:
                    if change_password(current_user["username"], cp_new1):
                        st.success("✅ Contraseña actualizada correctamente. Vuelve a iniciar sesión.")
                        logout()
                        st.rerun()
                    else:
                        st.error("Error al cambiar la contraseña.")

    with tab_log:
        st.markdown("### Registro de accesos (últimos 100)")
        logs = get_access_log(100)
        if not logs:
            st.info("Sin registros aún.")
        else:
            import pandas as pd
            df_log = pd.DataFrame(logs)[["timestamp", "username", "event"]]
            df_log["timestamp"] = pd.to_datetime(df_log["timestamp"]).dt.strftime("%d/%m/%Y %H:%M:%S")
            df_log.columns = ["Fecha", "Usuario", "Evento"]
            st.dataframe(df_log, use_container_width=True, hide_index=True)


# ── SIDEBAR CON INFO DE SESIÓN ────────────────────────────────────────────────

def render_sidebar_with_auth(current_user: dict):
    """Sidebar enriquecido con información de sesión y botón de logout."""
    with st.sidebar:
        st.markdown(f"""
            <div style="text-align:center; padding: 20px 0 10px 0;">
                <div style="font-size: 2.5rem;">🌿</div>
                <h1 style="font-size:1.4rem; margin:0; color:#C9A84C !important; letter-spacing:2px;">NATURA</h1>
                <p style="color:#C9A84C88; font-size:0.75rem; margin:4px 0 0 0; letter-spacing:1px;">FLORES & PLANTAS</p>
            </div>
        """, unsafe_allow_html=True)

        # Info usuario
        rol_icon = "👑" if current_user["rol"] == "admin" else "✏️"
        st.markdown(f"""
        <div style="background:#1A1A1A; border:1px solid #C9A84C22; border-radius:8px; padding:10px 12px; margin-bottom:8px;">
            <div style="color:#C9A84C; font-size:0.8rem; font-weight:600;">{'👑 Admin' if current_user['rol'] == 'admin' else '✏️ Editor'}</div>
            <div style="color:#F5F0E8; font-size:0.9rem; margin-top:2px;">@{current_user['username']}</div>
            <div style="color:#C9A84C44; font-size:0.7rem; margin-top:4px;">Sesión iniciada: {current_user['login_time'][11:16]}</div>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        menu_items = {
            "🏠 Dashboard": "dashboard",
            "🌸 Productos": "productos",
            "🖼️ Galería": "galeria",
            "👥 Equipo": "equipo",
            "🌐 Web Pública": "web",
        }
        if current_user["rol"] == "admin":
            menu_items["🔐 Usuarios"] = "usuarios"
            menu_items["⚙️ Administración"] = "administracion"

        if "menu" not in st.session_state:
            st.session_state["menu"] = "dashboard"

        for label, key in menu_items.items():
            is_active = st.session_state["menu"] == key
            btn_type = "primary" if is_active else "secondary"
            if st.button(label, key=f"menu_{key}", use_container_width=True, type=btn_type):
                st.session_state["menu"] = key
                st.rerun()

        st.divider()

        # ── Modo mantenimiento ─────────────────────────────────────────────
        if current_user["rol"] == "admin":
            st.markdown("### 🌐 Web Pública")
            try:
                r = requests.get(f"{BACKEND_URL}/api/status", timeout=8)
                _maint_active = r.json().get("maintenance_mode", False) if r.ok else False
            except Exception:
                _maint_active = False

            _label = "🔴 Mantenimiento ACTIVO" if _maint_active else "🟢 Web visible"
            st.markdown(f"**Estado:** {_label}")

            _title = st.text_input("Título", value="Próximamente", key="maint_title")
            _msg = st.text_area("Mensaje", value="Estamos preparando algo especial. Vuelve pronto.", key="maint_msg", height=70)

            def _set_maintenance(active: bool):
                resp = requests.post(
                    f"{BACKEND_URL}/api/status",
                    json={"maintenance_mode": active, "maintenance_title": _title, "maintenance_message": _msg, "secret": BBDD_SECRET},
                    timeout=15,
                )
                if not resp.ok:
                    raise RuntimeError(f"Error {resp.status_code}: {resp.text}")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔴 Activar", key="maint_on", use_container_width=True, type="primary", disabled=_maint_active):
                    try:
                        _set_maintenance(True)
                        get_maintenance_status.clear()
                        st.toast("✅ Activado", icon="🔴"); st.rerun()
                    except Exception as e:
                        st.error(f"❌ {e}")
            with col2:
                if st.button("🟢 Desact.", key="maint_off", use_container_width=True, disabled=not _maint_active):
                    try:
                        _set_maintenance(False)
                        get_maintenance_status.clear()
                        st.toast("✅ Desactivado", icon="🟢"); st.rerun()
                    except Exception as e:
                        st.error(f"❌ {e}")
            st.divider()

        st.markdown(f"<small style='color:#C9A84C44;'>⏰ {datetime.now().strftime('%H:%M:%S')}</small>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

        # ── Cerrar sesión ──────────────────────────────────────────────────
        if st.button("🚪 Cerrar sesión", key="btn_logout", use_container_width=True):
            logout()
            st.rerun()


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    inject_css()

    # Verificar sesión
    current_user = require_login(BBDD_SECRET)

    if current_user is None:
        render_login()
        st.stop()

    # Usuario autenticado — renderizar app
    render_sidebar_with_auth(current_user)

    menu = st.session_state.get("menu", "dashboard")

    if menu == "dashboard":
        render_dashboard()
    elif menu == "productos":
        render_productos()
    elif menu == "galeria":
        render_galeria()
    elif menu == "equipo":
        render_equipo()
    elif menu == "usuarios" and current_user["rol"] == "admin":
        render_usuarios(current_user)
    elif menu == "administracion" and current_user["rol"] == "admin":
        render_administracion()
    elif menu == "web" and current_user["rol"] == "admin":
        st.title("🌐 Estado de la Web")
        st.info("Usa los controles del sidebar para activar/desactivar el modo mantenimiento.")
        try:
            r = requests.get(f"{BACKEND_URL}/api/health", timeout=8)
            st.json(r.json())
        except Exception as e:
            st.error(f"No se pudo conectar con el backend: {e}")
    elif menu in ("usuarios", "web"):
        st.warning("⛔ No tienes permisos para acceder a esta sección.")

if __name__ == "__main__":
    main()
