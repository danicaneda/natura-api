"""
migrate_to_cloudinary.py
Sube todas las imágenes locales a Cloudinary y actualiza las URLs en los .db

Uso:
    1. Crea cuenta gratuita en https://cloudinary.com
    2. Copia tus credenciales del Dashboard de Cloudinary
    3. Añádelas al archivo .env de BBDD
    4. Ejecuta: python migrate_to_cloudinary.py
"""

import os
import sqlite3
import cloudinary
import cloudinary.uploader
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY    = os.environ.get("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")

if not all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
    print("❌ Faltan credenciales de Cloudinary en el archivo .env")
    print("   Añade estas variables:")
    print("   CLOUDINARY_CLOUD_NAME=tu_cloud_name")
    print("   CLOUDINARY_API_KEY=tu_api_key")
    print("   CLOUDINARY_API_SECRET=tu_api_secret")
    exit(1)

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)

MEDIA_BASE = Path("media")
url_map = {}

print("🚀 Subiendo imágenes a Cloudinary...\n")

for subdir in ["productos", "gallery", "equipo"]:
    folder_path = MEDIA_BASE / subdir
    if not folder_path.exists():
        print(f"  ⚠️  {subdir}: carpeta no encontrada, saltando")
        continue
    images = list(folder_path.glob("*.jpg")) + list(folder_path.glob("*.jpeg")) + \
             list(folder_path.glob("*.png")) + list(folder_path.glob("*.webp"))
    print(f"📁 {subdir}: {len(images)} imágenes")
    for img in images:
        local_url = f"/media/{subdir}/{img.name}"
        try:
            result = cloudinary.uploader.upload(
                str(img),
                public_id=f"natura/{subdir}/{img.stem}",
                overwrite=True,
                resource_type="image",
                quality="auto",
                fetch_format="auto",
            )
            cloud_url = result["secure_url"]
            url_map[local_url] = cloud_url
            print(f"  ✅ {img.name} → {cloud_url}")
        except Exception as e:
            print(f"  ❌ {img.name}: {e}")

print(f"\n💾 {len(url_map)} imágenes subidas a Cloudinary")

# ── ACTUALIZAR productos.db ────────────────────────────────────────────────────
print("\n📦 Actualizando productos.db...")
conn = sqlite3.connect("productos.db")
rows = conn.execute("SELECT id, imagen_url FROM productos WHERE imagen_url IS NOT NULL").fetchall()
updated = 0
for row_id, url in rows:
    new_url = url_map.get(url, url)
    if new_url != url:
        conn.execute("UPDATE productos SET imagen_url=? WHERE id=?", (new_url, row_id))
        updated += 1
        print(f"  ✅ producto {row_id}: {url} → {new_url}")
conn.commit()
conn.close()
print(f"  {updated} productos actualizados")

# ── ACTUALIZAR gallery.db ──────────────────────────────────────────────────────
print("\n📦 Actualizando gallery.db...")
conn = sqlite3.connect("gallery.db")
rows = conn.execute("SELECT id, imagen_url FROM gallery_images WHERE imagen_url IS NOT NULL").fetchall()
updated = 0
for row_id, url in rows:
    new_url = url_map.get(url, url)
    if new_url != url:
        conn.execute("UPDATE gallery_images SET imagen_url=? WHERE id=?", (new_url, row_id))
        updated += 1
        print(f"  ✅ galería {row_id}: {url} → {new_url}")
conn.commit()
conn.close()
print(f"  {updated} imágenes de galería actualizadas")

# ── ACTUALIZAR equipo.db ───────────────────────────────────────────────────────
print("\n📦 Actualizando equipo.db...")
conn = sqlite3.connect("equipo.db")
rows = conn.execute("SELECT id, imagen_url FROM equipo WHERE imagen_url IS NOT NULL").fetchall()
updated = 0
for row_id, url in rows:
    new_url = url_map.get(url, url)
    if new_url != url:
        conn.execute("UPDATE equipo SET imagen_url=? WHERE id=?", (new_url, row_id))
        updated += 1
        print(f"  ✅ equipo {row_id}: {url} → {new_url}")
conn.commit()
conn.close()
print(f"  {updated} miembros de equipo actualizados")

print("\n✅ Migración completada.")
print("👉 Ahora ve al panel BBDD y las imágenes ya se subirán automáticamente a Cloudinary.")
