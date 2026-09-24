# -*- coding: utf-8 -*-
"""
Dashboard financiero de cierre del mes — "¿cómo vamos y cómo cerramos?" (solo Andrés).

Genera un HTML oscuro con ECharts (estilo FP&A) desde los datos del repo:
  - cierre_mes.proyectar_cierre(): proyección de cierre, margen calibrado, desviaciones
  - ventas_mes_actual / ventas_historico: curva diaria real vs meta vs proyección
  - Metas 2026, Fcst EERR, P&L (GAV por partida), KT (meses de inventario)

Uso:
  python dashboard_cierre.py                # genera data/outputs/dashboard_cierre_mes.html
  python dashboard_cierre.py --enviar       # además lo manda por mail a andres@unionx.cl
"""
from __future__ import annotations

import base64
import calendar
import json
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

from cierre_mes import MESES, RECURRENTES, _metas_2026, _tn, proyectar_cierre

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "outputs" / "dashboard_cierre_mes.html"


def es(v, dec=1):
    if round(v, dec) == 0:
        v = 0.0
    s = f"{abs(v):,.{dec}f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return ("−" if v < 0 else "") + s


def mm(v, dec=1):
    return ("−$" if round(v, dec) < 0 else "$") + es(abs(v), dec) + " M"


def pct(v, dec=1):
    return ("+" if v >= 0 else "−") + es(abs(v), dec) + "%"


# ------------------------------------------------------------------ datos
def datos():
    p = proyectar_cierre()
    anio, mes, dia, dias_mes = p["anio"], p["mes"], p["dia"], p["dias_mes"]
    meta = p["meta"]

    # --- curva diaria: real acumulado (fuente producción, con exclusiones), meta prorrateada
    # (curva LY total) y proyección
    cols = ["fecha_venta", "tipo_negocio", "venta_neta"]
    real_acum = pd.Series(p["diario"]).sort_index().cumsum()

    hist = pd.read_parquet(ROOT / "data/historico/ventas_historico.parquet", columns=cols)
    hist["fecha_venta"] = pd.to_datetime(hist["fecha_venta"])
    ly = hist[(hist.fecha_venta.dt.year == anio - 1) & (hist.fecha_venta.dt.month == mes)]
    dias_ly = calendar.monthrange(anio - 1, mes)[1]

    def curva(df):
        d = df.groupby(df.fecha_venta.dt.day).venta_neta.sum().reindex(range(1, dias_ly + 1), fill_value=0)
        c = d.cumsum() / d.sum() if d.sum() else pd.Series([i / dias_ly for i in range(1, dias_ly + 1)],
                                                         index=range(1, dias_ly + 1))
        return c.reindex(range(1, dias_mes + 1)).ffill().fillna(1.0)

    c_tot = curva(ly)
    c_rec = curva(ly[_tn(ly["tipo_negocio"]).isin(RECURRENTES)])
    meta_acum = meta["Venta"] * c_tot
    s0 = c_rec.loc[dia]
    proy = {}
    for d in range(dia, dias_mes + 1):
        frac = (c_rec.loc[d] - s0) / (1 - s0) if s0 < 1 else 1
        proy[d] = p["venta_acum"] + (p["venta_proy"] - p["venta_acum"]) * frac

    # --- ingresos por línea de negocio (real a la fecha + proyección vs meta PPTO)
    lineas = []
    for l in sorted(p["lineas"], key=lambda l: -max(l["proy"], l["meta_venta"])):
        if l["meta_venta"] <= 0 or l["linea"] == "Otros":
            continue
        lineas.append({"n": l["linea"], "real": l["acum"], "proy": l["proy"], "meta": l["meta_venta"],
                       "var": (l["proy"] / l["meta_venta"] - 1) * 100, "regla": l["regla"]})

    # --- YTD: meses cerrados (Fcst EERR real) + mes en curso proyectado
    f = pd.read_parquet(ROOT / "data/finanzas/fcst_eerr.parquet")

    def fl(y, m1, m2, linea):
        s = f[(f.year == y) & (f.month >= m1) & (f.month <= m2) & (f.linea == linea)]
        return float(s.valor_fcst.sum()) / 1e6

    L = {"venta": "Ingreso de Explotación", "mc": "Margen de Contribución", "gav": "TOTAL GAV",
         "ebitda": "EBITDA", "md": "Margen de Explotación"}
    ytd = {k: fl(anio, 1, mes - 1, l) for k, l in L.items()}
    ytd["gav"] = abs(ytd["gav"])
    ytd["venta"] += p["venta_proy"]
    ytd["mc"] += p["mc_proy"]
    ytd["md"] += p["md_proy"]
    ytd["gav"] += p["gav"]
    ytd["ebitda"] += p["ebitda_proy"]
    ly_ytd = {k: fl(anio - 1, 1, mes, l) for k, l in L.items()}
    ly_ytd["gav"] = abs(ly_ytd["gav"])
    ly_mes = {k: fl(anio - 1, mes, mes, l) for k, l in L.items()}
    ly_mes["gav"] = abs(ly_mes["gav"])
    meta_ytd = {"venta": 0.0, "mc": 0.0, "gav": 0.0, "ebitda": 0.0}
    for mth in range(1, mes + 1):
        mt = _metas_2026(anio, mth)
        meta_ytd["venta"] += mt["Venta"]
        meta_ytd["mc"] += mt["Contribución"]
        meta_ytd["gav"] += mt["GAV"]
        meta_ytd["ebitda"] += mt["EBITDA"]

    # --- tendencia EBITDA 12 meses (cerrados) + mes en curso proyectado
    tend = []
    y, m = anio, mes
    for _ in range(12):
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        v = fl(y, m, m, L["venta"])
        e = fl(y, m, m, L["ebitda"])
        tend.append({"lbl": f"{MESES[m - 1]}-{str(y)[2:]}", "ebitda": e, "mg": e / v * 100 if v else 0, "proy": False})
    tend.reverse()
    tend.append({"lbl": p["etiqueta"] + "e", "ebitda": p["ebitda_proy"],
                 "mg": p["ebitda_proy"] / p["venta_proy"] * 100 if p["venta_proy"] else 0, "proy": True})

    # --- composición GAV último mes cerrado (P&L)
    pyl = pd.read_parquet(ROOT / "data/finanzas/pyl_mensual.parquet")
    yg, mg_ = (anio, mes - 1) if mes > 1 else (anio - 1, 12)
    g = pyl[(pyl.year == yg) & (pyl.month == mg_) & (pyl.seccion == "Gastos de Administración y Vtas:")
            & ~pyl.linea.isin(["Total GAV", "Resultado Operacional"])].groupby("linea").valor.sum().abs() / 1000
    grupos = {"Remuneraciones": ["Sueldos, honorarios y leyes sociales"],
              "Oficina y arriendos": ["Oficina y arriendos"],
              "Marketing branding": ["Marketing Branding"]}
    comp = []
    usado = set()
    for nom, ls in grupos.items():
        v = float(g.reindex(ls).fillna(0).sum())
        usado |= set(ls)
        comp.append({"name": nom, "value": round(v, 1)})
    comp.append({"name": "Resto GAV", "value": round(float(g[~g.index.isin(usado)].sum()), 1)})
    gav_mes_lbl = f"{MESES[mg_ - 1]}-{str(yg)[2:]}"

    # --- meses de inventario (último balance real: planilla cargada hasta mes-2)
    kt = pd.read_parquet(ROOT / "data/finanzas/kt.parquet")
    yk, mk = (anio, mes - 2) if mes > 2 else (anio - 1, mes + 10)
    s = kt[(kt.year == yk) & (kt.month == mk) & (kt.linea == "Meses de existencias móvil")].valor
    meses_inv = float(s.iloc[0]) if len(s) else None
    inv_lbl = f"{MESES[mk - 1]}-{str(yk)[2:]}"

    return dict(p=p, real_acum=real_acum, meta_acum=meta_acum, proy=proy, lineas=lineas,
                ytd=ytd, ly_ytd=ly_ytd, ly_mes=ly_mes, meta_ytd=meta_ytd, tend=tend, comp=comp,
                gav_mes_lbl=gav_mes_lbl, meses_inv=meses_inv, inv_lbl=inv_lbl)


# ------------------------------------------------------------------ HTML
def semaforo(D):
    p, m = D["p"], D["p"]["meta"]
    out = []

    def add(nombre, estado, valor, ref):
        out.append({"n": nombre, "e": estado, "v": valor, "r": ref})

    pv = p["venta_proy"] / m["Venta"] * 100 if m["Venta"] else 0
    add("Venta vs FCST", "v" if pv >= 100 else ("a" if pv >= 90 else "r"), f"{es(pv, 0)}%", "verde ≥100% · amarillo ≥90%")
    mc_meta = m["Contribución"] / m["Venta"] * 100 if m["Venta"] else 0
    dmc = p["mc_pct"] * 100 - mc_meta
    add("Margen contribución", "v" if dmc >= 0 else ("a" if dmc >= -1 else "r"),
        f"{es(p['mc_pct'] * 100)}%", f"FCST {es(mc_meta)}%")
    add("EBITDA del mes", {"verde": "v", "amarillo": "a", "rojo": "r"}[p["semaforo"]],
        mm(p["ebitda_proy"]), f"FCST {mm(m['EBITDA'])}")
    gy, gm = D["ytd"]["gav"], D["meta_ytd"]["gav"]
    dg = (gy / gm - 1) * 100 if gm else 0
    add("GAV acumulado año", "v" if dg <= 0 else ("a" if dg <= 3 else "r"), mm(gy, 0), f"ppto {mm(gm, 0)} ({pct(dg)})")
    mi = D["meses_inv"]
    if mi is not None:
        add(f"Meses de inventario ({D['inv_lbl']})", "v" if mi <= 5.5 else ("a" if mi <= 6.5 else "r"),
            es(mi), "mercado 3–5,5")
    return out


def render(D) -> str:
    p, m = D["p"], D["p"]["meta"]
    dias = list(range(1, p["dias_mes"] + 1))
    real = [round(D["real_acum"].get(d), 1) if d <= p["dia"] else None for d in dias]
    meta_c = [round(D["meta_acum"].loc[d], 1) for d in dias]
    proy = [round(D["proy"][d], 1) if d in D["proy"] else None for d in dias]

    mgn_proy = p["ebitda_proy"] / p["venta_proy"] * 100 if p["venta_proy"] else 0
    mgn_meta = m["EBITDA"] / m["Venta"] * 100 if m["Venta"] else 0
    frac = p["dia"] / p["dias_mes"]
    fc = p["ppto"]
    vp, vm, va = p["venta_proy"], m["Venta"], p["venta_acum"]
    md_prev = p.get("md_prev_pct")
    # (título, real a la fecha, proyección, FCST, es gasto, ppto, base % real, base % proy, base % fcst, extra)
    kpis = [
        ("Ingresos (venta neta)", va, vp, vm, False, fc["Venta"], None, None, None, ""),
        ("Margen directo", p["md_acum"], p["md_proy"], m["MD"], False, None, va, vp, vm,
         (f"mes anterior {es(md_prev * 100)}% · " if md_prev is not None else "") +
         f"var {('+' if p['md_proy'] / vp - md_prev >= 0 else '−') if md_prev is not None else ''}"
         f"{es(abs(p['md_proy'] / vp - md_prev) * 100) + ' pp' if md_prev is not None else ''}"),
        ("Margen de contribución", p["mc_acum"], p["mc_proy"], m["Contribución"], False, fc["Contribución"], va, vp, vm, ""),
        ("Gastos operativos (GAV)", p["gav"] * frac, p["gav"], m["GAV"], True, fc["GAV"], va, vp, vm, ""),
        ("EBITDA", p["mc_acum"] - (p["gav"] - p["da"]) * frac, p["ebitda_proy"], m["EBITDA"], False, None, va, vp, vm, ""),
    ]

    def spv(v, base):
        return f"<span class='sv'>{es(v / base * 100)}%</span>" if base else ""

    def card(t, real_, proy_, meta_, gasto, ppto_, b_real, b_proy, b_meta, extra_txt):
        gap = proy_ - meta_
        ok = (gap <= 0) if gasto else (gap >= 0)
        # % solo cuando la referencia es positiva y relevante; si no, diferencia en pesos
        if meta_ and meta_ >= 10 and abs(meta_) >= abs(proy_) * 0.2:
            var = pct(gap / meta_ * 100)
        else:
            var = ("+" if gap >= 0 else "−") + mm(abs(gap))[1:]
        sub = f"FCST {mm(meta_)}{spv(meta_, b_meta)}" + (f" · ppto {mm(ppto_, 0)}" if ppto_ else "")
        col = "#22C55E" if ok else "#EF4444"
        arrow = "▲" if gap >= 0 else "▼"
        realtxt = (f"<div class='kr'>Real al {p['dato_hasta'].strftime('%d-%m')}: <b>{mm(real_)}</b>{spv(real_, b_real)}</div>"
                   if real_ is not None else "<div class='kr'>&nbsp;</div>")
        badge = " <span class='plan'>fcst eerr</span>" if gasto else ""
        extra = f"<div class='kx'>{extra_txt}</div>" if extra_txt else ""
        return f"""<div class="card"><div class="kt">{t}{badge}</div>
          <div class="kv">{mm(proy_)}{spv(proy_, b_proy)}</div><div class="kp">proyección de cierre</div>
          <div class="kvar" style="color:{col}">{arrow} {var} <span class="kmeta">{sub}</span></div>{extra}{realtxt}</div>"""

    cards = "".join(card(*k) for k in kpis)

    def row_ytd(nombre, k, gasto=False):
        y, my_, ly = D["ytd"][k], D["meta_ytd"][k], D["ly_ytd"][k]
        d1, d2 = y - my_, y - ly

        def c(d):
            ok = (d <= 0) if gasto else (d >= 0)
            return "pos" if ok else "neg"
        pm_ = (d1 / abs(my_) * 100) if my_ else 0
        sp = (lambda v, b: f"<span class='sv'>{es(v / b * 100)}%</span>" if (k != "venta" and b) else "")
        return (f"<tr><td>{nombre}</td><td class='n'>{mm(y, 0)}{sp(y, D['ytd']['venta'])}</td>"
                f"<td class='n mut'>{mm(my_, 0)}{sp(my_, D['meta_ytd']['venta'])}</td>"
                f"<td class='n {c(d1)}'>{pct(pm_)}</td><td class='n mut'>{mm(ly, 0)}</td>"
                f"<td class='n {c(d2)}'>{pct(d2 / abs(ly) * 100) if ly else '—'}</td></tr>")

    tabla_ytd = (row_ytd("Venta neta", "venta") + row_ytd("Margen contribución", "mc")
                 + row_ytd("GAV", "gav", True) + row_ytd("EBITDA", "ebitda"))

    def row_mes(nombre, proy_, meta_, ly_, gasto=False, pctv=True):
        d = proy_ - meta_
        ok = (d <= 0) if gasto else (d >= 0)
        sp = (lambda v, b: f"<span class='sv'>{es(v / b * 100)}%</span>" if (pctv and b) else "")
        return (f"<tr><td>{nombre}</td><td class='n'>{mm(proy_)}{sp(proy_, p['venta_proy'])}</td>"
                f"<td class='n mut'>{mm(meta_)}{sp(meta_, m['Venta'])}</td>"
                f"<td class='n {'pos' if ok else 'neg'}'>{'+' if d >= 0 else '−'}{mm(abs(d))[1:]}</td>"
                f"<td class='n mut'>{mm(ly_)}</td></tr>")

    tabla_cierre = (row_mes("Venta neta", p["venta_proy"], m["Venta"], D["ly_mes"]["venta"], pctv=False)
                    + row_mes("Margen directo", p["md_proy"], m["MD"], D["ly_mes"].get("md", 0.0))
                    + row_mes("Margen contribución", p["mc_proy"], m["Contribución"], D["ly_mes"]["mc"])
                    + row_mes("GAV (fcst)", p["gav"], m["GAV"], D["ly_mes"]["gav"], True)
                    + row_mes("EBITDA", p["ebitda_proy"], m["EBITDA"], D["ly_mes"]["ebitda"]))

    desv = p["desviaciones"]
    top = [d for d in desv if d[3] < 0][:4] + [d for d in reversed(desv) if d[3] > 0][:3]
    tabla_desv = "".join(
        f"<tr><td>{c}</td><td class='n'>{mm(v)}</td><td class='n mut'>{mm(mt)}</td>"
        f"<td class='n {'pos' if g >= 0 else 'neg'}'>{'+' if g >= 0 else '−'}{mm(abs(g))[1:]}</td></tr>"
        for c, v, mt, g in top)

    sem = semaforo(D)
    colsem = {"v": "#22C55E", "a": "#F59E0B", "r": "#EF4444"}
    tabla_sem = "".join(
        f"<tr><td><span class='dot' style='background:{colsem[s['e']]}'></span>{s['n']}</td>"
        f"<td class='n'>{s['v']}</td><td class='mut small'>{s['r']}</td></tr>" for s in sem)

    lin = D["lineas"]
    lin_cats = [l["n"] for l in lin if l["meta"]]
    lin_real = [round(l["real"], 1) for l in lin if l["meta"]]
    lin_proy = [round(l["proy"], 1) for l in lin if l["meta"]]
    lin_meta = [round(l["meta"], 1) for l in lin if l["meta"]]
    lin_var = [(f"{'+' if l['var'] >= 0 else '−'}{es(abs(l['var']), 0)}%" if l["var"] is not None else "") for l in lin if l["meta"]]

    tend = D["tend"]
    t_lbl = [t["lbl"] for t in tend]
    t_eb = [{"value": round(t["ebitda"], 1), "itemStyle": {"color": "#F59E0B" if t["proy"] else ("#3B82F6" if t["ebitda"] >= 0 else "#EF4444")}} for t in tend]
    t_mg = [round(t["mg"], 1) for t in tend]

    # --- detalle por línea: regla aplicada y margen (base FCST + operaciones puntuales)
    tabla_lin = ""
    for l in p["lineas"]:
        if l["linea"] == "Otros":
            continue
        senal = f"{es(l['mc_senal'] * 100)}%" if l["mc_senal"] is not None else "—"
        punt = mm(l["puntual_venta"]) if l["puntual_venta"] else "—"
        tabla_lin += (f"<tr><td>{l['linea']}</td><td class='n'>{mm(l['acum'])}</td><td class='n'>{mm(l['proy'])}</td>"
                      f"<td class='n mut'>{mm(l['fcst_venta'])}</td><td class='n mut'>{mm(l['ppto_venta'])}</td>"
                      f"<td class='small'>{l['regla']}</td><td class='n'>{es(l['base_pct'] * 100)}% <span class='sv'>{l['fuente_base']}</span></td>"
                      f"<td class='n mut'>{senal}</td><td class='n'>{punt}</td><td class='n'><b>{es(l['mc_pct'] * 100)}%</b></td></tr>")

    tabla_ops = "".join(
        f"<tr><td>{o['documento']}</td><td>{o['canal']}</td><td class='n'>{mm(o['venta'])}</td>"
        f"<td class='n'>{es(o['mc_pct'] * 100)}%{' ✎' if o['override'] else ''}</td><td class='n mut'>{es(o['base_pct'] * 100)}%</td>"
        f"<td class='n {'pos' if o['impacto'] >= 0 else 'neg'}'>{'+' if o['impacto'] >= 0 else '−'}{mm(abs(o['impacto']))[1:]}</td></tr>"
        for o in sorted(p["operaciones"], key=lambda o: -abs(o["impacto"]))) or \
        "<tr><td colspan='6' class='mut'>Sin operaciones puntuales ≥ $5M este mes</td></tr>"

    alertas = []
    imp = sum(o["impacto"] for o in p["operaciones"])
    if p["operaciones"]:
        alertas.append(f"Las operaciones puntuales aportan {'+' if imp >= 0 else '−'}{mm(abs(imp))[1:]} de margen sobre la base de su línea. "
                       "Su margen sale del RAW; si no corresponde, se corrige caso a caso (✎ = corregido).")
    if p["excluidos"]:
        docs = ", ".join(e["documento"] for e in p["excluidos"])
        alertas.append(f"Documentos excluidos por decisión ({mm(p['excluido_mm'])} en el dato actual): {docs} — "
                       f"{p['excluidos'][0]['motivo']}. Cuando entre la factura reemitida hay que excluirla (si no, la venta se duplica).")
    if p["fuente"] != "producción":
        alertas.append(f"Fuente: {p['fuente']} — el dato puede estar desfasado.")
    asum = [l["linea"] for l in p["lineas"] if l["regla"].startswith("FCST")]
    if asum:
        alertas.append(f"Se asume que cumple el FCST: {', '.join(asum)}.")
    html_alertas = "".join(f"<li>{a}</li>" for a in alertas)

    ahora = datetime.now().strftime("%d-%m-%Y %H:%M")
    J = json.dumps
    return f"""<title>Cierre del Mes UnionX</title>
<meta charset="utf-8">
<style>
:root{{--bg:#0A1424;--panel:#101D33;--line:#1E2E4A;--ink:#E6EDF7;--mut:#8397B5;--blue:#3B82F6;--pos:#22C55E;--neg:#EF4444;--amb:#F59E0B}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:'Segoe UI',system-ui,-apple-system,sans-serif;font-size:13px}}
.wrap{{max-width:1500px;margin:0 auto;padding:18px 22px 30px}}
header{{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;margin-bottom:14px;flex-wrap:wrap}}
h1{{margin:0;font-size:24px;letter-spacing:.01em}} h1 span{{color:var(--blue)}}
.sub{{color:var(--mut);font-size:12.5px;margin-top:3px}}
.chips{{display:flex;gap:8px;flex-wrap:wrap}}
.chip{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 12px;font-size:12px;color:var(--mut)}}
.chip b{{color:var(--ink);font-weight:600}}
.cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:12px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px 15px}}
.kt{{color:var(--mut);font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}}
.plan{{background:#1E2E4A;color:#9FB3D1;border-radius:4px;padding:1px 5px;font-size:9.5px;margin-left:4px}}
.kv{{font-size:26px;font-weight:700;margin-top:6px;font-variant-numeric:tabular-nums}}
.kp{{color:var(--mut);font-size:10.5px;margin-top:-2px}}
.kvar{{font-size:13px;font-weight:600;margin-top:7px}} .kmeta{{color:var(--mut);font-weight:400;font-size:11.5px;margin-left:4px}}
.sv{{font-size:11px;font-weight:500;color:var(--mut);margin-left:6px;font-variant-numeric:tabular-nums}}
.kx{{color:var(--mut);font-size:11px;margin-top:3px}}
.kr{{color:var(--mut);font-size:11.5px;margin-top:5px;border-top:1px solid var(--line);padding-top:6px}} .kr b{{color:var(--ink)}}
.grid{{display:grid;gap:12px;margin-bottom:12px}}
.g2{{grid-template-columns:1.55fr 1fr}} .g3{{grid-template-columns:1.2fr .9fr 1fr}} .g3b{{grid-template-columns:1.1fr 1fr 1fr}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;min-width:0}}
.pt{{font-size:13.5px;font-weight:700;margin-bottom:2px}} .ps{{color:var(--mut);font-size:11px;margin-bottom:6px}}
.ch{{width:100%;height:270px}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th{{color:var(--mut);font-weight:600;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;text-align:right;padding:6px 6px;border-bottom:1px solid var(--line)}}
th:first-child,td:first-child{{text-align:left}}
td{{padding:6px 6px;border-bottom:1px solid var(--line)}}
.n{{text-align:right;font-variant-numeric:tabular-nums;font-family:Consolas,'Cascadia Mono',monospace;font-size:12px}}
.mut{{color:var(--mut)}} .pos{{color:var(--pos)}} .neg{{color:var(--neg)}} .small{{font-size:11px}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;vertical-align:-1px}}
footer{{color:var(--mut);font-size:11px;line-height:1.5;margin-top:6px}}
@media(max-width:1100px){{.cards{{grid-template-columns:repeat(2,1fr)}}.g2,.g3,.g3b{{grid-template-columns:1fr}}}}
</style>
<div class="wrap">
<header>
  <div><h1>Dashboard Financiero · <span>{p['etiqueta']}</span></h1>
  <div class="sub">¿Cómo vamos y cómo cerramos? · Comercial Innovatek SpA · MM CLP neto</div></div>
  <div class="chips">
    <div class="chip">Dato de venta al <b>{p['dato_hasta'].strftime('%d-%m-%Y')}</b></div>
    <div class="chip">Día <b>{p['dia']}/{p['dias_mes']}</b> · llevamos el <b>{es(p['share_ly'] * 100, 0)}%</b> del mes</div>
    <div class="chip">Comparación: <b>FCST vigente</b> · ppto referencia</div>
  </div>
</header>

<div class="cards">{cards}</div>

<div class="grid g2">
  <div class="panel"><div class="pt">Desempeño diario del mes</div>
    <div class="ps">Venta neta acumulada · real vs FCST prorrateado vs proyección de cierre</div>
    <div id="c_dia" class="ch"></div></div>
  <div class="panel"><div class="pt">Ingresos por línea de negocio</div>
    <div class="ps">Real a la fecha, proyección de cierre y FCST del mes</div>
    <div id="c_lin" class="ch"></div></div>
</div>

<div class="grid g3">
  <div class="panel"><div class="pt">Variaciones principales · acumulado año</div>
    <div class="ps">Ene–{MESES[p['mes'] - 1]} (meses cerrados reales + {p['etiqueta']} proyectado)</div>
    <table><tr><th>Línea</th><th>Real+proy</th><th>Ppto</th><th>vs ppto</th><th>Año ant.</th><th>vs AA</th></tr>{tabla_ytd}</table></div>
  <div class="panel"><div class="pt">Composición del GAV</div>
    <div class="ps">Último mes cerrado ({D['gav_mes_lbl']}) · MM CLP</div>
    <div id="c_gav" class="ch" style="height:230px"></div></div>
  <div class="panel"><div class="pt">Top desviaciones del mes</div>
    <div class="ps">Canales recurrentes · proyección de cierre vs FCST</div>
    <table><tr><th>Canal</th><th>Proy.</th><th>FCST</th><th>Desv.</th></tr>{tabla_desv}</table></div>
</div>

<div class="grid g3b">
  <div class="panel"><div class="pt">EBITDA y margen</div>
    <div class="ps">Últimos 12 meses cerrados + {p['etiqueta']} proyectado (naranjo)</div>
    <div id="c_eb" class="ch" style="height:240px"></div></div>
  <div class="panel"><div class="pt">Proyección de cierre de mes</div>
    <div class="ps">Si seguimos al ritmo actual</div>
    <table><tr><th>Línea</th><th>Proyección</th><th>FCST</th><th>Desv.</th><th>{MESES[p['mes'] - 1]}-{str(p['anio'] - 1)[2:]}</th></tr>{tabla_cierre}</table></div>
  <div class="panel"><div class="pt">Semáforo de la operación</div>
    <div class="ps">Estado al cierre proyectado</div>
    <table>{tabla_sem}</table></div>
</div>

<div class="grid">
  <div class="panel"><div class="pt">Proyección por línea de negocio</div>
    <div class="ps">Regla de venta · margen de contribución base (resultado del mes anterior o FCST) · señal del RAW (solo referencia) · operaciones puntuales con margen propio</div>
    <table><tr><th>Línea</th><th>Real</th><th>Proyección</th><th>FCST</th><th>Ppto</th><th style="text-align:left">Regla</th><th>MC base (fuente)</th><th>Señal RAW</th><th>Puntual</th><th>MC final</th></tr>{tabla_lin}</table></div>
</div>
<div class="grid" style="grid-template-columns:1.1fr 1fr">
  <div class="panel"><div class="pt">Operaciones puntuales del mes</div>
    <div class="ps">Documentos ≥ $5M · van con su margen propio, separados del flujo normal</div>
    <table><tr><th>Documento</th><th style="text-align:left">Canal</th><th>Venta</th><th>MC</th><th>Base línea</th><th>Impacto margen</th></tr>{tabla_ops}</table></div>
  <div class="panel"><div class="pt">Alertas del dato y supuestos</div>
    <div class="ps">Lo que hay que tener presente al leer este dashboard</div>
    <ul style="margin:4px 0 0;padding-left:18px;line-height:1.55;font-size:12.5px">{html_alertas}</ul></div>
</div>

<footer>
<b>Cómo se calcula.</b> Venta: Marketplace, Fidelización, Páginas Web y el canal UnionX B2B se proyectan con la curva del mismo mes del año anterior (backtest ene–ago 2026 al día 21: error medio −1,4%, ±5%); Distribución y Corporativo se asume que cumplen el FCST, salvo que lo real ya lo supere.
Margen directo (venta − costo): real a la fecha del RAW (el costo llega a tiempo) + resto del mes al % del flujo normal. Margen de contribución: el flujo normal de Marketplace, Fidelización y Páginas Web usa el resultado del mes anterior ({p['seguimiento']['mes']}) del Drive de Seguimiento de contribución; Distribución y Corporativo el % del FCST VENTAS; las operaciones puntuales ≥ $5M van con su margen propio (RAW: margen directo − comisión y logística + ajuste contable de {p['calibracion']['mes']}), corregible caso a caso.
Comparación: venta, margen directo y de contribución contra el Fcst EERR; GAV contra el FCST GASTO 2026 (la proyección del GAV es el resultado vigente del Fcst EERR); el PPTO queda como referencia. EBITDA = margen − GAV + depreciación (igual que la planilla).
Fuente de venta: {p['fuente']}. Tendencia y acumulado año: Fcst EERR. Meses de inventario: último balance cargado. Generado {ahora}.
</footer>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/6.1.0/echarts.min.js"></script>
<script>
const MUT='#8397B5', LINE='#1E2E4A', INK='#E6EDF7';
const fmt=v=>v==null?'':v.toLocaleString('es-CL',{{maximumFractionDigits:1}});
const base={{textStyle:{{fontFamily:'Segoe UI,system-ui,sans-serif',color:INK}},
  tooltip:{{trigger:'axis',backgroundColor:'#0F1B30',borderColor:LINE,textStyle:{{color:INK,fontSize:12}},valueFormatter:v=>fmt(v)}},
  legend:{{top:0,right:0,textStyle:{{color:MUT,fontSize:11}},itemWidth:12,itemHeight:8}},
  grid:{{left:8,right:14,top:28,bottom:4,containLabel:true}}}};
const ax=(o)=>Object.assign({{axisLine:{{lineStyle:{{color:LINE}}}},axisTick:{{show:false}},axisLabel:{{color:MUT,fontSize:10.5}},splitLine:{{lineStyle:{{color:LINE,type:'dashed'}}}}}},o||{{}});
function mk(id,opt){{const c=echarts.init(document.getElementById(id));c.setOption(Object.assign({{}},base,opt));new ResizeObserver(()=>c.resize()).observe(document.getElementById(id));}}

mk('c_dia',{{grid:{{left:8,right:78,top:28,bottom:4,containLabel:true}},xAxis:ax({{type:'category',data:{J(dias)},splitLine:{{show:false}}}}),yAxis:ax({{type:'value',axisLabel:{{color:MUT,formatter:v=>fmt(v)}}}}),
  series:[
   {{name:'Real',type:'line',data:{J(real)},symbol:'none',lineStyle:{{width:3,color:'#3B82F6'}},areaStyle:{{color:'rgba(59,130,246,.15)'}}}},
   {{name:'FCST prorrateado',type:'line',data:{J(meta_c)},symbol:'none',lineStyle:{{width:1.8,color:'#8397B5',type:'dashed'}}}},
   {{name:'Proyección',type:'line',data:{J(proy)},symbol:'none',lineStyle:{{width:2.4,color:'#F59E0B',type:'dotted'}},
     endLabel:{{show:true,formatter:p=>'$'+fmt(p.value)+' M',color:'#F59E0B',fontWeight:'bold'}}}}]}});

mk('c_lin',{{grid:{{left:8,right:48,top:28,bottom:4,containLabel:true}},
  xAxis:ax({{type:'value',axisLabel:{{color:MUT,formatter:v=>fmt(v)}}}}),
  yAxis:ax({{type:'category',data:{J(lin_cats)},inverse:true,splitLine:{{show:false}},axisLabel:{{color:INK,fontSize:11.5}}}}),
  series:[
   {{name:'Real a la fecha',type:'bar',data:{J(lin_real)},itemStyle:{{color:'#1D4ED8',borderRadius:[0,3,3,0]}},barGap:'-100%',barWidth:14,z:3}},
   {{name:'Proyección',type:'bar',data:{J(lin_proy)},itemStyle:{{color:'rgba(59,130,246,.35)',borderRadius:[0,3,3,0]}},barWidth:14,
     label:{{show:true,position:'right',color:INK,fontSize:11,formatter:p=>{J(lin_var)}[p.dataIndex]}}}},
   {{name:'FCST',type:'scatter',data:{J(lin_meta)},symbol:'rect',symbolSize:[3,20],itemStyle:{{color:'#F59E0B'}},z:4}}]}});

mk('c_gav',{{tooltip:{{trigger:'item',backgroundColor:'#0F1B30',borderColor:LINE,textStyle:{{color:INK}},formatter:p=>p.name+'<br>$'+fmt(p.value)+' M ('+p.percent.toFixed(0)+'%)'}},
  legend:{{orient:'vertical',right:0,top:'middle',textStyle:{{color:MUT,fontSize:11}}}},
  series:[{{type:'pie',radius:['52%','78%'],center:['36%','52%'],data:{J(D['comp'])},
    label:{{show:true,position:'center',formatter:'$'+fmt({round(sum(c['value'] for c in D['comp']), 1)})+' M',color:INK,fontSize:15,fontWeight:'bold'}},
    labelLine:{{show:false}},itemStyle:{{borderColor:'#101D33',borderWidth:2}},
    color:['#3B82F6','#22C55E','#F59E0B','#64748B']}}]}});

mk('c_eb',{{xAxis:ax({{type:'category',data:{J(t_lbl)},splitLine:{{show:false}},axisLabel:{{color:MUT,fontSize:10,interval:0,rotate:40}}}}),
  yAxis:[ax({{type:'value',axisLabel:{{color:MUT,formatter:v=>fmt(v)}}}}),ax({{type:'value',splitLine:{{show:false}},axisLabel:{{color:MUT,formatter:v=>v+'%'}}}})],
  series:[{{name:'EBITDA (MM)',type:'bar',data:{J(t_eb)},barWidth:'55%',itemStyle:{{borderRadius:[3,3,0,0]}}}},
          {{name:'Margen EBITDA %',type:'line',yAxisIndex:1,data:{J(t_mg)},symbol:'circle',symbolSize:5,lineStyle:{{color:'#22C55E',width:2}},itemStyle:{{color:'#22C55E'}}}}]}});
</script>"""


def cuerpo_mail(p: dict) -> str:
    """Resumen email-safe (sin JS): KPIs de cierre vs FCST, líneas, desviaciones y puntuales."""
    m = p["meta"]
    vp = p["venta_proy"]
    col = {"verde": "#16A34A", "amarillo": "#D97706", "rojo": "#DC2626"}[p["semaforo"]]
    td = "padding:4px 8px;border-bottom:1px solid #E2E8F0"
    tdn = td + ";text-align:right;font-family:Consolas,monospace"

    def pc(v, b):
        return f" <span style='color:#94A3B8;font-size:11px'>{es(v / b * 100)}%</span>" if b else ""

    def fila(nombre, proy, fcst, gasto=False, pct_=True):
        d = proy - fcst
        ok = (d <= 0) if gasto else (d >= 0)
        return (f"<tr><td style='{td}'>{nombre}</td>"
                f"<td style='{tdn}'><b>{mm(proy)}</b>{pc(proy, vp) if pct_ else ''}</td>"
                f"<td style='{tdn};color:#64748B'>{mm(fcst)}{pc(fcst, m['Venta']) if pct_ else ''}</td>"
                f"<td style='{tdn};color:{'#16A34A' if ok else '#DC2626'}'>{'+' if d >= 0 else '−'}{mm(abs(d))[1:]}</td></tr>")

    kpis = (fila("Venta neta", vp, m["Venta"], pct_=False) + fila("Margen directo", p["md_proy"], m["MD"])
            + fila("Margen contribución", p["mc_proy"], m["Contribución"])
            + fila("GAV", p["gav"], m["GAV"], gasto=True) + fila("EBITDA", p["ebitda_proy"], m["EBITDA"]))
    lin = "".join(
        f"<tr><td style='{td}'>{l['linea']}</td><td style='{tdn}'>{mm(l['acum'])}</td><td style='{tdn}'><b>{mm(l['proy'])}</b></td>"
        f"<td style='{tdn};color:#64748B'>{mm(l['fcst_venta'])}</td>"
        f"<td style='{tdn};color:{'#16A34A' if l['proy'] >= l['fcst_venta'] else '#DC2626'}'>"
        f"{(('+' if l['proy'] >= l['fcst_venta'] else '−') + es(abs(l['proy'] / l['fcst_venta'] - 1) * 100, 0) + '%') if l['fcst_venta'] else '—'}</td></tr>"
        for l in p["lineas"] if l["linea"] != "Otros")
    desv = p["desviaciones"]
    bajo = " · ".join(f"{c} −{mm(abs(g), 0)[1:]}" for c, _, _, g in [d for d in desv if d[3] < 0][:4])
    sobre = " · ".join(f"{c} +{mm(g, 0)[1:]}" for c, _, _, g in [d for d in reversed(desv) if d[3] > 0][:3])
    ops = "".join(f"<li>{o['documento']} · {o['canal']}: {mm(o['venta'])} al {es(o['mc_pct'] * 100)}% de margen "
                  f"(impacto {'+' if o['impacto'] >= 0 else '−'}{mm(abs(o['impacto']))[1:]} sobre la base de su línea)</li>"
                  for o in p["operaciones"])
    return f"""<div style="font-family:Segoe UI,Arial,sans-serif;max-width:720px;color:#1E293B">
<div style="font-size:11px;letter-spacing:.1em;color:#2563EB;font-weight:700">UNIONX · DASHBOARD FINANCIERO · CIERRE {p['etiqueta'].upper()}</div>
<h2 style="margin:6px 0 2px;color:{col}">EBITDA proyectado {mm(p['ebitda_proy'])} vs FCST {mm(m['EBITDA'])}</h2>
<div style="color:#64748B;font-size:12.5px">Venta real al {p['dato_hasta'].strftime('%d-%m')}: {mm(p['venta_acum'])} · día {p['dia']}/{p['dias_mes']} · si seguimos al ritmo actual</div>
<table style="border-collapse:collapse;font-size:13px;margin-top:10px">
<tr style="color:#64748B;font-size:11px"><td></td><td style="text-align:right;padding:2px 8px">Proyección</td><td style="text-align:right;padding:2px 8px">FCST</td><td style="text-align:right;padding:2px 8px">Diferencia</td></tr>
{kpis}</table>
<h3 style="font-size:14px;margin:16px 0 4px;color:#1F3864">Venta por línea de negocio</h3>
<table style="border-collapse:collapse;font-size:13px">
<tr style="color:#64748B;font-size:11px"><td></td><td style="text-align:right;padding:2px 8px">Real</td><td style="text-align:right;padding:2px 8px">Proyección</td><td style="text-align:right;padding:2px 8px">FCST</td><td style="text-align:right;padding:2px 8px">vs FCST</td></tr>
{lin}</table>
<p style="font-size:13px;margin:12px 0 4px"><b>Canales bajo el FCST:</b> {bajo or '—'}<br><b>Sobre el FCST:</b> {sobre or '—'}</p>
{('<p style="font-size:13px;margin:10px 0 2px"><b>Operaciones puntuales del mes</b> (van con su margen propio):</p><ul style="font-size:13px;margin:2px 0">' + ops + '</ul>') if ops else ''}
<p style="font-size:12.5px;color:#64748B;margin-top:14px">El dashboard completo (gráficos, acumulado del año, composición del GAV, semáforo y detalle por línea) va adjunto: ábrelo en el navegador.</p>
</div>"""


def enviar(html: str, p: dict):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    import os
    tok = os.environ.get("GMAIL_TOKEN_JSON")
    creds = (Credentials.from_authorized_user_info(json.loads(tok)) if tok
             else Credentials.from_authorized_user_file(str(ROOT / "agente-comex/config/token.json")))
    if not creds.valid:
        creds.refresh(Request())
    m = p["meta"]
    msg = EmailMessage()
    msg["To"] = os.environ.get("DASH_CIERRE_TO", "andres@unionx.cl")
    cc = os.environ.get("DASH_CIERRE_CC", "").strip()
    if cc:
        msg["Cc"] = cc
    msg["From"] = "andres@unionx.cl"
    msg["Subject"] = (f"📊 Dashboard Cierre {p['etiqueta']} · EBITDA proy {mm(p['ebitda_proy'])} vs FCST {mm(m['EBITDA'])}"
                      f" · venta {es(p['venta_proy'] / m['Venta'] * 100, 0)}% del FCST")
    msg.set_content("Dashboard financiero de cierre del mes (ver versión HTML y el adjunto).")
    msg.add_alternative(cuerpo_mail(p), subtype="html")
    msg.add_attachment(html.encode("utf-8"), maintype="text", subtype="html",
                       filename=f"Dashboard_Cierre_{p['etiqueta']}.html")
    svc = build("gmail", "v1", credentials=creds)
    svc.users().messages().send(userId="me", body={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}).execute()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    D = datos()
    html = render(D)
    OUT.write_text(html, encoding="utf-8")
    print(f"OK -> {OUT}")
    if "--preview-mail" in sys.argv:
        (OUT.parent / "dashboard_cierre_mail_preview.html").write_text(cuerpo_mail(D["p"]), encoding="utf-8")
        print("Preview del mail ->", OUT.parent / "dashboard_cierre_mail_preview.html")
    if "--enviar" in sys.argv:
        enviar(html, D["p"])
        import os
        print(f"Enviado a {os.environ.get('DASH_CIERRE_TO', 'andres@unionx.cl')} · cc {os.environ.get('DASH_CIERRE_CC', '—')}")
