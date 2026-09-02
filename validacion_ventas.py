#!/usr/bin/env python3
"""
Mecanismo de seguridad: valida un DataFrame de ventas antes de publicarlo
(Gate 1, en extract_mes_actual) o de enviarlo por email (Gate 2, en el pulso).

Filosofía: "siempre hay posibilidad de error" — preferir NO actualizar / NO
enviar antes que publicar un dato malo al CEO.

Uso:
    from validacion_ventas import validar_ventas_df
    ok, problemas, stats = validar_ventas_df(df_nuevo, df_previo)
    if not ok:
        # no publicar / no enviar; alertar
"""
from __future__ import annotations
import pandas as pd
from datetime import datetime, timedelta, timezone

CHILE_TZ = timezone(timedelta(hours=-4))

# Columnas mínimas que el dashboard necesita
COLS_REQUERIDAS = ['fecha_venta', 'sku', 'canal', 'tipo_movimiento',
                   'venta_bruta', 'venta_neta', 'cantidad']

# Umbrales de comparación vs versión previa (mismo mes)
DROP_MIN = 0.50   # el total nuevo no puede ser < 50% del previo
EXPLODE_MAX = 5.0  # ni > 5x del previo
DIAS_FRESCURA_MAX = 3  # la fecha máxima no puede ser más vieja que esto


def _num(s):
    return pd.to_numeric(s, errors='coerce')


def validar_ventas_df(df_nuevo: pd.DataFrame, df_previo: pd.DataFrame | None = None):
    """Devuelve (ok: bool, problemas: list[str], stats: dict).

    ok=True solo si pasa TODOS los checks duros. `problemas` describe cada fallo.
    `stats` se usa para logging/alertas aunque pase.
    """
    problemas: list[str] = []
    stats: dict = {}

    # --- 0. Existe y no vacío ---
    if df_nuevo is None or len(df_nuevo) == 0:
        return False, ["DataFrame nuevo vacío o None"], {'filas': 0}

    n = len(df_nuevo)
    stats['filas'] = int(n)

    # --- 1. Columnas requeridas ---
    faltan = [c for c in COLS_REQUERIDAS if c not in df_nuevo.columns]
    if faltan:
        problemas.append(f"Faltan columnas requeridas: {faltan}")
        # sin columnas clave no tiene sentido seguir con checks numéricos
        return False, problemas, stats

    vb = _num(df_nuevo['venta_bruta'])
    total_vb = float(vb.fillna(0).sum())
    stats['venta_bruta_total'] = round(total_vb, 0)
    stats['nan_venta_bruta'] = int(vb.isna().sum())

    # --- 2. Venta bruta finita y > 0 ---
    if not pd.notna(total_vb) or total_vb == float('inf') or total_vb == float('-inf'):
        problemas.append(f"venta_bruta total no finita: {total_vb}")
    if total_vb <= 0:
        problemas.append(f"venta_bruta total <= 0 ({total_vb:,.0f}) — extract probablemente vacío/roto")

    # --- 3. Frescura: fecha máxima no futura ni muy vieja ---
    fv = pd.to_datetime(df_nuevo['fecha_venta'], errors='coerce')
    fmax = fv.max()
    stats['fecha_max'] = str(fmax.date()) if pd.notna(fmax) else None
    hoy = datetime.now(CHILE_TZ).date()
    if pd.isna(fmax):
        problemas.append("fecha_venta no parseable (todas NaT)")
    else:
        fmax_d = fmax.date()
        if fmax_d > hoy + timedelta(days=1):
            problemas.append(f"fecha_venta máxima en el futuro: {fmax_d} (hoy {hoy})")
        if fmax_d < hoy - timedelta(days=DIAS_FRESCURA_MAX):
            problemas.append(f"dato viejo: fecha máxima {fmax_d}, hace > {DIAS_FRESCURA_MAX} días")

    # --- 4. Comparación vs versión previa (solo DÍAS COMPLETOS COMUNES) ---
    # Los dos parquets casi nunca cubren el mismo span: el extract arranca en
    # CUTOFF (que avanza con el freeze), el rollover de mes cambia el rango, y el
    # último día de cada snapshot está a medio transcurrir. Comparar totales
    # completos genera falsos positivos en ambos sentidos:
    #   - "caída catastrófica" al soltar el mes recién congelado,
    #   - "explosión" contra un previo truncado o capturado temprano en el día
    #     (01-sep-2026: 9,1x → bloqueó el parquet y el Pulso quedó sin datos).
    # Se compara SOLO la ventana común excluyendo el día de corte de cada uno
    # (parcial): ahí los totales sí deben ser casi idénticos, y una caída real
    # (pérdida de datos) sigue saltando.
    if df_previo is not None and len(df_previo) > 0 and 'venta_bruta' in df_previo.columns:
        fv_prev = pd.to_datetime(df_previo['fecha_venta'], errors='coerce')
        ini = max(fv.min(), fv_prev.min()) if fv.notna().any() and fv_prev.notna().any() else pd.NaT
        fin = (min(fmax, fv_prev.max()).normalize() - timedelta(days=1)) if pd.notna(fmax) and fv_prev.notna().any() else pd.NaT
        if pd.notna(ini) and pd.notna(fin) and ini <= fin:
            m_new, m_prev = (fv >= ini) & (fv <= fin), (fv_prev >= ini) & (fv_prev <= fin)
            total_new = float(_num(df_nuevo.loc[m_new, 'venta_bruta']).fillna(0).sum())
            total_prev = float(_num(df_previo.loc[m_prev, 'venta_bruta']).fillna(0).sum())
            n_new, n_prev = int(m_new.sum()), int(m_prev.sum())
            stats['ventana_comparada'] = f"{str(ini)[:10]}..{str(fin)[:10]}"
            stats['venta_bruta_previo'] = round(total_prev, 0)
            stats['filas_previo'] = n_prev
            if total_prev > 0:
                ratio = total_new / total_prev
                stats['ratio_venta'] = round(ratio, 3)
                if ratio < DROP_MIN:
                    problemas.append(
                        f"caída catastrófica de venta en {stats['ventana_comparada']}: "
                        f"{total_new:,.0f} es {ratio:.0%} del previo {total_prev:,.0f} "
                        f"(umbral {DROP_MIN:.0%})")
                if ratio > EXPLODE_MAX:
                    problemas.append(
                        f"explosión sospechosa de venta en {stats['ventana_comparada']}: "
                        f"{ratio:.1f}x el previo")
            if n_prev > 0:
                rratio = n_new / n_prev
                if rratio < 0.30:
                    problemas.append(f"filas cayeron a {rratio:.0%} del previo "
                                     f"({n_new} vs {n_prev}) en {stats['ventana_comparada']}")
                if rratio > EXPLODE_MAX:
                    problemas.append(f"filas explotaron a {rratio:.1f}x del previo "
                                     f"en {stats['ventana_comparada']}")
        else:
            stats['comparacion_previo'] = (
                f"saltada (sin días completos comunes: nuevo {str(fv.min())[:10]}..{str(fmax)[:10]}"
                f" vs previo {str(fv_prev.min())[:10]}..{str(fv_prev.max())[:10]})")

    ok = len(problemas) == 0
    return ok, problemas, stats


def resumen_validacion(ok, problemas, stats) -> str:
    """Texto legible para logs/alertas."""
    estado = "OK ✅" if ok else "FALLÓ ❌"
    lines = [f"Validación ventas: {estado}",
             f"  filas={stats.get('filas')}  venta_bruta=${stats.get('venta_bruta_total', 0):,.0f}"
             f"  fecha_max={stats.get('fecha_max')}"]
    if 'ratio_venta' in stats:
        lines.append(f"  ratio vs previo: {stats['ratio_venta']}")
    if problemas:
        lines.append("  Problemas:")
        lines += [f"    - {p}" for p in problemas]
    return "\n".join(lines)
