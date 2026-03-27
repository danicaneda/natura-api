"""
setup_admin.py — Script de configuración inicial del usuario administrador.

Uso:
    python setup_admin.py

Ejecutar UNA SOLA VEZ tras el primer despliegue para crear el admin principal.
"""

import sys
import getpass
from auth import init_users_db, create_user, user_exists, change_password

def main():
    print("\n" + "="*55)
    print("  🌿  NATURA — Configuración de Administrador")
    print("="*55)

    init_users_db()

    username = input("\nNombre de usuario admin [admin]: ").strip() or "admin"

    if user_exists(username):
        print(f"\n⚠️  El usuario '{username}' ya existe.")
        change = input("¿Cambiar su contraseña? (s/N): ").strip().lower()
        if change == "s":
            while True:
                pwd1 = getpass.getpass("Nueva contraseña (mín. 8 caracteres): ")
                pwd2 = getpass.getpass("Repite la contraseña: ")
                if pwd1 != pwd2:
                    print("❌ Las contraseñas no coinciden. Intenta de nuevo.")
                    continue
                if len(pwd1) < 8:
                    print("❌ La contraseña debe tener al menos 8 caracteres.")
                    continue
                if change_password(username, pwd1):
                    print(f"\n✅ Contraseña actualizada para '{username}'.")
                else:
                    print("❌ Error al cambiar la contraseña.")
                break
        else:
            print("Sin cambios.")
        return

    print(f"\nCreando usuario administrador: '{username}'")
    while True:
        pwd1 = getpass.getpass("Contraseña (mín. 8 caracteres): ")
        pwd2 = getpass.getpass("Repite la contraseña: ")
        if pwd1 != pwd2:
            print("❌ Las contraseñas no coinciden. Intenta de nuevo.")
            continue
        if len(pwd1) < 8:
            print("❌ La contraseña debe tener al menos 8 caracteres.")
            continue
        break

    if create_user(username, pwd1, rol="admin"):
        print(f"\n✅ Usuario '{username}' creado correctamente con rol 'admin'.")
        print("\n⚠️  IMPORTANTE:")
        print("   - Guarda esta contraseña en un lugar seguro.")
        print("   - Añade AUTH_PEPPER al archivo .env para máxima seguridad.")
        print("   - No compartas el archivo users.db.\n")
    else:
        print("❌ Error al crear el usuario.")
        sys.exit(1)

if __name__ == "__main__":
    main()
