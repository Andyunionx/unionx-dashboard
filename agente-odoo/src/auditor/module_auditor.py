"""
Auditor de modulos Odoo. Inspecciona un modulo segun 5 dimensiones:
calidad de datos, configuracion, automatizaciones, eficiencia, escalabilidad.

Output: dict con findings priorizados (alto/medio/bajo) + propuesta de accion.
"""
from datetime import datetime
from typing import Optional


# Mapa de modulos a sus modelos representativos
MODULE_MODELS = {
    "Contabilidad": ["account.move", "account.move.line", "account.account", "account.journal"],
    "Ventas": ["sale.order", "sale.order.line", "res.partner"],
    "Inventario": ["stock.picking", "stock.move", "stock.quant", "product.product"],
    "Compras": ["purchase.order", "purchase.order.line"],
    "Manufactura": ["mrp.production", "mrp.bom"],
    "CRM": ["crm.lead"],
}


class ModuleAuditor:
    """Audita un modulo Odoo y genera findings."""

    def __init__(self, odoo_query):
        self.odoo = odoo_query

    def audit_module(self, module_name: str) -> dict:
        """Ejecuta el audit completo de un modulo."""
        if module_name not in MODULE_MODELS:
            return {"error": f"Modulo '{module_name}' no esta registrado"}

        models = MODULE_MODELS[module_name]
        findings = {
            "module": module_name,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "models_inspected": models,
            "data_quality": self._audit_data_quality(module_name, models),
            "configuration": self._audit_configuration(module_name, models),
            "automations": self._audit_automations(module_name, models),
            "efficiency": self._audit_efficiency(module_name, models),
            "scalability": self._audit_scalability(module_name, models),
        }
        findings["summary"] = self._summarize(findings)
        return findings

    # -------- Calidad de datos --------

    def _audit_data_quality(self, module: str, models: list[str]) -> list[dict]:
        findings = []

        if module == "Contabilidad":
            # Caso del mail Yohana: facturas rechazadas en Odoo
            try:
                rejected = self.odoo.count(
                    "account.move",
                    [("l10n_cl_dte_status", "=", "rejected"),
                     ("move_type", "in", ["out_invoice", "out_refund"])],
                )
                if rejected > 0:
                    findings.append({
                        "severity": "alto" if rejected > 10 else "medio",
                        "category": "calidad de datos",
                        "title": f"{rejected} facturas con DTE rechazado en Odoo",
                        "detail": "Validar contra SII. Posible desincronizacion de estados.",
                        "action": "Revisar facturas y aplicar sii_status_fix donde corresponda.",
                    })

                draft_old = self.odoo.count(
                    "account.move",
                    [("state", "=", "draft"), ("move_type", "in", ["out_invoice", "out_refund"])],
                )
                if draft_old > 5:
                    findings.append({
                        "severity": "medio",
                        "category": "calidad de datos",
                        "title": f"{draft_old} facturas en estado borrador",
                        "detail": "Borradores acumulados pueden generar confusion en reportes.",
                        "action": "Revisar y validar/cancelar segun corresponda.",
                    })
            except Exception as e:
                findings.append({"severity": "info", "title": f"Error auditando contabilidad: {e}"})

        if module == "Inventario":
            try:
                # Productos sin categoria (problema clasico)
                no_cat = self.odoo.count("product.template", [("categ_id", "=", False)])
                if no_cat > 0:
                    findings.append({
                        "severity": "medio",
                        "category": "calidad de datos",
                        "title": f"{no_cat} productos sin categoria",
                        "detail": "Afecta reportes por categoria y reglas de inventario.",
                        "action": "Asignar categoria a todos los productos activos.",
                    })

                # Stock negativo
                neg_qty = self.odoo.count("stock.quant", [("quantity", "<", 0)])
                if neg_qty > 0:
                    findings.append({
                        "severity": "alto",
                        "category": "calidad de datos",
                        "title": f"{neg_qty} quants con cantidad negativa",
                        "detail": "Indica movimientos sin stock real. Riesgo en disponibilidad y costeo.",
                        "action": "Ajustar inventario fisico y revisar movimientos huerfanos.",
                    })
            except Exception as e:
                findings.append({"severity": "info", "title": f"Error auditando inventario: {e}"})

        if module == "Ventas":
            try:
                # Ordenes en draft con mas de 30 dias
                from datetime import timedelta
                cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
                stale_drafts = self.odoo.count(
                    "sale.order",
                    [("state", "=", "draft"), ("create_date", "<", cutoff)],
                )
                if stale_drafts > 0:
                    findings.append({
                        "severity": "medio",
                        "category": "calidad de datos",
                        "title": f"{stale_drafts} cotizaciones en borrador con +30 dias",
                        "detail": "Cotizaciones viejas distorsionan pipeline y reportes.",
                        "action": "Revisar y cancelar/cerrar cotizaciones obsoletas.",
                    })
            except Exception as e:
                findings.append({"severity": "info", "title": f"Error auditando ventas: {e}"})

        return findings

    # -------- Configuracion --------

    def _audit_configuration(self, module: str, models: list[str]) -> list[dict]:
        findings = []

        if module == "Contabilidad":
            try:
                journals = self.odoo.search_read(
                    "account.journal", [], ["id", "name", "type", "default_account_id"], limit=50
                )
                no_default = [j for j in journals if not j.get("default_account_id")]
                if no_default:
                    findings.append({
                        "severity": "medio",
                        "category": "configuracion",
                        "title": f"{len(no_default)} diarios sin cuenta por defecto",
                        "detail": "Diarios sin default obligan ingreso manual de cuenta en cada asiento.",
                        "action": "Configurar default_account_id en cada diario.",
                        "items": [j["name"] for j in no_default[:10]],
                    })
            except Exception as e:
                findings.append({"severity": "info", "title": f"Error auditando journals: {e}"})

        return findings

    # -------- Automatizaciones --------

    def _audit_automations(self, module: str, models: list[str]) -> list[dict]:
        findings = []
        try:
            # Server actions activas relacionadas a estos modelos
            actions = self.odoo.search_read(
                "ir.actions.server",
                [("model_name", "in", models)],
                ["id", "name", "model_name", "state", "code"],
                limit=50,
            )
            if actions:
                findings.append({
                    "severity": "info",
                    "category": "automatizaciones",
                    "title": f"{len(actions)} server actions configuradas",
                    "detail": "Revisar que sigan vigentes y no tengan codigo legacy.",
                    "items": [{"name": a["name"], "model": a["model_name"]} for a in actions[:10]],
                })

            # Automated actions (base.automation)
            automated = self.odoo.search_read(
                "base.automation",
                [("model_name", "in", models)],
                ["id", "name", "model_name", "active", "trigger"],
                limit=50,
            )
            inactive = [a for a in automated if not a.get("active")]
            if inactive:
                findings.append({
                    "severity": "bajo",
                    "category": "automatizaciones",
                    "title": f"{len(inactive)} automated actions inactivas",
                    "detail": "Reglas configuradas pero apagadas. Revisar si deben eliminarse.",
                    "items": [a["name"] for a in inactive[:10]],
                })
        except Exception as e:
            findings.append({"severity": "info", "title": f"Error auditando automatizaciones: {e}"})

        return findings

    # -------- Eficiencia --------

    def _audit_efficiency(self, module: str, models: list[str]) -> list[dict]:
        findings = []

        if module == "Inventario":
            try:
                # Productos con description_pickingout con HTML (caso conocido)
                with_html = self.odoo.count(
                    "product.template",
                    [("description_pickingout", "ilike", "<br")],
                )
                if with_html > 0:
                    findings.append({
                        "severity": "medio",
                        "category": "eficiencia",
                        "title": f"{with_html} productos con HTML en description_pickingout",
                        "detail": "Las guias de despacho muestran HTML literal en vez de texto limpio.",
                        "action": "Ejecutar limpiar_description_picking.py (ya existe en /odoo).",
                    })
            except Exception:
                pass

        return findings

    # -------- Escalabilidad --------

    def _audit_scalability(self, module: str, models: list[str]) -> list[dict]:
        findings = []
        for model in models:
            try:
                total = self.odoo.count(model, [])
                if total > 100000:
                    findings.append({
                        "severity": "medio",
                        "category": "escalabilidad",
                        "title": f"{model}: {total:,} registros",
                        "detail": "Volumen alto. Validar indices y performance de vistas.",
                        "action": "Revisar campos consultados en reportes vs indices existentes.",
                    })
            except Exception:
                continue
        return findings

    # -------- Resumen --------

    def _summarize(self, findings: dict) -> dict:
        all_findings = []
        for dim in ["data_quality", "configuration", "automations", "efficiency", "scalability"]:
            all_findings.extend(findings.get(dim, []))
        by_severity = {"alto": 0, "medio": 0, "bajo": 0, "info": 0}
        for f in all_findings:
            by_severity[f.get("severity", "info")] = by_severity.get(f.get("severity", "info"), 0) + 1
        return {
            "total_findings": len(all_findings),
            "by_severity": by_severity,
        }
