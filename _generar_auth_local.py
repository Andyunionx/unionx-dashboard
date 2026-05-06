"""
Genera auth_config.yaml local con un usuario por defecto.
Útil para probar el dashboard con auth en tu PC antes de subirlo al cloud.

Uso:
    python _generar_auth_local.py andres@unionx.cl 'mi_password' "Andrés Browne"
"""
import sys
from pathlib import Path
import secrets
import yaml
import bcrypt


def hash_password(plain: str) -> str:
    """Hash bcrypt compatible con streamlit-authenticator."""
    return bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def main():
    if len(sys.argv) < 4:
        print("Uso: python _generar_auth_local.py <email> <password> <nombre>")
        print("Ej:  python _generar_auth_local.py andres@unionx.cl ROTATED-2026-05-07 'Andrés Browne'")
        sys.exit(1)

    email, password, nombre = sys.argv[1], sys.argv[2], sys.argv[3]
    username = email.split('@')[0]
    pw_hash = hash_password(password)

    config = {
        'credentials': {
            'usernames': {
                username: {
                    'email': email,
                    'name': nombre,
                    'password': pw_hash,
                }
            }
        },
        'cookie': {
            'expiry_days': 7,
            'key': secrets.token_hex(16),
            'name': 'unionx_dashboard_auth',
        },
        'preauthorized': {
            'emails': [email],
        },
    }

    out = Path(__file__).parent / 'auth_config.yaml'
    with open(out, 'w', encoding='utf-8') as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
    print(f"[OK] {out}")
    print(f"User: {username}  ({email})")
    print(f"Password hash: {pw_hash[:30]}...")


if __name__ == '__main__':
    main()
