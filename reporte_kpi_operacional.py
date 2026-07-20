# -*- coding: utf-8 -*-
"""Reporte KPI Operacional MENSUAL — generalizado (data-driven, email-safe).

Generaliza `enviar_kpi_junio.py` a CUALQUIER mes cerrado. Por defecto reporta el
**mes anterior** (mes cerrado más reciente); se puede forzar con MES_KPI/YEAR_KPI.

Diseñado para correr en CI (GitHub Actions) el PRIMER LUNES de cada mes:
  - Calcula todo desde parquet (WMS categoria_wms + ventas_historico + control_gestion
    + snapshot OTIF). No hay nada hardcodeado del mes.
  - HTML email-safe (tablas con estilos inline; sin CSS vars ni SVG, que no rendean
    en Gmail/Outlook). La versión "fancy" con gráficos vive en el artifact de claude.ai
    (link opcional vía ARTIFACT_URL).
  - Envía por Gmail a EMAIL_TO con copia a EMAIL_CC (Gerardo por defecto).

Operacional (pick/entrega/recepción) = bodega CA1 + BRSt (lo que opera el equipo,
clasificado por categoria_wms: excluye despachos que ejecuta el marketplace,
acredita reposiciones a fulfillment + salidas BRSt). Comercial = total empresa.

Uso:
  python reporte_kpi_operacional.py                 # solo genera HTML (revisión)
  SEND=1 python reporte_kpi_operacional.py          # genera + envía
  MES_KPI=6 YEAR_KPI=2026 SEND=1 python ...         # fuerza un mes puntual
Env: EMAIL_TO, EMAIL_CC, ARTIFACT_URL, SEND.
"""
import os, sys, base64, json, calendar, datetime
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "agente-comex"))
from src.gmail_client import GmailClient
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Resolución del mes (por defecto = mes cerrado más reciente = mes anterior) ─
NOMBRES = {1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
           7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"}
ABREV = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
         7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}

_hoy = datetime.date.today()
if os.environ.get("MES_KPI"):
    MES = int(os.environ["MES_KPI"]); YEAR = int(os.environ.get("YEAR_KPI", _hoy.year))
else:
    _last_prev = _hoy.replace(day=1) - datetime.timedelta(days=1)  # último día del mes anterior
    MES, YEAR = _last_prev.month, _last_prev.year
MES_PREV = 12 if MES == 1 else MES - 1
YEAR_PREV = YEAR - 1 if MES == 1 else YEAR
MES_NOMBRE, MES_PREV_NOMBRE = NOMBRES[MES], NOMBRES[MES_PREV]
_ndays = calendar.monthrange(YEAR, MES)[1]
INI = pd.Timestamp(f"{YEAR}-{MES:02d}-01")
FIN = pd.Timestamp(f"{YEAR}-{MES:02d}-{_ndays} 23:59:59")

PERSONAS = 5
# Horas REALES trabajadas por mes (dotación × días hábiles + horas extra). Manual (no hay feed).
# may=798 · jun=1139 (930 base + 209 extra por Cyber, semana con 7 personas) — validado.
# Fallback = PERSONAS × 186 (~mes estándar 22 días). El denominador honesto de la
# productividad son las horas REALMENTE trabajadas (incl. extra), no la dotación base.
HORAS_MES = {5: 798.0, 6: 1139.0}
HORAS = HORAS_MES.get(MES, PERSONAS * 186.0)

B2B_TN = ["Corporativo", "Distribucion", "Distribución", "Fidelizacion", "Fidelización"]
PICK_CATS = ["pick_ca1", "pick_reserva"]
ENT_CATS = ["entrega_ca1", "reposicion_fulfillment", "entrega_reserva"]

EMAIL_TO = [e.strip() for e in os.environ.get("EMAIL_TO", "andres@unionx.cl").split(",") if e.strip()]
EMAIL_CC = [e.strip() for e in os.environ.get("EMAIL_CC", "gerardo@unionx.cl").split(",") if e.strip()]
ARTIFACT_URL = os.environ.get("ARTIFACT_URL", "").strip()

# ── Colores / helpers ──────────────────────────────────────────────────────
AZ = "#1E3A5F"; GR = "#EBF0F8"; VE = "#16a34a"; NA = "#d97706"; RO = "#dc2626"; GR2 = "#64748B"
def clp(n): return "$" + "{:,.0f}".format(n).replace(",", ".")
def miles(n): return "{:,.0f}".format(n).replace(",", ".")
def pct_c(v, ok=95, warn=85): return VE if v >= ok else (NA if v >= warn else RO)
def otif_fmt(v): return f"{v:.1f}%" if v and v > 0 else "s/d"
def th(t, a="right"): return f'<th style="padding:7px 10px;text-align:{a};color:#fff;font-size:12px;">{t}</th>'
def td(t, b=False, a="right", c=""):
    return f'<td style="padding:6px 10px;text-align:{a};{"font-weight:bold;" if b else ""}{c}">{t}</td>'
def hdr(cols): return f'<tr style="background:{AZ};">{"".join(cols)}</tr>'
def rowz(i, cols, total=False):
    s = f"background:{AZ};color:white;font-weight:bold;" if total else (f"background:{GR};" if i % 2 == 0 else "background:#fff;")
    return f'<tr style="{s}font-size:12px;">{"".join(cols)}</tr>'
def tbl(rows): return f'<div style="overflow-x:auto;margin-bottom:8px;"><table style="width:100%;border-collapse:collapse;font-size:12px;">{rows}</table></div>'
def sec(t): return f'<h3 style="color:{AZ};margin:22px 0 6px;padding-bottom:4px;border-bottom:2px solid {GR};">{t}</h3>'
def kpi(lbl, val, sub="", c=""):
    return (f'<td style="background:{GR};padding:14px 10px;border-radius:6px;text-align:center;vertical-align:top;">'
            f'<div style="font-size:10px;color:{GR2};text-transform:uppercase;letter-spacing:.4px;">{lbl}</div>'
            f'<div style="font-size:17px;font-weight:bold;color:{c or AZ};">{val}</div>'
            f'{"<div style=font-size:11px;color:"+GR2+";>"+sub+"</div>" if sub else ""}</td>')
def ksp(): return '<td style="width:1%;"></td>'

# ── Carga WMS (parquet con categoria_wms) ───────────────────────────────────
wms = pd.read_parquet(ROOT / "data/operaciones/volumen_inventario_hist.parquet")
wms["fecha_done"] = pd.to_datetime(wms["fecha_done"])
_tiene_cat = "categoria_wms" in wms.columns
wmes = wms[(wms["fecha_done"] >= INI) & (wms["fecha_done"] <= FIN)].copy()
if _tiene_cat:
    picks = wmes[wmes["categoria_wms"].isin(PICK_CATS)]
    ents = wmes[wmes["categoria_wms"].isin(ENT_CATS)]
    recs = wmes[wmes["categoria_wms"] == "recepcion_putaway"]
else:  # fallback parquet antiguo
    PICKS = ["Bodega Carrascal Nº9-10: Pick", "Bodega Carrascal N°9-10: Pick"]
    picks = wmes[wmes["picking_type_name"].isin(PICKS)]
    ents = wmes[wmes["picking_type_name"].str.contains("Delivery Orders", na=False)
                & wmes["picking_type_name"].str.contains("Carrascal", na=False)]
    recs = wmes[wmes["picking_type_name"].str.contains("Almacenamiento", na=False)]
uds_pick, n_pick = picks["n_unidades"].sum(), picks["picking_id"].nunique()
uds_ent, n_ent = ents["n_unidades"].sum(), ents["picking_id"].nunique()
uds_rec, n_rec = recs["n_unidades"].sum(), recs["picking_id"].nunique()

# Ventas TOTAL EMPRESA (todos los canales)
COLS = ["fecha_venta", "cantidad", "pedido", "venta_neta", "tipo_negocio", "canal", "anio_venta", "mes_venta"]
vh = pd.read_parquet(ROOT / "data/historico/ventas_historico.parquet", columns=COLS)
vh["fecha_venta"] = pd.to_datetime(vh["fecha_venta"])
vta = vh[(vh["anio_venta"] == YEAR) & (vh["mes_venta"] == MES)].copy()
uds_vta = vta["cantidad"].sum(); n_ped = vta["pedido"].nunique(); vta_neta = vta["venta_neta"].sum()
pvp = vta_neta / n_ped if n_ped else 0

# Costo operativo (control_gestion, area OPERACIONES, FCST=real, incl. reverso+seguros ops)
cg = pd.read_parquet(ROOT / "data/finanzas/control_gestion.parquet")
def costo_mes(m, y=YEAR):
    return abs(cg[(cg["year"] == y) & (cg["month"] == m) & (cg["area"] == "OPERACIONES")
                  & (cg["kpi"] == "GASTO") & (cg["escenario"] == "FCST")]["valor"].sum()) * 1000
def vol_mes(m, y=YEAR):
    d = vh[(vh["anio_venta"] == y) & (vh["mes_venta"] == m)]
    return d["pedido"].nunique(), d["cantidad"].sum(), d["venta_neta"].sum()
def ent_equipo_mes(m, y=YEAR):
    d = wms[(wms["fecha_done"].dt.year == y) & (wms["fecha_done"].dt.month == m)]
    if _tiene_cat:
        d = d[d["categoria_wms"].isin(ENT_CATS)]
    else:
        d = d[d["picking_type_name"].str.contains("Delivery Orders", na=False)
              & d["picking_type_name"].str.contains("Carrascal", na=False)]
    return d["n_unidades"].sum()
def pick_equipo_mes(m, y=YEAR):
    d = wms[(wms["fecha_done"].dt.year == y) & (wms["fecha_done"].dt.month == m)]
    if _tiene_cat:
        d = d[d["categoria_wms"].isin(PICK_CATS)]
    else:
        PICKS = ["Bodega Carrascal Nº9-10: Pick", "Bodega Carrascal N°9-10: Pick"]
        d = d[d["picking_type_name"].isin(PICKS)]
    return d["n_unidades"].sum()

# Stock (foto actual)
sku = pd.read_parquet(ROOT / "data/stock/skus.parquet").drop_duplicates("SKU")
val_inv = sku["Valor"].sum()
n_crit = int((sku["Semaforo"] == "CRITICO").sum())
n_bajo = int((sku["Semaforo"] == "BAJO").sum())
rot30 = sku["Rot 30d Uds"].mean(); rot90 = sku["Rot 90d Uds"].mean()
prod = uds_pick / HORAS if HORAS else 0

# OTIF snapshot
snap = json.load(open(ROOT / "data/kpis_wms/snapshot.json", encoding="utf-8"))
rpm = snap.get("otif_drive", {}).get("resumen_por_mes", {})
om = rpm.get(f"{YEAR}-{MES:02d}", {})
otif_t = om.get("otif_total_pct", 0) * 100; otif_e = om.get("otif_empresa_pct", 0) * 100
otif_c = om.get("otif_courier_pct", 0) * 100; n_ok = om.get("n_otif_ok", 0); n_otp = om.get("n_pedidos", 0)

# ── KPIs macro ──────────────────────────────────────────────────────────────
kpis_row = (
    f'<table style="width:100%;border-collapse:collapse;margin:16px 0;"><tr>'
    + kpi("Uds Pick equipo", miles(uds_pick), f"{miles(n_pick)} pickings (CA1+BRSt)")
    + ksp() + kpi("Uds Entregadas", miles(uds_ent), f"{miles(n_ent)} despachos + reposic.")
    + ksp() + kpi("Uds Vendidas", miles(uds_vta), f"{miles(n_ped)} pedidos · total empresa")
    + ksp() + kpi("Venta Neta", clp(vta_neta), f"PVP {clp(pvp)}/ped · total empresa")
    + ksp() + kpi("Productividad", f"{prod:.1f} uds/h", f"{PERSONAS}p × {HORAS:.0f}h", c=VE if prod >= 40.1 else NA)
    + '</tr><tr><td style="height:6px;"></td></tr><tr>'
    + kpi("Valor inventario", clp(val_inv))
    + ksp() + kpi("Rotación 30d", f"{rot30:.2f}x", c=VE if rot30 >= 0.8 else NA)
    + ksp() + kpi("Rotación 90d", f"{rot90:.2f}x")
    + ksp() + kpi("Quiebre crítico", miles(n_crit), f"Bajo: {miles(n_bajo)}", c=RO if n_crit > 100 else NA)
    + ksp() + kpi("OTIF Total", otif_fmt(otif_t), (f"{miles(n_ok)}/{miles(n_otp)} ped" if otif_t > 0 else f"falta {ABREV[MES].lower()} en snapshot"), c=pct_c(otif_t) if otif_t > 0 else GR2)
    + '</tr></table>'
)

# ── B2B vs B2C (total empresa) ──────────────────────────────────────────────
vta["seg"] = vta["tipo_negocio"].apply(lambda x: "B2B" if x in B2B_TN else "B2C")
gseg = vta.groupby("seg").agg(ped=("pedido", "nunique"), uds=("cantidad", "sum"), vn=("venta_neta", "sum"))
rows = [hdr([th("Segmento", "left"), th("Pedidos"), th("Unidades"), th("Uds/Ped"), th("Venta Neta"), th("PVP")])]
for i, s in enumerate(["B2C", "B2B"]):
    if s in gseg.index:
        r = gseg.loc[s]
        rows.append(rowz(i, [td(s, a="left"), td(miles(r.ped)), td(miles(r.uds)),
                             td(f"{r.uds/r.ped:.1f}"), td(clp(r.vn)), td(clp(r.vn/r.ped))]))
rows.append(rowz(0, [td("<b>TOTAL</b>", a="left"), td(miles(n_ped), True), td(miles(uds_vta), True),
                     td(f"{uds_vta/n_ped:.1f}", True), td(clp(vta_neta), True), td(clp(pvp), True)], total=True))
b2b_html = sec("B2B vs B2C — total empresa") + tbl("".join(rows))

# ── Tendencia YTD (ene..mes): entregas equipo · COP/uds · %costo/vta · OTIF ──
rows = [hdr([th("Mes", "left"), th("Entregas equipo"), th("Costo Op"), th("COP/unidad"),
             th("% s/Venta"), th("OTIF Total")])]
for i, m in enumerate(range(1, MES + 1)):
    c = costo_mes(m); _, u, vn = vol_mes(m); ee = ent_equipo_mes(m)
    ot = rpm.get(f"{YEAR}-{m:02d}", {}).get("otif_total_pct", 0) * 100
    rows.append(rowz(i, [td(ABREV[m], a="left"), td(miles(ee)), td(clp(c)),
                         td(clp(c/u) if u else "—"), td(f"{c/vn*100:.1f}%" if vn else "—"),
                         td(otif_fmt(ot), c=f"color:{pct_c(ot)};" if ot > 0 else f"color:{GR2};")]))
h1_html = (sec(f"Tendencia {YEAR} — operación &amp; costo (ene-{ABREV[MES].lower()})")
           + tbl("".join(rows))
           + f'<div style="font-size:11px;color:{GR2};">Entregas equipo = entrega_ca1 + reposiciones fulfillment + BRSt (fix 13-jul). '
           f'COP/unidad = costo op ÷ unidades vendidas (total empresa). OTIF desde snapshot Drive.</div>')

# ── Cruce operacional semanal (venta / pick / entrega) ──────────────────────
vta["sem"] = vta["fecha_venta"].dt.to_period("W-MON")
pk = picks.copy(); pk["sem"] = pk["fecha_done"].dt.to_period("W-MON")
en = ents.copy(); en["sem"] = en["fecha_done"].dt.to_period("W-MON")
sv = vta.groupby("sem").agg(pv=("pedido", "nunique"), uv=("cantidad", "sum"))
sp = pk.groupby("sem").agg(pp=("picking_id", "nunique"), up=("n_unidades", "sum"))
se = en.groupby("sem").agg(pe=("picking_id", "nunique"), ue=("n_unidades", "sum"))
cru = sv.join(sp, how="outer").join(se, how="outer").fillna(0).sort_index()
rows = [hdr([th("Semana", "left"), th("Ped Venta"), th("Uds Venta"), th("Ped Pick"),
             th("Uds Pick"), th("Ped Entrega"), th("Uds Entrega")])]
for i, (s, r) in enumerate(cru.iterrows()):
    rows.append(rowz(i, [td(str(s).split("/")[0][5:], a="left"), td(miles(r.pv)), td(miles(r.uv)),
                         td(miles(r.pp)), td(miles(r.up)), td(miles(r.pe)), td(miles(r.ue))]))
rows.append(rowz(0, [td("<b>TOTAL</b>", a="left"), td(miles(cru.pv.sum()), True), td(miles(cru.uv.sum()), True),
                     td(miles(cru.pp.sum()), True), td(miles(cru.up.sum()), True),
                     td(miles(cru.pe.sum()), True), td(miles(cru.ue.sum()), True)], total=True))
cruce_html = (sec("Cruce operacional semanal — pedidos venta / pick / entrega")
              + tbl("".join(rows))
              + f'<div style="font-size:11px;color:{GR2};">Venta = total empresa · Pick/Entrega = equipo (CA1+BRSt, incl. reposiciones fulfillment).</div>')

# ── OTIF mensual ────────────────────────────────────────────────────────────
if otif_t > 0:
    _otif_prev = rpm.get(f"{YEAR_PREV}-{MES_PREV:02d}", {}).get("otif_total_pct", 0) * 100
    _cae = _otif_prev and otif_t < _otif_prev - 2
    _callout = ""
    if _cae:
        _callout = (f'<div style="background:#FEF2F2;border-left:4px solid {RO};padding:10px 14px;margin:8px 0;font-size:12px;line-height:1.5;">'
                    f'⚠️ <b>OTIF cayó {_otif_prev:.1f}% → {otif_t:.1f}%</b> ({otif_t-_otif_prev:+.1f} pts). El OTIF Total exige on-time <b>Y</b> completo: '
                    f'empresa {otif_e:.1f}% (preparación) y courier {otif_c:.1f}% (última milla) están sobre el total {otif_t:.1f}%, '
                    f'lo que indica que el quiebre viene de pedidos que fallan en <b>ambas</b> dimensiones o de la combinación. '
                    f'Revisar causa raíz (quiebres de stock que atrasan preparación + retrasos courier).</div>')
    otif_html = (sec(f"OTIF — {MES_NOMBRE}")
        + f'<table style="width:100%;border-collapse:collapse;margin:8px 0;"><tr>'
        + kpi("OTIF Total", otif_fmt(otif_t), f"{miles(n_ok)}/{miles(n_otp)} pedidos", c=pct_c(otif_t))
        + ksp() + kpi("OTIF Empresa", otif_fmt(otif_e), "preparación bodega", c=pct_c(otif_e))
        + ksp() + kpi("OTIF Courier", otif_fmt(otif_c), "última milla", c=pct_c(otif_c))
        + '</tr></table>' + _callout)
else:
    otif_html = (sec(f"OTIF — {MES_NOMBRE}")
        + f'<div style="background:#FEF3C7;border-left:4px solid {NA};padding:10px 14px;margin:8px 0;font-size:12px;">'
        f'⚠️ <b>{MES_NOMBRE} sin dato OTIF</b> en el snapshot. '
        f'Requiere refrescar el archivo OTIF de Drive + regenerar snapshot para cerrar el mes.</div>')

# ── Por canal (total empresa, PVP total) ────────────────────────────────────
pc = vta.groupby("canal").agg(ped=("pedido", "nunique"), uds=("cantidad", "sum"), vn=("venta_neta", "sum"))
pc = pc.sort_values("vn", ascending=False).head(12)
rows = [hdr([th("Canal", "left"), th("Pedidos"), th("Unidades"), th("Venta Neta"), th("%Vta"), th("PVP")])]
for i, (c, r) in enumerate(pc.iterrows()):
    rows.append(rowz(i, [td(c, a="left"), td(miles(r.ped)), td(miles(r.uds)), td(clp(r.vn)),
                         td(f"{r.vn/vta_neta*100:.1f}%"), td(clp(r.vn/r.ped))]))
rows.append(rowz(0, [td("<b>TOTAL</b>", a="left"), td(miles(n_ped), True), td(miles(uds_vta), True),
                     td(clp(vta_neta), True), td("100%", True), td(clp(pvp), True)], total=True))
canal_html = sec("Venta por canal — total empresa") + tbl("".join(rows))

# ── Costo operativo: pedido + unidad + MoM + YTD + explicación ──────────────
c_act, c_prev = costo_mes(MES), costo_mes(MES_PREV, YEAR_PREV)
p_act, u_act, vn_act = vol_mes(MES); p_prev, u_prev, vn_prev = vol_mes(MES_PREV, YEAR_PREV)
c_ytd = sum(costo_mes(m) for m in range(1, MES + 1))
ytd = vh[(vh["anio_venta"] == YEAR) & (vh["mes_venta"].between(1, MES))]
p_ytd, u_ytd, vn_ytd = ytd["pedido"].nunique(), ytd["cantidad"].sum(), ytd["venta_neta"].sum()
sub = (cg[(cg["year"] == YEAR) & (cg["month"] == MES) & (cg["area"] == "OPERACIONES")
          & (cg["kpi"] == "GASTO") & (cg["escenario"] == "FCST")].groupby("sub_area")["valor"].sum() * 1000).abs().sort_values(ascending=False)
sub_lbl = {"LOGISTICA": "Logística", "POSTVENTA": "Postventa", "OPERACIONES": "Operaciones",
           "GRUPO ETER": "Grupo Eter", "FINANZAS Y ADMINISTRACIÓN": "Finanzas y Adm."}
sub_txt = " · ".join(f"{sub_lbl.get(k, k.title())} {clp(v)}" for k, v in sub.items() if v > 0)

def fila_cop(lbl, c, p, u, vn, i):
    return rowz(i, [td(lbl, a="left"), td(clp(c)), td(clp(c/p) if p else "—"),
                    td(clp(c/u) if u else "—"), td(f"{c/vn*100:.1f}%" if vn else "—")])
rows = [hdr([th("Período", "left"), th("Costo Op"), th("COP / Pedido"), th("COP / Unidad"), th("% s/Venta")])]
rows.append(fila_cop(MES_PREV_NOMBRE, c_prev, p_prev, u_prev, vn_prev, 0))
rows.append(fila_cop(f"<b>{MES_NOMBRE}</b>", c_act, p_act, u_act, vn_act, 1))
rows.append(rowz(0, [td(f"<b>YTD Ene-{ABREV[MES]}</b>", a="left"), td(clp(c_ytd), True), td(clp(c_ytd/p_ytd) if p_ytd else "—", True),
                     td(clp(c_ytd/u_ytd) if u_ytd else "—", True), td(f"{c_ytd/vn_ytd*100:.1f}%" if vn_ytd else "—", True)], total=True))
dped = (p_act - p_prev) / p_prev * 100 if p_prev else 0
duds = (u_act - u_prev) / u_prev * 100 if u_prev else 0
_copu_prev_s = clp(c_prev/u_prev) if u_prev else "—"
_copu_act_s = clp(c_act/u_act) if u_act else "—"
expl = (f'<div style="background:{GR};border-left:4px solid {AZ};padding:10px 14px;margin:8px 0;font-size:12px;line-height:1.5;">'
        f'<b>Lectura {MES_NOMBRE}:</b> pedidos {dped:+.0f}% y unidades {duds:+.0f}% vs {MES_PREV_NOMBRE.lower()}. '
        f'El costo operativo es mayormente <b>fijo</b> (nómina + arriendo), por lo que la métrica honesta es el '
        f'<b>COP/unidad</b> ({_copu_prev_s} → {_copu_act_s}). '
        f'El COP/pedido oscila por el mix (efecto denominador, no ineficiencia).</div>')
costo_html = (sec(f"Costo Operativo — {MES_NOMBRE} (vs {MES_PREV_NOMBRE} y YTD)") + tbl("".join(rows)) + expl
              + f'<div style="font-size:11px;color:{GR2};margin:2px 0 8px;">Desglose {MES_NOMBRE.lower()}: {sub_txt}. '
              f'Base = área OPERACIONES (incl. reverso + seguros operacionales). Fuente: P&amp;L control de gestión (FCST=Real).</div>')

# ── Resumen ejecutivo (lectura del mes vs mes anterior) ─────────────────────
otif_prev = rpm.get(f"{YEAR_PREV}-{MES_PREV:02d}", {}).get("otif_total_pct", 0) * 100
prod_prev = (pick_equipo_mes(MES_PREV, YEAR_PREV) / HORAS_MES.get(MES_PREV, PERSONAS * 186.0)) if HORAS_MES.get(MES_PREV, PERSONAS * 186.0) else 0
copu_prev = (c_prev / u_prev) if u_prev else 0
def _delta(act, prev, arriba=True):
    if not prev: return "", GR2
    d = (act - prev) / prev * 100
    col = VE if ((d >= 0) == arriba) else RO
    return f" ({d:+.0f}% vs {MES_PREV_NOMBRE.lower()})", col
def _li(txt, col):
    return f'<li style="margin:4px 0;"><span style="color:{col};font-weight:bold;font-size:14px;">●</span> {txt}</li>'
dpt, dpc = _delta(prod, prod_prev, True)
dot, doc = _delta(otif_t, otif_prev, True)
duc, dcc = _delta(c_act/u_act if u_act else 0, copu_prev, arriba=False)  # COP/uds: bajar es bueno
# OTIF: sólo marcar ALERTA si cayó > 2 pts; si no, lectura neutra.
_otif_alerta = otif_prev and otif_t and otif_t < otif_prev - 2
if otif_t > 0:
    _otif_li = _li(f'<b>OTIF {otif_t:.1f}%</b>{dot}' + (f' — <b style="color:{RO};">ALERTA</b>: caída de servicio.' if _otif_alerta else ' — servicio dentro de rango.'), doc)
else:
    _otif_li = _li(f'<b>OTIF s/d</b> — falta el mes en el snapshot (refrescar OTIF Drive).', GR2)
resumen_html = (
    f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:14px 18px;margin:14px 0;">'
    f'<div style="font-size:11px;color:{GR2};text-transform:uppercase;letter-spacing:.5px;font-weight:bold;margin-bottom:6px;">Lectura del mes</div>'
    f'<ul style="margin:0;padding-left:4px;list-style:none;font-size:13px;line-height:1.5;">'
    + _li(f'<b>Venta</b> {clp(vta_neta)} · {miles(uds_vta)} uds · {miles(n_ped)} pedidos (total empresa).', AZ)
    + _li(f'<b>Productividad {prod:.1f} uds/h</b>{dpt} — bench 40,1. El equipo movió {miles(int(uds_pick))} uds en {HORAS:.0f}h.', dpc)
    + _otif_li
    + _li(f'<b>COP/unidad {_copu_act_s}</b>{duc} — el costo op total fue {clp(c_act)} (fijo).', dcc)
    + _li(f'<b>Inventario</b> {clp(val_inv)} · {miles(n_crit)} SKUs en quiebre crítico · rotación 90d {rot90:.2f}x.', NA if n_crit > 60 else AZ)
    + '</ul></div>'
)

# ── Link al reporte fancy (artifact), si se pasó ────────────────────────────
artifact_html = ""
if ARTIFACT_URL:
    artifact_html = (f'<div style="background:{AZ};border-radius:8px;padding:14px 18px;margin:14px 0;text-align:center;">'
                     f'<a href="{ARTIFACT_URL}" style="color:#fff;font-size:14px;font-weight:bold;text-decoration:none;">'
                     f'📊 Ver reporte ejecutivo con gráficos (versión CEO) →</a></div>')

# ── Ensamble ────────────────────────────────────────────────────────────────
body = f"""<div style="font-family:Calibri,Arial,sans-serif;max-width:900px;color:#1a1a1a;">
<h2 style="color:{AZ};border-bottom:3px solid {AZ};padding-bottom:8px;margin-bottom:4px;">Reporte KPI Operacional — {MES_NOMBRE} {YEAR}</h2>
<p style="font-size:12px;color:{GR2};margin-top:0;">Período 01 al {_ndays} de {MES_NOMBRE.lower()} {YEAR} · {PERSONAS} personas × {HORAS:.0f}h ·
Operacional = bodega CA1 + BRSt (incl. reposiciones a fulfillment) · Comercial = total empresa</p>
{artifact_html}{resumen_html}{kpis_row}{h1_html}{b2b_html}{cruce_html}{otif_html}{canal_html}{costo_html}
<hr style="border:1px solid {GR};margin-top:28px;">
<p style="font-size:11px;color:#94A3B8;">Reporte automático mensual · UnionX Operaciones · Entregas del equipo por categoria_wms (excluye despachos del marketplace, acredita reposiciones + BRSt). Fuente: Odoo WMS + parquet ventas + snapshot OTIF + P&amp;L control gestión (área Operaciones, incl. reverso + seguros).</p>
</div>"""

if __name__ == "__main__":
    print(f"=== KPI {MES_NOMBRE} {YEAR} ===", flush=True)
    print(f"Pick equipo {miles(uds_pick)} uds ({miles(n_pick)} pk) | Entregas {miles(uds_ent)} uds | Prod {prod:.1f} uds/h ({HORAS:.0f}h)", flush=True)
    print(f"Venta {clp(vta_neta)} | {miles(uds_vta)} uds | {miles(n_ped)} ped | PVP {clp(pvp)}", flush=True)
    print(f"COP {MES_NOMBRE}: pedido {clp(c_act/p_act) if p_act else '—'} | unidad {_copu_act_s} | {c_act/vn_act*100:.1f}% venta" if vn_act else "", flush=True)
    print(f"OTIF total {otif_fmt(otif_t)} | Inventario {clp(val_inv)} | críticos {n_crit}", flush=True)
    print(f"TO={EMAIL_TO} CC={EMAIL_CC} artifact={'sí' if ARTIFACT_URL else 'no'}", flush=True)
    out = ROOT / "data" / "outputs" / f"kpi_{ABREV[MES].lower()}_{YEAR}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(f"HTML guardado: {out}", flush=True)
    if os.environ.get("SEND") == "1":
        gc = GmailClient()
        msg = MIMEMultipart(); msg["to"] = ",".join(EMAIL_TO)
        if EMAIL_CC: msg["cc"] = ",".join(EMAIL_CC)
        msg["from"] = "andres@unionx.cl"
        msg["subject"] = f"Reporte KPI Operacional — {MES_NOMBRE} {YEAR}"
        msg.attach(MIMEText(body, "html", "utf-8"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        resp = gc.service.users().messages().send(userId="me", body={"raw": raw}).execute()
        print("Enviado OK:", resp.get("id"), flush=True)
    else:
        print("(SEND!=1 → no se envía, solo HTML de revisión)", flush=True)
