# -*- coding: utf-8 -*-
"""Reporte KPI Operacional — Mayo 2026 (recreado y versionado).

Cambios vs versión perdida:
  1. Venta neta / uds / PVP = TOTAL EMPRESA (todos los canales), no solo CA1
     (el fulfillment se preparó antes en bodega; usar CA1 infla el PVP).
  2. Cruce semanal incluye pedidos VENTA / PICK / ENTREGADOS.
  3. PVP por canal = total empresa.
  4. Costo operativo: COP/pedido Y COP/unidad, con explicación del mix y
     comparación vs mes anterior y vs acumulado YTD.

Operacional (pick/entrega/recepción) = CA1 (lo que opera el equipo).
Comercial (venta/uds/pedidos/PVP/canal) = total empresa.
Envía solo a andres@ (revisión). EMAIL_TO override por env.
"""
import os, sys, base64
from pathlib import Path
import pandas as pd

ROOT = Path(r"g:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA")
sys.path.insert(0, str(ROOT / "agente-comex"))
from src.gmail_client import GmailClient
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Parámetros del mes ─────────────────────────────────────────────────────
MES = 5
MES_NOMBRE = "Mayo"
INI = pd.Timestamp(f"2026-{MES:02d}-01")
FIN = pd.Timestamp(f"2026-{MES:02d}-31 23:59:59")
PERSONAS = 5
HORAS = 798.0
B2B_TN = ["Corporativo", "Distribucion", "Distribución", "Fidelizacion", "Fidelización"]
EMAIL_TO = [e.strip() for e in os.environ.get("EMAIL_TO", "andres@unionx.cl").split(",") if e.strip()]

# ── Colores / helpers ──────────────────────────────────────────────────────
AZ = "#1E3A5F"; GR = "#EBF0F8"; VE = "#16a34a"; NA = "#d97706"; RO = "#dc2626"; GR2 = "#64748B"
def clp(n): return "$" + "{:,.0f}".format(n).replace(",", ".")
def miles(n): return "{:,.0f}".format(n).replace(",", ".")
def pct_c(v, ok=95, warn=85): return VE if v >= ok else (NA if v >= warn else RO)
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

# ── Carga ──────────────────────────────────────────────────────────────────
wms = pd.read_parquet(ROOT / "data/operaciones/volumen_inventario_hist.parquet")
wms["fecha_done"] = pd.to_datetime(wms["fecha_done"])
wmes = wms[(wms["fecha_done"] >= INI) & (wms["fecha_done"] <= FIN)].copy()
PICKS = ["Bodega Carrascal Nº9-10: Pick", "Bodega Carrascal N°9-10: Pick"]
picks = wmes[wmes["picking_type_name"].isin(PICKS)]
ents = wmes[wmes["picking_type_name"].str.contains("Delivery Orders", na=False)
            & wmes["picking_type_name"].str.contains("Carrascal", na=False)]
recs = wmes[wmes["picking_type_name"].str.contains("Almacenamiento", na=False)]
uds_pick, n_pick = picks["n_unidades"].sum(), len(picks)
uds_ent, n_ent = ents["n_unidades"].sum(), len(ents)
uds_rec, n_rec = recs["n_unidades"].sum(), len(recs)

# Ventas TOTAL EMPRESA (todos los canales)
COLS = ["fecha_venta", "cantidad", "pedido", "venta_neta", "tipo_negocio", "canal", "anio_venta", "mes_venta"]
vh = pd.read_parquet(ROOT / "data/historico/ventas_historico.parquet", columns=COLS)
vh["fecha_venta"] = pd.to_datetime(vh["fecha_venta"])
vta = vh[(vh["anio_venta"] == 2026) & (vh["mes_venta"] == MES)].copy()
uds_vta = vta["cantidad"].sum(); n_ped = vta["pedido"].nunique(); vta_neta = vta["venta_neta"].sum()
pvp = vta_neta / n_ped if n_ped else 0

# Costo operativo (control_gestion, area OPERACIONES, FCST=real)
cg = pd.read_parquet(ROOT / "data/finanzas/control_gestion.parquet")
def costo_mes(m): return abs(cg[(cg["year"] == 2026) & (cg["month"] == m) & (cg["area"] == "OPERACIONES")
                                & (cg["kpi"] == "GASTO") & (cg["escenario"] == "FCST")]["valor"].sum()) * 1000
def vol_mes(m):
    d = vh[(vh["anio_venta"] == 2026) & (vh["mes_venta"] == m)]
    return d["pedido"].nunique(), d["cantidad"].sum(), d["venta_neta"].sum()

# Stock
sku = pd.read_parquet(ROOT / "data/stock/skus.parquet").drop_duplicates("SKU")
val_inv = sku["Valor"].sum()
n_crit = int((sku["Semaforo"] == "CRITICO").sum())
n_bajo = int((sku["Semaforo"] == "BAJO").sum())
rot30 = sku["Rot 30d Uds"].mean(); rot90 = sku["Rot 90d Uds"].mean()
prod = uds_pick / HORAS if HORAS else 0

# ── KPIs macro ──────────────────────────────────────────────────────────────
kpis_row = (
    f'<table style="width:100%;border-collapse:collapse;margin:16px 0;"><tr>'
    + kpi("Uds Pick CA1", miles(uds_pick), f"{miles(n_pick)} pickings")
    + ksp() + kpi("Uds Entregadas", miles(uds_ent), f"{miles(n_ent)} despachos")
    + ksp() + kpi("Uds Vendidas", miles(uds_vta), f"{miles(n_ped)} pedidos · total empresa")
    + ksp() + kpi("Venta Neta", clp(vta_neta), f"PVP {clp(pvp)}/ped · total empresa")
    + ksp() + kpi("Productividad", f"{prod:.1f} uds/h", f"{PERSONAS}p × {HORAS:.0f}h", c=VE if prod >= 40.1 else NA)
    + '</tr><tr><td style="height:6px;"></td></tr><tr>'
    + kpi("Valor inventario", clp(val_inv))
    + ksp() + kpi("Rotación 30d", f"{rot30:.2f}x", c=VE if rot30 >= 0.8 else NA)
    + ksp() + kpi("Rotación 90d", f"{rot90:.2f}x")
    + ksp() + kpi("Quiebre crítico", miles(n_crit), f"Bajo: {miles(n_bajo)}", c=RO if n_crit > 100 else NA)
    + ksp() + kpi("Uds Recibidas", miles(uds_rec), f"{miles(n_rec)} recepciones")
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

# ── Cruce operacional semanal (venta / pick / entrega) ──────────────────────
vta["sem"] = vta["fecha_venta"].dt.to_period("W-MON")
pk = picks.copy(); pk["sem"] = pk["fecha_done"].dt.to_period("W-MON")
en = ents.copy(); en["sem"] = en["fecha_done"].dt.to_period("W-MON")
sv = vta.groupby("sem").agg(pv=("pedido", "nunique"), uv=("cantidad", "sum"))
sp = pk.groupby("sem").agg(pp=("name", "count"), up=("n_unidades", "sum"))
se = en.groupby("sem").agg(pe=("name", "count"), ue=("n_unidades", "sum"))
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
              + f'<div style="font-size:11px;color:{GR2};">Venta = total empresa · Pick/Entrega = CA1 (equipo).</div>')

# ── OTIF mensual ────────────────────────────────────────────────────────────
import json
snap = json.load(open(ROOT / "data/kpis_wms/snapshot.json", encoding="utf-8"))
om = snap.get("otif_drive", {}).get("resumen_por_mes", {}).get(f"2026-{MES:02d}", {})
otif_t = om.get("otif_total_pct", 0) * 100; otif_e = om.get("otif_empresa_pct", 0) * 100
otif_c = om.get("otif_courier_pct", 0) * 100; n_ok = om.get("n_otif_ok", 0); n_otp = om.get("n_pedidos", 0)
otif_html = (sec("OTIF — Mayo")
    + f'<table style="width:100%;border-collapse:collapse;margin:8px 0;"><tr>'
    + kpi("OTIF Total", f"{otif_t:.1f}%", f"{miles(n_ok)}/{miles(n_otp)} pedidos", c=pct_c(otif_t))
    + ksp() + kpi("OTIF Empresa", f"{otif_e:.1f}%", "preparación bodega", c=pct_c(otif_e))
    + ksp() + kpi("OTIF Courier", f"{otif_c:.1f}%", "última milla", c=pct_c(otif_c))
    + '</tr></table>')

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
c_may, c_abr = costo_mes(MES), costo_mes(MES - 1)
p_may, u_may, vn_may = vol_mes(MES); p_abr, u_abr, vn_abr = vol_mes(MES - 1)
c_ytd = sum(costo_mes(m) for m in range(1, MES + 1))
ytd = vh[(vh["anio_venta"] == 2026) & (vh["mes_venta"].between(1, MES))]
p_ytd, u_ytd, vn_ytd = ytd["pedido"].nunique(), ytd["cantidad"].sum(), ytd["venta_neta"].sum()
sub = (cg[(cg["year"] == 2026) & (cg["month"] == MES) & (cg["area"] == "OPERACIONES")
          & (cg["kpi"] == "GASTO") & (cg["escenario"] == "FCST")].groupby("sub_area")["valor"].sum() * 1000).abs().sort_values(ascending=False)
sub_lbl = {"LOGISTICA": "Logística", "POSTVENTA": "Postventa", "OPERACIONES": "Operaciones",
           "GRUPO ETER": "Grupo Eter", "FINANZAS Y ADMINISTRACIÓN": "Finanzas y Adm."}
sub_txt = " · ".join(f"{sub_lbl.get(k, k.title())} {clp(v)}" for k, v in sub.items() if v > 0)

def fila_cop(lbl, c, p, u, vn, i):
    return rowz(i, [td(lbl, a="left"), td(clp(c)), td(clp(c/p) if p else "—"),
                    td(clp(c/u) if u else "—"), td(f"{c/vn*100:.1f}%" if vn else "—")])
rows = [hdr([th("Período", "left"), th("Costo Op"), th("COP / Pedido"), th("COP / Unidad"), th("% s/Venta")])]
rows.append(fila_cop("Abril", c_abr, p_abr, u_abr, vn_abr, 0))
rows.append(fila_cop(f"<b>{MES_NOMBRE}</b>", c_may, p_may, u_may, vn_may, 1))
rows.append(rowz(0, [td("<b>YTD Ene-May</b>", a="left"), td(clp(c_ytd), True), td(clp(c_ytd/p_ytd), True),
                     td(clp(c_ytd/u_ytd), True), td(f"{c_ytd/vn_ytd*100:.1f}%", True)], total=True))
dped = (p_may - p_abr) / p_abr * 100; duds = (u_may - u_abr) / u_abr * 100
expl = (f'<div style="background:{GR};border-left:4px solid {AZ};padding:10px 14px;margin:8px 0;font-size:12px;line-height:1.5;">'
        f'<b>¿Por qué varía?</b> Mayo movió <b>menos pedidos ({dped:+.0f}%)</b> pero <b>más unidades ({duds:+.0f}%)</b> '
        f'que abril: cayó el B2C marketplace (órdenes chicas) y se concentró el B2B (órdenes grandes). '
        f'Como el costo operativo es mayormente <b>fijo</b> (nómina + arriendo), repartirlo entre menos pedidos sube el '
        f'<b>COP/pedido</b> ($' + f'{c_abr/p_abr:,.0f}'.replace(",", ".") + f'→${c_may/p_may:,.0f}'.replace(",", ".") + f') — efecto denominador, no ineficiencia. '
        f'En cambio el <b>COP/unidad bajó</b> ($' + f'{c_abr/u_abr:,.0f}'.replace(",", ".") + f'→${c_may/u_may:,.0f}'.replace(",", ".") + f'): por unidad, mayo fue MÁS eficiente.</div>')
costo_html = (sec("Costo Operativo — Mayo (vs Abril y YTD)") + tbl("".join(rows)) + expl
              + f'<div style="font-size:11px;color:{GR2};margin:2px 0 8px;">Desglose mayo: {sub_txt}. '
              f'Base = total empresa. Fuente: P&amp;L 2025-2026 (FCST=Real).</div>')

# ── Ensamble ────────────────────────────────────────────────────────────────
body = f"""<div style="font-family:Calibri,Arial,sans-serif;max-width:900px;color:#1a1a1a;">
<h2 style="color:{AZ};border-bottom:3px solid {AZ};padding-bottom:8px;margin-bottom:4px;">Reporte KPI Operacional — {MES_NOMBRE} 2026</h2>
<p style="font-size:12px;color:{GR2};margin-top:0;">Período 01 al 31 de {MES_NOMBRE.lower()} 2026 · {PERSONAS} personas × {HORAS:.0f}h ·
Operacional = bodega CA1 · Comercial = total empresa (todos los canales)</p>
{kpis_row}{b2b_html}{cruce_html}{otif_html}{canal_html}{costo_html}
<hr style="border:1px solid {GR};margin-top:28px;">
<p style="font-size:11px;color:#94A3B8;">Reporte automático · UnionX Operaciones · Fuente: Odoo WMS + parquet ventas + snapshot OTIF + P&amp;L control gestión.</p>
</div>"""

if __name__ == "__main__":
    print(f"COP Mayo: pedido {clp(c_may/p_may)} | unidad {clp(c_may/u_may)} | {c_may/vn_may*100:.1f}% venta", flush=True)
    print(f"Enviando a: {EMAIL_TO}", flush=True)
    gc = GmailClient()
    msg = MIMEMultipart(); msg["to"] = ",".join(EMAIL_TO); msg["from"] = "andres@unionx.cl"
    msg["subject"] = f"Reporte KPI Operacional — {MES_NOMBRE} 2026"
    msg.attach(MIMEText(body, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    resp = gc.service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print("Enviado OK:", resp.get("id"))
