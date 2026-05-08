"""
Genera Top 3 insights del día desde Turso (para incluir en email diario).

Detecta:
- Mejor canal del día
- Mayor caída vs últimos 7 días (anomalía)
- Top SKU del día
- Quiebres con demanda activa
"""
import os
from datetime import datetime, timedelta
from typing import List

import requests


URL = os.environ.get('LIBSQL_URL', '').rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '')
HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'}


def _query(sql: str):
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    r = requests.post(f"{URL}/v2/pipeline", json=body, headers=HEADERS, timeout=300)
    r.raise_for_status()
    return r.json()['results'][0]['response']['result']['rows']


def _val(row, idx, type_='value'):
    cell = row[idx]
    if cell.get('type') == 'null':
        return None
    return cell.get(type_)


def generar_insights() -> List[dict]:
    """Devuelve lista de insights con shape: {emoji, titulo, detalle, color}."""
    insights = []
    hoy = datetime.now().date()
    ayer = hoy - timedelta(days=1)
    hace_7d = hoy - timedelta(days=7)
    hace_30d = hoy - timedelta(days=30)

    # ----- 1. Venta de ayer vs promedio últimos 7 días (anomalía detection) -----
    try:
        rows_ayer = _query(f"""
            SELECT ROUND(SUM(venta_bruta), 0)
            FROM ventas
            WHERE fecha_venta = '{ayer.strftime('%Y-%m-%d')}'
              AND tipo_movimiento = 'Venta'
        """)
        venta_ayer = float(_val(rows_ayer[0], 0) or 0) if rows_ayer else 0

        rows_avg = _query(f"""
            SELECT ROUND(AVG(daily), 0) FROM (
                SELECT fecha_venta, SUM(venta_bruta) as daily
                FROM ventas
                WHERE fecha_venta >= '{hace_7d.strftime('%Y-%m-%d')}'
                  AND fecha_venta < '{ayer.strftime('%Y-%m-%d')}'
                  AND tipo_movimiento = 'Venta'
                GROUP BY fecha_venta
            )
        """)
        avg_7d = float(_val(rows_avg[0], 0) or 0) if rows_avg else 0

        if avg_7d > 0:
            delta_pct = (venta_ayer - avg_7d) / avg_7d * 100
            if delta_pct >= 20:
                insights.append({
                    'emoji': '🚀',
                    'titulo': f"Venta ayer: ${venta_ayer/1e6:.1f}M  (+{delta_pct:.0f}% sobre promedio 7d)",
                    'detalle': f"Promedio últimos 7 días: ${avg_7d/1e6:.1f}M",
                    'color': '#16A34A',
                })
            elif delta_pct <= -20:
                insights.append({
                    'emoji': '⚠️',
                    'titulo': f"Venta ayer: ${venta_ayer/1e6:.1f}M  ({delta_pct:.0f}% bajo promedio 7d)",
                    'detalle': f"Promedio últimos 7 días: ${avg_7d/1e6:.1f}M — REVISAR",
                    'color': '#DC2626',
                })
            else:
                insights.append({
                    'emoji': '📊',
                    'titulo': f"Venta ayer: ${venta_ayer/1e6:.1f}M  ({delta_pct:+.0f}% vs promedio 7d)",
                    'detalle': f"Promedio últimos 7 días: ${avg_7d/1e6:.1f}M",
                    'color': '#1E40AF',
                })
    except Exception as e:
        print(f"[WARN] insight venta ayer: {e}", flush=True)

    # ----- 2. Top canal del último día con cambio vs LY -----
    try:
        rows_canal = _query(f"""
            SELECT canal, ROUND(SUM(venta_bruta), 0) as venta
            FROM ventas
            WHERE fecha_venta = '{ayer.strftime('%Y-%m-%d')}'
              AND tipo_movimiento = 'Venta'
            GROUP BY canal
            ORDER BY venta DESC LIMIT 1
        """)
        if rows_canal:
            canal = _val(rows_canal[0], 0)
            venta = float(_val(rows_canal[0], 1) or 0)
            insights.append({
                'emoji': '🏆',
                'titulo': f"Top canal ayer: {canal}",
                'detalle': f"Vendió ${venta/1e6:.1f}M",
                'color': '#1E40AF',
            })
    except Exception as e:
        print(f"[WARN] insight top canal: {e}", flush=True)

    # ----- 3. Anomalía: canal con mayor caída vs últimos 7d -----
    try:
        rows_can_ayer = _query(f"""
            SELECT canal, ROUND(SUM(venta_bruta), 0)
            FROM ventas
            WHERE fecha_venta = '{ayer.strftime('%Y-%m-%d')}'
              AND tipo_movimiento = 'Venta'
            GROUP BY canal
        """)
        rows_can_avg = _query(f"""
            SELECT canal, ROUND(SUM(venta_bruta) / 7.0, 0)
            FROM ventas
            WHERE fecha_venta >= '{hace_7d.strftime('%Y-%m-%d')}'
              AND fecha_venta < '{ayer.strftime('%Y-%m-%d')}'
              AND tipo_movimiento = 'Venta'
            GROUP BY canal
        """)
        ayer_dict = {_val(r, 0): float(_val(r, 1) or 0) for r in rows_can_ayer}
        avg_dict = {_val(r, 0): float(_val(r, 1) or 0) for r in rows_can_avg}

        peor = None
        peor_pct = 0
        for canal, avg in avg_dict.items():
            if avg < 100000:  # ignorar canales chicos
                continue
            ayer_v = ayer_dict.get(canal, 0)
            pct = (ayer_v - avg) / avg * 100
            if pct < peor_pct:
                peor_pct = pct
                peor = (canal, avg, ayer_v)

        if peor and peor_pct < -30:
            canal, avg, ayer_v = peor
            insights.append({
                'emoji': '🚨',
                'titulo': f"Anomalía: {canal} cayó {peor_pct:.0f}% vs promedio 7d",
                'detalle': f"Ayer ${ayer_v/1e6:.1f}M vs promedio ${avg/1e6:.1f}M",
                'color': '#DC2626',
            })
    except Exception as e:
        print(f"[WARN] insight anomalía: {e}", flush=True)

    # ----- 4. Margen Frontal: % vs venta del día -----
    try:
        rows_mg = _query(f"""
            SELECT ROUND(SUM(venta_bruta), 0), ROUND(SUM(margen_front), 0), ROUND(SUM(venta_neta), 0)
            FROM ventas
            WHERE fecha_venta = '{ayer.strftime('%Y-%m-%d')}'
        """)
        if rows_mg:
            v_bruta = float(_val(rows_mg[0], 0) or 0)
            mg_front = float(_val(rows_mg[0], 1) or 0)
            v_neta = float(_val(rows_mg[0], 2) or 0)
            if v_neta > 0:
                pct_mg = mg_front / v_neta * 100
                color = '#16A34A' if pct_mg >= 50 else ('#EA580C' if pct_mg >= 30 else '#DC2626')
                insights.append({
                    'emoji': '💰',
                    'titulo': f"Margen Frontal ayer: {pct_mg:.1f}% (${mg_front/1e6:.1f}M)",
                    'detalle': f"Sobre venta neta de ${v_neta/1e6:.1f}M",
                    'color': color,
                })
    except Exception as e:
        print(f"[WARN] insight margen: {e}", flush=True)

    return insights[:4]  # máximo 4


def render_insights_html(insights: List[dict]) -> str:
    """Renderiza los insights como bloque HTML para email."""
    if not insights:
        return "<p style='color:#94A3B8;'>Sin insights generados hoy.</p>"

    blocks = []
    for ins in insights:
        block = f"""
        <div style="background:white;border-left:4px solid {ins['color']};padding:12px 16px;margin-bottom:8px;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <div style="font-size:1.05rem;font-weight:600;color:#1E293B;">
                {ins['emoji']} {ins['titulo']}
            </div>
            <div style="font-size:0.85rem;color:#64748B;margin-top:4px;">{ins['detalle']}</div>
        </div>
        """
        blocks.append(block)

    return '\n'.join(blocks)


if __name__ == '__main__':
    insights = generar_insights()
    print(f"=== Insights generados ===\n")
    for i, ins in enumerate(insights, 1):
        print(f"{i}. {ins['emoji']} {ins['titulo']}")
        print(f"   {ins['detalle']}\n")
