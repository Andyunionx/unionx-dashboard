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


def _q(sql: str, retries: int = 3):
    body = {"requests": [{"type": "execute", "stmt": {"sql": sql}}, {"type": "close"}]}
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.post(f"{URL}/v2/pipeline", json=body, headers=HEADERS, timeout=120)
            r.raise_for_status()
            res = r.json()['results'][0]
            if res.get('type') == 'error':
                raise RuntimeError(res['error']['message'])
            return res['response']['result']['rows']
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_err = e
            import time
            time.sleep(2 ** attempt)
    raise last_err


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
# REGLA 5: Forecast Prophet — proyección bajo objetivo/LY
# ============================================================
def regla_proyeccion_prophet():
    """Lee forecast_resumen.json y crea alerta si proyección está -10% bajo LY."""
    import json as _json
    fc_path = Path(__file__).parent / 'data' / 'forecast' / 'forecast_resumen.json'
    if not fc_path.exists():
        return None
    try:
        with open(fc_path, encoding='utf-8') as f:
            r = _json.load(f)
    except Exception:
        return None

    proyeccion = r.get('proyeccion_mes', 0)
    venta_ly = r.get('venta_ly_mes_completo', 0)
    pct_vs_ly = r.get('pct_vs_ly')

    if not pct_vs_ly:
        return None

    if pct_vs_ly < -10:
        sev = 'critical' if pct_vs_ly < -25 else 'warning'
        crear_alerta(
            tipo='proyeccion_prophet_bajo_LY',
            severity=sev,
            titulo=f"Proyección fin de mes: {pct_vs_ly:+.1f}% vs LY (Prophet)",
            mensaje=f"Proyectamos cerrar el mes en ${proyeccion/1e6:.1f}M vs ${venta_ly/1e6:.1f}M LY.",
            contexto={
                'proyeccion': proyeccion,
                'venta_ly': venta_ly,
                'pct_vs_ly': pct_vs_ly,
                'venta_actual_mes': r.get('venta_actual_mes'),
                'dias_pendientes': r.get('dias_pendientes'),
            },
            fecha_objetivo=r.get('fecha_actual'),
            target_apps=['ventas', 'operaciones'],
        )
        print(f"  📈 proyeccion_prophet_bajo_LY: {pct_vs_ly:+.1f}%")
        return True
    return None


# ============================================================
# REGLA 5b: Cuello de botella WMS — capacidad vs demanda proyectada
# ============================================================
def regla_capacidad_wms_sobrecarga():
    """
    Cruza el forecast diario de capacidad (data/capacidad/volumen_operacional_diario.parquet)
    con el PPTO mensual de Ingresos (data/finanzas/ppto_2026.parquet) para detectar
    semanas/meses donde la operación se va a saturar.

    Reglas:
      - Si en los próximos 30 días hay >=5 días con pct_carga_equipo > 100% → warning
      - Si en los próximos 30 días hay >=3 días con pct_carga_equipo > 150% → critical
      - Si el PPTO mensual de un mes próximo (≤60d) implica pedidos B2C que exceden
        la capacidad mensual proyectada en > 30% → critical de planificación

    Pedidos B2C según PPTO se estiman con el Método C (mix 76.6% × ticket $25.791
    calibrado con 2026 YTD). Cuando exista metric oficial reemplazar el cálculo.
    """
    import pandas as _pd
    proyecto = Path(__file__).parent
    cap_path = proyecto / 'data' / 'capacidad' / 'volumen_operacional_diario.parquet'
    ppto_path = proyecto / 'data' / 'finanzas' / 'ppto_2026.parquet'

    if not cap_path.exists():
        return None

    try:
        cap = _pd.read_parquet(cap_path)
    except Exception:
        return None
    if cap.empty or 'fecha' not in cap.columns or 'pct_carga_equipo' not in cap.columns:
        return None

    cap['fecha'] = _pd.to_datetime(cap['fecha'])
    hoy = _pd.Timestamp(datetime.now().date())
    horizonte = cap[(cap['fecha'] >= hoy) & (cap['fecha'] <= hoy + _pd.Timedelta(days=30))]

    n_alertas = 0

    # Regla A — días con sobrecarga en 30d
    dias_sobrecarga = horizonte[horizonte['pct_carga_equipo'] > 100]
    dias_criticos = horizonte[horizonte['pct_carga_equipo'] > 150]

    if len(dias_criticos) >= 3:
        peor = dias_criticos.nlargest(1, 'pct_carga_equipo').iloc[0]
        crear_alerta(
            tipo='wms_sobrecarga_critica',
            severity='critical',
            titulo=f"{len(dias_criticos)} días con carga WMS >150% en próximos 30d",
            mensaje=(
                f"Peor día: {peor['fecha'].date()} con {peor['pct_carga_equipo']:.0f}% de carga "
                f"({int(peor.get('pedidos_a_procesar', 0)):,} pedidos vs capacidad). "
                f"Se necesita refuerzo de turnos, horas extra o contratación temporal YA."
            ),
            contexto={
                'n_dias_sobre_150': int(len(dias_criticos)),
                'peor_dia': str(peor['fecha'].date()),
                'peor_pct': float(peor['pct_carga_equipo']),
                'peor_pedidos': int(peor.get('pedidos_a_procesar', 0)),
                'horizonte_dias': 30,
            },
            fecha_objetivo=str(peor['fecha'].date()),
            target_apps=['operaciones'],
        )
        print(f"  🔴 wms_sobrecarga_critica: {len(dias_criticos)} días >150% (peor {peor['pct_carga_equipo']:.0f}%)")
        n_alertas += 1
    elif len(dias_sobrecarga) >= 5:
        peor = dias_sobrecarga.nlargest(1, 'pct_carga_equipo').iloc[0]
        crear_alerta(
            tipo='wms_sobrecarga',
            severity='warning',
            titulo=f"{len(dias_sobrecarga)} días con carga WMS >100% en próximos 30d",
            mensaje=(
                f"Peor día: {peor['fecha'].date()} con {peor['pct_carga_equipo']:.0f}%. "
                f"Planificar refuerzo de equipo o redistribuir picos."
            ),
            contexto={
                'n_dias_sobre_100': int(len(dias_sobrecarga)),
                'peor_dia': str(peor['fecha'].date()),
                'peor_pct': float(peor['pct_carga_equipo']),
                'horizonte_dias': 30,
            },
            fecha_objetivo=str(peor['fecha'].date()),
            target_apps=['operaciones'],
        )
        print(f"  🟡 wms_sobrecarga: {len(dias_sobrecarga)} días >100% (peor {peor['pct_carga_equipo']:.0f}%)")
        n_alertas += 1

    # Regla B — PPTO mensual implica pedidos B2C > capacidad mensual proyectada
    if ppto_path.exists():
        try:
            ppto = _pd.read_parquet(ppto_path)
            ppto['linea'] = ppto['linea'].astype(str)
            ing = ppto[(ppto['year'] == hoy.year) &
                       (ppto['linea'].str.startswith('Ingreso'))]
            ppto_mes = ing.groupby('month')['valor_ppto'].sum()
        except Exception:
            ppto_mes = None

        # Parámetros calibración Método C (2026 YTD)
        MIX_B2C = 0.766
        TICKET_B2C = 25791

        if ppto_mes is not None:
            for mes_num in [(hoy + _pd.Timedelta(days=30)).month,
                             (hoy + _pd.Timedelta(days=60)).month]:
                if mes_num not in ppto_mes.index:
                    continue
                revenue_ppto = float(ppto_mes[mes_num])
                pedidos_b2c_ppto = revenue_ppto * MIX_B2C / TICKET_B2C

                # Capacidad mensual proyectada en ese mes (sumar pedidos_proyectados del mes)
                mes_mask = (cap['fecha'].dt.month == mes_num) & (cap['fecha'].dt.year == hoy.year)
                cap_mes = float(cap.loc[mes_mask, 'pedidos_proyectados'].sum())
                if cap_mes <= 0:
                    continue
                # Capacidad B2C implícita (mismo mix)
                cap_b2c_mes = cap_mes * MIX_B2C
                gap_pct = (pedidos_b2c_ppto - cap_b2c_mes) / cap_b2c_mes * 100

                if gap_pct > 30:
                    sev = 'critical' if gap_pct > 100 else 'warning'
                    nombre_mes = {1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
                                  5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
                                  9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'}[mes_num]
                    crear_alerta(
                        tipo='wms_gap_ppto_capacidad',
                        severity=sev,
                        titulo=f"{nombre_mes}: PPTO implica +{gap_pct:.0f}% sobre capacidad WMS",
                        mensaje=(
                            f"PPTO {nombre_mes} = ${revenue_ppto/1e6:.0f}MM → "
                            f"~{pedidos_b2c_ppto:,.0f} pedidos B2C esperados, "
                            f"vs capacidad WMS proyectada {cap_b2c_mes:,.0f}. "
                            f"Decisión: ¿pre-contratar, ampliar turnos, o ajustar PPTO?"
                        ),
                        contexto={
                            'mes': mes_num,
                            'revenue_ppto': revenue_ppto,
                            'pedidos_b2c_ppto': float(pedidos_b2c_ppto),
                            'capacidad_b2c_mes': cap_b2c_mes,
                            'gap_pct': gap_pct,
                            'metodo': 'Método C (mix 76.6% × ticket $25.791)',
                        },
                        fecha_objetivo=f"{hoy.year}-{mes_num:02d}-01",
                        target_apps=['operaciones'],
                    )
                    print(f"  🔴 wms_gap_ppto: mes {mes_num}, +{gap_pct:.0f}% sobre capacidad")
                    n_alertas += 1

    return n_alertas if n_alertas else None


# ============================================================
# REGLA 6: Gap de pedidos (Yuju/Multivende cortados)
# ============================================================
def regla_gap_pedidos():
    """
    Si no entra ningún pedido a Odoo (vía Yuju/Multivende/manual) por más de 1h
    durante horario activo Chile → alerta.

    Horario activo: Lun-Sáb 09:00-23:00, Dom 10:00-22:00 (hora Chile).
    Severidades: warning si gap > 60 min, critical si > 120 min.

    Detecta corte de Yuju → Odoo (caso real 2026-05-09 que motivó esta regla).
    """
    try:
        from zoneinfo import ZoneInfo
        ahora_cl = datetime.now(ZoneInfo('America/Santiago'))
    except Exception:
        # Fallback: asumir UTC-4 (Chile horario invierno)
        ahora_cl = datetime.now() - timedelta(hours=4)

    hora = ahora_cl.hour
    dow = ahora_cl.weekday()  # 0=Lun, 6=Dom

    # Solo evaluar en horario activo
    if dow == 6:  # Domingo
        if hora < 10 or hora >= 22:
            return None
    else:  # Lun-Sáb
        if hora < 9 or hora >= 23:
            return None

    # Última venta en Turso (combinada fecha + hora)
    rows = _q("""
        SELECT MAX(fecha_venta || ' ' || hora_venta)
        FROM ventas
        WHERE tipo_movimiento = 'Venta'
          AND fecha_venta >= date('now', '-2 days')
    """)
    if not rows:
        return None
    ultimo_str = _val(rows[0], 0)
    if not ultimo_str:
        return None

    try:
        # hora_venta puede ser 'HH:MM:SS' o vacío. Construimos datetime sin tz
        ultimo = datetime.strptime(ultimo_str.strip(), '%Y-%m-%d %H:%M:%S')
    except ValueError:
        try:
            ultimo = datetime.strptime(ultimo_str.strip()[:16], '%Y-%m-%d %H:%M')
        except Exception:
            return None

    # Comparar como naive (ambos hora Chile)
    ahora_naive = ahora_cl.replace(tzinfo=None) if ahora_cl.tzinfo else ahora_cl
    delta_min = int((ahora_naive - ultimo).total_seconds() / 60)

    if delta_min < 60:
        return None

    sev = 'critical' if delta_min > 120 else 'warning'
    crear_alerta(
        tipo='gap_pedidos',
        severity=sev,
        titulo=f"Sin pedidos hace {delta_min} min — posible corte Yuju → Odoo",
        mensaje=(
            f"Último pedido registrado: {ultimo_str} (hace {delta_min} min, hora Chile). "
            f"Revisar panel Yuju, ir.cron de Odoo y Queue de Multivende. "
            f"Horario activo Chile: lun-sab 09-23, dom 10-22."
        ),
        contexto={
            'ultimo_pedido': ultimo_str,
            'delta_min': delta_min,
            'evaluado_en_chile': str(ahora_naive),
            'hora_chile': hora,
            'dia_semana': dow,
        },
        fecha_objetivo=str(ahora_cl.date()),
        target_apps=['ventas', 'operaciones'],
    )
    print(f"  🔴 gap_pedidos: {delta_min} min sin pedidos (último {ultimo_str})")
    return True


# ============================================================
# DATA QUALITY: reglas de inconsistencia que pueden sesgar el forecast
# ============================================================
def regla_dq_margen_100():
    """SKUs con costo_total=0 pero venta>0 → margen 100%, probable error de costeo."""
    rows = _q("""
        SELECT sku, producto, marca, ROUND(SUM(venta_bruta),0)
        FROM ventas
        WHERE fecha_venta >= date('now','-30 days')
          AND tipo_movimiento = 'Venta'
          AND venta_bruta > 0
          AND (costo_total = 0 OR costo_total IS NULL)
        GROUP BY sku, producto, marca
        HAVING SUM(venta_bruta) > 100000
        ORDER BY 4 DESC
        LIMIT 20
    """)
    if not rows:
        return None
    detalles = []
    for r in rows:
        detalles.append({
            'sku': _val(r, 0),
            'producto': (_val(r, 1) or '?')[:50],
            'marca': _val(r, 2),
            'venta_30d': float(_val(r, 3) or 0),
        })
    crear_alerta(
        tipo='dq_margen_100',
        severity='warning',
        titulo=f"{len(detalles)} SKUs con margen 100% (costo $0) - ventas > $100K LTM",
        mensaje=f"Productos sin costo registrado pero con ventas. Top: " +
                ", ".join(f"{d['sku']} (${d['venta_30d']/1e6:.1f}M)" for d in detalles[:5]),
        contexto={'skus_afectados': detalles},
        target_apps=['ventas'],
    )
    print(f"  ⚠️  dq_margen_100: {len(detalles)} SKUs")
    return len(detalles)


def regla_dq_sin_marca():
    """SKUs con marca NULL/?/vacía pero ventas > $100K LTM."""
    rows = _q("""
        SELECT sku, producto, ROUND(SUM(venta_bruta),0)
        FROM ventas
        WHERE fecha_venta >= date('now','-30 days')
          AND tipo_movimiento = 'Venta'
          AND (marca IS NULL OR marca = '?' OR marca = '' OR TRIM(marca) = '')
        GROUP BY sku, producto
        HAVING SUM(venta_bruta) > 100000
        ORDER BY 3 DESC
        LIMIT 20
    """)
    if not rows:
        return None
    detalles = [{'sku': _val(r, 0), 'producto': (_val(r, 1) or '?')[:50],
                 'venta_30d': float(_val(r, 2) or 0)} for r in rows]
    crear_alerta(
        tipo='dq_sin_marca',
        severity='warning',
        titulo=f"{len(detalles)} SKUs sin marca asignada con ventas relevantes",
        mensaje=f"Falta clasificacion de marca. Sesgo en forecast por marca/categoria. Top: " +
                ", ".join(f"{d['sku']}" for d in detalles[:5]),
        contexto={'skus_afectados': detalles},
        target_apps=['ventas'],
    )
    print(f"  ⚠️  dq_sin_marca: {len(detalles)} SKUs")
    return len(detalles)


def regla_dq_precio_inconsistente():
    """SKU con precio_unit < 50% del precio típico (precio lista estimado).

    Lee parquet de pricing_historico (precio_lista_estimado) y compara con
    la última venta efectiva.
    """
    pricing_path = Path(__file__).parent / 'data' / 'pricing_historico' / 'pricing_diario.parquet'
    if not pricing_path.exists():
        return None
    try:
        import pandas as pd
        df = pd.read_parquet(pricing_path)
        # Ultimos 7 dias por SKU x canal: precio promedio vs precio lista estimado
        ult = df[df['fecha'] >= pd.Timestamp.now() - pd.Timedelta(days=7)].copy()
        ult = ult[(ult['precio_lista_estimado'] > 0) & (ult['precio_promedio_dia'] > 0)]
        ult['ratio'] = ult['precio_promedio_dia'] / ult['precio_lista_estimado']
        # Inconsistente: precio < 50% lista (no es promo, es error)
        # Filtramos solo los que NO tienen promo_activa para no falsear con descuentos legítimos
        sospechosos = ult[(ult['ratio'] < 0.5) & (ult['promo_activa'] == 0)]
        if sospechosos.empty:
            return None
        agrupado = sospechosos.groupby(['sku', 'canal']).agg(
            ratio_min=('ratio', 'min'),
            precio_lista=('precio_lista_estimado', 'mean'),
            precio_dia=('precio_promedio_dia', 'mean'),
        ).reset_index().sort_values('ratio_min').head(20)

        detalles = agrupado.to_dict(orient='records')
        crear_alerta(
            tipo='dq_precio_inconsistente',
            severity='warning',
            titulo=f"{len(agrupado)} (SKU, canal) con precio < 50% del lista estimado",
            mensaje=f"Posible error de precios/lista (NO es promo declarada). Sesgo en regresor pricing del forecast.",
            contexto={'casos': detalles[:10]},
            target_apps=['ventas'],
        )
        print(f"  ⚠️  dq_precio_inconsistente: {len(agrupado)} casos")
        return len(agrupado)
    except Exception as e:
        print(f"  [skip] dq_precio_inconsistente: {e}")
        return None


def regla_dq_descripcion_faltante():
    """Productos con descripción/nombre tipo '[?]' o vacío y ventas > $100K LTM."""
    rows = _q("""
        SELECT sku, marca, ROUND(SUM(venta_bruta),0)
        FROM ventas
        WHERE fecha_venta >= date('now','-30 days')
          AND tipo_movimiento = 'Venta'
          AND (producto IS NULL OR producto = '' OR producto LIKE '[?]%' OR producto LIKE '?%')
        GROUP BY sku, marca
        HAVING SUM(venta_bruta) > 100000
        ORDER BY 3 DESC
        LIMIT 20
    """)
    if not rows:
        return None
    detalles = [{'sku': _val(r, 0), 'marca': _val(r, 1),
                 'venta_30d': float(_val(r, 2) or 0)} for r in rows]
    crear_alerta(
        tipo='dq_sin_descripcion',
        severity='info',
        titulo=f"{len(detalles)} SKUs sin descripción con ventas LTM > $100K",
        mensaje=f"Productos sin descripcion adecuada. Top: " +
                ", ".join(d['sku'] for d in detalles[:5]),
        contexto={'skus_afectados': detalles},
        target_apps=['ventas'],
    )
    print(f"  ℹ️  dq_sin_descripcion: {len(detalles)} SKUs")
    return len(detalles)


# ============================================================
# MAIN
# ============================================================
def main():
    print(f"=== Evaluación de alertas — {datetime.now()} ===\n", flush=True)
    crear_tabla_alertas()

    print("Reglas de negocio:")
    regla_anomalia_global()
    regla_anomalia_canal()
    regla_mes_bajo_proyeccion()
    regla_margen_bajo()
    regla_proyeccion_prophet()
    regla_capacidad_wms_sobrecarga()
    regla_gap_pedidos()

    print("\nReglas de Data Quality (sesgo forecast):")
    regla_dq_margen_100()
    regla_dq_sin_marca()
    regla_dq_descripcion_faltante()
    regla_dq_precio_inconsistente()

    print("\n[OK] Evaluación completa")


if __name__ == '__main__':
    main()
