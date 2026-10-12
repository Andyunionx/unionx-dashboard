"""Excel de la evaluación de un producto, 100% con fórmulas (regla de Andrés: hoja Supuestos + fórmulas, nunca valores
pegados). Replica motor.py celda a celda; el validador (validar_excel.py) recalcula el libro y lo compara con Python.

Hojas: Resumen · Producto (datos editables) · Supuestos (parámetros editables) · Costeo · Canales · ROI (3 escenarios) ·
Sensibilidad · Flujo (lote mes a mes, 3 escenarios) · Radar (datos de la competencia) · Léeme.
Lo único que no es fórmula: el precio de compra objetivo y el lote sugerido (búsqueda numérica del motor; el libro
permite comprobarlos poniendo ese precio en Producto).
"""
from __future__ import annotations

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L
from openpyxl.workbook.defined_name import DefinedName

from motor import CANAL_TXT, CANALES

AZUL, VERDE, GRIS, AMARILLO = "1F3864", "1E6B5C", "595959", "FFF2CC"
BORDE = Border(*(Side(style="thin", color="D0D7DE"),) * 4)
CLP, USD, PCT, X2, N0, N2 = '"$"#,##0', '"US$"#,##0.00', "0.0%", '0.00"x"', "#,##0", "#,##0.00"
MAX_MES = 65


class Hoja:
    """Escribe filas 'etiqueta | valor | unidad | fuente' y registra nombres definidos."""

    def __init__(self, wb, titulo, anchos=(44, 18, 12, 70)):
        self.wb, self.ws, self.r = wb, wb.create_sheet(titulo), 1
        for i, w in enumerate(anchos, 1):
            self.ws.column_dimensions[L(i)].width = w

    def titulo(self, txt, color=AZUL):
        c = self.ws.cell(self.r, 1, txt)
        c.font = Font(bold=True, color="FFFFFF", size=11)
        for j in range(1, 5):
            self.ws.cell(self.r, j).fill = PatternFill("solid", fgColor=color)
        self.r += 1

    def fila(self, etiqueta, valor, nombre=None, fmt=None, unidad="", fuente="", entrada=False):
        ws = self.ws
        ws.cell(self.r, 1, etiqueta)
        c = ws.cell(self.r, 2, valor)
        if fmt:
            c.number_format = fmt
        if entrada:
            c.fill = PatternFill("solid", fgColor=AMARILLO)
            c.font = Font(bold=True, color=AZUL)
        ws.cell(self.r, 3, unidad)
        ws.cell(self.r, 4, fuente).alignment = Alignment(wrap_text=False)
        for j in range(1, 5):
            ws.cell(self.r, j).border = BORDE
        if nombre:
            self.wb.defined_names[nombre] = DefinedName(nombre, attr_text=f"'{ws.title}'!$B${self.r}")
        self.r += 1
        return f"'{ws.title}'!$B${self.r - 1}"

    def blanco(self):
        self.r += 1


def armar(r: dict, par: dict, salida) -> None:
    p, rad = r["producto"], r["radar"]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    res = Hoja(wb, "Resumen", (46, 22, 22, 22, 50))

    # ── Producto (entradas) ──────────────────────────────────────────────────
    pr = Hoja(wb, "Producto")
    pr.titulo("Producto y cotización (celdas amarillas: editables)")
    e = lambda *a, **k: pr.fila(*a, entrada=True, **k)
    pr.fila("Producto", p.get("nombre", ""), "NOMBRE")
    pr.fila("Fábrica", p.get("fabrica", ""))
    e("Precio de compra unitario", p["precio_usd"], "PRECIO_USD", USD, "USD", f"incoterm {p['incoterm']}")
    e("Incoterm FOB (1) / EXW (0)", 1 if str(p["incoterm"]).upper() == "FOB" else 0, "INCOTERM_FOB", N0, "", "FOB: sin local charge")
    e("Compra vía Steven (1 = sí)", 1 if p["via_steven"] else 0, "VIA_STEVEN", N0, "", "3% de comisión sobre P×Q + local charge")
    e("Unidades del lote", p["qty"], "QTY", N0, "u")
    e("Unidades por caja master", p["uds_ctn"], "UDS_CTN", N0, "u")
    e("Volumen de la caja master", p["cbm_ctn"], "CBM_CTN", "0.0000", "m³")
    e("Modalidad (Consolidado / Contenedor propio / LCL)", p["modalidad"], "MODALIDAD")
    e("Flete por contenedor 40HQ", p["flete_contenedor_usd"], "FLETE_CONT", USD, "USD", f"puerto {p['puerto']}")
    e("Flete LCL todo incluido", p.get("flete_lcl_m3") or 0, "FLETE_LCL_M3", USD, "USD/m³", "solo si la modalidad es LCL")
    e("Tránsito puerto origen → San Antonio", par["transito_dias"].get(p["puerto"], par["transito_dias"]["Otro"]), "TRANSITO", N0, "días",
      f"{p['puerto']} (tabla de puertos en Supuestos)")
    e("Producción", p["lt_produccion"], "LT_PROD", N0, "días")
    e("Anticipo a fábrica", p["anticipo_pct"], "ANTICIPO", PCT)
    e("Saldo pagado en origen (1) / en Chile (0)", 1 if p["saldo_en"] == "Origen" else 0, "SALDO_ORIGEN", N0)
    pr.blanco()
    pr.titulo("Venta")
    e("Precio de lista con IVA", p["pvp_iva"], "PVP_IVA", CLP, "CLP")
    e("Descuento promedio sobre lista", p["descuento"], "DESCUENTO", PCT, "", "eventos, promociones")
    e("Velocidad de venta", p["velocidad_mes"], "VELOCIDAD", N2, "u/mes")
    for c in CANALES:
        e(f"Mix {CANAL_TXT[c]}", p["mix"][c], f"MIX_{c.upper()}", PCT)
    pr.fila("Control: el mix suma", "=MIX_MKP+MIX_WEB+MIX_FID+MIX_B2B", None, PCT, "", "debe ser 100%")
    e("Precio B2B / precio de lista neto", p["factor_precio_b2b"], "FACTOR_B2B", PCT)
    for c in CANALES:
        e(f"Comisión {CANAL_TXT[c].lower()}", p[f"com_{c}"], f"COM_{c.upper()}", PCT, "", "RAW de ventas: real de la categoría")
        e(f"Logística {CANAL_TXT[c].lower()}", p[f"log_{c}"], f"LOG_{c.upper()}", PCT)
    e("Devoluciones (% de unidades)", p["dev_pct"], "DEV_PCT", PCT)
    e("Marketing (lineal, no aplica a B2B)", p["marketing_pct"], "MKT", PCT, "", "decisión Andrés 9-oct")
    pr.blanco()
    pr.titulo("Del motor (no editables)", GRIS)
    radar_ok = 1 if (rad.get("disponible") and not r["bloqueo_competencia"]
                     and not any("velocidad de venta es un supuesto" in x for x in r.get("alertas", []))) else 0
    pr.fila("Radar disponible, sin bloqueo y velocidad confirmada (1/0)", radar_ok, "RADAR_OK", N0, "", "condición para COMPRAR")
    pr.fila("Guerra de precios (1/0)", 1 if r["guerra_precios"] else 0, "GUERRA", N0, "", "competidor ≥ 5× nuestro volumen → conservador con precio −15%")
    pr.fila("Contribución de referencia de la categoría", r["benchmark_contrib_pct"], "BENCH", PCT, "", f"{p['categoria_ref']} (ROI por producto)")
    pr.fila("Precio de compra objetivo (motor)", r["fob_objetivo_usd"], "FOB_OBJ", USD, "USD", "máximo con EVA conservador ≥ 0 y contribución ≥ categoría")
    pr.fila("PVP ideal con IVA (motor)", r.get("pvp_ideal"), "PVP_IDEAL", CLP, "CLP", "mínimo con este costo para la misma meta")
    pr.fila("Modo de la evaluación", {"completo": "Costo y PVP dados", "precio_objetivo": "Solo costo → PVP ideal",
                                      "costo_objetivo": "Solo PVP → costo máximo"}.get(r.get("modo"), ""), "MODO")

    # ── Supuestos ────────────────────────────────────────────────────────────
    su = Hoja(wb, "Supuestos")
    su.titulo("Supuestos (editables; fuente de cada uno en la columna D)")
    s = lambda *a, **k: su.fila(*a, entrada=True, **k)
    s("Dólar", par["tc"], "TC", N2, "CLP/USD", "dólar observado del día")
    s("IVA", par["iva"], "IVA", PCT)
    s("Comisión Steven", par["comision_steven"], "COM_STEVEN", PCT, "", "costeo COMEX")
    s("Local charge + long vehicle por contenedor", par["local_charge_contenedor"], "LOCAL_CONT", USD, "USD", "mediana últimos 12 precosteos")
    s("Form F", par["form_f"], "FORM_F", USD, "USD/embarque")
    s("Capacidad 40HQ", par["capacidad_40hq_m3"], "CAP_40HQ", N0, "m³")
    s("Gastos Chile por contenedor", par["gastos_chile_contenedor"], "GASTOS_CONT", CLP, "CLP", "costeo COMEX")
    s("Gastos Chile por embarque LCL", par["gastos_chile_lcl"], "GASTOS_LCL", CLP, "CLP", "1 solo caso (25TP0124)")
    s("Agente de aduana", par["agente_aduana_pct"], "AGENTE", "0.00%", "", "sobre CIF")
    s("Arancel", p["arancel_pct"], "ARANCEL", PCT, "", "0% con certificado de origen; 6% sin")
    s("Seguro", p["seguro_pct"], "SEGURO", PCT, "", "sobre P×Q + China")
    for puerto, d in par["transito_dias"].items():
        su.fila(f"Tránsito {puerto}", d, None, N0, "días", "ROI por producto")
    s("Aduana", par["aduana_dias"], "ADUANA_DIAS", N0, "días")
    s("Crédito flete e internación", par["credito_flete_dias"], "CRED_DIAS", N0, "días")
    s("Días de cobro", par["dias_cobro"], "DIAS_COBRO", N2, "días", "CxC / venta con IVA")
    s("Recupero del IVA de importación", par["iva_recupero_meses"], "IVA_REC", N0, "meses")
    s("Costo de capital", par["tasa_capital"], "TASA_CAP", PCT, "", "ROI por producto")
    s("Almacenaje", par["almacenaje_m3_anio"], "ALMAC", CLP, "CLP/m³·año", "ROI (pool de espacio)")
    s("Manipulación", par["manipulacion_u"], "MANIP_U", CLP, "CLP/u B2C", "ROI (pool de manipulación)")
    s("Peso de la manipulación por caja", par["peso_b2b_manip"], "PESO_B2B", N2, "", "ABC: la unidad B2B cuesta 53% de una B2C")
    s("Unidades por caja promedio (B2B)", par["uds_caja_prom_b2b"], "UCP", N2, "u")
    s("Insumos", par["insumos_pedido"], "INS_PED", CLP, "CLP/pedido")
    s("Unidades por pedido", par["uds_por_pedido"], "UPP", N2, "u")
    s("Postventa", par["postventa_u_devuelta"], "PV_DEV", CLP, "CLP/u devuelta")
    s("Marketplace por fulfillment", par["fulfillment_share_mkp"], "FF_SHARE", PCT, "", "se manipula por caja")
    s("Stock promedio / lote", par["inventario_prom_factor"], "INV_FACTOR", PCT)
    s("Meses máximos de venta del lote", 60, "MAX_MESES", N0, "meses")
    for nom, k in (("conservador", "CONS"), ("optimista", "OPT")):
        es = par["escenarios"][nom]
        s(f"Escenario {nom}: velocidad", es["vel"], f"VEL_{k}", PCT)
        s(f"Escenario {nom}: precio", es["precio"], f"PRECIO_{k}", PCT)
        s(f"Escenario {nom}: dólar", es["tc"], f"TC_{k}", PCT)
    s("Escenario optimista sin descuento (1/0)", 1, "SINDESC_OPT", N0)
    s("Umbral contra la competencia", par["umbral_competencia"], "UMBRAL", PCT)

    # ── Costeo ───────────────────────────────────────────────────────────────
    co = Hoja(wb, "Costeo")
    co.titulo("Costo internado del lote (mismo cálculo que el precosteo COMEX)")
    f = co.fila
    f("Cajas", "=ROUNDUP(QTY/UDS_CTN,0)", "CAJAS", N0, "cajas")
    f("Volumen", "=CAJAS*CBM_CTN", "CBM", N2, "m³")
    f("Contenedores propios", '=IF(MODALIDAD="Contenedor propio",ROUNDUP(CBM/CAP_40HQ,0),0)', "N_CONT", N0)
    f("Fracción de contenedor que paga", '=IF(MODALIDAD="LCL",0,IF(MODALIDAD="Contenedor propio",N_CONT,CBM/CAP_40HQ))', "FRAC", N2, "", "consolidado: su parte por CBM")
    f("Fábrica (P×Q)", "=QTY*PRECIO_USD", "PXQ", USD, "USD")
    f("Local charge", '=IF(OR(MODALIDAD="LCL",INCOTERM_FOB=1),0,LOCAL_CONT*FRAC)', "LOCAL", USD, "USD")
    f("Form F", '=IF(MODALIDAD="LCL",FORM_F,FORM_F*FRAC)', "FF", USD, "USD")
    f("Comisión Steven", "=IF(VIA_STEVEN=1,COM_STEVEN*(PXQ+LOCAL),0)", "COMIS", USD, "USD")
    f("Inland China (comisión + local + Form F)", "=COMIS+LOCAL+FF", "CHINA", USD, "USD")
    f("Flete", '=IF(MODALIDAD="LCL",FLETE_LCL_M3*CBM,FLETE_CONT*FRAC)', "FLETE", USD, "USD")
    f("Seguro", "=SEGURO*(PXQ+CHINA)", "SEG", USD, "USD")
    f("CIF", "=PXQ+CHINA+FLETE+SEG", "CIF", USD, "USD")
    f("Arancel", "=ARANCEL*CIF", "ARANC", USD, "USD")
    f("Agente de aduana", "=AGENTE*CIF", "AGT", USD, "USD")
    f("Gastos Chile", '=IF(MODALIDAD="LCL",GASTOS_LCL,GASTOS_CONT*FRAC)', "GASTOS", CLP, "CLP")
    f("COSTO INTERNADO DEL LOTE", "=(CIF+ARANC+AGT)*TC+GASTOS", "INTERNADO", CLP, "CLP")
    f("Costo internado unitario", "=INTERNADO/QTY", "COSTO_U", CLP, "CLP/u")
    f("Costo internado unitario (USD)", "=COSTO_U/TC", None, USD, "USD/u")
    f("Sobrecosto sobre P×Q", "=INTERNADO/(PXQ*TC)-1", None, PCT)
    f("IVA de importación (crédito fiscal: caja, no costo)", "=IVA*(CIF+ARANC)*TC", "IVA_IMP", CLP, "CLP")
    f("FOB China por unidad", "=(PXQ+CHINA)/QTY", "FOB_CHINA_U", USD, "USD/u", "comparable con el FOB de la DIN")
    f("Volumen por unidad", "=CBM_CTN/UDS_CTN", "M3_U", "0.00000", "m³/u")

    # ── Canales ──────────────────────────────────────────────────────────────
    ws = wb.create_sheet("Canales")
    cab = ["Canal", "Mix", "Precio neto", "Comisión", "Envío", "Marketing", "Canal $/u", "Manipulación", "Insumos", "Postventa", "Operación $/u"]
    for j, t in enumerate(cab, 1):
        c = ws.cell(1, j, t)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        ws.column_dimensions[L(j)].width = 16
    ws.column_dimensions["A"].width = 16
    filas_c = {"mkp": ("MIX_MKP", "PRECIO_BASE", "COM_MKP", "LOG_MKP", "MKT", "(1-FF_SHARE)*MANIP_U+FF_SHARE*MANIP_CAJA", "(1-FF_SHARE)*INS_PED_U", "PV_U"),
               "web": ("MIX_WEB", "PRECIO_BASE", "COM_WEB", "LOG_WEB", "MKT", "MANIP_U", "INS_PED_U", "PV_U"),
               "fid": ("MIX_FID", "PRECIO_BASE", "COM_FID", "LOG_FID", "MKT", "MANIP_U", "INS_PED_U", "PV_U"),
               "b2b": ("MIX_B2B", "PRECIO_BASE*FACTOR_B2B", "COM_B2B", "LOG_B2B", "0", "MANIP_CAJA", "0", "0")}
    for i, c in enumerate(CANALES, 2):
        mix, pre, com, log, mkt, man, ins, pv = filas_c[c]
        vals = [CANAL_TXT[c], f"={mix}", f"={pre}", f"={com}", f"={log}", f"={mkt}", f"=C{i}*(D{i}+E{i}+F{i})", f"={man}", f"={ins}", f"={pv}", f"=H{i}+I{i}+J{i}"]
        for j, v in enumerate(vals, 1):
            cell = ws.cell(i, j, v)
            cell.number_format = PCT if j in (2, 4, 5, 6) else CLP
            cell.border = BORDE
    aux = [("Precio de lista neto", "=PVP_IVA/(1+IVA)", "LISTA_NETA"), ("Precio base (lista − descuento)", "=LISTA_NETA*(1-DESCUENTO)", "PRECIO_BASE"),
           ("Manipulación por unidad que va en caja", "=MANIP_U*PESO_B2B*UCP/UDS_CTN", "MANIP_CAJA"), ("Insumos por unidad", "=INS_PED/UPP", "INS_PED_U"),
           ("Postventa por unidad vendida", "=DEV_PCT*PV_DEV", "PV_U"), ("PRECIO NETO PROMEDIO", "=SUMPRODUCT(B2:B5,C2:C5)", "PRECIO_PROM"),
           ("Costo de canal promedio $/u", "=SUMPRODUCT(B2:B5,G2:G5)", "CANAL_U"), ("Operación promedio $/u", "=SUMPRODUCT(B2:B5,K2:K5)", "OPER_U")]
    for k, (t, fo, nm) in enumerate(aux, 8):
        ws.cell(k, 1, t)
        c = ws.cell(k, 3, fo)
        c.number_format = CLP
        wb.defined_names[nm] = DefinedName(nm, attr_text=f"'Canales'!$C${k}")
    ws.column_dimensions["A"].width = 38

    # ── ROI: 3 escenarios ────────────────────────────────────────────────────
    ws = wb.create_sheet("ROI")
    ws.column_dimensions["A"].width = 46
    for j, t in enumerate(("Conservador", "Base", "Optimista"), 2):
        c = ws.cell(1, j, t)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        ws.column_dimensions[L(j)].width = 20
    esc_in = {"vel": ("VEL_CONS", "1", "VEL_OPT"), "pre": ("IF(GUERRA=1,0.85,PRECIO_CONS)", "1", "PRECIO_OPT"),
              "tc": ("TC_CONS", "1", "TC_OPT"), "sd": ("0", "0", "SINDESC_OPT")}
    filas_r = [("vel", "Multiplicador de velocidad", None, PCT), ("pre", "Multiplicador de precio", None, PCT), ("tc", "Multiplicador del dólar", None, PCT),
               ("sd", "Sin descuento (1/0)", None, N0),
               ("tce", "Dólar", "=TC*{tc}", N2), ("ratio", "Precio vs base", "={pre}*IF({sd}=1,1/(1-DESCUENTO),1)", N2),
               ("velm", "Velocidad (u/mes)", "=VELOCIDAD*{vel}", N2), ("u", "Unidades al año", "={velm}*12", N0),
               ("pp", "Precio neto promedio", "=PRECIO_PROM*{ratio}", CLP), ("cu", "Costo internado unitario", "=((CIF+ARANC+AGT)*{tce}+GASTOS)/QTY", CLP),
               ("v", "Venta anual", "={u}*{pp}", CLP), ("c", "Costo de venta", "={u}*{cu}", CLP),
               ("can", "Comisión + envío + marketing", "={u}*CANAL_U*{ratio}", CLP), ("op", "Manipulación + insumos + postventa", "={u}*OPER_U", CLP),
               ("alm", "Almacenaje", "=INV_FACTOR*QTY*M3_U*ALMAC", CLP), ("ctr", "CONTRIBUCIÓN", "={v}-{c}-{can}-{op}-{alm}", CLP),
               ("cp", "Contribución % de la venta", "=IF({v}>0,{ctr}/{v},0)", PCT), ("cd", "Costo diario", "={c}/365", CLP),
               ("fd", "FOB diario", "=MIN({u}*PRECIO_USD*{tce}/365,{cd})", CLP), ("ka", "Capital: anticipo en producción", "=ANTICIPO*{fd}*LT_PROD", CLP),
               ("kt", "Capital: pagado en tránsito + aduana", "=IF(SALDO_ORIGEN=1,1,ANTICIPO)*{fd}*TRANSITO+{fd}*ADUANA_DIAS", CLP),
               ("kb", "Capital: inventario promedio", "=INV_FACTOR*QTY*{cu}", CLP), ("kc", "Capital: cuentas por cobrar", "={v}/365*DIAS_COBRO", CLP),
               ("cr", "Crédito de flete e internación", "=MAX({cd}-{fd},0)*MAX(0,CRED_DIAS-ADUANA_DIAS)", CLP),
               ("cap", "CAPITAL EMPLEADO", "=MAX({ka}+{kt}+{kb}+{kc}-{cr},0)", CLP), ("eva", "EVA (contribución − costo de capital)", "={ctr}-TASA_CAP*{cap}", CLP),
               ("roi", "ROI sobre capital", '=IF({cap}>0,{ctr}/{cap},"")', X2), ("gm", "GMROI", '=IF({kb}>0,({v}-{c})/{kb},"")', X2),
               ("rot", "Rotación del inventario", '=IF({kb}>0,{c}/{kb},"")', X2)]
    pos = {k: i for i, (k, *_) in enumerate(filas_r, 2)}
    for k, t, fo, fmt in filas_r:
        i = pos[k]
        ws.cell(i, 1, t).font = Font(bold=t.isupper())
        for j in range(3):
            col = L(j + 2)
            ref = {kk: f"{col}{pos[kk]}" for kk in pos}
            val = f"={esc_in[k][j]}" if k in esc_in else fo.format(**ref)
            c = ws.cell(i, j + 2, val)
            c.number_format = fmt
            c.border = BORDE
    for nm, k, j in (("EVA_CONS", "eva", 0), ("EVA_BASE", "eva", 1), ("CTR_BASE", "ctr", 1), ("CPCT_BASE", "cp", 1)):
        wb.defined_names[nm] = DefinedName(nm, attr_text=f"'ROI'!${L(j + 2)}${pos[k]}")
    roi_pos = pos

    # ── Sensibilidad ─────────────────────────────────────────────────────────
    ws = wb.create_sheet("Sensibilidad")
    cab = ["Caso", "Dólar ×", "Flete ×", "Precio ×", "Costo internado/u", "Precio neto", "Contribución/u", "%"]
    for j, t in enumerate(cab, 1):
        c = ws.cell(1, j, t)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        ws.column_dimensions[L(j)].width = 16
    ws.column_dimensions["A"].width = 46
    casos = [("Base", 1, 1, 1), ("Dólar +10%", 1.1, 1, 1), ("Dólar −10%", 0.9, 1, 1), ("Flete +30%", 1, 1.3, 1), ("Flete −30%", 1, 0.7, 1),
             ("Precio de venta −10%", 1, 1, 0.9), ("Pesimista (dólar +10%, flete +30%, precio −10%)", 1.1, 1.3, 0.9)]
    for i, (n, tm, fm, pm) in enumerate(casos, 2):
        vals = [n, tm, fm, pm, f"=((PXQ+CHINA+FLETE*C{i}+SEG)*(1+ARANCEL+AGENTE)*TC*B{i}+GASTOS)/QTY", f"=PRECIO_PROM*D{i}",
                f"=F{i}-E{i}-CANAL_U*D{i}-OPER_U-INV_FACTOR*QTY*M3_U*ALMAC/(VELOCIDAD*12)", f"=IF(F{i}>0,G{i}/F{i},0)"]
        for j, v in enumerate(vals, 1):
            c = ws.cell(i, j, v)
            c.number_format = N2 if j in (2, 3, 4) else (PCT if j == 8 else CLP)
            c.border = BORDE
            if j in (2, 3, 4):
                c.fill = PatternFill("solid", fgColor=AMARILLO)

    # ── Flujo del lote (3 bloques) ───────────────────────────────────────────
    ws = wb.create_sheet("Flujo")
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 18
    c0 = 3                                                     # columna del mes 0
    meses = range(MAX_MES + 1)
    fl_pos = {}
    r0 = 1
    for j, (nom, col_roi) in enumerate((("Conservador", "B"), ("Base", "C"), ("Optimista", "D"))):
        rr = lambda k: f"'ROI'!${col_roi}${roi_pos[k]}"
        cst = [("tce", "Dólar", f"={rr('tce')}", N2), ("ratio", "Precio vs base", f"={rr('ratio')}", N2), ("velm", "Velocidad (u/mes)", f"={rr('velm')}", N2),
               ("pxq", "Fábrica en CLP", "=PXQ*{tce}", CLP), ("china", "Inland China en CLP", "=CHINA*{tce}", CLP),
               ("aran", "Arancel en CLP", "=ARANC*{tce}", CLP), ("cred", "Flete + seguro + agente + gastos Chile", "=(FLETE+SEG+AGT)*{tce}+GASTOS", CLP),
               ("ivai", "IVA de importación", "=IVA*(CIF+ARANC)*{tce}", CLP), ("netou", "Cobro neto por unidad", "=(PRECIO_PROM-CANAL_U)*{ratio}", CLP),
               ("cu", "Costo internado unitario", f"={rr('cu')}", CLP), ("inv", "Inversión (costo internado del lote)", "=(CIF+ARANC+AGT)*{tce}+GASTOS", CLP),
               ("memb", "Mes de embarque", "=ROUND(LT_PROD/30,0)", N0), ("mlleg", "Mes de llegada", "=ROUND((LT_PROD+TRANSITO)/30,0)", N0),
               ("mdisp", "Mes disponible para venta", "=ROUND((LT_PROD+TRANSITO+ADUANA_DIAS)/30,0)", N0), ("lag", "Meses de cobro", "=ROUND(DIAS_COBRO/30,0)", N0),
               ("mcred", "Mes de pago de flete e internación", "={mlleg}+ROUND(CRED_DIAS/30,0)", N0), ("msal", "Mes del saldo a fábrica", "=IF(SALDO_ORIGEN=1,{memb},{mlleg})", N0)]
        c = ws.cell(r0, 1, f"Flujo del lote — escenario {nom}")
        c.font = Font(bold=True, color="FFFFFF")
        for jj in range(1, 4):
            ws.cell(r0, jj).fill = PatternFill("solid", fgColor=VERDE)
        pc = {}
        for k, (kk, t, fo, fmt) in enumerate(cst, r0 + 1):
            pc[kk] = f"$B${k}"
        for k, (kk, t, fo, fmt) in enumerate(cst, r0 + 1):
            ws.cell(k, 1, t)
            cc = ws.cell(k, 2, fo.format(**pc))
            cc.number_format = fmt
        rm = r0 + len(cst) + 2                              # fila de meses
        nombres = ["Mes", "Stock al inicio", "Unidades vendidas", "Pago a fábrica", "Inland China", "Arancel, flete e internación",
                   "IVA de importación (paga y recupera)", "Almacenaje", "Costos de venta (operación)", "Cobros netos de canal",
                   "FLUJO NETO", "FLUJO ACUMULADO", "aux: mes con flujo final", "aux: payback"]
        rk = {n: rm + i for i, n in enumerate(nombres)}
        for n, rw in rk.items():
            ws.cell(rw, 1, n).font = Font(bold=n.isupper())
        fin_col = L(c0 + MAX_MES)
        for m in meses:
            col = L(c0 + m)
            prev = L(c0 + m - 1) if m else None
            R = lambda n: f"{col}{rk[n]}"
            ws.cell(rk["Mes"], c0 + m, m).font = Font(bold=True)
            M_ = f"{col}${rk['Mes']}"
            si = (f"=QTY" if m == 0 else f"=IF({M_}<={pc['mdisp']},QTY,{prev}{rk['Stock al inicio']}-{prev}{rk['Unidades vendidas']})")
            vals = {
                "Stock al inicio": si,
                "Unidades vendidas": f"=IF(AND({M_}>={pc['mdisp']},{M_}<=MAX_MESES),MIN({pc['velm']},{R('Stock al inicio')}),0)",
                "Pago a fábrica": f"=-IF({M_}=0,ANTICIPO*{pc['pxq']},0)-IF({M_}={pc['msal']},(1-ANTICIPO)*{pc['pxq']},0)",
                "Inland China": f"=-IF({M_}={pc['memb']},{pc['china']},0)",
                "Arancel, flete e internación": f"=-IF({M_}={pc['mlleg']},{pc['aran']},0)-IF({M_}={pc['mcred']},{pc['cred']},0)",
                "IVA de importación (paga y recupera)": f"=-IF({M_}={pc['mlleg']},{pc['ivai']},0)+IF({M_}={pc['mlleg']}+IVA_REC,{pc['ivai']},0)",
                "Almacenaje": f"=-IF(AND({M_}>={pc['mdisp']},{M_}<=MAX_MESES,{R('Stock al inicio')}>0.000000001),{R('Stock al inicio')}*M3_U*ALMAC/12,0)",
                "Costos de venta (operación)": f"=-{R('Unidades vendidas')}*OPER_U",
                "Cobros netos de canal": (f"=IF({M_}-{pc['lag']}>=0,INDEX(${L(c0)}${rk['Unidades vendidas']}:${fin_col}${rk['Unidades vendidas']},1,"
                                          f"{M_}-{pc['lag']}+1),0)*{pc['netou']}"),
                "FLUJO NETO": f"=SUM({col}{rk['Pago a fábrica']}:{col}{rk['Cobros netos de canal']})",
                "FLUJO ACUMULADO": f"={R('FLUJO NETO')}" if m == 0 else f"={prev}{rk['FLUJO ACUMULADO']}+{R('FLUJO NETO')}",
                "aux: mes con flujo final": (f"=IF(OR({R('Cobros netos de canal')}<>0,{M_}={pc['mlleg']}+IVA_REC,{M_}={pc['mcred']}),{M_},0)"),
                "aux: payback": ('=""' if m == 0 else
                                 f'=IF(AND({R("FLUJO ACUMULADO")}>=0,MIN(${L(c0)}${rk["FLUJO ACUMULADO"]}:{prev}${rk["FLUJO ACUMULADO"]})<0),{M_},"")'),
            }
            for n, v in vals.items():
                cc = ws.cell(rk[n], c0 + m, v)
                cc.number_format = N0 if n in ("Stock al inicio", "Unidades vendidas") else CLP
        rng = lambda n: f"${L(c0)}${rk[n]}:${fin_col}${rk[n]}"
        rmet = rk["aux: payback"] + 2
        met = [("Último mes del ciclo", f"=MAX({rng('aux: mes con flujo final')})", N0, "fin"),
               ("Ciclo (meses, desde el anticipo)", "={fin}+1", N0, "ciclo"),
               ("Utilidad del lote", f"=INDEX({rng('FLUJO ACUMULADO')},1,{{fin}}+1)", CLP, "util"),
               ("ROI del lote", "={util}/" + pc["inv"], PCT, "roil"),
               ("ROI anualizado", '=IF({roil}>-1,(1+{roil})^(12/{ciclo})-1,"")', PCT, "roia"),
               ("Payback (mes)", f'=IF(COUNT({rng("aux: payback")})=0,"no recupera",MIN({rng("aux: payback")}))', N0, "pb"),
               ("Caja máxima necesaria", f"=-MIN({rng('FLUJO ACUMULADO')})", CLP, "expo"),
               ("Unidades sin vender al mes máximo", f"=MAX(0,QTY-SUM({rng('Unidades vendidas')}))", N0, "sinv"),
               ("Días de inventario del lote", f"=QTY/{pc['velm']}*30", N0, "dinv"),
               ("GMROI del lote", f"=SUM({rng('Unidades vendidas')})*(PRECIO_PROM*{pc['ratio']}-{pc['cu']})/({pc['inv']}/2)", X2, "gml")]
        mp = {}
        for i, (t, fo, fmt, key) in enumerate(met):
            mp[key] = f"$B${rmet + i}"
        for i, (t, fo, fmt, key) in enumerate(met):
            ws.cell(rmet + i, 1, t).font = Font(bold=True)
            cc = ws.cell(rmet + i, 2, fo.format(**mp) if "{" in fo else fo)
            cc.number_format = fmt
        fl_pos[nom] = {k: f"'Flujo'!{v}" for k, v in mp.items()}
        r0 = rmet + len(met) + 2
    ws.freeze_panes = "C2"

    # ── Radar ────────────────────────────────────────────────────────────────
    ws = wb.create_sheet("Radar")
    ws.column_dimensions["A"].width = 38
    if not rad.get("disponible"):
        ws.cell(1, 1, f"[PENDIENTE] {rad.get('motivo', 'radar no disponible')}")
    else:
        ws.cell(1, 1, f"Tipo {rad.get('tipo')} · partida {rad.get('arancel') or '—'} · {rad.get('desde')} a {rad.get('hasta')} · "
                      f"importador INFERIDO (nivel de evidencia por fila) · internado de la competencia = ESTIMADO").font = Font(italic=True)
        cab = ["Importador", "Evidencia", "Unidades 12m", "DIN", "FOB/u prom", "FOB/u último", "Última compra", "Internado/u estimado",
               "Nuestro FOB vs ellos", "Tendencia", "Fábricas", "Forwarder", "Naviera"]
        for j, t in enumerate(cab, 1):
            c = ws.cell(3, j, t)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor=AZUL)
            ws.column_dimensions[L(j)].width = max(ws.column_dimensions[L(j)].width or 0, 15)
        for i, x in enumerate(rad.get("competidores", []), 4):
            vals = [x["importador"], x["nivel"], x["unidades_12m"], x["din_12m"], x["fob_u_prom"], x["fob_u_ultimo"], x["ultima_compra"],
                    x["internado_u_estimado_clp"], x["dif_fob_pct"], x["tendencia"], ", ".join(map(str, x["fabricas"])), x["forwarder"], x["naviera"]]
            for j, v in enumerate(vals, 1):
                c = ws.cell(i, j, v)
                c.number_format = {3: N0, 5: USD, 6: USD, 8: CLP, 9: PCT}.get(j, "General")
        k = 5 + len(rad.get("competidores", []))
        ws.cell(k, 1, "Coincidencias por palabras clave").font = Font(bold=True)
        for j, t in enumerate(["Confianza", "Mes", "Importador", "Glosa", "Proveedor", "Unidades", "FOB/u"], 1):
            ws.cell(k + 1, j, t).font = Font(bold=True)
        for i, x in enumerate(rad.get("coincidencias", []), k + 2):
            for j, v in enumerate([x["confianza"], x["mes"], x["importador"] + (" (UnionX)" if x["es_unionx"] else ""), x["glosa"], x["proveedor"],
                                   x["unidades"], x["fob_u"]], 1):
                ws.cell(i, j, v).number_format = {6: N0, 7: USD}.get(j, "General")
        k = k + 3 + len(rad.get("coincidencias", []))
        ws.cell(k, 1, "Fábricas de la competencia (para cotizar)").font = Font(bold=True)
        for i, x in enumerate(rad.get("fabricas", []), k + 1):
            ws.cell(i, 1, x["proveedor"])
            ws.cell(i, 2, x["unidades"]).number_format = N0
            ws.cell(i, 3, x["fob_u"]).number_format = USD
        k += 2 + len(rad.get("fabricas", []))
        ws.cell(k, 1, "Referencia de la competencia (FOB/u)")
        ws.cell(k, 2, rad.get("fob_referencia_u")).number_format = USD
        ws.cell(k, 3, rad.get("fob_referencia_txt"))

    # ── Resumen ──────────────────────────────────────────────────────────────
    w = res.ws
    w.cell(1, 1, f"Evaluación de producto — {p.get('nombre', '')}").font = Font(bold=True, size=14, color=AZUL)
    w.cell(2, 1, "Veredicto a estos precios")
    v = w.cell(2, 2, '=IF(CTR_BASE<=0,"NO COMPRAR",IF(EVA_BASE<=0,"NO COMPRAR",IF(AND(EVA_CONS>0,CPCT_BASE>=BENCH,RADAR_OK=1),"COMPRAR","NEGOCIAR")))')
    v.font = Font(bold=True, size=14, color="B5651D")
    w.cell(3, 1, "Razón (motor)")
    w.cell(3, 2, r["razon"])
    w.cell(4, 1, "Precio de compra máximo (motor)")
    w.cell(4, 2, "=FOB_OBJ").number_format = USD
    w.cell(5, 1, "PVP ideal con IVA (motor)")
    w.cell(5, 2, "=PVP_IDEAL").number_format = CLP
    filas = [("Costo internado unitario", "=COSTO_U", CLP), ("Precio neto promedio", "=PRECIO_PROM", CLP),
             ("Contribución base (% venta)", "=CPCT_BASE", PCT), ("Referencia de la categoría", "=BENCH", PCT)]
    for i, (t, fo, fmt) in enumerate(filas, 7):
        w.cell(i, 1, t)
        w.cell(i, 2, fo).number_format = fmt
    w.cell(11, 1, "Escenario").font = Font(bold=True)
    for j, nom in enumerate(("Conservador", "Base", "Optimista"), 2):
        w.cell(11, j, nom).font = Font(bold=True)
        col = L(j)
        for i, (t, fo, fmt) in enumerate([("Contribución anual", f"='ROI'!{col}{roi_pos['ctr']}", CLP), ("Capital", f"='ROI'!{col}{roi_pos['cap']}", CLP),
                                           ("EVA (9%)", f"='ROI'!{col}{roi_pos['eva']}", CLP), ("ROI sobre capital", f"='ROI'!{col}{roi_pos['roi']}", X2),
                                           ("ROI del lote", f"={fl_pos[nom]['roil']}", PCT), ("ROI anualizado", f"={fl_pos[nom]['roia']}", PCT),
                                           ("Payback (mes)", f"={fl_pos[nom]['pb']}", N0), ("Caja máxima", f"={fl_pos[nom]['expo']}", CLP)], 12):
            w.cell(i, 1, t)
            w.cell(i, j, fo).number_format = fmt
    ls = r.get("lote_sugerido")
    if ls:
        w.cell(21, 1, "Lote sugerido (motor)").font = Font(bold=True)
        w.cell(21, 2, ls["qty"]).number_format = N0
        w.cell(21, 3, f"~{ls['meses']:.0f} meses de venta · EVA conservador {ls['eva_conservador']:,.0f}".replace(",", "."))

    # ── Léeme ────────────────────────────────────────────────────────────────
    le = wb.create_sheet("Léeme")
    le.column_dimensions["A"].width = 130
    txt = ["Agente Producto — evaluación de compra (UnionX)",
           "Celdas amarillas: editables (Producto y Supuestos). Todo lo demás son fórmulas.",
           "Costo internado = mismo cálculo que el precosteo del agente COMEX (3% Steven, local charge, Form F, flete por CBM, agente 0,16% CIF, gastos Chile).",
           "Contribución, capital y EVA = mismas fórmulas del ROI por producto (costo de capital 9%). Marketing lineal 3% (decisión 9-oct).",
           "Veredicto: COMPRAR si el EVA del conservador es positivo, la contribución base alcanza la de la categoría y el cruce con el radar no lo bloquea; "
           "NO COMPRAR si el EVA base no es positivo; si no, NEGOCIAR.",
           "Radar: importador inferido (Aduana publica sin nombre), cada fila con su nivel de evidencia; el internado de la competencia es una estimación.",
           "El precio de compra objetivo lo calcula el motor (búsqueda numérica): para comprobarlo, ponerlo en Producto → Precio de compra y ver que el EVA conservador quede ≈ 0."]
    for i, t in enumerate(txt, 1):
        le.cell(i, 1, t).font = Font(bold=(i == 1), size=13 if i == 1 else 11)
    wb.move_sheet("Léeme", offset=-(len(wb.sheetnames) - 1))
    wb.active = wb.sheetnames.index("Resumen")
    wb.save(salida)
