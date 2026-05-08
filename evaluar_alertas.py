#!/usr/bin/env python3
"""
Evaluador de alertas de negocio. Corre después de cada sync de ventas.

Reglas evaluadas:
- ANOMALÍA: venta de ayer cayó > 30% vs promedio últimos 7 días
- ANOMALÍA: canal específico cayó > 40% vs promedio 7d
- BAJO_FORECAST: venta del mes < 85% de forecast (cuando exista forecast)
- QUIEBRE_CRITICO: SKU sin stock con venta últimos 30d > umbral (requiere stock data)

Uso:
    python evaluar_alertas.py
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

# Setup path para importar helpers
sys.path.insert(0, str(Path(__file__).parent / 'views'))

from alertas_helper import crear_alerta, crear_tabla_alertas

URL = os.environ.get('LIBSQL_URL', '').rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '')

if not URL or not TOKEN:
    print("[ERROR] LIBSQL_URL/LIBSQL_AUTH_TOKEN no seteados", flush=True)
    sys.exit(1)

HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'}


def _q(sql: str):
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    r = requests.post(f"{URL}/v2/pipeline", json=body, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.json()['results'][0]['response']['result']['rows']


def _val(row, idx):
    cell = row[idx]
    if cell.get('type') == 'null':
        return None
    return cell.get('value')


# ============================================================
# REGLA 1: Anomalía global de ventas
# ============================================================
def regla_anomalia_global():
    """Si la venta de ayer cae > 30% vs promedio 7d → alerta."""
    hoy = datetime.now().date()
    ayer = hoy - timedelta(days=1)
    hace_7d = hoy - timedelta(days=7)

    rows_ayer = _q(f"""
        SELECT ROUND(SUM(venta_bruta), 0) FROM ventas
        WHERE fecha_venta = '{ayer}' AND tipo_movimiento = 'Venta'
    """)
    venta_ayer = float(_val(rows_ayer[0], 0) or 0) if rows_ayer else 0

    rows_avg = _q(f"""
        SELECT ROUND(AVG(daily), 0) FROM (
            SELECT fecha_venta, SUM(venta_bruta) as daily FROM ventas
            WHERE fecha_venta >= '{hace_7d}' AND fecha_venta < '{ayer}'
              AND tipo_movimiento = 'Venta'
            GROUP BY fecha_venta
        )
    """)
    avg_7d = float(_val(rows_avg[0], 0) or 0) if rows_avg else 0

    if avg_7d <= 0 or venta_ayer <= 0:
        return None

    pct = (venta_ayer - avg_7d) / avg_7d * 100
    if pct < -30:
        sev = 'critical' if pct < -50 else 'warning'
        crear_alerta(
            tipo='venta_anomalia_global',
            severity=sev,
            titulo=f"Venta ayer cayó {pct:.0f}% vs promedio 7 días",
            mensaje=f"Ayer ${venta_ayer/1e6:.1f}M vs promedio ${avg_7d/1e6:.1f}M. Revisar urgente.",
            contexto={'venta_ayer': venta_ayer, 'avg_7d': avg_7d, 'pct': pct, 'fecha': str(ayer)},
            fecha_objetivo=str(ayer),
            target_apps=['ventas', 'operaciones'],
        )
        print(f"  🔴 anomalía_global: {pct:.0f}%")
        return True
    return None


# ============================================================
# REGLA 2: Canal con caída fuerte
# ============================================================
def regla_anomalia_canal():
    """Top canales con caída > 40% vs promedio 7d."""
    hoy = datetime.now().date()
    ayer = hoy - timedelta(days=1)
    hace_7d = hoy - timedelta(days=7)

    rows_ayer = _q(f"""
        SELECT canal, ROUND(SUM(venta_bruta), 0) FROM ventas
        WHERE fecha_venta = '{ayer}' AND tipo_movimiento = 'Venta'
        GROUP BY canal
    """)
    rows_avg = _q(f"""
        SELECT canal, ROUND(SUM(venta_bruta) / 7.0, 0) FROM ventas
        WHERE fecha_venta >= '{hace_7d}' AND fecha_venta < '{ayer}'
          AND tipo_movimiento = 'Venta'
        GROUP BY canal
    """)
    ayer_dict = {_val(r, 0): float(_val(r, 1) or 0) for r in rows_ayer}
    avg_dict = {_val(r, 0): float(_val(r, 1) or 0) for r in rows_avg}

    n_alertas = 0
    for canal, avg in avg_dict.items():
        if avg < 500000:  # ignorar canales chicos
            continue
        ayer_v = ayer_dict.get(canal, 0)
        pct = (ayer_v - avg) / avg * 100
        if pct < -40:
            sev = 'critical' if pct < -60 else 'warning'
            crear_alerta(
                tipo='canal_caida',
                severity=sev,
                titulo=f"Canal {canal} cayó {pct:.0f}% vs promedio 7 días",
                mensaje=f"Ayer ${ayer_v/1e6:.1f}M vs promedio ${avg/1e6:.1f}M.",
                contexto={'canal': canal, 'venta_ayer': ayer_v, 'avg_7d': avg, 'pct': pct},
                fecha_objetivo=str(ayer),
                target_apps=['ventas', 'operaciones'],
            )
            print(f"  🟡 canal_caida: {canal} {pct:.0f}%")
            n_alertas += 1
    return n_alertas


# ============================================================
# REGLA 3: Mes va bajo proyección lineal (sin Prophet aún)
# ============================================================
def regla_mes_bajo_proyeccion():
    """
    Compara venta acumulada del mes vs proyección lineal basada en LY.
    Si va < 85% del esperado → alerta.
    """
    hoy = datetime.now().date()
    primer_dia_mes = hoy.replace(day=1)
    primer_dia_ly = primer_dia_mes.replace(year=hoy.year - 1)
    mismo_dia_ly = hoy.replace(year=hoy.year - 1)

    # Venta acumulada del mes actual
    rows = _q(f"""
        SELECT ROUND(SUM(venta_bruta), 0) FROM ventas
        WHERE fecha_venta >= '{primer_dia_mes}' AND fecha_venta <= '{hoy}'
    """)
    venta_mes_actual = float(_val(rows[0], 0) or 0) if rows else 0

    # Venta mismo período LY
    rows_ly = _q(f"""
        SELECT ROUND(SUM(venta_bruta), 0) FROM ventas
        WHERE fecha_venta >= '{primer_dia_ly}' AND fecha_venta <= '{mismo_dia_ly}'
    """)
    venta_periodo_ly = float(_val(rows_ly[0], 0) or 0) if rows_ly else 0

    if venta_periodo_ly <= 0:
        return None

    pct = (venta_mes_actual - venta_periodo_ly) / venta_periodo_ly * 100
    if pct < -15:  # 15% bajo el mismo período LY
        sev = 'critical' if pct < -30 else 'warning'
        crear_alerta(
            tipo='mes_bajo_LY',
            severity=sev,
            titulo=f"Mes acumulado {pct:.1f}% vs mismo período LY",
            mensaje=f"Al {hoy} llevamos ${venta_mes_actual/1e6:.1f}M vs ${venta_periodo_ly/1e6:.1f}M LY mismo día.",
            contexto={
                'venta_mes_actual': venta_mes_actual,
                'venta_periodo_ly': venta_periodo_ly,
                'pct': pct,
                'fecha': str(hoy),
            },
            fecha_objetivo=str(hoy),
            target_apps=['ventas', 'operaciones'],
        )
        print(f"  🟡 mes_bajo_LY: {pct:.1f}%")
        return True
    return None


# ============================================================
# REGLA 4: Margen Frontal del mes < umbral
# ============================================================
def regla_margen_bajo():
    """Si margen frontal del mes < 30% sobre venta neta → alerta."""
    hoy = datetime.now().date()
    primer_dia_mes = hoy.replace(day=1)

    rows = _q(f"""
        SELECT ROUND(SUM(margen_front), 0), ROUND(SUM(venta_neta), 0)
        FROM ventas
        WHERE fecha_venta >= '{primer_dia_mes}' AND fecha_venta <= '{hoy}'
    """)
    if not rows:
        return None
    margen = float(_val(rows[0], 0) or 0)
    venta_neta = float(_val(rows[0], 1) or 0)
    if venta_neta <= 0:
        return None

    pct_margen = margen / venta_neta * 100
    if pct_margen < 30:
        sev = 'critical' if pct_margen < 20 else 'warning'
        crear_alerta(
            tipo='margen_bajo',
            severity=sev,
            titulo=f"Margen Frontal del mes: {pct_margen:.1f}%",
            mensaje=f"Sobre venta neta ${venta_neta/1e6:.1f}M, margen frontal ${margen/1e6:.1f}M ({pct_margen:.1f}%). Bajo target 30%.",
            contexto={'margen': margen, 'venta_neta': venta_neta, 'pct_margen': pct_margen},
            fecha_objetivo=str(hoy),
            target_apps=['ventas'],
        )
        print(f"  🟡 margen_bajo: {pct_margen:.1f}%")
        return True
    return None


# ============================================================
# MAIN
# ============================================================
def main():
    print(f"=== Evaluación de alertas — {datetime.now()} ===\n", flush=True)
    crear_tabla_alertas()

    print("Reglas:")
    regla_anomalia_global()
    regla_anomalia_canal()
    regla_mes_bajo_proyeccion()
    regla_margen_bajo()

    print("\n[OK] Evaluación completa")


if __name__ == '__main__':
    main()
