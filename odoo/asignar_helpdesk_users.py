"""
Asigna el grupo "Helpdesk: Usuario - Todos los tickets" a 3 usuarias.

Usuarias objetivo:
  - Joselyn Barreto
  - Fernanda Avila
  - Camila Bustos

Flujo:
  1. Conecta a Odoo PRODUCCION (lectura).
  2. Busca el group_id por xml_id (helpdesk.group_helpdesk_user).
  3. Busca los 3 user_ids por nombre (match flexible).
  4. Muestra estado ANTES (grupos actuales).
  5. PIDE CONFIRMACION explicita por consola.
  6. Ejecuta el write() solo si el usuario escribe SI.
  7. Muestra estado DESPUES.

NO toca permisos contables ni nada existente: solo SUMA el grupo de Helpdesk.
"""
import json
import sys
import io
from pathlib import Path

# UTF-8 en Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent / "finanzas-unionx" / "backend"))
from app.core.odoo_client import OdooClient  # type: ignore

CONFIG_PATH = Path(__file__).parent / "odoo_config.json"

# Nivel de Helpdesk a asignar.
# Opciones disponibles en Odoo:
#   helpdesk.group_helpdesk_user        -> Usuario: Todos los tickets  (RECOMENDADO)
#   helpdesk.group_helpdesk_manager     -> Administrador
HELPDESK_GROUP_XMLID = "helpdesk.group_helpdesk_user"

USUARIAS = [
    "Joselyn Barreto",
    "Fernanda Avila",
    "Camila Bustos",
]


def buscar_group_id(client: OdooClient, xml_id: str) -> int:
    """Resuelve un xml_id -> res_id usando ir.model.data."""
    module, name = xml_id.split(".", 1)
    res = client._execute_with_retry(
        "search_read", "ir.model.data",
        [[("module", "=", module), ("name", "=", name)]],
        {"fields": ["res_id", "model"], "limit": 1},
    )
    if not res:
        raise RuntimeError(
            f"No se encontro xml_id '{xml_id}'. "
            "Probable causa: el modulo Helpdesk NO esta instalado."
        )
    if res[0]["model"] != "res.groups":
        raise RuntimeError(f"xml_id '{xml_id}' no apunta a res.groups (apunta a {res[0]['model']}).")
    return res[0]["res_id"]


def buscar_usuario(client: OdooClient, nombre: str) -> dict:
    """Busca un usuario por nombre (ilike). Devuelve dict o lanza si no hay match unico."""
    matches = client._execute_with_retry(
        "search_read", "res.users",
        [[("name", "ilike", nombre), ("active", "=", True)]],
        {"fields": ["id", "name", "login", "groups_id"], "limit": 5},
    )
    if not matches:
        raise RuntimeError(f"Usuario '{nombre}' NO encontrado en res.users.")
    if len(matches) > 1:
        nombres = ", ".join(f"{m['name']} ({m['login']})" for m in matches)
        raise RuntimeError(
            f"Usuario '{nombre}' tiene {len(matches)} matches: {nombres}. "
            "Hace falta afinar el nombre."
        )
    return matches[0]


def grupos_actuales(client: OdooClient, group_ids: list[int]) -> list[str]:
    """Devuelve los nombres de los grupos dados."""
    if not group_ids:
        return []
    grupos = client._execute_with_retry(
        "search_read", "res.groups",
        [[("id", "in", group_ids)]],
        {"fields": ["full_name"]},
    )
    return sorted(g["full_name"] for g in grupos)


def main():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)["produccion"]

    print("=" * 90)
    print(f"Conectando a: {cfg['url']}  (DB: {cfg['db_name']})")
    import os
    password = cfg.get("password") or os.getenv("ANDRES_ODOO_PASSWORD")
    if not password:
        raise RuntimeError(
            "Password no encontrada. Setear env var ANDRES_ODOO_PASSWORD o "
            "ejecutar: python scripts/configurar_credenciales.py"
        )
    client = OdooClient(cfg["url"], cfg["db_name"], cfg["username"], password)
    uid = client.authenticate()
    print(f"[OK] UID conectado = {uid}")
    print("=" * 90)

    # 1. Resolver group_id de Helpdesk
    print(f"\n[1/4] Buscando grupo '{HELPDESK_GROUP_XMLID}'...")
    group_id = buscar_group_id(client, HELPDESK_GROUP_XMLID)
    grupo_info = client._execute_with_retry(
        "search_read", "res.groups",
        [[("id", "=", group_id)]],
        {"fields": ["full_name"]},
    )[0]
    print(f"      group_id={group_id}  ->  {grupo_info['full_name']}")

    # 2. Buscar las 3 usuarias
    print(f"\n[2/4] Buscando usuarias...")
    usuarios_data = []
    for nombre in USUARIAS:
        u = buscar_usuario(client, nombre)
        ya_lo_tiene = group_id in u["groups_id"]
        marca = "YA TIENE" if ya_lo_tiene else "FALTA"
        print(f"      [{marca:8}] {u['name']:30} | login={u['login']} | id={u['id']}")
        usuarios_data.append({**u, "ya_lo_tiene": ya_lo_tiene})

    pendientes = [u for u in usuarios_data if not u["ya_lo_tiene"]]
    if not pendientes:
        print("\n[INFO] Las 3 usuarias YA tienen el grupo. Nada que hacer.")
        return

    # 3. Confirmacion
    print("\n" + "=" * 90)
    print("VOY A AGREGAR el grupo Helpdesk a:")
    for u in pendientes:
        print(f"   - {u['name']} ({u['login']})")
    print("=" * 90)
    resp = input("\nConfirmar? Escribe SI para ejecutar: ").strip().upper()
    if resp != "SI":
        print("[ABORTADO] No se hizo ningun cambio.")
        return

    # 4. Aplicar (write con (4, group_id) = link existing record)
    print(f"\n[3/4] Aplicando cambios...")
    for u in pendientes:
        client._execute_with_retry(
            "write", "res.users",
            [[u["id"]], {"groups_id": [(4, group_id)]}],
            {},
        )
        print(f"      [OK] {u['name']} -> grupo agregado")

    # 5. Verificacion post
    print(f"\n[4/4] Verificando estado final...")
    for u in pendientes:
        u_now = client._execute_with_retry(
            "search_read", "res.users",
            [[("id", "=", u["id"])]],
            {"fields": ["groups_id"], "limit": 1},
        )[0]
        if group_id in u_now["groups_id"]:
            print(f"      [VERIFICADO] {u['name']}: grupo presente.")
        else:
            print(f"      [WARN] {u['name']}: el grupo NO aparece tras el write. Revisar.")

    print("\n" + "=" * 90)
    print("LISTO. Cambios aplicados con tu sesion (andres@grupoeter.cl).")
    print("Quedan trazados en el log de auditoria de Odoo.")
    print("=" * 90)


if __name__ == "__main__":
    main()
