"""
🚀 Setup AUTOMÁTICO — App Operaciones (Streamlit Cloud) — Modo simple.

Versión simplificada: NO te pide nada. Lee todo de archivos locales:
  - .env                    → ANDRES_ODOO_PASSWORD (la usa también para OPS)
  - auth_config.yaml        → usuarios autorizados (los reusa)
  - credentials.json        → bloque [gcp_service_account]

Genera:
  - streamlit_secrets_ops.toml.LOCAL   (TOML para copiar a Streamlit Cloud)
  - pasos_streamlit_cloud.txt          (instrucciones simplificadas)

Uso:
    python scripts/setup_app_operaciones_simple.py
"""
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


def cargar_password_de_env():
    """Lee ANDRES_ODOO_PASSWORD del archivo .env local."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("ANDRES_ODOO_PASSWORD="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def cargar_auth():
    yaml_path = PROJECT_ROOT / "auth_config.yaml"
    if not yaml_path.exists():
        return None
    try:
        import yaml
        with open(yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def cargar_sa():
    cred_path = PROJECT_ROOT / "credentials.json"
    if not cred_path.exists():
        return None
    try:
        with open(cred_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main():
    print(color("\n🚀 Setup automático — App Operaciones\n", "bold"))

    # 1. Validar que tenemos todo lo necesario
    pwd_odoo = cargar_password_de_env()
    if not pwd_odoo:
        print(color("❌ No se encontró ANDRES_ODOO_PASSWORD en .env local.", "red"))
        print("   Ejecutá primero: python scripts/configurar_credenciales.py")
        sys.exit(1)
    print(color(f"  ✅ Password Odoo cargada (longitud: {len(pwd_odoo)} chars)", "green"))

    auth_yaml = cargar_auth()
    if not auth_yaml:
        print(color("⚠️  auth_config.yaml no encontrado — el TOML no incluirá usuarios.", "yellow"))
    else:
        n_users = len(auth_yaml.get("credentials", {}).get("usernames", {}))
        print(color(f"  ✅ Auth: {n_users} usuarios cargados", "green"))

    sa = cargar_sa()
    if not sa:
        print(color("⚠️  credentials.json no encontrado — el TOML no incluirá Service Account.", "yellow"))
    else:
        print(color(f"  ✅ Service Account: {sa.get('client_email', '?')}", "green"))

    # 2. Generar TOML — SSO Odoo (sin bloque [auth], con lista de emails autorizados)
    lines = []
    lines.append(f"# 🔒 Secrets para App Operaciones — Streamlit Cloud")
    lines.append(f"# Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"# Pegá TODO en: share.streamlit.io → tu app NUEVA → Settings → Secrets")
    lines.append(f"#")
    lines.append(f"# AUTH: SSO contra Odoo. Cada user ingresa su login Odoo y validamos con XML-RPC.")
    lines.append(f"# La lista OPS_ALLOWED_EMAILS define quién puede entrar.")
    lines.append("")

    lines.append("# ============ EMAILS AUTORIZADOS (SSO Odoo) ============")
    lines.append("# Solo estos emails pueden hacer login con su password Odoo.")
    lines.append("# Para agregar/quitar users: edita esta lista en Streamlit Cloud (sin redeploy).")
    lines.append('OPS_ALLOWED_EMAILS = "andres@grupoeter.cl,bodega@grupoeter.cl,gabriela@grupoeter.cl,facturacion@melollevo.cl"')
    lines.append("")

    lines.append("# ============ ODOO — cuenta servicio para extraer datos ============")
    lines.append("# Se usa para queries de stock, ventas, etc. NO afecta el login del dashboard.")
    lines.append('OPS_ODOO_USER = "andres@grupoeter.cl"')
    lines.append(f'OPS_ODOO_PASSWORD = "{pwd_odoo}"')
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

    toml_path = PROJECT_ROOT / "streamlit_secrets_ops.toml.LOCAL"
    toml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 3. Generar pasos
    pasos = """
🚀 PASOS RESTANTES (3 pasos · ~5 min)
======================================

PASO A — Crear la 2da app en Streamlit Cloud
─────────────────────────────────────────────
1. https://share.streamlit.io/ → "Create app" (botón arriba a la derecha)
2. Llená:
   • Repository:     Andyunionx/unionx-dashboard
   • Branch:         main
   • Main file path: dashboard_operaciones.py    ⚠️ DISTINTO al app Ventas
   • App URL:        unionx-operaciones (a tu gusto)
3. Click "Advanced settings"

PASO B — Pegar Secrets
──────────────────────
1. Abrí en VS Code: streamlit_secrets_ops.toml.LOCAL (raíz del repo)
2. Copiá TODO el contenido (Ctrl+A, Ctrl+C)
3. En Streamlit Cloud: pegalo en "Secrets" (Ctrl+V)
4. Click Deploy
5. Esperar ~1-2 min

PASO C — Validar
────────────────
1. Abrir la URL pública nueva
2. Login con tu usuario actual (andres@unionx.cl)
3. En el sidebar deberías ver:
   🚢 UnionX Operaciones
   🟢 Odoo OPS · andres@grupoeter.cl
4. Click "📦 Stock LIVE" → carga en 30-60s la 1ra vez

LIMPIEZA — cuando todo funcione
────────────────────────────────
   rm streamlit_secrets_ops.toml.LOCAL
   rm pasos_streamlit_cloud.txt
"""
    txt_path = PROJECT_ROOT / "pasos_streamlit_cloud.txt"
    txt_path.write_text(pasos, encoding="utf-8")

    print(color(f"\n✅ Listo!", "green"))
    print(f"   📄 {toml_path.name}     ({toml_path.stat().st_size} bytes)")
    print(f"   📋 {txt_path.name}      ({txt_path.stat().st_size} bytes)")
    print()
    print(color("Próximo paso:", "bold"))
    print(f"   Abrí en VS Code:   {txt_path.name}")
    print(f"   Y luego seguí los 3 pasos A/B/C.")
    print()
    print(color("🔒 Ambos archivos están gitignored — no se suben a GitHub.", "blue"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(color("\nCancelado.", "yellow"))
        sys.exit(1)
