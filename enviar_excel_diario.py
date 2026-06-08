#!/usr/bin/env python3
"""
Envía Excel RAW (40 cols) con la data actualizada de Turso por email.
Diseñado para correr en GitHub Actions cron diario a las 8am Chile.

Vars de entorno:
  LIBSQL_URL              — URL Turso
  LIBSQL_AUTH_TOKEN       — Token Turso
  RESEND_API_KEY          — API key Resend
  EMAIL_TO                — destinatarios (coma-separados, ej: andres@unionx.cl,otro@unionx.cl)
  EMAIL_FROM              — remitente (ej: onboarding@resend.dev o notifications@tu-dominio)
"""
import base64
import io
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

URL = os.environ.get('LIBSQL_URL', '').rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
EMAIL_TO = [e.strip() for e in os.environ.get(
    'EMAIL_TO',
    'andres@grupoeter.cl,nicolas@unionx.cl,nicole@unionx.cl'
).split(',') if e.strip()]
EMAIL_FROM = os.environ.get('EMAIL_FROM', 'onboarding@resend.dev')

if not URL or not TOKEN:
    print("[ERROR] LIBSQL_URL/LIBSQL_AUTH_TOKEN no seteados.", flush=True)
    sys.exit(1)
if not RESEND_API_KEY:
    print("[ERROR] RESEND_API_KEY no seteado.", flush=True)
    sys.exit(1)

# Mapeo DB -> RAW (orden de las 40 columnas del Excel original)
DB_TO_RAW = {
    'tipo_movimiento': 'Tipo Movimiento',
    'bodega': 'Bodega',
    'documento': 'Documento',
    'fecha_documento': 'Fecha Documento',
    'pedido': 'Pedido',
    'estado_pedido': 'Estado Pedido',
    'tipo_despacho': 'Tipo Despacho',
    'sku': 'SKU',
    'canal': 'Canal',
    'fecha_venta': 'Fecha Venta',
    'hora_venta': 'Hora Venta',
    'producto': 'Producto',
    'categoria_macro': 'Categoría macro',
    'categoria_padre': 'Categoría padre',
    'categoria_hijo': 'Categoría hijo',
    'categoria_comercial': 'Categoría comercial',
    'estado_sku': 'Estado SKU',
    'pack': 'Pack',
    'marca': 'Marca',
    'proveedor': 'Proveedor',
    'tipo_marca': 'Tipo Marca',
    'tipo_compra': 'Tipo Compra',
    'tipo_negocio': 'Tipo Negocio',
    'kam': 'KAM',
    'estado_canal': 'Estado Canal',
    'anio_venta': 'Año venta',
    'mes_venta': 'Mes venta',
    'semana_venta': 'Semana venta',
    'dia_semana': 'Día semana',
    'hora_venta_num': 'Hora venta',
    'cantidad': 'Cantidad',
    'venta_bruta': 'Venta bruta',
    # venta_neta excluida por preferencia operativa
    'costo_unitario': 'Costo Unitario',
    'costo_total': 'Costo Total',
    'margen_front': 'Margen Front',
    'comision_pct': 'Comision %',
    'comision': 'Comisión',
    'logistica': 'Logística',
    'marketing': 'Marketing',
    'margen_final': 'Mg final',
}
DB_COLS = list(DB_TO_RAW.keys())
RAW_COLS = [DB_TO_RAW[c] for c in DB_COLS]

HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'}


def turso_query(sql, params=None):
    body = {"requests": [
        {"type": "execute", "stmt": {"sql": sql, "args": params or []}},
        {"type": "close"}
    ]}
    r = requests.post(f"{URL}/v2/pipeline", json=body, headers=HEADERS, timeout=600)
    r.raise_for_status()
    return r.json()['results'][0]['response']['result']


def descargar_ventas() -> pd.DataFrame:
    """Descarga ventas SOLO del mes actual (formato RAW 40 cols)."""
    # Calcular primer y último día del mes actual
    hoy = datetime.now()
    primer_dia = hoy.replace(day=1).strftime('%Y-%m-%d')
    if hoy.month == 12:
        ultimo_dia = hoy.replace(year=hoy.year + 1, month=1, day=1).strftime('%Y-%m-%d')
    else:
        ultimo_dia = hoy.replace(month=hoy.month + 1, day=1).strftime('%Y-%m-%d')

    print(f"[1/3] Descargando ventas del mes actual ({primer_dia} a {hoy.strftime('%Y-%m-%d')})...", flush=True)
    t0 = time.time()
    chunk_size = 80000
    all_rows = []
    last_rowid = 0

    while True:
        result = turso_query(
            f"SELECT rowid, {','.join(DB_COLS)} FROM ventas "
            f"WHERE fecha_venta >= '{primer_dia}' AND fecha_venta < '{ultimo_dia}' "
            f"AND rowid > {last_rowid} "
            f"ORDER BY rowid LIMIT {chunk_size}"
        )
        rows = result['rows']
        if not rows:
            break
        for r in rows:
            vals = [c.get('value') if isinstance(c, dict) else c for c in r]
            last_rowid = int(vals[0])
            all_rows.append(vals[1:])
        if len(rows) < chunk_size:
            break

    elapsed = time.time() - t0
    print(f"      [OK] {len(all_rows):,} filas en {elapsed:.0f}s", flush=True)

    df = pd.DataFrame(all_rows, columns=DB_COLS)
    df = df.rename(columns=DB_TO_RAW)
    return df


def generar_excel(df: pd.DataFrame) -> bytes:
    """Convierte DataFrame a bytes XLSX."""
    print(f"[2/3] Generando Excel...", flush=True)
    t0 = time.time()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Raw ventas')
    data = buf.getvalue()
    elapsed = time.time() - t0
    size_mb = len(data) / 1024 / 1024
    print(f"      [OK] {size_mb:.1f} MB en {elapsed:.0f}s", flush=True)
    return data


def upload_to_fileio(xlsx_bytes: bytes, fname: str) -> str:
    """Sube el Excel a file.io (anónimo, gratis, expira 14 días). Devuelve URL de descarga."""
    print(f"      Subiendo {len(xlsx_bytes)/1024/1024:.1f} MB a file.io...", flush=True)
    r = requests.post(
        'https://file.io/?expires=14d',
        files={'file': (fname, io.BytesIO(xlsx_bytes), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
        timeout=600,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get('success'):
        raise RuntimeError(f"file.io rechazó: {data}")
    return data['link']


def enviar_email(xlsx_bytes: bytes, n_filas: int):
    """Envía email vía Resend con XLSX adjunto + Top insights del día."""
    print(f"[3/3] Enviando email a {EMAIL_TO}...", flush=True)
    hoy = datetime.now()
    fecha = hoy.strftime('%Y-%m-%d')
    mes_nombre = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'][hoy.month - 1]
    fname = f"Raw ventas {mes_nombre} {hoy.year}.xlsx"
    size_mb = len(xlsx_bytes) / 1024 / 1024

    # Generar insights
    print("      Generando Top insights...", flush=True)
    try:
        from generar_insights import generar_insights, render_insights_html
        insights = generar_insights()
        insights_html = render_insights_html(insights)
    except Exception as e:
        print(f"      [WARN] insights fallaron: {e}", flush=True)
        insights_html = ""

    body_insights_block = f"""
        <div style="background:#F8FAFC;padding:16px;border-radius:8px;margin:16px 0;">
            <h3 style="margin:0 0 12px 0;color:#1E293B;font-size:1rem;">🔥 Top insights del día</h3>
            {insights_html}
        </div>
    """ if insights_html else ""

    if size_mb > 25:
        print(f"      Adjunto {size_mb:.1f} MB > 25 MB (límite Gmail). Subiendo a file.io...", flush=True)
        download_url = upload_to_fileio(xlsx_bytes, fname)
        print(f"      [OK] Link: {download_url}", flush=True)
        body_html = (
            f"<div style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;max-width:680px;margin:auto;'>"
            f"<h2 style='color:#1E293B;margin:0 0 8px 0;'>📊 Reporte UnionX — {fecha}</h2>"
            f"{body_insights_block}"
            f"<hr style='border:none;border-top:1px solid #E2E8F0;margin:16px 0;'/>"
            f"<p><b>📥 Descarga el Excel:</b> <a href='{download_url}'>{fname}</a></p>"
            f"<p style='color:#888;font-size:0.85rem'>El archivo pesa {size_mb:.1f} MB y supera el límite de adjuntos de Gmail. "
            f"El link expira en 14 días o tras 1 descarga.</p>"
            f"<p><b>Total filas:</b> {n_filas:,} · <b>Tamaño:</b> {size_mb:.1f} MB</p>"
            f"<p>Dashboard live: <a href='https://unionx-dashboard-7ppjm2cem2zkfxwzkv3pzc.streamlit.app/'>Dashboard UnionX</a></p>"
            f"</div>"
        )
        attachments = []
    else:
        body_html = (
            f"<div style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;max-width:680px;margin:auto;'>"
            f"<h2 style='color:#1E293B;margin:0 0 8px 0;'>📊 Reporte UnionX — {fecha}</h2>"
            f"{body_insights_block}"
            f"<hr style='border:none;border-top:1px solid #E2E8F0;margin:16px 0;'/>"
            f"<p>📎 Adjunto Excel con ventas de <b>{mes_nombre} {hoy.year}</b> (formato RAW 40 columnas).</p>"
            f"<p><b>Total filas:</b> {n_filas:,} · <b>Tamaño:</b> {size_mb:.1f} MB</p>"
            f"<p>Dashboard live: <a href='https://unionx-dashboard-7ppjm2cem2zkfxwzkv3pzc.streamlit.app/'>Dashboard UnionX</a></p>"
            f"</div>"
        )
        attachments = [{
            "filename": fname,
            "content": base64.b64encode(xlsx_bytes).decode('ascii'),
        }]

    payload = {
        "from": EMAIL_FROM,
        "to": EMAIL_TO,
        "subject": f"Raw Ventas UnionX — {mes_nombre} {hoy.year} ({fecha})",
        "html": body_html,
    }
    if attachments:
        payload["attachments"] = attachments

    r = requests.post(
        "https://api.resend.com/emails",
        json=payload,
        headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'},
        timeout=60,
    )
    if r.status_code >= 400:
        print(f"      [ERROR] Resend respondio {r.status_code}: {r.text[:300]}", flush=True)
        sys.exit(1)
    print(f"      [OK] Email enviado. Resend ID: {r.json().get('id', '?')}", flush=True)


def main():
    print(f"=== Email diario Raw Ventas — {datetime.now()} ===", flush=True)
    df = descargar_ventas()
    xlsx_bytes = generar_excel(df)
    enviar_email(xlsx_bytes, len(df))
    print("\n[OK] Proceso terminado.", flush=True)


if __name__ == '__main__':
    main()
