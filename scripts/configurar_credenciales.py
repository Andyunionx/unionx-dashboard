"""
🔐 Configurador de credenciales — UnionX

Este script te pide la password Odoo de forma SEGURA (input oculto, no se ve
mientras escribís, no queda en el historial del terminal) y la guarda en:

  1. Env var de usuario Windows (ANDRES_ODOO_PASSWORD)
  2. Archivo .env del proyecto

Uso:
    python scripts/configurar_credenciales.py

También opcionalmente te ayuda a copiar el credentials.json de Google Cloud
a las 2 ubicaciones donde el código lo necesita.
"""
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# Forzar UTF-8 en Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def color(t, c):
    cs = {"red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m",
          "blue": "\033[94m", "bold": "\033[1m", "reset": "\033[0m"}
    return f"{cs.get(c, '')}{t}{cs['reset']}"


def actualizar_env_file(key: str, value: str):
    """Lee .env, actualiza/agrega key=value, guarda."""
    lines = []
    found = False
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if raw.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(raw)
    if not found:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def setear_env_var_windows(key: str, value: str) -> bool:
    """Setea env var de usuario en Windows."""
    if sys.platform != "win32":
        print(color(f"  (no Windows: ANDRES_ODOO_PASSWORD se debe setear manualmente: export {key}=...)", "yellow"))
        return False
    try:
        # Usar setx con quoting correcto
        result = subprocess.run(
            ["setx", key, value],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True
        else:
            print(color(f"  ⚠ setx falló: {result.stderr}", "yellow"))
            return False
    except Exception as e:
        print(color(f"  ⚠ Error seteando env var: {e}", "yellow"))
        return False


def configurar_password():
    print(color("\n🔑 PASO 1 — Password de Odoo", "bold"))
    print(color("(El input no se mostrará — es lo correcto y seguro)", "blue"))

    p1 = getpass.getpass("  Pegá/escribí la nueva password: ")
    if not p1:
        print(color("  ❌ Password vacía. Cancelado.", "red"))
        return False
    if len(p1) < 8:
        print(color("  ⚠ Password corta (<8 chars). Recomiendo 15+ caracteres.", "yellow"))
        cont = input("  ¿Seguir igual? (s/N): ").strip().lower()
        if cont != "s":
            return False
    p2 = getpass.getpass("  Confirmá: ")
    if p1 != p2:
        print(color("  ❌ Las passwords no coinciden. Cancelado.", "red"))
        return False

    # Guardar
    print(color("\n  Guardando...", "blue"))

    # 1. .env
    actualizar_env_file("ANDRES_ODOO_PASSWORD", p1)
    print(color(f"  ✅ Guardada en {ENV_FILE.relative_to(PROJECT_ROOT)}", "green"))

    # 2. Env var Windows
    if setear_env_var_windows("ANDRES_ODOO_PASSWORD", p1):
        print(color("  ✅ Env var Windows User actualizada (ANDRES_ODOO_PASSWORD)", "green"))
        print(color("     Nota: terminales abiertas necesitan REINICIARSE para ver el nuevo valor.", "yellow"))

    return True


def configurar_credentials_json():
    print(color("\n🔑 PASO 2 — Service Account de Google Cloud (opcional)", "bold"))
    print("  Si rotaste la key del Service Account 'union-x-revenue', pegá la ruta del .json descargado.")
    print("  (ENTER para saltar)\n")

    raw = input("  Ruta del nuevo credentials.json: ").strip().strip('"').strip("'")
    if not raw:
        print(color("  Saltado.", "yellow"))
        return False

    src = Path(raw)
    if not src.exists() or not src.is_file():
        print(color(f"  ❌ Archivo no encontrado: {src}", "red"))
        return False

    # Validar que sea un service account
    try:
        content = src.read_text(encoding="utf-8")
        if '"type": "service_account"' not in content:
            print(color("  ⚠ El archivo no parece un Service Account de Google.", "yellow"))
            cont = input("  ¿Copiar igual? (s/N): ").strip().lower()
            if cont != "s":
                return False
    except Exception as e:
        print(color(f"  ❌ Error leyendo archivo: {e}", "red"))
        return False

    destinos = [
        PROJECT_ROOT / "credentials.json",
        PROJECT_ROOT / "eerr-finanzas" / "credentials.json",
    ]

    for dst in destinos:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(color(f"  ✅ Copiado a {dst.relative_to(PROJECT_ROOT)}", "green"))
        except Exception as e:
            print(color(f"  ⚠ Falló copia a {dst}: {e}", "yellow"))

    return True


def validar():
    """Valida que todo quedó bien (sin mostrar valores)."""
    print(color("\n🧪 PASO 3 — Validación", "bold"))

    # .env tiene la key?
    if ENV_FILE.exists() and "ANDRES_ODOO_PASSWORD=" in ENV_FILE.read_text(encoding="utf-8"):
        print(color("  ✅ .env tiene ANDRES_ODOO_PASSWORD", "green"))
    else:
        print(color("  ⚠ .env NO tiene ANDRES_ODOO_PASSWORD", "yellow"))

    # Env var Windows?
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 '[Environment]::GetEnvironmentVariable("ANDRES_ODOO_PASSWORD", "User") -ne $null'],
                capture_output=True, text=True, timeout=10
            )
            if "True" in r.stdout:
                print(color("  ✅ Env var Windows User existe", "green"))
            else:
                print(color("  ⚠ Env var Windows User NO existe", "yellow"))
        except Exception:
            print(color("  ⚠ No se pudo verificar env var Windows", "yellow"))

    # credentials.json?
    if (PROJECT_ROOT / "credentials.json").exists():
        print(color("  ✅ credentials.json existe en raíz", "green"))
    else:
        print(color("  ℹ credentials.json no existe en raíz (ok si saltaste paso 2)", "blue"))


def main():
    print(color("=" * 60, "bold"))
    print(color("🔐 CONFIGURADOR DE CREDENCIALES — UnionX", "bold"))
    print(color("=" * 60, "bold"))
    print()
    print("Este script va a guardar tu password Odoo en lugares seguros")
    print("del proyecto (env var Windows + .env gitignored). Nada se imprime")
    print("en pantalla y nada queda en el chat de Claude.\n")

    ok_pwd = configurar_password()
    if ok_pwd:
        configurar_credentials_json()
        validar()
        print(color("\n🎉 LISTO. Reiniciá Streamlit/Flask para que tomen los nuevos valores.", "green"))
        print()
        print("Próximos pasos sugeridos:")
        print("  1. Cerrar TODAS las ventanas de PowerShell/cmd que tengas abiertas")
        print("  2. Abrir una nueva PowerShell")
        print("  3. Verificar: $env:ANDRES_ODOO_PASSWORD (debe mostrar tu password)")
        print("  4. Reiniciar dashboards: cierre + relanza")
    else:
        print(color("\n❌ Configuración no completada.", "red"))
        sys.exit(1)


if __name__ == "__main__":
    main()
