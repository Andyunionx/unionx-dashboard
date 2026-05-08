"""
🚀 Setup asistido — App Operaciones (Streamlit Cloud).

Genera 2 archivos LOCALES (gitignored):
  1. streamlit_secrets_ops.toml.LOCAL  — bloque TOML listo para copiar a Streamlit Cloud Secrets
  2. pasos_streamlit_cloud.txt          — instrucciones step-by-step

NO sube nada, NO commitea nada, NO modifica el sistema productivo.

Uso:
    python scripts/setup_app_operaciones.py
"""
import getpass
import json
import os
import secrets as _secrets
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        os.environ["PYTHONIOENCODING"] = "utf-8"


def color(t, c):
    cs = {"red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m",
          "blue": "\033[94m", "bold": "\033[1m", "reset": "\033[0m"}
    return f"{cs.get(c, '')}{t}{cs['reset']}"


def header(title):
    print()
    print(color("=" * 70, "bold"))
    print(color(f"  {title}", "bold"))
    print(color("=" * 70, "bold"))


def cargar_service_account():
    cred_path = PROJECT_ROOT / "credentials.json"
    if not cred_path.exists():
        print(color("\n⚠️  credentials.json no encontrado en raíz.", "yellow"))
        respuesta = input("¿Continuar SIN bloque gcp_service_account? (s/N): ").strip().lower()
        if respuesta != "s":
            sys.exit(1)
        return None
    try:
        with open(cred_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(color(f"❌ Error leyendo credentials.json: {e}", "red"))
        return None


def cargar_auth_local():
    yaml_path = PROJECT_ROOT / "auth_config.yaml"
    if yaml_path.exists():
        try:
            import yaml
            with open(yaml_path, encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception:
            pass
    return None


def main():
    header("🚀 Setup App Operaciones — Streamlit Cloud")
    print("Genera los archivos para crear la 2da app en Streamlit Cloud.")
    print("NO sube nada — solo prepara los textos para copy/paste.\n")

    # PASO 1
    header("PASO 1 / 4 — Email del usuario Odoo Operaciones")
    print("Email del usuario que vas a crear (o ya creaste) en Odoo.")
    print(color("Ejemplo: operaciones@unionx.cl", "blue"))
    email_ops = input("\n  Email: ").strip()
    if not email_ops or "@" not in email_ops:
        print(color("❌ Email inválido.", "red"))
        sys.exit(1)

    # PASO 2
    header("PASO 2 / 4 — Password del usuario Odoo Operaciones")
    print(color("(El input no se mostrará — es lo correcto y seguro)", "blue"))

    while True:
        pw1 = getpass.getpass("\n  Password: ")
        if not pw1:
            print(color("❌ Vacía.", "red"))
            sys.exit(1)
        if len(pw1) < 8:
            cont = input("  Password corta (<8). ¿Seguir igual? (s/N): ").strip().lower()
            if cont != "s":
                continue
        pw2 = getpass.getpass("  Confirmá: ")
        if pw1 != pw2:
            print(color("❌ No coinciden. Reintentá.", "red"))
            continue
        break

    # PASO 3
    header("PASO 3 / 4 — Auth")
    print("  1. Mismos usuarios que la app Ventas (Recomendado)")
    print("  2. Skip — adapto el [auth] manualmente")
    eleccion = input("\n  Elegí [1/2]: ").strip() or "1"

    auth_yaml = cargar_auth_local()
    auth_block_data = None
    if eleccion == "1":
        if auth_yaml:
            print(color("✅ Reutilizando lista de usuarios.", "green"))
            auth_yaml["cookie"]["name"] = "unionx-ops-auth"
            auth_yaml["cookie"]["key"] = _secrets.token_hex(32)
            auth_block_data = auth_yaml
        else:
            print(color("⚠️  No encontré auth_config.yaml local. Skip.", "yellow"))

    # PASO 4
    header("PASO 4 / 4 — Service Account de Google")
    sa = cargar_service_account()

    # GENERAR
    header("Generando archivos…")

    toml_path = PROJECT_ROOT / "streamlit_secrets_ops.toml.LOCAL"
    txt_path = PROJECT_ROOT / "pasos_streamlit_cloud.txt"

    lines = []
    lines.append(f"# 🔒 Secrets para App Operaciones — Streamlit Cloud")
    lines.append(f"# Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"# Pegá TODO en: share.streamlit.io → tu app → Settings → Secrets")
    lines.append("")

    if auth_block_data:
        lines.append("# ============ AUTH ============")
        lines.append("[auth]")
        lines.append("")
        creds = auth_block_data.get("credentials", {}).get("usernames", {})
        for username, data in creds.items():
            lines.append(f"[auth.credentials.usernames.{username}]")
            lines.append(f'email = "{data.get("email", "")}"')
            lines.append(f'name = "{data.get("name", "")}"')
            lines.append(f'password = "{data.get("password", "")}"')
            lines.append("")
        cookie = auth_block_data.get("cookie", {})
        lines.append("[auth.cookie]")
        lines.append(f'name = "{cookie.get("name", "unionx-ops-auth")}"')
        lines.append(f'key = "{cookie.get("key", "")}"')
        lines.append(f'expiry_days = {cookie.get("expiry_days", 30)}')
        lines.append("")
    else:
        lines.append("# ============ AUTH (adaptar manualmente) ============")
        lines.append("# [auth]")
        lines.append("# [auth.credentials.usernames.<USUARIO>]")
        lines.append("# email = \"...\"")
        lines.append("# name = \"...\"")
        lines.append("# password = \"$2b$12$...\"")
        lines.append("# ")
        lines.append("# [auth.cookie]")
        lines.append('# name = "unionx-ops-auth"')
        lines.append(f'# key = "{_secrets.token_hex(32)}"')
        lines.append("# expiry_days = 30")
        lines.append("")

    lines.append("# ============ ODOO Operaciones ============")
    lines.append(f'OPS_ODOO_USER = "{email_ops}"')
    lines.append(f'OPS_ODOO_PASSWORD = "{pw1}"')
    lines.append("")

    if sa:
        lines.append("# ============ SERVICE ACCOUNT GOOGLE (Sheets) ============")
        lines.append("[gcp_service_account]")
        lines.append(f'type = "{sa.get("type", "")}"')
        lines.append(f'project_id = "{sa.get("project_id", "")}"')
        lines.append(f'private_key_id = "{sa.get("private_key_id", "")}"')
        pk = sa.get("private_key", "").replace("\n", "\\n")
        lines.append(f'private_key = "{pk}"')
        lines.append(f'client_email = "{sa.get("client_email", "")}"')
        lines.append(f'client_id = "{sa.get("client_id", "")}"')
        lines.append(f'auth_uri = "{sa.get("auth_uri", "")}"')
        lines.append(f'token_uri = "{sa.get("token_uri", "")}"')
        lines.append(f'auth_provider_x509_cert_url = "{sa.get("auth_provider_x509_cert_url", "")}"')
        lines.append(f'client_x509_cert_url = "{sa.get("client_x509_cert_url", "")}"')
        lines.append(f'universe_domain = "{sa.get("universe_domain", "googleapis.com")}"')
        lines.append("")

    toml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # PASOS
    pasos_text = f"""
🚀 PASOS PARA DESPLEGAR LA APP OPERACIONES EN STREAMLIT CLOUD
=============================================================

PASO 1 — Crear usuario en Odoo (si no lo hiciste)
──────────────────────────────────────────────────
1. Login a https://unionxb2b.odoo.com como Andrés
2. Settings → Users & Companies → Users → Create
3. Datos:
   - Name: "Operaciones UnionX"
   - Login (Email): {email_ops}
   - Password: la que ingresaste en este script
4. Permisos sugeridos:
   ✅ Inventory: User
   ✅ Manufacturing: User
   ✅ Sales: User
   ✅ Helpdesk: User
   ❌ Accounting: ninguno
5. Save

PASO 2 — Crear app #2 en Streamlit Cloud
──────────────────────────────────────────
1. Andá a https://share.streamlit.io/
2. Click "New app"
3. Repository: Andyunionx/unionx-dashboard
4. Branch: main
5. Main file path: dashboard_operaciones.py    ⚠️ DISTINTO al app Ventas
6. App URL (a tu gusto): unionx-operaciones
7. NO clickear Deploy todavía → Advanced settings → Secrets

PASO 3 — Pegar Secrets
──────────────────────
1. Abrí: streamlit_secrets_ops.toml.LOCAL (en raíz del proyecto)
2. Copiá TODO (Ctrl+A, Ctrl+C)
3. Pegalo en el campo Secrets de Streamlit Cloud
4. Click Save

PASO 4 — Deploy
─────────────────
1. Volver a la pantalla principal y click Deploy
2. Esperar ~1-2 min

PASO 5 — Validar
──────────────────
1. Abrir la URL pública (https://unionx-operaciones-xxx.streamlit.app/)
2. Login
3. Sidebar debería mostrar:
   🚢 UnionX Operaciones
   🟢 Odoo OPS · {email_ops}
4. Si ves 🔴: revisar typos en OPS_ODOO_PASSWORD
5. Click "📦 Stock LIVE" → carga en 30-60s

PASO 6 — Borrar archivos locales con secretos
──────────────────────────────────────────────
Una vez confirmado que funciona en cloud:
   rm streamlit_secrets_ops.toml.LOCAL
   rm pasos_streamlit_cloud.txt

(Están gitignored, no se suben a GitHub. Igual mejor borrarlos.)

────────────────────────────────────────────────────────────
Troubleshooting: ver OPERACIONES_DASHBOARD_IMPLEMENTACION.md
────────────────────────────────────────────────────────────
"""
    txt_path.write_text(pasos_text, encoding="utf-8")

    print(color("\n✅ Listo!\n", "green"))
    print(f"📄 Secrets:    {toml_path.relative_to(PROJECT_ROOT)}")
    print(f"📋 Pasos:      {txt_path.relative_to(PROJECT_ROOT)}")
    print()
    print(color("Próximos pasos:", "bold"))
    print(f"  1. Abrir y leer:  {txt_path.name}")
    print(f"  2. Copiar contenido de:  {toml_path.name}")
    print(f"  3. Seguir los 6 pasos del .txt")
    print()
    print(color("Ambos archivos están gitignored — no van a GitHub.", "blue"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(color("\n\nCancelado.", "yellow"))
        sys.exit(1)
