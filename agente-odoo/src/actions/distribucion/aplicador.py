"""
Lee el Excel aprobado, aplica cambios en Odoo y confirma la factura.
Usa xmlrpc directo para write() ya que execute_kw espera args=[ids, values].
"""
from __future__ import annotations
import xmlrpc.client
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import openpyxl
from .clasificador import CUENTAS_DESTINO
from .memoria import registrar_aprobacion, registrar_correccion

SEP_MARKER = "▼FACTURA"
COL_LINE_ID = 2; COL_GLOSA = 3; COL_CTA_PROP_COD = 6
COL_APROBADO = 12; COL_CTA_CORRECTA = 13; COL_SEP_MOVE_ID = 2
CUENTA_CATCHALL_ID = 1377

CODIGO_A_INFO  = {info["codigo"]: info for info in CUENTAS_DESTINO.values()}
CODIGO_A_CLAVE = {info["codigo"]: clave for clave, info in CUENTAS_DESTINO.items()}


def _odoo_write(client, model: str, ids: list, values: dict) -> bool:
    uid = client.authenticate()
    models = xmlrpc.client.ServerProxy(
        f"{client.url}/xmlrpc/2/object", allow_none=True,
        transport=xmlrpc.client.SafeTransport())
    return models.execute_kw(client.db, uid, client.password,
                              model, "write", [ids, values], {})


def _odoo_action_post(client, move_id: int) -> dict:
    uid = client.authenticate()
    models = xmlrpc.client.ServerProxy(
        f"{client.url}/xmlrpc/2/object", allow_none=True,
        transport=xmlrpc.client.SafeTransport())
    return models.execute_kw(client.db, uid, client.password,
                              "account.move", "action_post", [[move_id]], {})


@dataclass
class LineaAplicada:
    line_id: int; glosa: str; cuenta_final_codigo: str
    cuenta_final_odoo_id: int; fue_corregida: bool; cambio_cuenta: bool


@dataclass
class FacturaAplicada:
    move_id: int
    lineas: list[LineaAplicada] = field(default_factory=list)
    confirmada: bool = False
    errores: list[str] = field(default_factory=list)


@dataclass
class ResultadoAplicacion:
    facturas: list[FacturaAplicada] = field(default_factory=list)
    errores_globales: list[str] = field(default_factory=list)
    dry_run: bool = True
    partner_rut: Optional[str] = None
    partner_nombre: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not self.errores_globales and all(not f.errores for f in self.facturas)

    @property
    def total_lineas(self) -> int:
        return sum(len(f.lineas) for f in self.facturas)


def _is_posted_error(e) -> bool:
    s = str(e)
    return "solo lectura" in s or "read-only" in s.lower() or "publicado" in s


def _leer_excel(ruta) -> tuple[list[dict], str, str]:
    wb = openpyxl.load_workbook(ruta); ws = wb["Propuesta"]
    bloques = []; bloque_actual = None
    for row in ws.iter_rows(min_row=1, values_only=True):
        if row[0] is None:
            continue
        marker = str(row[0] or "").strip()
        if marker == SEP_MARKER:
            if bloque_actual:
                bloques.append(bloque_actual)
            try:
                move_id = int(row[COL_SEP_MOVE_ID - 1])
            except (TypeError, ValueError):
                move_id = 0
            bloque_actual = {"move_id": move_id, "lineas": []}
            continue
        if bloque_actual is None:
            continue
        try:
            line_id = int(row[COL_LINE_ID - 1])
        except (TypeError, ValueError):
            continue
        glosa = str(row[COL_GLOSA - 1] or "").strip()
        aprobado_raw = str(row[COL_APROBADO - 1] or "").strip().upper()
        cuenta_prop = str(row[COL_CTA_PROP_COD - 1] or "").strip()
        cuenta_corr = str(row[COL_CTA_CORRECTA - 1] or "").strip()
        if aprobado_raw not in ("SI", "SÍ", "S", "NO"):
            continue
        aprobado = aprobado_raw in ("SI", "SÍ", "S")
        cuenta_final = cuenta_prop if aprobado else cuenta_corr
        fue_corregida = not aprobado
        info = CODIGO_A_INFO.get(cuenta_final, {})
        odoo_id = info.get("odoo_id", 0)
        cambio = (odoo_id != CUENTA_CATCHALL_ID and odoo_id != 0)
        bloque_actual["lineas"].append(LineaAplicada(
            line_id=line_id, glosa=glosa, cuenta_final_codigo=cuenta_final,
            cuenta_final_odoo_id=odoo_id, fue_corregida=fue_corregida, cambio_cuenta=cambio))
    if bloque_actual:
        bloques.append(bloque_actual)
    return bloques, "", ""


def _aplicar_bloque(odoo_client, move_id, lineas, dry_run):
    fa = FacturaAplicada(move_id=move_id)
    lineas_a_cambiar = [l for l in lineas if l.cambio_cuenta and l.cuenta_final_odoo_id]
    for l in lineas:
        if l.cambio_cuenta:
            print(f"    → Línea {l.line_id}: → {l.cuenta_final_codigo}")
        else:
            print(f"    ≡ Línea {l.line_id}: mantiene 42410104")
        fa.lineas.append(l)

    if lineas_a_cambiar:
        orm_commands = [(1, l.line_id, {"account_id": l.cuenta_final_odoo_id})
                        for l in lineas_a_cambiar]
        if not dry_run:
            try:
                _odoo_write(odoo_client, "account.move", [move_id], {"line_ids": orm_commands})
                for l in lineas_a_cambiar:
                    print(f"    ✓ Línea {l.line_id}: → {l.cuenta_final_odoo_id} ({l.cuenta_final_codigo})")
            except Exception as e:
                if _is_posted_error(e):
                    print(f"    ℹ️  Factura {move_id} ya fue procesada (posted) — skip")
                    fa.confirmada = True
                else:
                    msg = f"Error escribiendo en factura {move_id}: {e}"
                    print(f"    ✗ {msg}"); fa.errores.append(msg)
        else:
            for l in lineas_a_cambiar:
                print(f"    [DRY] Línea {l.line_id}: → {l.cuenta_final_codigo}")

    if fa.confirmada:
        print(f"    ℹ️  Factura {move_id} ya estaba confirmada — nada que hacer")
    elif fa.errores:
        print(f"    ⚠️  Factura {move_id} NO confirmada por errores")
    elif move_id:
        if not dry_run:
            try:
                _odoo_action_post(odoo_client, move_id)
                fa.confirmada = True
                print(f"    ✓ Factura {move_id} CONFIRMADA (posted)")
            except Exception as e:
                if _is_posted_error(e):
                    fa.confirmada = True
                    print(f"    ℹ️  Factura {move_id} ya estaba confirmada")
                else:
                    msg = f"Error confirmando {move_id}: {e}"
                    print(f"    ✗ {msg}"); fa.errores.append(msg)
        else:
            fa.confirmada = True
            print(f"    [DRY] Factura {move_id} sería confirmada")
    return fa


def aplicar_distribucion(odoo_client, ruta_excel, aprobado_por="analista@unionx.cl",
                          dry_run=True, directorio_memoria=None) -> ResultadoAplicacion:
    dir_memo = Path(directorio_memoria) if directorio_memoria else None
    bloques, rut, nombre = _leer_excel(ruta_excel)
    resultado = ResultadoAplicacion(dry_run=dry_run, partner_rut=rut, partner_nombre=nombre)
    if not bloques:
        resultado.errores_globales.append("El Excel no tiene bloques de factura válidos.")
        return resultado

    for bloque in bloques:
        move_id = bloque["move_id"]; lineas = bloque["lineas"]
        if not lineas:
            continue
        print(f"  Factura move_id={move_id} | {len(lineas)} línea(s)")
        fa = _aplicar_bloque(odoo_client, move_id, lineas, dry_run)
        resultado.facturas.append(fa)
        if dir_memo and rut:
            for linea in fa.lineas:
                clave = CODIGO_A_CLAVE.get(linea.cuenta_final_codigo, "")
                if linea.fue_corregida:
                    registrar_correccion(rut, nombre, linea.glosa, clave, aprobado_por, dir_memo)
                else:
                    registrar_aprobacion(rut, nombre, linea.glosa, clave, aprobado_por, dir_memo)
    return resultado


def aplicar_directo(odoo_client, resultado_clasificacion, dry_run=True) -> FacturaAplicada:
    factura = resultado_clasificacion.factura
    move_id = factura.move_id
    print(f"  [{factura.name}] {factura.partner_nombre} | ${factura.monto_total:,.0f}")

    lineas_cl = resultado_clasificacion.lineas
    lineas_ap = []
    for linea_cl in lineas_cl:
        odoo_id = linea_cl.cuenta_odoo_id
        cambio = (odoo_id != 0 and odoo_id != CUENTA_CATCHALL_ID)
        la = LineaAplicada(line_id=linea_cl.line_id, glosa=linea_cl.glosa,
                            cuenta_final_codigo=linea_cl.cuenta_codigo,
                            cuenta_final_odoo_id=odoo_id, fue_corregida=False,
                            cambio_cuenta=cambio)
        cuenta_label = linea_cl.cuenta_codigo or "sin clasificar → 42410104"
        if cambio:
            print(f"    → Línea {linea_cl.line_id}: {linea_cl.cuenta_codigo} ({linea_cl.cuenta_nombre})")
        else:
            print(f"    ≡ Línea {linea_cl.line_id}: mantiene 42410104 ({cuenta_label})")
        lineas_ap.append(la)

    fa = FacturaAplicada(move_id=move_id, lineas=lineas_ap)
    lineas_a_cambiar = [l for l in lineas_ap if l.cambio_cuenta]

    if lineas_a_cambiar:
        orm_commands = [(1, l.line_id, {"account_id": l.cuenta_final_odoo_id})
                        for l in lineas_a_cambiar]
        if not dry_run:
            try:
                _odoo_write(odoo_client, "account.move", [move_id], {"line_ids": orm_commands})
                for l in lineas_a_cambiar:
                    print(f"    ✓ Línea {l.line_id}: → {l.cuenta_final_odoo_id} ({l.cuenta_final_codigo})")
            except Exception as e:
                if _is_posted_error(e):
                    print(f"    ℹ️  Factura {move_id} ya fue procesada (posted) — skip")
                    fa.confirmada = True
                else:
                    msg = f"Error escribiendo en factura {move_id}: {e}"
                    print(f"    ✗ {msg}"); fa.errores.append(msg)
        else:
            for l in lineas_a_cambiar:
                print(f"    [DRY] Línea {l.line_id}: → {l.cuenta_final_odoo_id} ({l.cuenta_final_codigo})")

    if fa.confirmada:
        print(f"    ℹ️  Factura {move_id} ya estaba confirmada — nada que hacer")
    elif fa.errores:
        print(f"    ⚠️  Factura {move_id} NO confirmada por errores")
    else:
        if not dry_run:
            try:
                _odoo_action_post(odoo_client, move_id)
                fa.confirmada = True
                print(f"    ✓ Factura {move_id} CONFIRMADA (posted)")
            except Exception as e:
                if _is_posted_error(e):
                    fa.confirmada = True
                    print(f"    ℹ️  Factura {move_id} ya estaba confirmada")
                else:
                    msg = f"Error confirmando {move_id}: {e}"
                    print(f"    ✗ {msg}"); fa.errores.append(msg)
        else:
            fa.confirmada = True
            print(f"    [DRY] Factura {move_id} sería confirmada")
    return fa
