#!/usr/bin/env python3
"""
MCP Server para UnionX — permite a Claude Desktop conversar con tus datos.

Configuración Claude Desktop (claude_desktop_config.json):
{
  "mcpServers": {
    "unionx": {
      "command": "C:/Users/andre/AppData/Local/Programs/Python/Python312/python.exe",
      "args": ["G:/Mi unidad/TRABAJO/RESPALDO/OPERACIONES/UNION X - IA/mcp_server_unionx.py"],
      "env": {
        "LIBSQL_URL": "https://unionx-ventas-andresunionx.aws-us-east-1.turso.io",
        "LIBSQL_AUTH_TOKEN": "..."
      }
    }
  }
}

Tools expuestas:
- consultar_kpis(fecha_desde, fecha_hasta) — KPIs venta/margen del período
- ventas_por_canal(fecha_desde, fecha_hasta) — desglose por canal
- top_skus(fecha_desde, fecha_hasta, limit) — top SKUs por venta
- comparar_yoy(periodo) — Delta YoY
- analizar_canal(canal, fecha_desde, fecha_hasta) — análisis profundo de 1 canal
- alertas_activas() — alertas abiertas (severity, mensaje)
- forecast_mes_actual() — proyección Prophet fin de mes
- evolucion_diaria(fecha_desde, fecha_hasta) — venta día a día
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

# Permitir cargar .env local si existe
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _user_env_from_registry(name: str) -> str:
    """Fallback Windows: leer User env var desde HKCU\\Environment.

    Claude Desktop a veces no hereda User env vars en el subproceso que launchea.
    """
    if sys.platform != 'win32':
        return ''
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as k:
            val, _ = winreg.QueryValueEx(k, name)
            return str(val)
    except (OSError, FileNotFoundError):
        return ''


URL = (os.environ.get('LIBSQL_URL') or _user_env_from_registry('LIBSQL_URL') or '').rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN') or _user_env_from_registry('LIBSQL_AUTH_TOKEN') or ''
HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'}


def _q(sql: str, args: list = None):
    if not URL:
        raise RuntimeError("LIBSQL_URL no seteado")
    request_args = []
    if args:
        for v in args:
            if v is None:
                request_args.append({"type": "null"})
            elif isinstance(v, int):
                request_args.append({"type": "integer", "value": str(v)})
            elif isinstance(v, float):
                request_args.append({"type": "float", "value": v})
            else:
                request_args.append({"type": "text", "value": str(v)})
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql, "args": request_args}}, {"type": "close"}]}
    r = requests.post(f"{URL}/v2/pipeline", json=body, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.json()['results'][0]['response']['result']


def _val(row, idx, default=None):
    cell = row[idx]
    if cell.get('type') == 'null':
        return default
    return cell.get('value', default)


# ============================================================
# TOOL IMPLEMENTATIONS
# ============================================================
def tool_consultar_kpis(fecha_desde: str, fecha_hasta: str) -> dict:
    """KPIs venta/margen para período (incluye comparación YoY)."""
    rows = _q("""
        SELECT
            ROUND(SUM(venta_bruta), 0) as venta_bruta,
            ROUND(SUM(venta_neta), 0) as venta_neta,
            ROUND(SUM(margen_front), 0) as margen_front,
            ROUND(SUM(margen_final), 0) as margen_final,
            ROUND(SUM(CASE WHEN tipo_movimiento='Venta' THEN cantidad ELSE 0 END), 0) as unidades,
            COUNT(DISTINCT documento) as ordenes
        FROM ventas
        WHERE fecha_venta BETWEEN ? AND ?
    """, [fecha_desde, fecha_hasta])
    if not rows or not rows.get('rows'):
        return {"error": "Sin datos"}
    r = rows['rows'][0]
    venta_bruta = float(_val(r, 0, 0))
    venta_neta = float(_val(r, 1, 0))
    margen_front = float(_val(r, 2, 0))
    margen_final = float(_val(r, 3, 0))
    unidades = float(_val(r, 4, 0))
    ordenes = int(_val(r, 5, 0))

    # YoY
    from datetime import datetime as _dt
    d1 = _dt.strptime(fecha_desde[:10], '%Y-%m-%d').replace(year=_dt.strptime(fecha_desde[:10], '%Y-%m-%d').year - 1)
    d2 = _dt.strptime(fecha_hasta[:10], '%Y-%m-%d').replace(year=_dt.strptime(fecha_hasta[:10], '%Y-%m-%d').year - 1)
    rows_ly = _q("SELECT ROUND(SUM(venta_bruta), 0), ROUND(SUM(margen_front), 0) FROM ventas WHERE fecha_venta BETWEEN ? AND ?",
                 [d1.strftime('%Y-%m-%d'), d2.strftime('%Y-%m-%d')])
    venta_ly = float(_val(rows_ly['rows'][0], 0, 0)) if rows_ly['rows'] else 0
    margen_ly = float(_val(rows_ly['rows'][0], 1, 0)) if rows_ly['rows'] else 0

    return {
        "periodo": f"{fecha_desde} a {fecha_hasta}",
        "venta_bruta": venta_bruta,
        "venta_bruta_M": round(venta_bruta / 1e6, 2),
        "venta_neta": venta_neta,
        "margen_front": margen_front,
        "margen_final": margen_final,
        "pct_margen_front": round(margen_front / venta_neta * 100, 1) if venta_neta else 0,
        "unidades": int(unidades),
        "ordenes": ordenes,
        "venta_LY": venta_ly,
        "delta_yoy_pct": round((venta_bruta - venta_ly) / abs(venta_ly) * 100, 1) if venta_ly else None,
        "margen_LY": margen_ly,
    }


def tool_ventas_por_canal(fecha_desde: str, fecha_hasta: str, top: int = 20) -> dict:
    """Desglose de ventas por canal."""
    rows = _q(f"""
        SELECT canal, ROUND(SUM(venta_bruta), 0), ROUND(SUM(margen_front), 0), COUNT(DISTINCT documento)
        FROM ventas
        WHERE fecha_venta BETWEEN ? AND ?
        GROUP BY canal ORDER BY 2 DESC LIMIT {int(top)}
    """, [fecha_desde, fecha_hasta])
    out = []
    for r in rows.get('rows', []):
        v = float(_val(r, 1, 0))
        m = float(_val(r, 2, 0))
        out.append({
            "canal": _val(r, 0),
            "venta": v,
            "venta_M": round(v / 1e6, 2),
            "margen_front": m,
            "pct_margen": round(m / v * 100, 1) if v else 0,
            "ordenes": int(_val(r, 3, 0)),
        })
    return {"periodo": f"{fecha_desde} a {fecha_hasta}", "canales": out}


def tool_top_skus(fecha_desde: str, fecha_hasta: str, limit: int = 20) -> dict:
    """Top SKUs por venta."""
    rows = _q(f"""
        SELECT sku, producto, ROUND(SUM(venta_bruta), 0), ROUND(SUM(cantidad), 0), marca, categoria_macro
        FROM ventas
        WHERE fecha_venta BETWEEN ? AND ? AND tipo_movimiento='Venta'
        GROUP BY sku, producto ORDER BY 3 DESC LIMIT {int(limit)}
    """, [fecha_desde, fecha_hasta])
    out = []
    for r in rows.get('rows', []):
        out.append({
            "sku": _val(r, 0),
            "producto": _val(r, 1),
            "venta": float(_val(r, 2, 0)),
            "unidades": int(float(_val(r, 3, 0))),
            "marca": _val(r, 4),
            "categoria": _val(r, 5),
        })
    return {"periodo": f"{fecha_desde} a {fecha_hasta}", "top_skus": out}


def tool_analizar_canal(canal: str, fecha_desde: str, fecha_hasta: str) -> dict:
    """Análisis profundo de 1 canal."""
    canal_safe = canal.replace("'", "''")
    rows = _q(f"""
        SELECT
            ROUND(SUM(venta_bruta), 0),
            ROUND(SUM(margen_front), 0),
            COUNT(DISTINCT documento),
            ROUND(SUM(cantidad), 0),
            COUNT(DISTINCT sku),
            ROUND(AVG(venta_bruta), 0)
        FROM ventas
        WHERE canal = '{canal_safe}' AND fecha_venta BETWEEN ? AND ?
    """, [fecha_desde, fecha_hasta])
    r = rows.get('rows', [None])[0]
    if not r:
        return {"error": "Sin datos"}

    # Top KAMs del canal
    rows_kam = _q(f"""
        SELECT kam, ROUND(SUM(venta_bruta), 0)
        FROM ventas WHERE canal = '{canal_safe}' AND fecha_venta BETWEEN ? AND ?
        GROUP BY kam ORDER BY 2 DESC LIMIT 5
    """, [fecha_desde, fecha_hasta])

    # Top productos
    rows_prod = _q(f"""
        SELECT producto, ROUND(SUM(venta_bruta), 0)
        FROM ventas WHERE canal = '{canal_safe}' AND fecha_venta BETWEEN ? AND ?
        GROUP BY producto ORDER BY 2 DESC LIMIT 5
    """, [fecha_desde, fecha_hasta])

    return {
        "canal": canal,
        "periodo": f"{fecha_desde} a {fecha_hasta}",
        "venta_total": float(_val(r, 0, 0)),
        "margen_front": float(_val(r, 1, 0)),
        "ordenes": int(_val(r, 2, 0)),
        "unidades": int(float(_val(r, 3, 0))),
        "skus_distintos": int(_val(r, 4, 0)),
        "ticket_promedio": float(_val(r, 5, 0)),
        "top_kams": [{"kam": _val(rk, 0), "venta": float(_val(rk, 1, 0))} for rk in rows_kam.get('rows', [])],
        "top_productos": [{"producto": _val(rp, 0), "venta": float(_val(rp, 1, 0))} for rp in rows_prod.get('rows', [])],
    }


def tool_evolucion_diaria(fecha_desde: str, fecha_hasta: str) -> dict:
    """Venta diaria del período."""
    rows = _q("""
        SELECT fecha_venta, ROUND(SUM(venta_bruta), 0), ROUND(SUM(cantidad), 0)
        FROM ventas
        WHERE fecha_venta BETWEEN ? AND ? AND tipo_movimiento='Venta'
        GROUP BY fecha_venta ORDER BY fecha_venta
    """, [fecha_desde, fecha_hasta])
    return {
        "periodo": f"{fecha_desde} a {fecha_hasta}",
        "dias": [{
            "fecha": _val(r, 0),
            "venta": float(_val(r, 1, 0)),
            "unidades": int(float(_val(r, 2, 0))),
        } for r in rows.get('rows', [])],
    }


def tool_alertas_activas() -> dict:
    """Alertas abiertas en el sistema."""
    try:
        rows = _q("""
            SELECT id, fecha_creada, severity, titulo, mensaje, tipo
            FROM alertas WHERE status='open'
            ORDER BY severity DESC, fecha_creada DESC LIMIT 50
        """)
        out = []
        for r in rows.get('rows', []):
            out.append({
                "id": int(_val(r, 0, 0)),
                "fecha": _val(r, 1),
                "severity": _val(r, 2),
                "titulo": _val(r, 3),
                "mensaje": _val(r, 4),
                "tipo": _val(r, 5),
            })
        # Conteo por severity
        counts = {'critical': 0, 'warning': 0, 'info': 0}
        for a in out:
            counts[a['severity']] = counts.get(a['severity'], 0) + 1
        return {"alertas": out, "totales": counts}
    except Exception as e:
        return {"error": str(e), "alertas": []}


def tool_forecast_mes_actual() -> dict:
    """Proyección Prophet del mes actual."""
    fc_path = Path(__file__).parent / 'data' / 'forecast' / 'forecast_resumen.json'
    if not fc_path.exists():
        return {"error": "Aún no hay forecast generado. El cron corre diario 06:00 UTC."}
    with open(fc_path, encoding='utf-8') as f:
        return json.load(f)


def tool_comparar_yoy(fecha_desde: str, fecha_hasta: str) -> dict:
    """Compara mismo período TY vs LY (alias de consultar_kpis)."""
    return tool_consultar_kpis(fecha_desde, fecha_hasta)


# ============================================================
# MCP PROTOCOL (stdio JSON-RPC simple)
# ============================================================
TOOLS = {
    "consultar_kpis": {
        "function": tool_consultar_kpis,
        "description": "KPIs venta/margen/unidades de un período + comparación YoY (mismo período año anterior)",
        "params": {"fecha_desde": "YYYY-MM-DD", "fecha_hasta": "YYYY-MM-DD"},
    },
    "ventas_por_canal": {
        "function": tool_ventas_por_canal,
        "description": "Top canales por venta en un período (con margen y órdenes)",
        "params": {"fecha_desde": "YYYY-MM-DD", "fecha_hasta": "YYYY-MM-DD", "top": "int (default 20)"},
    },
    "top_skus": {
        "function": tool_top_skus,
        "description": "Top SKUs más vendidos en período",
        "params": {"fecha_desde": "YYYY-MM-DD", "fecha_hasta": "YYYY-MM-DD", "limit": "int (default 20)"},
    },
    "analizar_canal": {
        "function": tool_analizar_canal,
        "description": "Análisis profundo de 1 canal: KAMs, productos top, ticket promedio",
        "params": {"canal": "str", "fecha_desde": "YYYY-MM-DD", "fecha_hasta": "YYYY-MM-DD"},
    },
    "evolucion_diaria": {
        "function": tool_evolucion_diaria,
        "description": "Serie diaria de ventas en un período",
        "params": {"fecha_desde": "YYYY-MM-DD", "fecha_hasta": "YYYY-MM-DD"},
    },
    "alertas_activas": {
        "function": tool_alertas_activas,
        "description": "Lista de alertas abiertas en el sistema (anomalías, quiebres, etc.)",
        "params": {},
    },
    "forecast_mes_actual": {
        "function": tool_forecast_mes_actual,
        "description": "Proyección Prophet del mes actual (venta esperada fin de mes vs LY)",
        "params": {},
    },
    "comparar_yoy": {
        "function": tool_comparar_yoy,
        "description": "Compara venta de un período vs mismo período año anterior",
        "params": {"fecha_desde": "YYYY-MM-DD", "fecha_hasta": "YYYY-MM-DD"},
    },
}


def handle_initialize(req_id):
    return {
        "jsonrpc": "2.0", "id": req_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "unionx-data", "version": "1.0.0"},
        },
    }


def handle_tools_list(req_id):
    tools_list = []
    for name, info in TOOLS.items():
        # Convertir params a JSON Schema
        properties = {}
        required = []
        for pname, ptype in info["params"].items():
            if "default" in ptype:
                properties[pname] = {"type": "integer" if "int" in ptype else "string"}
            elif ptype.startswith("int"):
                properties[pname] = {"type": "integer"}
            else:
                properties[pname] = {"type": "string"}
                required.append(pname)
        tools_list.append({
            "name": name,
            "description": info["description"],
            "inputSchema": {"type": "object", "properties": properties, "required": required},
        })
    return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_list}}


def handle_tools_call(req_id, params):
    name = params.get("name")
    args = params.get("arguments", {})
    if name not in TOOLS:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Tool {name} no existe"}}
    try:
        result = TOOLS[name]["function"](**args)
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"content": [{"type": "text", "text": json.dumps(result, default=str, ensure_ascii=False, indent=2)}]},
        }
    except Exception as e:
        return {
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"},
        }


def main():
    """Loop stdio JSON-RPC para MCP."""
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            req = json.loads(line)
            method = req.get("method")
            req_id = req.get("id")
            params = req.get("params", {})

            if method == "initialize":
                resp = handle_initialize(req_id)
            elif method == "initialized" or method == "notifications/initialized":
                continue  # notification, no response needed
            elif method == "tools/list":
                resp = handle_tools_list(req_id)
            elif method == "tools/call":
                resp = handle_tools_call(req_id, params)
            else:
                resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method {method} no soportado"}}

            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        except Exception as e:
            try:
                err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
                sys.stdout.write(json.dumps(err) + "\n")
                sys.stdout.flush()
            except Exception:
                pass


if __name__ == "__main__":
    main()
