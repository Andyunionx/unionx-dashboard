# -*- coding: utf-8 -*-
"""Pulso KPI semanal (lunes). Compara SEMANA ACTUAL vs SEMANA ANTERIOR vs MAYO (ref).

KPIs WMS (operación CA1) + OTIF (mensual) + COP inferido (base TOTAL EMPRESA,
run-rate mensual prorrateado). Lo importante: resultados y si estamos cayendo.

Bases:
  - Operación (despachos/picks/recep): WMS CA1, por semana W-MON.
  - COP: costo run-rate (mes cerrado / 4,33) ÷ volumen TOTAL EMPRESA de la semana.
         Ref Mayo = COP mensual real. Métrica primaria estable = COP/unidad.
  - OTIF: mensual (no hay semanal confiable); se muestra tendencia.
__main__ imprime (no envía). SEND=1 + EMAIL_TO para enviar.
"""
import os, sys, json, base64
from pathlib import Path
import pandas as pd

ROOT = Path(r"g:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA")
sys.path.insert(0, str(ROOT / "agente-comex"))
AZ = "#1F4E79"; UNX = "#4884FC"; GR = "#EBF0F8"; VE = "#16a34a"; NA = "#d97706"; RO = "#dc2626"; GR2 = "#64748B"
def clp(n): return "$" + "{:,.0f}".format(n).replace(",", ".")
def miles(n): return "{:,.0f}".format(n).replace(",", ".")
def trend(cur, ref, mejor_arriba=True):
    if not ref: return ("—", GR2)
    d = (cur - ref) / abs(ref) * 100
    if abs(d) <= 1.5: return (f"➡️ {d:+.0f}%", GR2)
    sube = d > 0
    return (f"{'🔺' if sube else '🔻'} {d:+.0f}%", VE if (sube == mejor_arriba) else RO)

MES_CERRADO = 5  # Mayo (último mes cerrado = baseline)
B2B_TN = ["Corporativo", "Distribucion", "Distribución", "Fidelizacion", "Fidelización"]

# ── WMS por semana (operación CA1) ──────────────────────────────────────────
wms = pd.read_parquet(ROOT / "data/operaciones/volumen_inventario_hist.parquet")
wms["fecha_done"] = pd.to_datetime(wms["fecha_done"])
wms["sem"] = wms["fecha_done"].dt.to_period("W-MON")
PICKS = ["Bodega Carrascal Nº9-10: Pick", "Bodega Carrascal N°9-10: Pick"]
def filt(df, k):
    if k == "pick": return df[df["picking_type_name"].isin(PICKS)]
    if k == "ent":  return df[df["picking_type_name"].str.contains("Delivery Orders", na=False)
                              & df["picking_type_name"].str.contains("Carrascal", na=False)]
    if k == "rec":  return df[df["picking_type_name"].str.contains("Almacenamiento", na=False)]
wsorted = sorted(wms["sem"].dropna().unique())
W_ACT, W_PREV = wsorted[-1], wsorted[-2]
def wms_sem(sem):
    d = wms[wms["sem"] == sem]
    return dict(ped=len(filt(d, "ent")), uds=filt(d, "ent")["n_unidades"].sum(),
                upick=filt(d, "pick")["n_unidades"].sum(), rec=len(filt(d, "rec")))
wa, wp = wms_sem(W_ACT), wms_sem(W_PREV)
# Mayo: promedio semanal WMS
wmay = wms[(wms["fecha_done"].dt.year == 2026) & (wms["fecha_done"].dt.month == MES_CERRADO)]
n_sem_may = wmay["sem"].nunique() or 1
wmay_v = dict(ped=len(filt(wmay, "ent")) / n_sem_may, uds=filt(wmay, "ent")["n_unidades"].sum() / n_sem_may,
              upick=filt(wmay, "pick")["n_unidades"].sum() / n_sem_may, rec=len(filt(wmay, "rec")) / n_sem_may)

# ── Volumen TOTAL EMPRESA por semana (para COP) ─────────────────────────────
# June desde mes_actual (fresco), mayo desde historico. Evita doble conteo 1-jun.
mesact = pd.read_parquet(ROOT / "data/historico/ventas_mes_actual.parquet",
                         columns=["fecha_venta", "pedido", "cantidad", "venta_neta"])
mesact["fecha_venta"] = pd.to_datetime(mesact["fecha_venta"], errors="coerce")
mesact["sem"] = mesact["fecha_venta"].dt.to_period("W-MON")
def vta_sem(sem):
    d = mesact[mesact["sem"] == sem]
    return d["pedido"].nunique(), d["cantidad"].sum(), d["venta_neta"].sum()
pa, ua, vna = vta_sem(W_ACT); pp, up, vnp = vta_sem(W_PREV)

# ── Costo / COP ─────────────────────────────────────────────────────────────
cg = pd.read_parquet(ROOT / "data/finanzas/control_gestion.parquet")
costo_may = abs(cg[(cg["year"] == 2026) & (cg["month"] == MES_CERRADO) & (cg["area"] == "OPERACIONES")
                   & (cg["kpi"] == "GASTO") & (cg["escenario"] == "FCST")]["valor"].sum()) * 1000
costo_sem = costo_may / 4.33
# COP semanal (base total empresa)
def cop(p, u): return (costo_sem / p if p else 0, costo_sem / u if u else 0)
copp_a, copu_a = cop(pa, ua); copp_p, copu_p = cop(pp, up)
# Mayo ref = COP mensual real (total empresa)
hist = pd.read_parquet(ROOT / "data/historico/ventas_historico.parquet",
                       columns=["anio_venta", "mes_venta", "pedido", "cantidad"])
hmay = hist[(hist["anio_venta"] == 2026) & (hist["mes_venta"] == MES_CERRADO)]
p_may, u_may = hmay["pedido"].nunique(), hmay["cantidad"].sum()
copp_may, copu_may = costo_may / p_may, costo_may / u_may

# ── OTIF mensual ────────────────────────────────────────────────────────────
snap = json.load(open(ROOT / "data/kpis_wms/snapshot.json", encoding="utf-8"))
rpm = snap.get("otif_drive", {}).get("resumen_por_mes", {})
otif_ser = [(m, rpm[m]["otif_total_pct"] * 100) for m in sorted(rpm.keys())[-4:]]
K = snap.get("kpis", {})
ofr = K.get("ofr_30d", {}).get("valor", 0) * 100
oct_med = K.get("oct_30d", {}).get("mediana_h", 0)
pacc = K.get("pick_accuracy_30d", {}).get("valor", 0) * 100

# ── Stock ───────────────────────────────────────────────────────────────────
sku = pd.read_parquet(ROOT / "data/stock/skus.parquet").drop_duplicates("SKU")
val_inv = sku["Valor"].sum(); n_crit = int((sku["Semaforo"] == "CRITICO").sum())
sobre = sku[sku["Semaforo"] == "SOBRESTOCK"]["Valor"].sum()
sinv = int(((sku["Semaforo"] == "SIN VENTA") & (sku["Vta 90d Qty"].fillna(0) == 0)).sum())

# ── HTML ────────────────────────────────────────────────────────────────────
def th(t, a="right"): return f'<th style="padding:7px 9px;text-align:{a};color:#fff;font-size:11px;">{t}</th>'
def td(t, a="right", c=""): return f'<td style="padding:6px 9px;text-align:{a};{c}">{t}</td>'
def r3(i, lbl, act, prev, may, fmt=miles, mejor_arriba=True):
    f, col = trend(act, may, mejor_arriba)  # tendencia vs MAYO (baseline)
    bg = GR if i % 2 == 0 else "#fff"
    return (f'<tr style="background:{bg};font-size:12px;">'
            + td(lbl, "left") + td(fmt(act), c="font-weight:bold;") + td(fmt(prev), c="color:#94a3b8;")
            + td(fmt(may)) + td(f, c=f"color:{col};") + "</tr>")
lbl_act = str(W_ACT).split("/")[1]; lbl_prev = str(W_PREV).split("/")[1]
HEAD = f'<tr style="background:{AZ};">{th("KPI","left")}{th("Sem act ("+lbl_act[5:]+")")}{th("Sem ant")}{th("Mayo (sem)")}{th("vs Mayo")}</tr>'

op_tbl = f'<table style="width:100%;border-collapse:collapse;">{HEAD}' + \
    r3(0, "Pedidos despachados", wa["ped"], wp["ped"], wmay_v["ped"]) + \
    r3(1, "Uds despachadas", wa["uds"], wp["uds"], wmay_v["uds"]) + \
    r3(0, "Uds pickeadas", wa["upick"], wp["upick"], wmay_v["upick"]) + \
    r3(1, "Recepciones", wa["rec"], wp["rec"], wmay_v["rec"]) + "</table>"

HEADc = f'<tr style="background:{AZ};">{th("COP","left")}{th("Sem act")}{th("Sem ant")}{th("Mayo (mes)")}{th("vs Mayo")}</tr>'
cop_tbl = f'<table style="width:100%;border-collapse:collapse;">{HEADc}' + \
    r3(0, "COP / unidad", copu_a, copu_p, copu_may, fmt=clp, mejor_arriba=False) + \
    r3(1, "COP / pedido", copp_a, copp_p, copp_may, fmt=clp, mejor_arriba=False) + "</table>"

otif_txt = " → ".join(f"{m[-2:]} {v:.1f}%" for m, v in otif_ser)
otif_dir = "🔻 cayendo" if otif_ser[-1][1] < otif_ser[0][1] else "➡️ estable"

html = f"""<div style="font-family:Arial,sans-serif;color:#222;max-width:720px;line-height:1.5;">
<h2 style="color:{AZ};margin-bottom:2px;">📈 Pulso KPI Operacional — Semanal</h2>
<div style="color:#64748b;font-size:12px;">Semana actual {lbl_act} · vs semana anterior {lbl_prev} · vs Mayo (baseline)</div>

<h3 style="color:{AZ};border-bottom:2px solid {GR};padding-bottom:3px;margin-top:16px;">Operación (CA1)</h3>
{op_tbl}
<div style="font-size:11px;color:{GR2};">Mayo (sem) = promedio semanal del mes. Tendencia = semana actual vs ese promedio.</div>

<h3 style="color:{AZ};border-bottom:2px solid {GR};padding-bottom:3px;margin-top:16px;">Servicio</h3>
<div style="font-size:13px;">OTIF mensual: {otif_txt} <b>{otif_dir}</b> · OFR {ofr:.1f}%{' ⚠️' if ofr<90 else ''} · OCT med {oct_med:.0f}h · Pick accuracy {pacc:.2f}%</div>
<div style="font-size:11px;color:{GR2};">OTIF es mensual (no hay semanal confiable aún).</div>

<h3 style="color:{AZ};border-bottom:2px solid {GR};padding-bottom:3px;margin-top:16px;">COP inferido (base total empresa)</h3>
{cop_tbl}
<div style="font-size:11px;color:{GR2};">Costo semanal estimado = {clp(costo_may)}/mes ÷ 4,33 = {clp(costo_sem)}. COP/unidad es la métrica primaria (estable ante el mix B2B/B2C). Ref Mayo = COP mensual real.</div>

<h3 style="color:{AZ};border-bottom:2px solid {GR};padding-bottom:3px;margin-top:16px;">Stock</h3>
<div style="font-size:13px;">{clp(val_inv)} · {miles(n_crit)} críticos · Sobrestock {clp(sobre)} · Sin venta 90d {miles(sinv)} SKUs</div>

<div style="margin-top:14px;font-size:11px;color:#475569;">Data WMS al {wms['fecha_done'].max():%d-%b} · ventas al {mesact['fecha_venta'].max():%d-%b}</div>
</div>"""

if __name__ == "__main__":
    import re
    print(f"Semana actual: {W_ACT} | anterior: {W_PREV} | WMS max: {wms['fecha_done'].max():%d-%b} | ventas max: {mesact['fecha_venta'].max():%d-%b}")
    print(f"COP sem act: /uds {clp(copu_a)} /ped {clp(copp_a)} (vol {pa} ped, {ua:.0f} uds)")
    if os.environ.get("SEND") == "1":
        from src.gmail_client import GmailClient
        from email.mime.text import MIMEText
        to = [e.strip() for e in os.environ.get("EMAIL_TO", "andres@unionx.cl").split(",") if e.strip()]
        m = MIMEText(html, "html", "utf-8"); m["to"] = ",".join(to); m["from"] = "andres@unionx.cl"
        m["subject"] = f"📈 Pulso KPI Semanal — {lbl_act}"
        raw = base64.urlsafe_b64encode(m.as_bytes()).decode()
        print("Enviado:", GmailClient().service.users().messages().send(userId="me", body={"raw": raw}).execute().get("id"))
    else:
        t = re.sub("<[^>]+>", " ", html); t = re.sub("[ \t]+", " ", t); t = re.sub(" *\n+", "\n", t)
        sys.stdout.buffer.write(t.strip().encode("utf-8"))
