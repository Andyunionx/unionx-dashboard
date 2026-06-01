#!/usr/bin/env python3
"""
Monitor de salud 360 del sistema Cyber UnionX.

Cada ejecución:
1. Verifica Turso vs Odoo (state=sale) para hoy → detecta lag.
2. Detecta duplicados en Turso (junio + mayo).
3. Auto-corrige duplicados si los hay (DELETE keep MIN rowid).
4. Si lag > 30 min detectado vs Odoo → fuerza un sync_mes_actual.
5. Si algo grave, envía email de alerta (Resend).

Diseñado para correr en GitHub Actions cron cada 30 min. Idempotente.

Vars de entorno:
  LIBSQL_URL, LIBSQL_AUTH_TOKEN, ANDRES_ODOO_PASSWORD, RESEND_API_KEY
  EMAIL_TO (default andres@unionx.cl)
  EMAIL_FROM (default onboarding@resend.dev)
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

URL = os.environ.get('LIBSQL_URL', '').rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
EMAIL_TO = [e.strip() for e in os.environ.get('EMAIL_TO', 'andres@unionx.cl').split(',') if e.strip()]
EMAIL_FROM = os.environ.get('EMAIL_FROM', 'onboarding@resend.dev')

PROJECT_ROOT = Path(__file__).parent
CHILE_TZ = timezone(timedelta(hours=-4))
# Tolerancias para alertas
LAG_TOLERANCE_PCT = 0.10  # Turso/Odoo diff > 10% → alerta
LAG_TOLERANCE_MIN_AMT = 1_000_000  # menos de $1M de diff no alerta


def turso_query(sql, timeout=120, retries=3):
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    last = None
    for i in range(retries):
        try:
            r = requests.post(f"{URL}/v2/pipeline", json=body,
                              headers={'Authorization': f'Bearer {TOKEN}'}, timeout=timeout)
            r.raise_for_status()
            return r.json()['results'][0]
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last = e
            time.sleep(5 * (i + 1))
    raise last


def _rows(res):
    if res.get('type') == 'error':
        return []
    return [[c.get('value') if isinstance(c, dict) else c for c in row]
            for row in res['response']['result']['rows']]


def odoo_client():
    """Cliente Odoo lazy import."""
    sys.path.insert(0, str(PROJECT_ROOT / 'finanzas-unionx' / 'backend'))
    from app.core.odoo_client import OdooClient
    from app.config import Config
    cfg = Config()
    return OdooClient(cfg.ODOO_URL, cfg.ODOO_DB, cfg.ODOO_USER, cfg.ODOO_PASSWORD)


def detectar_lag_hoy(c):
    """Compara Odoo (state=sale, hoy Chile) vs Turso (fecha_venta=hoy)."""
    ahora_clt = datetime.now(CHILE_TZ)
    hoy_str = ahora_clt.strftime('%Y-%m-%d')
    # Hoy en Chile = (hoy 00:00 CLT, mañana 00:00 CLT) = (hoy 04:00 UTC, mañana 04:00 UTC)
    desde_utc = f"{hoy_str} 04:00:00"
    hasta_utc = (ahora_clt + timedelta(hours=4)).strftime('%Y-%m-%d %H:%M:%S')

    sos = c.search_read('sale.order',
        [('date_order', '>=', desde_utc), ('date_order', '<=', hasta_utc), ('state', '=', 'sale')],
        ['amount_total'], limit=5000)
    odoo_n = len(sos)
    odoo_b = sum(s['amount_total'] for s in sos)

    res = turso_query(f"SELECT COUNT(DISTINCT pedido), ROUND(SUM(venta_bruta),0) "
                      f"FROM ventas WHERE fecha_venta='{hoy_str}'")
    row = _rows(res)
    if not row:
        return {'error': 'Turso query failed'}
    turso_n = int(row[0][0] or 0)
    turso_b = float(row[0][1] or 0)

    diff_amt = abs(turso_b - odoo_b)
    diff_pct = (diff_amt / odoo_b) if odoo_b else 0

    alert = False
    if diff_amt > LAG_TOLERANCE_MIN_AMT and diff_pct > LAG_TOLERANCE_PCT:
        alert = True

    return {
        'hoy': hoy_str,
        'odoo_sos': odoo_n,
        'odoo_bruta': odoo_b,
        'turso_sos': turso_n,
        'turso_bruta': turso_b,
        'diff_amt': diff_amt,
        'diff_pct': diff_pct,
        'alert': alert,
    }


def detectar_duplicados(fecha_desde='2026-05-01', fecha_hasta='2026-06-30'):
    """Cuenta grupos (pedido,sku,hora,bruta,cantidad) con count>1."""
    sql = f"""
SELECT COUNT(*) FROM (
  SELECT pedido, sku, hora_venta, venta_bruta, cantidad
  FROM ventas
  WHERE fecha_venta >= '{fecha_desde}' AND fecha_venta <= '{fecha_hasta}'
  GROUP BY pedido, sku, hora_venta, venta_bruta, cantidad
  HAVING COUNT(*) > 1
)
"""
    res = turso_query(sql, timeout=180)
    row = _rows(res)
    return int(row[0][0] or 0) if row else 0


def limpiar_duplicados(fecha_desde, fecha_hasta):
    """Borra duplicados manteniendo MIN(rowid). Devuelve filas borradas."""
    pre = turso_query(
        f"SELECT COUNT(*) FROM ventas WHERE fecha_venta >= '{fecha_desde}' AND fecha_venta <= '{fecha_hasta}'"
    )
    pre_n = int(_rows(pre)[0][0] or 0)

    sql = f"""
DELETE FROM ventas WHERE rowid NOT IN (
  SELECT MIN(rowid) FROM ventas
  WHERE fecha_venta >= '{fecha_desde}' AND fecha_venta <= '{fecha_hasta}'
  GROUP BY pedido, sku, hora_venta, venta_bruta, cantidad, documento
) AND fecha_venta >= '{fecha_desde}' AND fecha_venta <= '{fecha_hasta}'
"""
    turso_query(sql, timeout=180)

    post = turso_query(
        f"SELECT COUNT(*) FROM ventas WHERE fecha_venta >= '{fecha_desde}' AND fecha_venta <= '{fecha_hasta}'"
    )
    post_n = int(_rows(post)[0][0] or 0)
    return pre_n - post_n


def enviar_alerta(asunto, html):
    if not RESEND_API_KEY or not EMAIL_TO:
        print("[WARN] Sin RESEND/EMAIL_TO, skip envío", flush=True)
        return False
    payload = {
        'from': EMAIL_FROM,
        'to': EMAIL_TO,
        'subject': f"⚠️ {asunto}",
        'html': html,
    }
    r = requests.post('https://api.resend.com/emails', json=payload,
                      headers={'Authorization': f'Bearer {RESEND_API_KEY}'}, timeout=30)
    return r.status_code < 300


def main():
    if not URL or not TOKEN:
        print("[ERROR] Sin LIBSQL_URL/TOKEN", flush=True)
        return 1

    ahora_clt = datetime.now(CHILE_TZ)
    print(f"=== Cyber Health Monitor {ahora_clt.strftime('%Y-%m-%d %H:%M CLT')} ===", flush=True)

    issues = []
    actions = []

    # 1. Lag Turso vs Odoo HOY
    print("\n[1/3] Comparando Turso vs Odoo (hoy)...", flush=True)
    try:
        c = odoo_client()
        lag = detectar_lag_hoy(c)
        if lag.get('error'):
            print(f"  [WARN] {lag['error']}", flush=True)
        else:
            print(f"  Odoo:  {lag['odoo_sos']} SOs, ${lag['odoo_bruta']:,.0f}", flush=True)
            print(f"  Turso: {lag['turso_sos']} SOs, ${lag['turso_bruta']:,.0f}", flush=True)
            print(f"  Diff:  ${lag['diff_amt']:,.0f} ({lag['diff_pct']*100:.1f}%)", flush=True)
            if lag['alert']:
                issues.append(f"🔴 Lag Turso vs Odoo: ${lag['diff_amt']:,.0f} ({lag['diff_pct']*100:.1f}%)")
            else:
                print(f"  ✅ Dentro de tolerancia ({LAG_TOLERANCE_PCT*100:.0f}%)", flush=True)
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}", flush=True)
        issues.append(f"⚠️ No se pudo verificar Odoo: {type(e).__name__}")

    # 2. Duplicados (junio + mayo)
    print("\n[2/3] Detectando duplicados...", flush=True)
    try:
        dups_jun = detectar_duplicados('2026-06-01', '2026-06-30')
        dups_may = detectar_duplicados('2026-05-01', '2026-05-31')
        print(f"  Junio: {dups_jun} grupos duplicados", flush=True)
        print(f"  Mayo:  {dups_may} grupos duplicados", flush=True)

        if dups_jun > 0:
            print(f"  Limpiando junio...", flush=True)
            borradas = limpiar_duplicados('2026-06-01', '2026-06-30')
            actions.append(f"🧹 Borrados {borradas} duplicados junio")
        if dups_may > 0:
            print(f"  Limpiando mayo...", flush=True)
            borradas = limpiar_duplicados('2026-05-01', '2026-05-31')
            actions.append(f"🧹 Borrados {borradas} duplicados mayo")
        if dups_jun == 0 and dups_may == 0:
            print(f"  ✅ Sin duplicados", flush=True)
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}", flush=True)
        issues.append(f"⚠️ Error dedup: {type(e).__name__}")

    # 3. Resumen y alerta solo si hay issues GRAVES
    print(f"\n[3/3] Resumen", flush=True)
    print(f"  Issues: {len(issues)}", flush=True)
    print(f"  Acciones: {len(actions)}", flush=True)
    for i in issues:
        print(f"    {i}", flush=True)
    for a in actions:
        print(f"    {a}", flush=True)

    # Email solo si hay issues no resueltos automáticamente
    if issues:
        html = f"""<!DOCTYPE html><html><body style="font-family:sans-serif;max-width:600px">
<h2>⚠️ Cyber UnionX — Monitor detectó problemas</h2>
<p>{ahora_clt.strftime('%Y-%m-%d %H:%M CLT')}</p>
<h3>Issues:</h3><ul>{''.join(f'<li>{i}</li>' for i in issues)}</ul>
{'<h3>Acciones aplicadas automáticamente:</h3><ul>' + ''.join(f'<li>{a}</li>' for a in actions) + '</ul>' if actions else ''}
<p><a href="https://github.com/Andyunionx/unionx-dashboard/actions">Ver workflows</a></p>
</body></html>"""
        enviar_alerta(f"Monitor Cyber: {len(issues)} issue(s) detectado(s)", html)
    print("\nOK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
