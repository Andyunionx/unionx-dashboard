"""Carga de configs YAML del agente Odoo."""
import json
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent.parent


def load_config() -> dict:
    """Carga config.yaml principal."""
    with open(BASE_DIR / "config" / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_triggers() -> dict:
    """Carga triggers.yaml."""
    with open(BASE_DIR / "config" / "triggers.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_allowed_actions() -> dict:
    """Carga allowed_actions.yaml (whitelist del executor)."""
    with open(BASE_DIR / "config" / "allowed_actions.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_odoo_credentials(env: str = "test") -> dict:
    """Carga credenciales de Odoo desde odoo/odoo_config.json."""
    config_path = BASE_DIR.parent / "odoo" / "odoo_config.json"
    with open(config_path, encoding="utf-8") as f:
        all_creds = json.load(f)
    if env not in all_creds:
        raise ValueError(f"Entorno Odoo '{env}' no existe. Disponibles: {list(all_creds.keys())}")
    return all_creds[env]
