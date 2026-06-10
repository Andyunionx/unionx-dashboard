"""
Clasifica glosas de líneas de factura → cuenta destino.
Estrategia: 1) Memoria proveedor  2) Claude API  3) Keywords fallback
"""
from __future__ import annotations
import json, os, re
from dataclasses import dataclass
from typing import Optional
from .detector import LineaFactura, FacturaParaDistribuir

CUENTAS_DESTINO = {
    "MARKETING_DIGITAL": {
        "codigo": "42410401", "nombre": "MARKETING DIGITAL", "odoo_id": 1380,
        "descripcion": "Publicidad, always on, banners, campañas, cupones, promociones",
        "keywords": ["always on", "publicidad", "ads ", " ads", "marketing", "promo",
                     "cupon", "cupón", "cupã³n", "descuento", "oferta", "campaign",
                     "banner", "destacado", "sponsored", "pauta", "oportunidades unicas",
                     "acuerdo comercial"],
    },
    "ENVIOS_GRANDES_CUENTA": {
        "codigo": "42410201", "nombre": "ENVIO GRANDES CUENTAS", "odoo_id": 1382,
        "descripcion": "Despacho, envío, flete, última milla, fulfillment",
        "keywords": ["despacho gratis", "despacho", "envio", "envío", "flete",
                     "ultima milla", "última milla", "fulfillment", "courier",
                     "delivery", "transporte", "sdlc", "last mile",
                     "logist", "cobro log"],
    },
    "COMISION_GRANDES_CUENTAS": {
        "codigo": "42410104", "nombre": "COMISIÓN GRANDES CUENTAS", "odoo_id": 1377,
        "descripcion": "Comisión de venta, fee, servicios, fulfillment MKP — mantiene cuenta origen",
        "keywords": ["comision", "comisión", "comisiã³n", "costo fijo",
                     "fee", "cargo adicional", "tasa", "liquidacion", "liquidación",
                     "servicio plataforma", "monthly", "anual", "suscripcion",
                     "membership", "licencia", "mkp comis", "aporte", "aportes",
                     # Fulfillment MKP por categoría de producto
                     "ventas mkp", "devoluciones mkp", ": ventas", ": devoluciones",
                     # Boletas/NC de fulfillment (formato "Boletas (N) del periodo")
                     "del periodo desde", "boletas (", "notas de credito",
                     # Hites: encoding roto de "Comisión"
                     "comisiï¿½n",
                     # Fintoc / Digital Payments
                     "uso api", "fintoc", "iniciaci", "reembolso", "pago anticipado",
                     # Ripley B2B, centralización
                     "cobro uso b2b", "centralizacion", "centralización",
                     # FBR: almacenamiento = comisión (no envíos)
                     "almacenamiento",
                     # Duty Free y otros: acciones comerciales = comisión por venta
                     "acciones comerciales", "accion comercial", "acción comercial"],
    },
}

UMBRAL_CONFIANZA_CLAUDE = 0.70
UMBRAL_CONFIANZA_KEYWORDS = 0.75


@dataclass
class CuentaClasificada:
    line_id: int
    glosa: str
    monto_neto: float
    cuenta_clave: str
    cuenta_codigo: str
    cuenta_nombre: str
    cuenta_odoo_id: int
    confianza: float
    razon: str
    metodo: str
    requiere_aprobacion: bool
    auto_aplicado: bool = False


@dataclass
class ResultadoClasificacion:
    factura: FacturaParaDistribuir
    lineas: list[CuentaClasificada]
    tiene_auto_aplicados: bool = False
    tiene_pendientes_aprobacion: bool = False

    @property
    def total_auto(self) -> int:
        return sum(1 for l in self.lineas if l.auto_aplicado)

    @property
    def total_pendientes(self) -> int:
        return sum(1 for l in self.lineas if l.requiere_aprobacion)


def _keyword_match(glosa: str) -> Optional[tuple[str, float, str]]:
    glosa_lower = glosa.lower()
    mejores: list[tuple[int, str, str, str]] = []
    for clave, info in CUENTAS_DESTINO.items():
        for kw in info["keywords"]:
            if kw in glosa_lower:
                mejores.append((len(kw), info["nombre"], kw, clave))
    if not mejores:
        return None
    mejores.sort(reverse=True)
    _, _, kw_matched, clave = mejores[0]
    return (clave, UMBRAL_CONFIANZA_KEYWORDS, f"Contiene '{kw_matched}'")


def _clasificar_con_claude(lineas: list[LineaFactura], partner_nombre: str) -> list[dict]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []
    try:
        import anthropic
    except ImportError:
        return []

    catalogo = "\n".join(
        f"- {clave}: {info['nombre']}\n  {info['descripcion']}"
        for clave, info in CUENTAS_DESTINO.items()
    )
    items = "\n".join(
        f"#{i} | '{l.glosa}' | ${l.monto_neto:,.0f} CLP"
        for i, l in enumerate(lineas)
    )
    prompt = f"""Clasifica cada línea de factura del proveedor '{partner_nombre}' en la cuenta correcta.

CUENTAS:
{catalogo}

LÍNEAS:
{items}

Responde SOLO con JSON:
{{"clasificaciones": [{{"indice": 0, "cuenta_clave": "COMISION_GRANDES_CUENTAS", "confianza": 0.90, "razon": "..."}}]}}

cuenta_clave debe ser exactamente uno de: MARKETING_DIGITAL, ENVIOS_GRANDES_CUENTA, COMISION_GRANDES_CUENTAS."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(model="claude-opus-4-7", max_tokens=2000,
                                       messages=[{"role": "user", "content": prompt}])
        texto = resp.content[0].text.strip()
        if texto.startswith("```"):
            lines = texto.split("\n")[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            texto = "\n".join(lines)
        return json.loads(texto).get("clasificaciones", [])
    except Exception as e:
        print(f"  ! Error en Claude: {e}")
        return []


def clasificar_factura(
    factura: FacturaParaDistribuir,
    memoria_proveedor: dict = None,
) -> ResultadoClasificacion:
    memoria_proveedor = memoria_proveedor or {}
    reglas_auto = {
        r["patron"]: r
        for r in memoria_proveedor.get("reglas", [])
        if r.get("aprobaciones", 0) >= 3
    }

    lineas_catchall = [l for l in factura.lineas if l.cuenta_actual_id == 1377]

    # 1. Memoria automática
    clasificadas_memo: dict[int, CuentaClasificada] = {}
    for linea in lineas_catchall:
        glosa_lower = linea.glosa.lower()
        for patron, regla in reglas_auto.items():
            if patron in glosa_lower:
                clave = regla["cuenta_destino"]
                info = CUENTAS_DESTINO.get(clave, {})
                clasificadas_memo[linea.line_id] = CuentaClasificada(
                    line_id=linea.line_id, glosa=linea.glosa, monto_neto=linea.monto_neto,
                    cuenta_clave=clave, cuenta_codigo=info.get("codigo", ""),
                    cuenta_nombre=info.get("nombre", ""), cuenta_odoo_id=info.get("odoo_id", 0),
                    confianza=1.0, razon=f"Memoria auto: '{patron}' ({regla['aprobaciones']} aprobaciones)",
                    metodo="memoria", requiere_aprobacion=False, auto_aplicado=True,
                )
                break

    pendientes = [l for l in lineas_catchall if l.line_id not in clasificadas_memo]

    # 2. Claude
    clasificadas_claude: dict[int, CuentaClasificada] = {}
    if pendientes:
        resultados = _clasificar_con_claude(pendientes, factura.partner_nombre)
        for r in resultados:
            idx = r.get("indice", -1)
            if 0 <= idx < len(pendientes):
                linea = pendientes[idx]
                clave = r.get("cuenta_clave", "")
                info = CUENTAS_DESTINO.get(clave, {})
                confianza = float(r.get("confianza", 0.0))
                clasificadas_claude[linea.line_id] = CuentaClasificada(
                    line_id=linea.line_id, glosa=linea.glosa, monto_neto=linea.monto_neto,
                    cuenta_clave=clave, cuenta_codigo=info.get("codigo", ""),
                    cuenta_nombre=info.get("nombre", ""), cuenta_odoo_id=info.get("odoo_id", 0),
                    confianza=confianza, razon=r.get("razon", ""),
                    metodo="claude", requiere_aprobacion=True,
                )

    # 3. Keywords
    pendientes_kw = [l for l in pendientes if l.line_id not in clasificadas_claude]
    clasificadas_kw: dict[int, CuentaClasificada] = {}
    for linea in pendientes_kw:
        match = _keyword_match(linea.glosa)
        if match:
            clave, confianza, razon = match
            info = CUENTAS_DESTINO[clave]
            clasificadas_kw[linea.line_id] = CuentaClasificada(
                line_id=linea.line_id, glosa=linea.glosa, monto_neto=linea.monto_neto,
                cuenta_clave=clave, cuenta_codigo=info["codigo"], cuenta_nombre=info["nombre"],
                cuenta_odoo_id=info["odoo_id"], confianza=confianza, razon=razon,
                metodo="keywords", requiere_aprobacion=True,
            )
        else:
            clasificadas_kw[linea.line_id] = CuentaClasificada(
                line_id=linea.line_id, glosa=linea.glosa, monto_neto=linea.monto_neto,
                cuenta_clave="", cuenta_codigo="",
                cuenta_nombre="⚠️ SIN CLASIFICAR — revisar manualmente",
                cuenta_odoo_id=0, confianza=0.0,
                razon="Glosa no reconocida", metodo="manual", requiere_aprobacion=True,
            )

    todas: list[CuentaClasificada] = []
    for linea in lineas_catchall:
        lid = linea.line_id
        c = clasificadas_memo.get(lid) or clasificadas_claude.get(lid) or clasificadas_kw.get(lid)
        if c:
            todas.append(c)

    return ResultadoClasificacion(
        factura=factura, lineas=todas,
        tiene_auto_aplicados=any(c.auto_aplicado for c in todas),
        tiene_pendientes_aprobacion=any(c.requiere_aprobacion for c in todas),
    )
