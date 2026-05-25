"""
Vista Bonos — Facturación.

Objetivo: tracking del bono mensual del área de facturación, calculado en
función del total de pedidos B2C facturados, con componentes de calidad
(notas de crédito) y SLA (velocidad facturación).

Datos:
  - data/historico/ventas_historico.parquet (cerrados hasta mes anterior)
  - data/historico/ventas_mes_actual.parquet (mes en curso, parcial)
  - data/contabilidad/cobranza/notas_credito.parquet (NC para calidad)
  - data/contabilidad/cobranza/pedidos_venta.parquet (proxy facturador via vendedor)
  - data/finanzas/ppto_2026.parquet (cumplimiento PPTO)

Roadmap completo: docs/BONOS_FACTURACION_ROADMAP.md
"""
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---- B2C clasificación ----
B2C_TIPOS = ('Marketplace', 'Páginas Propias', 'Tiendas Propias', 'Fidelización')

# ---- Parámetros Método C (calibración 2026 YTD) — usados si NO hay meta config ----
MIX_B2C_DEFAULT = 0.766
TICKET_B2C_DEFAULT = 25791


# ============================================================
# DATA LOADERS
# ============================================================
@st.cache_data(ttl=600)
def _load_ventas_year(year: int) -> pd.DataFrame:
    hist = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
    mes_actual = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
    frames = []
    if hist.exists():
        df = pd.read_parquet(hist)
        frames.append(df[df.get('anio_venta') == year])
    if mes_actual.exists():
        df2 = pd.read_parquet(mes_actual)
        frames.append(df2[df2.get('anio_venta') == year])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out['segmento'] = out['tipo_negocio'].apply(
        lambda x: 'B2C' if x in B2C_TIPOS else 'B2B'
    )
    return out


@st.cache_data(ttl=600)
def _load_nc() -> pd.DataFrame:
    p = PROJECT_ROOT / 'data' / 'contabilidad' / 'cobranza' / 'notas_credito.parquet'
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if 'fecha_emision' in df.columns:
        df['fecha_emision'] = pd.to_datetime(df['fecha_emision'], errors='coerce')
    return df


@st.cache_data(ttl=600)
def _load_ppto() -> pd.DataFrame:
    p = PROJECT_ROOT / 'data' / 'finanzas' / 'ppto_2026.parquet'
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df['linea'] = df['linea'].astype(str)
    return df


@st.cache_data(ttl=600)
def _load_pedidos_venta() -> pd.DataFrame:
    """Pedidos de Odoo con campo vendedor — proxy del facturador hasta H2.
    Cubre solo canales con asignación de vendedor (Melollevo + Website).
    Marketplaces (ML, Falabella, Walmart) NO tienen vendedor asignado."""
    p = PROJECT_ROOT / 'data' / 'contabilidad' / 'cobranza' / 'pedidos_venta.parquet'
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if 'fecha_pedido' in df.columns:
        df['fecha_pedido'] = pd.to_datetime(df['fecha_pedido'], errors='coerce')
    return df


@st.cache_data(ttl=3600)
def _load_bonos_config() -> pd.DataFrame:
    """Lee config persistida del bono por mes desde Turso.
    Tabla: bonos_facturacion_config (mes, n_personas, bono_persona_clp,
    base_clp, bono_pagado_real_clp, observacion).

    base_clp = n_personas × bono_persona_clp (pozo grupal).
    bono_pagado_real_clp = lo que efectivamente se pagó al cierre (manual)."""
    try:
        from views.alertas_helper import _query
        _query("""CREATE TABLE IF NOT EXISTS bonos_facturacion_config (
            mes TEXT PRIMARY KEY,
            n_personas INTEGER,
            bono_persona_clp REAL,
            base_clp REAL,
            bono_pagado_real_clp REAL,
            observacion TEXT,
            actualizado_en TEXT
        )""")
        # Migración suave: agregar columnas si no existen (idempotente)
        for col, tipo in [('n_personas', 'INTEGER'), ('bono_persona_clp', 'REAL')]:
            try:
                _query(f"ALTER TABLE bonos_facturacion_config ADD COLUMN {col} {tipo}")
            except Exception:
                pass  # ya existe

        res = _query("""SELECT mes, n_personas, bono_persona_clp, base_clp,
                               bono_pagado_real_clp, observacion
                        FROM bonos_facturacion_config ORDER BY mes""")
        if not res or not res.get('rows'):
            return pd.DataFrame(columns=['mes', 'n_personas', 'bono_persona_clp',
                                          'base_clp', 'bono_pagado_real_clp', 'observacion'])
        rows = []
        for r in res['rows']:
            def _v(i):
                c = r[i]
                return c.get('value') if c.get('type') != 'null' else None
            rows.append({
                'mes': _v(0),
                'n_personas': int(_v(1)) if _v(1) else None,
                'bono_persona_clp': float(_v(2)) if _v(2) else None,
                'base_clp': float(_v(3) or 0),
                'bono_pagado_real_clp': float(_v(4)) if _v(4) else None,
                'observacion': _v(5) or '',
            })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(columns=['mes', 'n_personas', 'bono_persona_clp',
                                      'base_clp', 'bono_pagado_real_clp', 'observacion'])


def _save_bono_config(mes: str, n_personas: int, bono_persona_clp: float,
                       bono_pagado_real_clp: float = None,
                       observacion: str = '') -> bool:
    base_clp = n_personas * bono_persona_clp
    try:
        from views.alertas_helper import _query
        _query("""INSERT INTO bonos_facturacion_config
                    (mes, n_personas, bono_persona_clp, base_clp,
                     bono_pagado_real_clp, observacion, actualizado_en)
                  VALUES (?, ?, ?, ?, ?, ?, ?)
                  ON CONFLICT(mes) DO UPDATE SET
                    n_personas=excluded.n_personas,
                    bono_persona_clp=excluded.bono_persona_clp,
                    base_clp=excluded.base_clp,
                    bono_pagado_real_clp=excluded.bono_pagado_real_clp,
                    observacion=excluded.observacion,
                    actualizado_en=excluded.actualizado_en""",
               [mes, int(n_personas), float(bono_persona_clp), float(base_clp),
                float(bono_pagado_real_clp) if bono_pagado_real_clp else None,
                observacion, datetime.now().isoformat()])
        return True
    except Exception as e:
        st.error(f"Error guardando config: {e}")
        return False


# ============================================================
# CÁLCULO MÉTRICAS Y BONO
# ============================================================
def _pedidos_b2c_mes(ventas: pd.DataFrame, year: int, month: int) -> int:
    sub = ventas[(ventas['anio_venta'] == year) &
                 (ventas['mes_venta'] == month) &
                 (ventas['segmento'] == 'B2C')]
    if sub.empty:
        return 0
    return int(sub['pedido'].nunique())


def _meta_b2c_mes(ppto: pd.DataFrame, year: int, month: int,
                   mix_b2c: float, ticket_b2c: float) -> float:
    sub = ppto[(ppto['year'] == year) & (ppto['month'] == month) &
               (ppto['linea'].str.startswith('Ingreso'))]
    if sub.empty:
        return 0.0
    revenue = float(sub['valor_ppto'].sum())
    return revenue * mix_b2c / ticket_b2c


def _nc_b2c_mes(nc: pd.DataFrame, ventas_mes: pd.DataFrame) -> int:
    """NC ligadas a pedidos B2C del mes (matching por origen_so → pedido)."""
    if nc.empty or ventas_mes.empty:
        return 0
    pedidos_b2c = set(ventas_mes.loc[ventas_mes['segmento'] == 'B2C', 'pedido'].dropna().astype(str))
    if 'origen_so' not in nc.columns:
        return 0
    # match flexible: la NC suele referenciar FAC nnn, no SO. Como proxy
    # contamos las NC del mes (es_nc=True) — área operativa real.
    nc_mes = nc[nc['fecha_emision'].dt.to_period('M') ==
                pd.Period(ventas_mes['fecha_venta'].max(), freq='M')]
    return int(nc_mes.get('es_nc', pd.Series([], dtype=bool)).sum()) if 'es_nc' in nc_mes.columns else len(nc_mes)


def _calcular_bono(pedidos_facturados: int, meta: float, nc_count: int,
                   sla_pct: float, base: float,
                   pesos: dict, umbral_nc_pct: float) -> dict:
    """Devuelve dict con factores y bono devengado."""
    # Factor volumen
    if meta <= 0:
        f_vol = 0.0
    else:
        ratio = pedidos_facturados / meta
        if ratio < 0.80:
            f_vol = 0.0
        elif ratio <= 1.20:
            # Mapear linealmente 0.80 → 0.0  y  1.20 → 1.20
            # piezas: 0.80-1.00 → 0→1, 1.00-1.20 → 1→1.2
            f_vol = round((ratio - 0.80) / 0.20 if ratio <= 1.0
                           else 1.0 + (ratio - 1.0), 4)
            f_vol = min(f_vol, 1.20)
        else:
            f_vol = 1.20

    # Factor calidad
    nc_pct = (nc_count / pedidos_facturados * 100) if pedidos_facturados > 0 else 0.0
    if umbral_nc_pct <= 0:
        f_cal = 1.0
    else:
        f_cal = max(0.0, 1.0 - (nc_pct / umbral_nc_pct - 1.0))
        f_cal = min(f_cal, 1.0)
        if nc_pct <= umbral_nc_pct:
            f_cal = 1.0

    # Factor SLA — directo
    f_sla = max(0.0, min(1.0, sla_pct / 100.0)) if sla_pct is not None else 0.0

    bono = base * (
        f_vol * pesos['volumen'] +
        f_cal * pesos['calidad'] +
        f_sla * pesos['sla']
    )

    return {
        'pedidos_facturados': pedidos_facturados,
        'meta': meta,
        'avance_pct': (pedidos_facturados / meta * 100) if meta > 0 else 0,
        'nc_count': nc_count,
        'nc_pct': nc_pct,
        'sla_pct': sla_pct,
        'f_volumen': f_vol,
        'f_calidad': f_cal,
        'f_sla': f_sla,
        'base': base,
        'bono_devengado': round(bono, -2),
    }


# ============================================================
# RENDER
# ============================================================
def _render_tab_resumen(ventas, nc, ppto, hoy, base, pesos, umbral_nc, modo_meta,
                         meta_manual, mix_b2c, ticket_b2c):
    """Tab 1 — KPIs mes en curso + desglose factores."""
    st.markdown("### 📅 Mes en curso")
    mes_actual_pedidos = _pedidos_b2c_mes(ventas, hoy.year, hoy.month)
    meta_mes_actual = (meta_manual if meta_manual is not None
                       else _meta_b2c_mes(ppto, hoy.year, hoy.month, mix_b2c, ticket_b2c))
    sub_mes = ventas[(ventas['anio_venta'] == hoy.year) & (ventas['mes_venta'] == hoy.month)]
    nc_mes = _nc_b2c_mes(nc, sub_mes)

    dia_mes_hoy = min(hoy.day, 31)
    if hoy.month == 12:
        proximo_mes = date(hoy.year + 1, 1, 1)
    else:
        proximo_mes = date(hoy.year, hoy.month + 1, 1)
    dias_mes = (proximo_mes - date(hoy.year, hoy.month, 1)).days
    proyeccion_mes = (mes_actual_pedidos / dia_mes_hoy * dias_mes) if dia_mes_hoy > 0 else 0

    sla_pct = 95.0  # placeholder hasta H1
    res = _calcular_bono(mes_actual_pedidos, meta_mes_actual, nc_mes,
                          sla_pct, base, pesos, umbral_nc)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pedidos B2C facturados (parcial)", f"{mes_actual_pedidos:,}",
              f"Proy. fin de mes: {proyeccion_mes:,.0f}")
    c2.metric("Meta del mes", f"{meta_mes_actual:,.0f}",
              f"{res['avance_pct']:.1f}% avance")
    c3.metric("Tasa NC", f"{res['nc_pct']:.2f}%",
              f"Umbral {umbral_nc:.1f}%", delta_color="inverse")
    c4.metric("💰 Bono devengado mes", f"${res['bono_devengado']:,.0f}",
              f"Base ${base:,.0f}")

    st.divider()
    st.markdown("### 🧮 Desglose del bono")
    df_fact = pd.DataFrame([
        {"Factor": "Volumen", "Peso": f"{pesos['volumen']*100:.0f}%",
         "Valor": f"{res['f_volumen']:.2f}",
         "Aporta al bono": f"${base * res['f_volumen'] * pesos['volumen']:,.0f}"},
        {"Factor": "Calidad (NC)", "Peso": f"{pesos['calidad']*100:.0f}%",
         "Valor": f"{res['f_calidad']:.2f}",
         "Aporta al bono": f"${base * res['f_calidad'] * pesos['calidad']:,.0f}"},
        {"Factor": "SLA", "Peso": f"{pesos['sla']*100:.0f}%",
         "Valor": f"{res['f_sla']:.2f}",
         "Aporta al bono": f"${base * res['f_sla'] * pesos['sla']:,.0f}"},
    ])
    st.dataframe(df_fact, use_container_width=True, hide_index=True)
    st.caption(
        "ℹ️ SLA usa placeholder 95% — pendiente integrar timestamp emisión factura vs "
        "creación SO en Odoo (H1)."
    )


def _render_tab_pozo(ventas, nc, ppto, hoy, base, pesos, umbral_nc,
                       modo_meta, meta_manual, mix_b2c, ticket_b2c, df_cfg):
    """Tab Distribución del Pozo Grupal.

    Como el bono es grupal y el jefe lo distribuye manualmente, este tab
    muestra cuánto da el pozo del mes y un cálculo orientativo "por persona
    si se repartiera parejo". El jefe asigna libremente el monto efectivo."""
    st.markdown("### 👥 Distribución del pozo grupal")
    st.caption(
        "El bono es **un pozo grupal** que el jefe de área distribuye **manualmente** "
        "entre las personas del equipo de facturación. Acá ves cuánto da el pozo "
        "según los factores del mes; la repartición la decide el jefe."
    )

    cfg_dict = (df_cfg.set_index('mes').to_dict('index')
                if df_cfg is not None and not df_cfg.empty else {})
    mes_key = f"{hoy.year}-{hoy.month:02d}"
    cfg_mes = cfg_dict.get(mes_key, {})

    n_personas = cfg_mes.get('n_personas') or 0
    bono_persona = cfg_mes.get('bono_persona_clp') or 0
    base_pozo = cfg_mes.get('base_clp') or (n_personas * bono_persona) or base

    # Calcular pozo devengado del mes
    pedidos_mes = _pedidos_b2c_mes(ventas, hoy.year, hoy.month)
    meta_mes = (meta_manual if meta_manual is not None
                else _meta_b2c_mes(ppto, hoy.year, hoy.month, mix_b2c, ticket_b2c))
    sub_mes = ventas[(ventas['anio_venta'] == hoy.year) & (ventas['mes_venta'] == hoy.month)]
    nc_mes = _nc_b2c_mes(nc, sub_mes)
    r = _calcular_bono(pedidos_mes, meta_mes, nc_mes, 95.0,
                        base_pozo, pesos, umbral_nc)

    if n_personas == 0 or bono_persona == 0:
        st.warning(
            "⚠️ Aún no cargas la configuración del pozo para "
            f"**{mes_key}**. Anda a la pestaña **💵 Carga Bonos** y "
            "carga N personas + bono por persona."
        )
        return

    pozo_por_persona_si_parejo = r['bono_devengado'] / n_personas if n_personas else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Personas en el equipo", f"{n_personas}")
    c2.metric("Bono por persona (target)", f"${bono_persona:,.0f}",
              "Si se cumple todo al 100%")
    c3.metric("💰 Pozo del mes (target)", f"${base_pozo:,.0f}",
              f"N × bono = {n_personas} × ${bono_persona:,.0f}")
    c4.metric("💵 Pozo devengado (mes)", f"${r['bono_devengado']:,.0f}",
              f"~${pozo_por_persona_si_parejo:,.0f}/persona si se reparte parejo",
              delta_color="off")

    st.divider()

    st.markdown("**Cómo se llegó al pozo devengado**")
    st.markdown(f"""
- Pedidos B2C facturados (parcial): **{pedidos_mes:,}** de meta {meta_mes:,.0f} → avance **{r['avance_pct']:.0f}%**
- Tasa NC: **{r['nc_pct']:.2f}%** (umbral {umbral_nc:.1f}%)
- Factor combinado: `{r['f_volumen']:.2f}` × {pesos['volumen']*100:.0f}% (vol) + `{r['f_calidad']:.2f}` × {pesos['calidad']*100:.0f}% (cal) + `{r['f_sla']:.2f}` × {pesos['sla']*100:.0f}% (sla)
- **Pozo devengado = ${base_pozo:,.0f} × factor combinado = ${r['bono_devengado']:,.0f}**
""")

    st.divider()
    st.markdown("### 📝 Distribución efectiva (manual)")
    st.info(
        f"El jefe de facturación reparte los **${r['bono_devengado']:,.0f}** "
        f"como considere entre las {n_personas} personas. Cuando esté cerrado, "
        f"registra el total pagado en **💵 Carga Bonos → Bono pagado real**."
    )

    pagado_mes = cfg_mes.get('bono_pagado_real_clp')
    if pagado_mes:
        diff = pagado_mes - r['bono_devengado']
        c1, c2 = st.columns(2)
        c1.metric("Pagado real cargado", f"${pagado_mes:,.0f}")
        c2.metric("Δ Pagado − Devengado", f"${diff:+,.0f}",
                   "Sobre pozo" if diff > 0 else "Bajo pozo",
                   delta_color="off")


def _render_tab_historico(ventas, nc, ppto, hoy, base, pesos, umbral_nc,
                            modo_meta, meta_manual, mix_b2c, ticket_b2c,
                            df_cfg):
    """Tab 3 — Histórico mes a mes + bono pagado real (si está cargado)."""
    st.markdown("### 📈 Histórico — bono devengado mes a mes")
    sla_pct = 95.0
    cfg_dict = (df_cfg.set_index('mes').to_dict('index')
                if df_cfg is not None and not df_cfg.empty else {})

    rows = []
    for m in range(1, hoy.month + 1):
        mes_key = f"{hoy.year}-{m:02d}"
        ped_m = _pedidos_b2c_mes(ventas, hoy.year, m)
        meta_m = (meta_manual if meta_manual is not None
                  else _meta_b2c_mes(ppto, hoy.year, m, mix_b2c, ticket_b2c))
        sub_m = ventas[(ventas['anio_venta'] == hoy.year) & (ventas['mes_venta'] == m)]
        nc_m = _nc_b2c_mes(nc, sub_m)
        # Base puede venir del config persistido
        base_m = cfg_dict.get(mes_key, {}).get('base_clp') or base
        r = _calcular_bono(ped_m, meta_m, nc_m, sla_pct, base_m, pesos, umbral_nc)
        pagado_real = cfg_dict.get(mes_key, {}).get('bono_pagado_real_clp')
        rows.append({
            "Mes": mes_key,
            "Pedidos B2C": ped_m,
            "Meta": int(meta_m),
            "Avance %": f"{r['avance_pct']:.0f}%",
            "NC %": f"{r['nc_pct']:.2f}%",
            "Factor Vol": f"{r['f_volumen']:.2f}",
            "Factor Cal": f"{r['f_calidad']:.2f}",
            "Base CLP": f"${base_m:,.0f}",
            "Bono devengado": f"${r['bono_devengado']:,.0f}",
            "Bono pagado real": f"${pagado_real:,.0f}" if pagado_real else "—",
            "_bono_num": r['bono_devengado'],
            "_pagado_num": pagado_real or 0,
        })
    df_hist = pd.DataFrame(rows)
    total_devengado = df_hist['_bono_num'].sum()
    total_pagado = df_hist['_pagado_num'].sum()
    st.dataframe(df_hist.drop(columns=['_bono_num', '_pagado_num']),
                 use_container_width=True, hide_index=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("💰 Devengado YTD", f"${total_devengado:,.0f}")
    c2.metric("💵 Pagado real YTD", f"${total_pagado:,.0f}" if total_pagado > 0 else "—")
    if total_pagado > 0:
        diff = total_pagado - total_devengado
        c3.metric("Δ Pagado − Devengado", f"${diff:,.0f}")


def _render_tab_config(hoy):
    """Tab Config — Carga manual del pozo por mes (N personas × bono persona)."""
    st.markdown("### 💵 Cargar bono mensual")
    st.caption(
        "Define el **pozo grupal** del mes: cuántas personas hay en facturación "
        "y cuánto bono target por persona. El pozo total = N × bono persona. "
        "Al cierre del mes registras lo que efectivamente se pagó."
    )

    df_cfg = _load_bonos_config()

    with st.form("form_bono_cfg"):
        c1, c2 = st.columns([1, 1])
        with c1:
            anio = st.selectbox("Año", [hoy.year - 1, hoy.year, hoy.year + 1],
                                 index=1)
        with c2:
            mes_n = st.selectbox("Mes", list(range(1, 13)), index=hoy.month - 1)
        mes_key = f"{anio}-{mes_n:02d}"
        st.caption(f"Clave mes: **{mes_key}**")

        # Pre-cargar si existe
        existing = df_cfg[df_cfg['mes'] == mes_key]
        prev_n = (int(existing['n_personas'].iloc[0])
                  if not existing.empty and existing['n_personas'].iloc[0] else 4)
        prev_bono_p = (float(existing['bono_persona_clp'].iloc[0])
                       if not existing.empty and existing['bono_persona_clp'].iloc[0] else 150_000)
        prev_pagado = (float(existing['bono_pagado_real_clp'].iloc[0])
                       if not existing.empty and existing['bono_pagado_real_clp'].iloc[0] else 0)
        prev_obs = existing['observacion'].iloc[0] if not existing.empty else ''

        st.markdown("**🎯 Pozo target del mes**")
        c3, c4, c5 = st.columns([1, 1, 1])
        with c3:
            n_personas = st.number_input("Personas en facturación", 1, 50, prev_n, 1,
                                          help="Cuántas personas conforman el equipo de facturación este mes.")
        with c4:
            bono_persona = st.number_input("Bono por persona target (CLP)",
                                            0, 2_000_000, int(prev_bono_p), 25_000,
                                            help="Cuánto recibe cada persona si el equipo cumple 100% (volumen, calidad, SLA).")
        with c5:
            pozo_calc = n_personas * bono_persona
            st.metric("💰 Pozo total target", f"${pozo_calc:,.0f}",
                       f"{n_personas} × ${bono_persona:,.0f}")

        st.divider()
        st.markdown("**💵 Cierre del mes (opcional)**")
        pagado_in = st.number_input(
            "Bono total pagado real (CLP)",
            0, 50_000_000, int(prev_pagado), 25_000,
            help="Suma de lo que se pagó efectivamente al equipo. Llenar al cierre del mes."
        )
        obs_in = st.text_input("Observación", prev_obs,
                                placeholder="Ej: Bonus extra por sobrecumplimiento, mes con feriado, etc.")

        submitted = st.form_submit_button("💾 Guardar / Actualizar", type="primary")
        if submitted:
            ok = _save_bono_config(mes_key, n_personas, bono_persona,
                                    pagado_in if pagado_in > 0 else None, obs_in)
            if ok:
                st.success(
                    f"✅ Guardado **{mes_key}**: {n_personas} personas × "
                    f"${bono_persona:,.0f} = pozo ${pozo_calc:,.0f}"
                    + (f" · pagado real ${pagado_in:,.0f}" if pagado_in else "")
                )
                st.cache_data.clear()
                st.rerun()

    st.divider()
    st.markdown("**📋 Config cargada actualmente:**")
    if df_cfg.empty:
        st.info("Aún no hay config persistida. Carga la primera arriba.")
    else:
        show = df_cfg.copy()
        show['n_personas'] = show['n_personas'].apply(lambda x: f"{int(x)}" if pd.notna(x) else "—")
        show['bono_persona_clp'] = show['bono_persona_clp'].apply(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        show['base_clp'] = show['base_clp'].apply(lambda x: f"${x:,.0f}")
        show['bono_pagado_real_clp'] = show['bono_pagado_real_clp'].apply(
            lambda x: f"${x:,.0f}" if pd.notna(x) and x else "—")
        show = show.rename(columns={
            'mes': 'Mes', 'n_personas': 'N personas',
            'bono_persona_clp': 'Bono/persona', 'base_clp': 'Pozo target',
            'bono_pagado_real_clp': 'Pagado real', 'observacion': 'Observación',
        })
        st.dataframe(show, use_container_width=True, hide_index=True)


def _render_tab_roadmap():
    """Tab Roadmap H0/H1/H2/H3 — versión bono grupal manual."""
    st.markdown("### 🛣️ Roadmap del módulo Bonos Facturación")
    st.caption(
        "Versión completa en `docs/BONOS_FACTURACION_ROADMAP.md`. "
        "Diseño actual: **scope solo B2C, pozo grupal, distribución manual por jefe.**"
    )

    st.markdown("#### 🎯 Decisiones tomadas (cerradas)")
    st.success("""
- ✅ **Scope:** solo pedidos B2C (Marketplace, Páginas Propias, Tiendas Propias, Fidelización)
- ✅ **Tipo de bono:** pozo grupal — N personas × bono por persona
- ✅ **Distribución:** manual — el jefe de facturación reparte el pozo entre el equipo
- ✅ **Umbral NC:** 1% (sobre esto cae factor calidad)
- ✅ **Cómo se carga el pozo:** manualmente desde la pestaña 💵 Carga Bonos
""")

    st.markdown("#### 📅 Fases")
    fases = [
        {
            "Fase": "🟢 H0 — HOY",
            "Pieza": "Pozo grupal mes (N × bono), pedidos B2C facturados, meta PPTO, tasa NC, bono devengado, histórico YTD, alarmas cuello botella WMS",
            "Dónde se ve": "Tabs Resumen / Pozo grupal / Histórico + Alertas Negocio",
            "Meta": "100% PPTO · NC ≤ 1%",
            "Estado": "✅ Operativo",
        },
        {
            "Fase": "🟡 H1 — 2-4 semanas",
            "Pieza": "SLA real (delta emisión factura − creación pedido en Odoo), alarma 'mes va bajo bono' al día 20",
            "Dónde se ve": "Tab Resumen (SLA real) + Alertas Negocio",
            "Meta": "SLA ≥ 95%",
            "Estado": "🟡 Config ya disponible · SLA pendiente extract Odoo",
        },
        {
            "Fase": "🟠 H2 — 1-3 meses",
            "Pieza": "Matching NC ↔ pedido B2C (por origen_so), tipificación NC por causa raíz (solo las por error facturación entran al cálculo), aprobación formal mes + export PDF planilla",
            "Dónde se ve": "Tab Histórico (NC depurada) + Tab Cierre Mensual (nuevo)",
            "Meta": "NC precisa por origen · Cero discusión post-cierre",
            "Estado": "⏳ Pendiente",
        },
        {
            "Fase": "🔵 H3 — 3-6 meses",
            "Pieza": "Pozo ponderado por mix canal (marketplaces más simples vs B2C custom), Forecast Prophet a nivel pedidos, dashboard externo del equipo (sin login)",
            "Dónde se ve": "Tab Resumen + pantalla operativa nueva",
            "Meta": "Equidad · awareness diario equipo",
            "Estado": "⏳ Pendiente",
        },
    ]
    st.dataframe(pd.DataFrame(fases), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("#### 🔄 Flujo mensual (cómo se usa)")
    st.markdown("""
1. **Inicio de mes** → vas a **💵 Carga Bonos** y cargas N personas + bono por persona.
2. **Durante el mes** → revisas **📊 Resumen** y **👥 Pozo grupal** para ver cómo va.
   - Te enteras temprano si el avance va bajo (volumen) o si subió la tasa NC.
3. **Cierre de mes** → ves el **pozo devengado** según factores cumplidos.
4. **El jefe de facturación reparte** el pozo entre las personas (criterio propio).
5. **Vas a 💵 Carga Bonos** y registras el **bono pagado real** total.
6. **📈 Histórico** queda con el track de devengado vs pagado y YTD acumulado.
""")


def render():
    st.title("💰 Bonos — Facturación")
    st.caption(
        "Bono mensual del área de facturación · scope **solo B2C** · "
        "factores volumen + calidad (NC) + SLA. Roadmap completo en `docs/BONOS_FACTURACION_ROADMAP.md`."
    )

    hoy = date.today()

    # ----------- SIDEBAR — Config bono -----------
    with st.sidebar:
        st.markdown("### ⚙️ Configuración Bono")
        st.caption(
            "💡 El **pozo** (cuánta plata hay en juego) se carga en la pestaña "
            "**💵 Carga Bonos**. Acá ajustas cómo se calcula qué porción del "
            "pozo se gana."
        )
        base = st.number_input(
            "Pozo fallback (CLP)",
            min_value=0, max_value=50_000_000, value=600_000, step=50_000,
            help="Solo se usa si no cargas N personas × bono persona en tab Config.",
        )

        st.markdown("---")
        st.markdown("**🎚️ Pesos de cada factor**")
        with st.expander("ℹ️ ¿Qué son los pesos?"):
            st.markdown("""
Definen **cuánto influye cada factor en el bono**.

Ejemplo con pozo = $1.000.000 y pesos 60/25/15:
- Si el equipo cumple TODO al 100% → cobra $1.000.000 completo.
- Si cumplen volumen 100% pero NC se dispara → pierden el 25% de calidad → cobran $750.000.
- Si volumen va al 50% (bajo umbral 80%) → pierden el 60% de volumen → cobran $400.000.

**Recomendación:** 60% volumen / 25% calidad / 15% SLA. Lo más importante es facturar todo el pedido (volumen), pero sin emitir mal (calidad).
""")

        preset = st.selectbox(
            "Preset rápido",
            ["Recomendado (60/25/15)",
             "Solo volumen (100/0/0)",
             "Volumen + calidad (70/30/0)",
             "Equilibrado (40/30/30)",
             "Personalizado"],
            index=0,
        )
        presets = {
            "Recomendado (60/25/15)": (60, 25, 15),
            "Solo volumen (100/0/0)": (100, 0, 0),
            "Volumen + calidad (70/30/0)": (70, 30, 0),
            "Equilibrado (40/30/30)": (40, 30, 30),
        }
        if preset != "Personalizado":
            peso_vol, peso_cal, peso_sla = presets[preset]
            st.caption(f"Volumen **{peso_vol}%** · Calidad **{peso_cal}%** · SLA **{peso_sla}%**")
        else:
            peso_vol = st.slider("Peso Volumen — cumplir meta de pedidos", 0, 100, 60, 5)
            peso_cal = st.slider("Peso Calidad — no emitir NC", 0, 100, 25, 5)
            peso_sla = st.slider("Peso SLA — facturar rápido", 0, 100, 15, 5)
            if (peso_vol + peso_cal + peso_sla) != 100:
                st.warning("⚠️ Pesos no suman 100%, se normalizan.")
        total = peso_vol + peso_cal + peso_sla or 1
        pesos = {'volumen': peso_vol / total, 'calidad': peso_cal / total,
                 'sla': peso_sla / total}

        st.markdown("---")
        st.markdown("**🎯 Umbrales**")
        umbral_nc = st.number_input(
            "Tasa NC máxima sin penalizar (%)", 0.1, 10.0, 1.0, 0.1,
            help="Sobre este % la calidad empieza a descontar. Al doble del umbral cae a 0."
        )

        st.markdown("---")
        st.markdown("**📐 Meta pedidos B2C del mes**")
        modo_meta = st.radio("Origen", ["PPTO (Método C)", "Manual"])
        if modo_meta == "Manual":
            meta_manual = st.number_input("Meta pedidos B2C", 0, 100_000, 14_000, 500)
            mix_b2c, ticket_b2c = MIX_B2C_DEFAULT, TICKET_B2C_DEFAULT
        else:
            meta_manual = None
            mix_b2c = st.number_input("Mix B2C asumido (%)", 50.0, 95.0, 76.6, 0.5) / 100
            ticket_b2c = st.number_input("Ticket B2C (CLP)", 10_000, 60_000, 25_791, 500)

    # ----------- CARGA DATOS -----------
    ventas = _load_ventas_year(hoy.year)
    nc = _load_nc()
    ppto = _load_ppto()
    df_cfg = _load_bonos_config()

    if ventas.empty:
        st.error("Sin datos de ventas para el año actual.")
        return

    # ----------- TABS -----------
    tab_res, tab_pozo, tab_hist, tab_cfg, tab_road = st.tabs([
        "📊 Resumen", "👥 Pozo grupal", "📈 Histórico",
        "💵 Carga Bonos", "🛣️ Roadmap",
    ])

    with tab_res:
        _render_tab_resumen(ventas, nc, ppto, hoy, base, pesos, umbral_nc,
                             modo_meta, meta_manual, mix_b2c, ticket_b2c)
    with tab_pozo:
        _render_tab_pozo(ventas, nc, ppto, hoy, base, pesos, umbral_nc,
                          modo_meta, meta_manual, mix_b2c, ticket_b2c, df_cfg)
    with tab_hist:
        _render_tab_historico(ventas, nc, ppto, hoy, base, pesos, umbral_nc,
                               modo_meta, meta_manual, mix_b2c, ticket_b2c, df_cfg)
    with tab_cfg:
        _render_tab_config(hoy)
    with tab_road:
        _render_tab_roadmap()
