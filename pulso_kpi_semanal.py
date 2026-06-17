# -*- coding: utf-8 -*-
"""Pulso KPI Operacional semanal (lunes). Semana L-D estricta.

Compara la ultima semana COMPLETA vs la semana anterior (week-over-week) y vs
MAYO mes (referencia estable que cierra el sesgo de una semana alta/baja).

DRIVERS (reales, no run-rate ciego):
  - Personas/horas: HORAS_SEMANA por semana (manual; default 5x42=210 h-pers).
    No hay feed automatico de horas -> se cargan aca.
  - Unidades/pedidos: Odoo WMS (pick/entrega) + ventas (total empresa).
  - Costo operativo TOTAL: costo mensual P&L (area OPERACIONES, FCST=real)
    prorrateado /4,33 (mayormente fijo). COP/unidad = costo / uds.
  - OTIF mensual (no hay semanal confiable). Inventario: snapshot actual.

Eventos extraordinarios (Cyber) se reportan en pulso aparte, no aca.
__main__ imprime (no envia). SEND=1 + EMAIL_TO para enviar.
"""
import os, sys, json, base64, datetime
from pathlib import Path
import pandas as pd

ROOT = Path(r"g:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA")
sys.path.insert(0, str(ROOT / "agente-comex"))
AZ = "#1F4E79"; UNX = "#4884FC"; GR = "#EBF0F8"; VE = "#16a34a"; RO = "#dc2626"; GR2 = "#64748B"
def clp(n): return "$" + "{:,.0f}".format(n).replace(",", ".")
def miles(n): return "{:,.0f}".format(n).replace(",", ".")

MES_REF = 5            # Mayo = mes de referencia (ultimo cerrado)
HORAS_MES_REF = 798.0  # mayo: 5 pers x 159,6h (confirmado)
PERS_DEFAULT, HRS_PERS_DEFAULT = 5, 42.0  # semana normal = 210 h-pers
# Horas reales por semana (manual; no hay feed). Default 5x42=210.
HORAS_SEMANA = {
    "2026-06-01/2026-06-07": 419.0,  # Cyber: Lun-Jue 7x12 + Vie 7x9 + Sab 4x5
    "2026-06-08/2026-06-14": 210.0,  # normal: 5 x 42
}
def horas_de(sem_str): return HORAS_SEMANA.get(sem_str, PERS_DEFAULT * HRS_PERS_DEFAULT)

# -- Semanas (L-D, calendario) ----------------------------------------------
_hoy = datetime.date.today()
W_ACT = pd.Timestamp(_hoy).to_period("W-SUN") - 1   # ultima semana terminada
W_PREV = W_ACT - 1
def _key(p): return str(p)
def _wlbl(p): return f"{p.start_time:%d}-{p.end_time:%d} {p.end_time:%b}"

# -- WMS (Odoo) por semana ---------------------------------------------------
wms = pd.read_parquet(ROOT / "data/operaciones/volumen_inventario_hist.parquet")
wms["fecha_done"] = pd.to_datetime(wms["fecha_done"])
wms["sem"] = wms["fecha_done"].dt.to_period("W-SUN")
PICKS = ["Bodega Carrascal Nº9-10: Pick", "Bodega Carrascal N°9-10: Pick"]
def _filt(df, k):
    if k == "pick": return df[df["picking_type_name"].isin(PICKS)]
    return df[df["picking_type_name"].str.contains("Delivery Orders", na=False)
              & df["picking_type_name"].str.contains("Carrascal", na=False)]
def wms_sem(sem):
    d = wms[wms["sem"] == sem]
    return dict(upick=_filt(d, "pick")["n_unidades"].sum(), pent=len(_filt(d, "ent")),
                uent=_filt(d, "ent")["n_unidades"].sum())
wa, wp = wms_sem(W_ACT), wms_sem(W_PREV)
wmay = wms[(wms["fecha_done"].dt.year == 2026) & (wms["fecha_done"].dt.month == MES_REF)]
wmay_v = dict(upick=_filt(wmay, "pick")["n_unidades"].sum(), pent=len(_filt(wmay, "ent")),
              uent=_filt(wmay, "ent")["n_unidades"].sum())

# -- Ventas total empresa (para COP) ----------------------------------------
mesact = pd.read_parquet(ROOT / "data/historico/ventas_mes_actual.parquet",
                         columns=["fecha_venta", "pedido", "cantidad", "venta_neta"])
mesact["fecha_venta"] = pd.to_datetime(mesact["fecha_venta"], errors="coerce")
mesact["sem"] = mesact["fecha_venta"].dt.to_period("W-SUN")
def vta_sem(sem):
    d = mesact[mesact["sem"] == sem]
    return d["pedido"].nunique(), d["cantidad"].sum(), d["venta_neta"].sum()
pa, ua, vna = vta_sem(W_ACT); pp, up, vnp = vta_sem(W_PREV)
hist = pd.read_parquet(ROOT / "data/historico/ventas_historico.parquet",
                       columns=["anio_venta", "mes_venta", "pedido", "cantidad", "venta_neta"])
hmay = hist[(hist["anio_venta"] == 2026) & (hist["mes_venta"] == MES_REF)]
p_may, u_may, vn_may = hmay["pedido"].nunique(), hmay["cantidad"].sum(), hmay["venta_neta"].sum()

# -- Costo operativo TOTAL (P&L area OPERACIONES, FCST=real) -----------------
cg = pd.read_parquet(ROOT / "data/finanzas/control_gestion.parquet")
costo_mes = abs(cg[(cg["year"] == 2026) & (cg["month"] == MES_REF) & (cg["area"] == "OPERACIONES")
                   & (cg["kpi"] == "GASTO") & (cg["escenario"] == "FCST")]["valor"].sum()) * 1000
costo_sem = costo_mes / 4.33  # prorrateo run-rate (costo mayormente fijo)

# -- Productividad y COP por columna -----------------------------------------
h_act, h_prev = horas_de(_key(W_ACT)), horas_de(_key(W_PREV))
def prod(upick, horas): return upick / horas if horas else 0
prod_a, prod_p, prod_may = prod(wa["upick"], h_act), prod(wp["upick"], h_prev), prod(wmay_v["upick"], HORAS_MES_REF)
def cu(uds): return costo_sem / uds if uds else 0
def cp(ped): return costo_sem / ped if ped else 0
copu_a, copu_p, copu_may = cu(ua), cu(up), (costo_mes / u_may if u_may else 0)
copp_a, copp_p, copp_may = cp(pa), cp(pp), (costo_mes / p_may if p_may else 0)
pctv_a = costo_sem / vna * 100 if vna else 0
pctv_p = costo_sem / vnp * 100 if vnp else 0
pctv_may = costo_mes / vn_may * 100 if vn_may else 0
BENCH = 40.1

# -- Servicio (snapshot) + Stock ---------------------------------------------
snap = json.load(open(ROOT / "data/kpis_wms/snapshot.json", encoding="utf-8"))
rpm = snap.get("otif_drive", {}).get("resumen_por_mes", {})
otif_ser = [(m, rpm[m]["otif_total_pct"] * 100) for m in sorted(rpm.keys())[-4:]] if rpm else []
K = snap.get("kpis", {})
ofr = K.get("ofr_30d", {}).get("valor", 0) * 100
pacc = K.get("pick_accuracy_30d", {}).get("valor", 0) * 100
oct_med = K.get("oct_30d", {}).get("mediana_h", 0)
sku = pd.read_parquet(ROOT / "data/stock/skus.parquet").drop_duplicates("SKU")
val_inv = sku["Valor"].sum(); n_crit = int((sku["Semaforo"] == "CRITICO").sum())
sobre = sku[sku["Semaforo"] == "SOBRESTOCK"]["Valor"].sum()
sinv = int(((sku["Semaforo"] == "SIN VENTA") & (sku["Vta 90d Qty"].fillna(0) == 0)).sum())

# -- HTML --------------------------------------------------------------------
UP, DN = "\U0001f53a", "\U0001f53b"  # triangulos arriba/abajo
def th(t, a="right"): return f'<th style="padding:7px 9px;text-align:{a};color:#fff;font-size:11px;">{t}</th>'
def td(t, a="right", c=""): return f'<td style="padding:6px 9px;text-align:{a};{c}">{t}</td>'
def tr(i, cells): return f'<tr style="background:{GR if i%2==0 else "#fff"};font-size:12px;">{"".join(cells)}</tr>'
def flecha(cur, ref, mejor_arriba=True):
    if not ref: return ("—", GR2)
    d = (cur - ref) / abs(ref) * 100
    if abs(d) <= 1.5: return (f"➡️ {d:+.0f}%", GR2)
    sube = d > 0
    return (f"{UP if sube else DN} {d:+.0f}%", VE if (sube == mejor_arriba) else RO)

lbl_a, lbl_p = _wlbl(W_ACT), _wlbl(W_PREV)
HOP = (f'<tr style="background:{AZ};">{th("Operación (CA1)","left")}{th("Sem "+lbl_a)}'
       f'{th("Sem "+lbl_p)}{th("Δ sem ant")}{th("Mayo mes")}</tr>')
def rop(i, lbl, a, p, may):
    f, col = flecha(a, p)
    return tr(i, [td(lbl, "left"), td(miles(a), c="font-weight:bold;"), td(miles(p), c="color:#94a3b8;"),
                  td(f, c=f"color:{col};"), td(miles(may))])
op_tbl = f'<table style="width:100%;border-collapse:collapse;">{HOP}' + \
    rop(0, "Uds pickeadas", wa["upick"], wp["upick"], wmay_v["upick"]) + \
    rop(1, "Uds entregadas", wa["uent"], wp["uent"], wmay_v["uent"]) + \
    rop(0, "Pedidos despachados", wa["pent"], wp["pent"], wmay_v["pent"]) + \
    rop(1, "Horas (h·pers)", h_act, h_prev, HORAS_MES_REF) + "</table>"

HEF = (f'<tr style="background:{AZ};">{th("Eficiencia","left")}{th("Sem "+lbl_a)}'
       f'{th("Sem "+lbl_p)}{th("Mayo mes")}{th("Δ vs Mayo")}</tr>')
def reff(i, lbl, a, p, may, fmt, mejor_arriba):
    f, col = flecha(a, may, mejor_arriba)
    return tr(i, [td(lbl, "left"), td(fmt(a), c="font-weight:bold;"), td(fmt(p), c="color:#94a3b8;"),
                  td(fmt(may)), td(f, c=f"color:{col};")])
_p1 = lambda x: f"{x:.1f}"
ef_tbl = f'<table style="width:100%;border-collapse:collapse;">{HEF}' + \
    reff(0, "Productividad (uds pick/h)", prod_a, prod_p, prod_may, _p1, True) + \
    reff(1, "COP / unidad", copu_a, copu_p, copu_may, clp, False) + \
    reff(0, "COP / pedido", copp_a, copp_p, copp_may, clp, False) + \
    reff(1, "% Costo / venta", pctv_a, pctv_p, pctv_may, lambda x: f"{x:.1f}%", False) + "</table>"

otif_txt = " → ".join(f"{m[-2:]} {v:.1f}%" for m, v in otif_ser) if otif_ser else "s/d"
otif_dir = (f"{DN} cayendo" if (otif_ser and otif_ser[-1][1] < otif_ser[0][1]) else "➡️ estable")

html = f"""<div style="font-family:Arial,sans-serif;color:#222;max-width:740px;line-height:1.5;">
<h2 style="color:{AZ};margin-bottom:2px;">\U0001f4c8 Pulso KPI Operacional — Semanal</h2>
<div style="color:#64748b;font-size:12px;">Semana <b>{lbl_a}</b> · vs semana anterior {lbl_p} · vs Mayo (mes)</div>

<h3 style="color:{AZ};border-bottom:2px solid {GR};padding-bottom:3px;margin-top:16px;">Operación</h3>
{op_tbl}
<div style="font-size:11px;color:{GR2};">Volúmenes: comparación semana vs semana · Mayo mes = escala (total del mes).</div>

<h3 style="color:{AZ};border-bottom:2px solid {GR};padding-bottom:3px;margin-top:16px;">Eficiencia (vs Mayo mes)</h3>
{ef_tbl}
<div style="font-size:11px;color:{GR2};">Productividad = uds pickeadas / horas reales de la semana (bench {BENCH} uds/h).
COP = costo operativo total prorrateado ({clp(costo_mes)}/mes ÷ 4,33 = {clp(costo_sem)}/sem) ÷ volumen.
COP/unidad = métrica primaria. Comparación vs Mayo mes (cierra el sesgo de una semana alta/baja).</div>

<h3 style="color:{AZ};border-bottom:2px solid {GR};padding-bottom:3px;margin-top:16px;">Servicio &amp; Stock</h3>
<div style="font-size:13px;">OTIF mensual: {otif_txt} <b>{otif_dir}</b> · OFR {ofr:.1f}% · OCT {oct_med:.0f}h · Pick {pacc:.2f}%</div>
<div style="font-size:13px;margin-top:4px;">Inventario {clp(val_inv)} · {miles(n_crit)} críticos · Sobrestock {clp(sobre)} · Sin venta 90d {miles(sinv)} SKUs</div>
<div style="font-size:11px;color:{GR2};margin-top:4px;">OTIF mensual (no hay semanal confiable). Inventario = foto actual.</div>
</div>"""

if __name__ == "__main__":
    print(f"Sem actual {lbl_a} ({_key(W_ACT)}) | anterior {lbl_p} | horas: act {h_act:.0f} prev {h_prev:.0f} mayo {HORAS_MES_REF:.0f}")
    print(f"Uds pick: act {miles(wa['upick'])} | prev {miles(wp['upick'])} | mayo {miles(wmay_v['upick'])}")
    print(f"Uds ent : act {miles(wa['uent'])} | prev {miles(wp['uent'])} | mayo {miles(wmay_v['uent'])}")
    print(f"Prod    : act {prod_a:.1f} | prev {prod_p:.1f} | mayo {prod_may:.1f} uds/h")
    print(f"Costo   : mes {clp(costo_mes)} | sem {clp(costo_sem)}")
    print(f"COP/uds : act {clp(copu_a)} | prev {clp(copu_p)} | mayo {clp(copu_may)}")
    print(f"COP/ped : act {clp(copp_a)} | prev {clp(copp_p)} | mayo {clp(copp_may)}")
    print(f"%cto/vta: act {pctv_a:.1f}% | prev {pctv_p:.1f}% | mayo {pctv_may:.1f}%")
    if os.environ.get("SEND") == "1":
        from email.mime.text import MIMEText
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        cj = os.environ.get("GMAIL_TOKEN_JSON", "")
        if not cj:
            _tp = ROOT / "agente-comex" / "config" / "token.json"
            cj = _tp.read_text() if _tp.exists() else ""
        cd = json.loads(cj); creds = Credentials.from_authorized_user_info(cd, cd.get("scopes"))
        if creds.expired and creds.refresh_token: creds.refresh(Request())
        svc = build("gmail", "v1", credentials=creds)
        to = [e.strip() for e in os.environ.get("EMAIL_TO", "andres@unionx.cl").split(",") if e.strip()]
        m = MIMEText(html, "html", "utf-8"); m["to"] = ",".join(to); m["from"] = "andres@unionx.cl"
        m["subject"] = f"\U0001f4c8 Pulso KPI Semanal — {lbl_a}"
        raw = base64.urlsafe_b64encode(m.as_bytes()).decode()
        print("Enviado:", svc.users().messages().send(userId="me", body={"raw": raw}).execute().get("id"))
    else:
        import re
        t = re.sub("<[^>]+>", " ", html); t = re.sub("[ \t]+", " ", t); t = re.sub(" *\n+", "\n", t)
        sys.stdout.buffer.write(t.strip().encode("utf-8"))
