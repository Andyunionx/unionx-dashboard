"""
🚓 POLICIA DE SEGURIDAD — escaner de secretos antes de commit/push.

Uso:
    python scripts/policia_seguridad.py             # escanea solo archivos staged (modo pre-commit)
    python scripts/policia_seguridad.py --all       # escanea TODOS los archivos del repo (auditoria)
    python scripts/policia_seguridad.py --history   # escanea historial Git completo (mas lento)
    python scripts/policia_seguridad.py --fix       # sugiere fixes y agrega entradas a .gitignore

Detecta:
  - Service Account JSON de Google ('"type": "service_account"')
  - OAuth refresh/access tokens
  - Passwords hardcoded comunes
  - Pattern especifico de la password Odoo actual ('ROTATED-2026-05-07')
  - Archivos sensibles trackeados (.env, credentials.json, token.json)
  - Private keys (BEGIN PRIVATE KEY, BEGIN RSA PRIVATE KEY)
  - AWS access keys (AKIA...)
  - Strings que parecen API keys

Codigo de salida:
  0 = limpio
  1 = secretos detectados (bloquea commit)
  2 = error de ejecucion
"""
import os
import re
import subprocess
import sys
from pathlib import Path

# Forzar UTF-8 en stdout/stderr para que funcionen los emojis en Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        # Fallback: desactivar emojis si no se puede reconfigurar
        os.environ["PYTHONIOENCODING"] = "utf-8"

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ============================================================================
# REGLAS DE DETECCION
# ============================================================================
PATTERNS = [
    # (id, descripcion, regex, severidad)
    ("SERVICE_ACCOUNT", "Google Service Account JSON",
     r'"type"\s*:\s*"service_account"', "CRITICA"),

    ("PRIVATE_KEY", "Private key (RSA/EC/OpenSSH)",
     r'-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----', "CRITICA"),

    ("OAUTH_REFRESH_TOKEN", "OAuth refresh_token con valor",
     r'"refresh_token"\s*:\s*"[^"]{20,}"', "CRITICA"),

    ("OAUTH_CLIENT_SECRET", "OAuth client_secret de Google",
     r'"client_secret"\s*:\s*"[^"]{15,}"', "CRITICA"),

    ("AWS_ACCESS_KEY", "AWS Access Key ID",
     r'\bAKIA[0-9A-Z]{16}\b', "CRITICA"),

    ("ODOO_PASSWORD_KNOWN", "Password Odoo conocida (ROTATED-2026-05-07)",
     r'ROTATED-2026-05-07', "CRITICA"),

    # Excluye placeholders comunes (<...>, $2b$..., REEMPLAZAR, env_var, getenv, etc)
    ("PASSWORD_HARDCODED", "Password hardcoded en codigo (= '...' o : '...')",
     r'(?i)(password|passwd|pwd)\s*[:=]\s*["\'](?!\$2[aby]\$|<|\{|\$\{|getenv|null|None|REEMPLAZAR|TU_|XXX|placeholder)[^"\']{6,}["\']', "ALTA"),

    ("API_KEY_HARDCODED", "Posible API key (sk_live_, pk_live_, AIza, ghp_, etc)",
     r'\b(sk_live_|pk_live_|AIza[0-9A-Za-z_-]{35}|ghp_[A-Za-z0-9]{36}|gho_[A-Za-z0-9]{36})', "ALTA"),

    ("STRIPE_KEY", "Stripe secret key",
     r'\bsk_(live|test)_[A-Za-z0-9]{20,}', "ALTA"),

    ("SLACK_WEBHOOK", "Slack webhook URL completa",
     r'https://hooks\.slack\.com/services/T[0-9A-Z]{8,}/B[0-9A-Z]{8,}/[A-Za-z0-9]{20,}', "ALTA"),

    ("BEARER_TOKEN", "Bearer token con valor en codigo (no env var)",
     r'(?i)bearer\s+[A-Za-z0-9_\-\.=]{30,}', "MEDIA"),
]

# Archivos que NUNCA deben estar trackeados
ARCHIVOS_PROHIBIDOS = [
    re.compile(r'^\.env$'),
    re.compile(r'^\.env\.[^t][^e][^m]'),  # .env.* excepto .env.template
    re.compile(r'(^|/)credentials\.json$'),
    re.compile(r'(^|/)token\.json$'),
    re.compile(r'(^|/)client_secret\.json$'),
    re.compile(r'\.pem$'),
    re.compile(r'\.key$'),
    re.compile(r'(^|/)id_rsa$'),
    re.compile(r'(^|/)secrets\.toml$'),  # solo el template OK
    re.compile(r'auth_config\.yaml$'),
]

# Archivos a saltar (no escanear contenido — son binarios o legitimos)
SKIP_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".png", ".jpg", ".jpeg", ".gif",
                   ".pdf", ".zip", ".docx", ".db", ".parquet", ".pyc", ".pyo",
                   ".woff", ".woff2", ".ttf", ".ico", ".mp4", ".webm"}
SKIP_DIRS = {"node_modules", "__pycache__", ".git", ".venv", "venv",
             "dist", "build", ".pytest_cache", ".claude/worktrees"}

# Archivos donde un match puede ser legitimo (template, doc, escaner)
ALLOWLIST_FILES = {
    "scripts/policia_seguridad.py",  # este mismo archivo tiene los patterns
    "scripts/configurar_credenciales.py",  # script que pide la password
    ".env.template",
    ".streamlit/secrets.toml.template",
    "SEGURIDAD.md",
    "auth_config.yaml.template",  # template de auth, contiene placeholders
    "DEPLOY_CLOUD.md",  # doc deploy con ejemplos $2b$
    "EXTRACCION_RAW_DESDE_ODOO.md",  # doc con placeholder <contraseña>
}


def color(text, c):
    """Colores ANSI basicos."""
    colors = {"red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m",
              "blue": "\033[94m", "bold": "\033[1m", "reset": "\033[0m"}
    return f"{colors.get(c, '')}{text}{colors['reset']}"


def listar_archivos_staged():
    """Devuelve archivos staged para commit (modo pre-commit)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
        )
        return [PROJECT_ROOT / f for f in result.stdout.splitlines() if f]
    except subprocess.CalledProcessError:
        return []


def listar_todos_archivos():
    """Devuelve todos los archivos no gitignored del repo."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
        )
        return [PROJECT_ROOT / f for f in result.stdout.splitlines() if f]
    except subprocess.CalledProcessError:
        return []


def listar_archivos_history():
    """Devuelve todos los archivos que aparecieron alguna vez en el historial."""
    try:
        result = subprocess.run(
            ["git", "log", "--all", "--name-only", "--pretty=format:"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
        )
        archivos = sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})
        return archivos
    except subprocess.CalledProcessError:
        return []


def es_archivo_skipeable(path: Path) -> bool:
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return True
    parts = path.parts
    if any(d in parts for d in SKIP_DIRS):
        return True
    return False


def archivo_en_allowlist(rel_path: str) -> bool:
    rel_norm = rel_path.replace("\\", "/")
    return rel_norm in ALLOWLIST_FILES


def escanear_archivo(path: Path) -> list[dict]:
    """Devuelve lista de findings (dict con id, linea, snippet, severidad)."""
    findings = []
    rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")

    # 1. Validar nombre prohibido
    for prohibido in ARCHIVOS_PROHIBIDOS:
        if prohibido.search(rel):
            findings.append({
                "id": "ARCHIVO_PROHIBIDO",
                "desc": f"Archivo no debe estar trackeado: {rel}",
                "severidad": "CRITICA",
                "linea": 0,
                "snippet": "(nombre de archivo)",
            })
            break

    # 2. Validar contenido si es file que conviene escanear
    if archivo_en_allowlist(rel):
        return findings  # whitelisted, no escanear contenido
    if es_archivo_skipeable(path):
        return findings
    if not path.exists() or not path.is_file():
        return findings

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return findings

    if len(content) > 5_000_000:  # >5MB no escanear contenido
        return findings

    for pattern_id, desc, regex, severidad in PATTERNS:
        for match in re.finditer(regex, content):
            # localizar linea
            linea = content[:match.start()].count("\n") + 1
            snippet = content[max(0, match.start() - 20):min(len(content), match.end() + 20)]
            snippet = snippet.replace("\n", " ").strip()[:120]
            findings.append({
                "id": pattern_id,
                "desc": desc,
                "severidad": severidad,
                "linea": linea,
                "snippet": snippet,
            })
    return findings


def reportar(findings_por_archivo: dict):
    """Imprime reporte ordenado."""
    if not findings_por_archivo:
        print(color("\n✅ POLICIA DE SEGURIDAD: limpio. Ningun secreto detectado.", "green"))
        return 0

    total_criticos = 0
    total_altos = 0

    print(color("\n🚓 POLICIA DE SEGURIDAD — HALLAZGOS\n", "bold"))

    for archivo, findings in sorted(findings_por_archivo.items()):
        print(color(f"📄 {archivo}", "bold"))
        for f in findings:
            sev = f["severidad"]
            sev_c = "red" if sev == "CRITICA" else "yellow" if sev == "ALTA" else "blue"
            tag = f"[{sev}]"
            print(f"  {color(tag, sev_c)} {f['id']} (linea {f['linea']}): {f['desc']}")
            if f["snippet"]:
                print(f"     {color(f['snippet'], 'yellow')}")
            if sev == "CRITICA":
                total_criticos += 1
            elif sev == "ALTA":
                total_altos += 1
        print()

    print(color(f"📊 Total: {total_criticos} CRITICOS · {total_altos} ALTOS", "bold"))

    if total_criticos > 0:
        print(color("\n🛑 BLOQUEADO: hay secretos CRITICOS. NO se puede commitear.", "red"))
        print(color("   Acciones recomendadas:", "bold"))
        print("   1. Mover el secreto a una env var o un archivo gitignored")
        print("   2. Si el archivo no debe estar trackeado, agregarlo a .gitignore + git rm --cached")
        print("   3. Si el secreto YA esta en el historial Git, rotar la credencial Y limpiar historial con git-filter-repo")
        return 1
    elif total_altos > 0:
        print(color("\n⚠️ CUIDADO: hay hallazgos de severidad ALTA. Revisa antes de commitear.", "yellow"))
        return 1
    return 0


def main():
    args = sys.argv[1:]
    modo = "staged"
    if "--all" in args:
        modo = "all"
    elif "--history" in args:
        modo = "history"

    print(color(f"🚓 Policia de seguridad — modo: {modo}", "blue"))

    if modo == "staged":
        archivos = listar_archivos_staged()
        if not archivos:
            print(color("Sin archivos staged. (Sugerencia: git add ... primero)", "yellow"))
            return 0
    elif modo == "all":
        archivos = listar_todos_archivos()
    else:  # history
        # En modo history solo reportamos archivos que aparecieron historicos pero ya no estan
        archivos_actuales = set(str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
                                for p in listar_todos_archivos())
        historicos = listar_archivos_history()
        sospechosos = [PROJECT_ROOT / h for h in historicos
                       if any(p.search(h) for p in ARCHIVOS_PROHIBIDOS)]
        if not sospechosos:
            print(color("✅ Historial limpio: ningun archivo sensible encontrado.", "green"))
            return 0
        print(color(f"⚠️ {len(sospechosos)} archivos sensibles en HISTORIAL Git:", "red"))
        for s in sospechosos:
            rel = str(s).replace(str(PROJECT_ROOT), "").lstrip("\\/")
            actual = "✅ no en HEAD" if rel not in archivos_actuales else "🔴 AUN EN HEAD"
            print(f"  - {rel}  {actual}")
        print(color("\nPara limpiar historial completo: usar 'git-filter-repo' (ver SEGURIDAD.md)", "yellow"))
        return 1

    print(f"  Escaneando {len(archivos)} archivos...")

    findings_por_archivo = {}
    for path in archivos:
        if not path.exists():
            continue
        findings = escanear_archivo(path)
        if findings:
            rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            findings_por_archivo[rel] = findings

    return reportar(findings_por_archivo)


if __name__ == "__main__":
    sys.exit(main())
