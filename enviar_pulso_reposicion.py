# -*- coding: utf-8 -*-
"""Pulso Reposición Fulfillment — envío lunes 07:30 CLT (email_diario.yml, gate lunes).

Pipeline: tránsito vivo (Seimex×Odoo, tolerante a falla) → pulso (panel Nicole
fresco) → mail HTML estilo Pulso UnionX con el Excel adjunto.

Credenciales CI: ANDRES_ODOO_PASSWORD · DRIVE_OAUTH_TOKEN_JSON · GMAIL_TOKEN_JSON
(mismos secrets del Pulso Diario). SEIMEX_* opcional: si falta, el tránsito usa
el último parquet committeado y se avisa en el mail.
Destinatarios: env EMAIL_TO (default equipo reposición).
"""
import os, sys, json, datetime
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
from enviar_pulso_cyber import _enviar_via_gmail

AZ = "#1E3A5F"; GR = "#EBF0F8"; ROJO = "#B3261E"
EMAIL_TO = [e.strip() for e in os.environ.get(
    "EMAIL_TO",
    "nicole@unionx.cl,nicolas@unionx.cl,trinidad@unionx.cl,claudia@unionx.cl,andres@unionx.cl"
).split(",") if e.strip()]

def clp(n): return "$" + "{:,.0f}".format(n).replace(",", ".")
def miles(n): return "{:,.0f}".format(n).replace(",", ".")


def main():
    hoy = datetime.date.today()
    semana = hoy.isocalendar()[1]

    # 1) tránsito vivo (tolerante: sin SEIMEX_* usa el parquet existente)
    transito_ok = True
    try:
        import transito_vivo
        transito_vivo._cargar_env()
        ops = transito_vivo.operaciones_vivas()
        det = transito_vivo.pendientes_odoo(ops)
        if not det.empty:
            det = det.groupby(["sku", "eta", "pi", "oc", "oc_estado", "stage"], as_index=False)["unidades"].sum()
            ts = datetime.datetime.now().isoformat(timespec="seconds")
            det["ts_actualizado"] = ts
            det.to_parquet(transito_vivo.SNAP / "transito_vivo.parquet", index=False)
            mensual = det.assign(mes=det["eta"].str[:7]).groupby(["sku", "mes"], as_index=False)["unidades"].sum()
            mensual["ts_actualizado"] = ts
            mensual.to_parquet(transito_vivo.SNAP / "planif_forecast_transito.parquet", index=False)
    except Exception as e:
        transito_ok = False
        print(f"[transito][WARN] {type(e).__name__}: {e} — se usa el último snapshot", flush=True)

    # 2) pulso
    from pulso_reposicion_fulfillment import construir, construir_excel_dinamico
    fn = construir()
    xlsx = construir_excel_dinamico(fn)   # reporte con tabla dinámica nativa

    res = pd.read_excel(fn, sheet_name="Resumen canal")
    ume = pd.read_excel(fn, sheet_name="UME v2")
    tot_uds = res["Unidades"].sum(); tot_skus = int((ume["Reposición"] > 0).sum())
    tot_m3 = res["m3"].sum(); tot_costo = res["Costo envío est."].sum()

    # tránsito para el mail
    tr_html = ""
    try:
        tr = pd.read_parquet("data/planificacion/snapshots/transito_vivo.parquet")
        g = tr.groupby(["pi", "eta"], as_index=False)["unidades"].sum().sort_values("eta")
        filas = "".join(f"<tr><td style='padding:4px 10px;'>{r.pi}</td>"
                        f"<td style='padding:4px 10px;'>{str(r.eta)[:10]}</td>"
                        f"<td style='padding:4px 10px;text-align:right;'>{miles(r.unidades)}</td></tr>"
                        for r in g.itertuples(index=False))
        tr_html = f"""<div style="font-size:13px;margin:14px 0 4px;"><b>🚢 Tránsito vivo</b>
        ({miles(tr['unidades'].sum())} uds — ya considerado en la restricción de cobertura):</div>
        <table style="border-collapse:collapse;font-size:12px;">
        <tr style="background:{AZ};color:#fff;"><th style="padding:4px 10px;text-align:left;">PI</th>
        <th style="padding:4px 10px;">ETA</th><th style="padding:4px 10px;">Uds</th></tr>{filas}</table>"""
    except Exception:
        pass

    gaps_html = ""
    try:
        gaps = json.load(open("data/planificacion/snapshots/transito_gaps.json", encoding="utf-8"))
        if gaps:
            det = " · ".join(f"{g['pi']} (ETA {g['eta']})" for g in gaps)
            gaps_html = (f'<div style="font-size:13px;margin:10px 0;padding:8px 12px;background:#FDECEA;'
                         f'border-left:4px solid {ROJO};"><b>⚠ Embarques sin OC en Odoo</b> — sus SKUs no se '
                         f'pueden proyectar: {det}</div>')
    except Exception:
        pass

    filas_canal = "".join(
        f"""<tr style="background:{GR if i % 2 == 0 else '#fff'};">
        <td style="padding:6px 12px;">{r['Canal']}</td>
        <td style="padding:6px 12px;text-align:right;"><b>{miles(r['Unidades'])}</b></td>
        <td style="padding:6px 12px;text-align:right;">{miles(r['SKUs'])}</td>
        <td style="padding:6px 12px;text-align:right;">{r['m3']:.1f}</td>
        <td style="padding:6px 12px;text-align:right;">{clp(r['Costo envío est.'])}</td>
        <td style="padding:6px 12px;">{r['Tramo']}</td></tr>"""
        for i, (_, r) in enumerate(res.iterrows()))

    aviso_transito = "" if transito_ok else (
        f'<div style="font-size:12px;color:{ROJO};margin:6px 0;">⚠ El tránsito no se pudo refrescar en esta '
        f'corrida (se usó el último snapshot).</div>')

    html = f"""<div style="font-family:Arial,sans-serif;color:#222;max-width:720px;line-height:1.5;">
<h2 style="color:{AZ};margin-bottom:2px;">📦 Pulso Reposición Fulfillment</h2>
<div style="color:#64748b;font-size:12px;">Semana {semana} · {hoy.strftime('%d/%m/%Y')} · v1 en marcha blanca</div>

<div style="font-size:14px;margin:12px 0;"><b>Sugerido de la semana:</b> {miles(tot_uds)} unidades ·
{miles(tot_skus)} SKU-canal · {tot_m3:.1f} m³ · envío estimado {clp(tot_costo)}</div>

<table style="border-collapse:collapse;font-size:13px;margin:8px 0;">
<tr style="background:{AZ};color:#fff;">
  <th style="padding:6px 12px;text-align:left;">Canal</th>
  <th style="padding:6px 12px;">Unidades</th>
  <th style="padding:6px 12px;">SKUs</th>
  <th style="padding:6px 12px;">m³</th>
  <th style="padding:6px 12px;">Envío est.</th>
  <th style="padding:6px 12px;text-align:left;">Tramo</th></tr>
{filas_canal}
</table>
{gaps_html}
{tr_html}
{aviso_transito}

<div style="font-size:13px;margin:14px 0;">📎 <b>Excel adjunto (tabla dinámica):</b> hoja <b>Dinámica</b>
(Canal → Marca → SKU, arrastrable; se refresca sola al abrir) sobre la hoja <b>Datos</b> (sábana completa por
SKU y canal, con stock live, stock CA1, tránsito y cobertura) · <b>Resumen canal</b> · <b>Cuadratura</b> Odoo
vs seller center · <b>Metodología</b>.</div>

<div style="font-size:12px;color:#475569;margin-top:14px;">Los parámetros comerciales (Reglas, UME MIN,
UME Manual, BLACKLIST, LARGE) se leen de la planilla de siempre en cada corrida — cualquier ajuste ahí queda
tomado el lunes siguiente. Feedback a este pulso: responder por esta cadena.</div>
</div>"""

    asunto = f"📦 Pulso Reposición Fulfillment · Semana {semana} · {miles(tot_uds)} uds · {hoy.strftime('%d-%m-%Y')}"
    fname = f"Reporte Reposicion Fulfillment semana {semana} - {hoy.strftime('%d-%m-%Y')}"
    print(f"Enviando a {EMAIL_TO}...", flush=True)
    msg_id = _enviar_via_gmail(asunto, html, xlsx, fname, EMAIL_TO)
    print("Enviado. msg_id:", msg_id, flush=True)
    return 0 if msg_id else 1


if __name__ == "__main__":
    sys.exit(main())
