"""
Compara libro de compras SII vs Odoo.
Match por RUT + tipo_doc + folio.
NUNCA escribe en Odoo.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from .sii_parser import CompraSII, normalizar_rut

TOLERANCIA_MONTO_CLP = 2.0


@dataclass
class CompraOdoo:
    move_id: int
    name: str
    partner_id: int
    partner_vat: str
    partner_name: str
    tipo_doc_code: str
    folio: str
    fecha: Optional[str]
    monto_neto: float
    monto_iva: float
    monto_total: float
    state: str
    move_type: str

    @property
    def match_key(self) -> str:
        return f"{self.partner_vat}|{self.tipo_doc_code}|{self.folio}"


@dataclass
class DiferenciaMonto:
    match_key: str
    rut: str
    tipo_doc: str
    folio: str
    monto_sii: float
    monto_odoo: float
    delta: float
    odoo_move_id: int


@dataclass
class ResultadoComparacion:
    periodo: str
    total_sii: int = 0
    total_odoo: int = 0
    matches_ok: int = 0
    faltantes_en_odoo: list[CompraSII] = field(default_factory=list)
    solo_en_odoo: list[CompraOdoo] = field(default_factory=list)
    diferencias_monto: list[DiferenciaMonto] = field(default_factory=list)

    def resumen(self) -> dict:
        return {
            "periodo": self.periodo,
            "total_sii": self.total_sii,
            "total_odoo": self.total_odoo,
            "matches_ok": self.matches_ok,
            "faltantes_en_odoo": len(self.faltantes_en_odoo),
            "solo_en_odoo": len(self.solo_en_odoo),
            "diferencias_monto": len(self.diferencias_monto),
            "monto_faltante_clp": sum(c.monto_total for c in self.faltantes_en_odoo),
        }


def _normalizar_compra_odoo(o: dict) -> CompraOdoo:
    vat = (o.get("partner_vat") or "").upper().strip()
    if vat.startswith("CL"):
        vat = vat[2:]
    vat = normalizar_rut(vat)
    return CompraOdoo(
        move_id=o["id"], name=o.get("name") or "",
        partner_id=o.get("partner_id") or 0,
        partner_vat=vat,
        partner_name=o.get("partner_name") or "",
        tipo_doc_code=str(o.get("tipo_doc_code") or ""),
        folio=str(o.get("folio") or ""),
        fecha=o.get("invoice_date"),
        monto_neto=float(o.get("amount_untaxed") or 0.0),
        monto_iva=float(o.get("amount_tax") or 0.0),
        monto_total=float(o.get("amount_total") or 0.0),
        state=o.get("state") or "",
        move_type=o.get("move_type") or "",
    )


def comparar(
    compras_sii: list[CompraSII],
    compras_odoo_raw: list[dict],
    periodo: str,
) -> ResultadoComparacion:
    res = ResultadoComparacion(periodo=periodo)
    res.total_sii  = len(compras_sii)
    res.total_odoo = len(compras_odoo_raw)

    compras_odoo = [_normalizar_compra_odoo(o) for o in compras_odoo_raw]
    sii_by_key  = {c.match_key: c for c in compras_sii}
    odoo_by_key = {c.match_key: c for c in compras_odoo}

    for key, c_sii in sii_by_key.items():
        if key not in odoo_by_key:
            res.faltantes_en_odoo.append(c_sii)

    for key, c_odoo in odoo_by_key.items():
        if key not in sii_by_key:
            res.solo_en_odoo.append(c_odoo)

    for key in sii_by_key.keys() & odoo_by_key.keys():
        c_sii  = sii_by_key[key]
        c_odoo = odoo_by_key[key]
        delta  = abs(c_sii.monto_total - c_odoo.monto_total)
        if delta <= TOLERANCIA_MONTO_CLP:
            res.matches_ok += 1
        else:
            res.diferencias_monto.append(DiferenciaMonto(
                match_key=key, rut=c_sii.rut,
                tipo_doc=c_sii.tipo_doc_nombre, folio=c_sii.folio,
                monto_sii=c_sii.monto_total, monto_odoo=c_odoo.monto_total,
                delta=c_sii.monto_total - c_odoo.monto_total,
                odoo_move_id=c_odoo.move_id,
            ))

    return res
