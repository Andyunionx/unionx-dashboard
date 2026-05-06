"""
Wrapper de Odoo para el agente. Reusa el OdooClient existente
en finanzas-unionx/backend/app/core/odoo_client.py.

Esta clase es SOLO LECTURA. Las escrituras pasan por executor/.
"""
import sys
from pathlib import Path
from typing import Optional

# Reusa el OdooClient existente
ODOO_CLIENT_PATH = Path(__file__).parent.parent.parent / "finanzas-unionx" / "backend"
sys.path.insert(0, str(ODOO_CLIENT_PATH))
from app.core.odoo_client import OdooClient  # type: ignore  # noqa: E402

from .config_loader import load_config, load_odoo_credentials


class OdooQuery:
    """Queries de solo lectura a Odoo, segun el intent recibido."""

    def __init__(self):
        config = load_config()
        env = config["odoo"]["environment"]
        creds = load_odoo_credentials(env)
        self.env = env
        self.client = OdooClient(
            url=creds["url"],
            db=creds["db_name"],
            username=creds["username"],
            password=creds["password"],
        )
        self.client.authenticate()
        print(f"[ODOO] Conectado a {env} ({creds['url']}) UID={self.client._uid}")

    # -------- Queries genericas --------

    def search_read(self, model: str, domain: list, fields: list, limit: int = 100):
        return self.client.search_read(model, domain, fields, limit=limit)

    def count(self, model: str, domain: list) -> int:
        return self.client._execute_with_retry("search_count", model, domain, {})

    # -------- Write helper (usado SOLO desde executor/) --------

    def write(self, model: str, ids: list[int], values: dict) -> bool:
        """
        Escribe en Odoo via XMLRPC directo.

        El wrapper _execute_with_retry no soporta write porque su signature
        coloca solo args[0] como posicional, mientras que Odoo write necesita
        [[ids], values_dict] como posicional.

        Para mantener auditoria, este metodo NO debe llamarse desde fuera del
        executor/ - el dispatcher es el unico camino autorizado.
        """
        import xmlrpc.client
        uid = self.client.authenticate()
        models = xmlrpc.client.ServerProxy(f"{self.client.url}/xmlrpc/2/object")
        return models.execute_kw(
            self.client.db,
            uid,
            self.client.password,
            model,
            "write",
            [ids, values],
        )

    # -------- Queries especificas por intent --------

    def find_rejected_invoices_with_dte(self, limit: int = 50) -> list[dict]:
        """
        Busca account.move con DTE rechazado en Odoo.
        Para el caso del mail de Yohana: detecta facturas rechazadas para
        validar contra el SII.
        """
        domain = [
            ("l10n_cl_dte_status", "=", "rejected"),
            ("move_type", "in", ["out_invoice", "out_refund"]),
        ]
        fields = [
            "id", "name", "partner_id", "invoice_date", "amount_total",
            "state", "l10n_cl_dte_status", "l10n_latam_document_number",
            "l10n_latam_document_type_id",
        ]
        return self.search_read("account.move", domain, fields, limit=limit)

    def get_invoice_by_folio(self, folio: str) -> Optional[dict]:
        """Busca factura por folio (l10n_latam_document_number)."""
        domain = [("l10n_latam_document_number", "=", folio)]
        fields = [
            "id", "name", "partner_id", "invoice_date", "amount_total",
            "state", "l10n_cl_dte_status",
        ]
        results = self.search_read("account.move", domain, fields, limit=1)
        return results[0] if results else None

    def get_module_summary(self, model: str) -> dict:
        """
        Resumen rapido de un modelo para auditor.
        Retorna: total_records, fields_count, sample.
        """
        total = self.count(model, [])
        sample = self.search_read(model, [], ["id"], limit=1)
        return {
            "model": model,
            "total_records": total,
            "sample_id": sample[0]["id"] if sample else None,
        }
