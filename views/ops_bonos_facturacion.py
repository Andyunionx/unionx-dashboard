"""
Vista Bonos — Facturación.

Modelo OFICIAL UnionX (cargado por Andrés 2026-05-25):

  Bono = Base × (OTIF × 40% + Productividad × 50% + Espíritu MLL × 10%)

  Donde:
    - OTIF (40%)            → objetivo >98%, ratio pagable 90-100%
                              ⚠️ se mide contra MES CERRADO (M-1).
                              En mayo se evalúa OTIF de abril.
    - Productividad (50%)   → objetivo >90%, ratio pagable 90-100%
                              medida como pedidos_b2c_mes / N_personas
                              (proxy total dividido entre el equipo).
    - Espíritu MLL (10%)    → SÍ / NO (0% o 100%, manual del jefe).

  Ratio pagable 90-100%:
    - factor < 90% del rango → 0
    - factor entre 90% y 100% → lineal 0 → 1
    - factor >= 100% → 1.0 (cap)

  Scope: solo pedidos B2C.
  Tipo de bono: pozo grupal (N personas × bono persona).
  Distribución: manual por el jefe.

Datos:
  - data/historico/ventas_historico.parquet (cerrados)
  - data/historico/ventas_mes_actual.parquet (mes en curso, parcial)
  - data/contabilidad/cobranza/notas_credito.parquet (NC — info paralela)
  - data/finanzas/ppto_2026.parquet (meta opcional desde PPTO)
  - Turso bonos_facturacion_config (N, bono persona, OTIF M-1, Espíritu, pagado)

Roadmap: docs/BONOS_FACTURACION_ROADMAP.md
"""
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---- B2C clasificación ----
B2C_TIPOS = ('Marketplace', 'Páginas Propias', 'Tiendas Propias', 'Fidelización')

# ---- Parámetros Método C (calibración 2026 YTD) — usados para meta PPTO ----
MIX_B2C_DEFAULT = 0.766
TICKET_B2C_DEFAULT = 25791

# ---- Pesos OFICIALES del bono (UnionX 2026-05) ----
PESO_OTIF = 0.40
PESO_PROD = 0.50
PESO_ESPIRITU = 0.10

# ---- Objetivos y rangos ratio ----
OTIF_OBJETIVO = 98.0   # >98%
PROD_OBJETIVO = 90.0   # >90%
RATIO_MIN = 90.0       # bajo esto paga 0
RATIO_MAX = 100.0      # sobre esto paga 1.0 (cap)


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


@st.cache_data(ttl=30)
def _load_bonos_config() -> pd.DataFrame:
    """Lee config persistida del bono por mes desde Turso.

    Tabla: bonos_facturacion_config — modelo OFICIAL (OTIF/Prod/Espíritu).
    """
    try:
        from views.alertas_helper import _query
        _query("""CREATE TABLE IF NOT EXISTS bonos_facturacion_config (
            mes TEXT PRIMARY KEY,
            n_personas INTEGER,
            bono_persona_clp REAL,
            base_clp REAL,
            otif_pct REAL,
            espiritu_mll_pct REAL,
            bono_pagado_real_clp REAL,
            observacion TEXT,
            actualizado_en TEXT
        )""")
        # Migración suave para tablas viejas (idempotente)
        for col, tipo in [('n_personas', 'INTEGER'),
                          ('bono_persona_clp', 'REAL'),
                          ('otif_pct', 'REAL'),
                          ('espiritu_mll_pct', 'REAL')]:
            try:
                _query(f"ALTER TABLE bonos_facturacion_config ADD COLUMN {col} {tipo}")
            except Exception:
                pass

        res = _query("""SELECT mes, n_personas, bono_persona_clp, base_clp,
                               otif_pct, espiritu_mll_pct,
                               bono_pagado_real_clp, observacion
                        FROM bonos_facturacion_config ORDER BY mes""")
        if not res or not res.get('rows'):
            return pd.DataFrame(columns=['mes', 'n_personas', 'bono_persona_clp',
                                          'base_clp', 'otif_pct', 'espiritu_mll_pct',
                                          'bono_pagado_real_clp', 'observacion'])
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
                'otif_pct': float(_v(4)) if _v(4) is not None else None,
                'espiritu_mll_pct': float(_v(5)) if _v(5) is not None else None,
                'bono_pagado_real_clp': float(_v(6)) if _v(6) else None,
                'observacion': _v(7) or '',
            })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(columns=['mes', 'n_personas', 'bono_persona_clp',
                                      'base_clp', 'otif_pct', 'espiritu_mll_pct',
                                      'bono_pagado_real_clp', 'observacion'])


def _save_bono_config(mes: str, n_personas: int, bono_persona_clp: float,
                       otif_pct: float = None, espiritu_mll_pct: float = None,
                       bono_pagado_real_clp: float = None,
                       observacion: str = '') -> bool:
    base_clp = n_personas * bono_persona_clp
    try:
        from views.alertas_helper import _query
        _query("""INSERT INTO bonos_facturacion_config
                    (mes, n_personas, bono_persona_clp, base_clp,
                     otif_pct, espiritu_mll_pct,
                     bono_pagado_real_clp, observacion, actualizado_en)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                  ON CONFLICT(mes) DO UPDATE SET
                    n_personas=excluded.n_personas,
                    bono_persona_clp=excluded.bono_persona_clp,
                    base_clp=excluded.base_clp,
                    otif_pct=excluded.otif_pct,
                    espiritu_mll_pct=excluded.espiritu_mll_pct,
                    bono_pagado_real_clp=excluded.bono_pagado_real_clp,
                    observacion=excluded.observacion,
                    actualizado_en=excluded.actualizado_en""",
               [mes, int(n_personas), float(bono_persona_clp), float(base_clp),
                float(otif_pct) if otif_pct is not None else None,
                float(espiritu_mll_pct) if espiritu_mll_pct is not None else None,
                float(bono_pagado_real_clp) if bono_pagado_real_clp else None,
                observacion, datetime.now().isoformat()])
        return True
    except Exception as e:
        st.error(f"Error guardando config: {e}")
        return False


# ============================================================
# CÁLCULO MÉTRICAS Y BONO (MODELO OFICIAL UnionX)
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
    """NC del mes — info paralela, NO entra al cálculo del bono oficial."""
    if nc.empty or ventas_mes.empty:
        return 0
    try:
        nc_mes = nc[nc['fecha_emision'].dt.to_period('M') ==
                    pd.Period(ventas_mes['fecha_venta'].max(), freq='M')]
    except Exception:
        return 0
    return int(nc_mes.get('es_nc', pd.Series([], dtype=bool)).sum()) if 'es_nc' in nc_mes.columns else len(nc_mes)


def _factor_ratio(valor_pct, ratio_min: float = RATIO_MIN,
                   ratio_max: float = RATIO_MAX) -> float:
    """Convierte un KPI % a factor 0-1 con piso ratio_min y techo ratio_max.

    Ej: con piso 90 y techo 100:
      valor < 90 → 0.0
      valor = 95 → 0.5
      valor >= 100 → 1.0

    Robusto a None, NaN y strings.
    """
    if valor_pct is None or pd.isna(valor_pct):
        return 0.0
    try:
        v = float(valor_pct)
    except (TypeError, ValueError):
        return 0.0
    if v < ratio_min:
        return 0.0
    if v >= ratio_max:
        return 1.0
    return (v - ratio_min) / (ratio_max - ratio_min)


def _safe_float(v, default: float = 0.0) -> float:
    """Convierte a float; devuelve default si None/NaN/inválido."""
    if v is None or pd.isna(v):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v, default: int = 0) -> int:
    if v is None or pd.isna(v):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _calcular_bono_oficial(base: float,
                             otif_pct: float,
                             pedidos_b2c: int, n_personas: int,
                             meta_total: float,
                             espiritu_mll_pct: float) -> dict:
    """Calcula el bono según el modelo oficial UnionX.

    Args:
      base: pozo total target (N × bono_persona).
      otif_pct: OTIF del mes anterior (M-1), en porcentaje 0-100.
        Ratio pagable 90-100% (<90 paga 0, lineal entre 90 y 100, cap 100).
      pedidos_b2c: pedidos B2C facturados en el mes actual.
      n_personas: cuántas personas en facturación.
      meta_total: meta de pedidos B2C del mes (PPTO).
        Productividad % = pedidos_b2c / meta. Ratio pagable 90-100%.
      espiritu_mll_pct: nota 0-100% asignada por el jefe.
        Ratio 0-100% (cualquier valor entre 0 y 100 paga proporcional).
    """
    # ---- OTIF (40%) — ratio 90-100% ----
    f_otif = _factor_ratio(otif_pct, RATIO_MIN, RATIO_MAX)

    # ---- Productividad (50%) — ratio 90-100% ----
    if meta_total > 0:
        prod_pct = (pedidos_b2c / meta_total) * 100
    else:
        prod_pct = 0.0
    f_prod = _factor_ratio(prod_pct, RATIO_MIN, RATIO_MAX)

    # ---- Espíritu MLL (10%) — ratio 0-100% (escala completa, no binario) ----
    if espiritu_mll_pct is None:
        f_esp = 0.0
    else:
        f_esp = max(0.0, min(1.0, espiritu_mll_pct / 100.0))

    # ---- Bono final ----
    factor_total = (f_otif * PESO_OTIF +
                    f_prod * PESO_PROD +
                    f_esp * PESO_ESPIRITU)
    bono = base * factor_total

    pedidos_por_persona = pedidos_b2c / n_personas if n_personas > 0 else 0
    meta_por_persona = meta_total / n_personas if n_personas > 0 else 0

    return {
        'otif_pct': otif_pct,
        'f_otif': f_otif,
        'aporta_otif': base * f_otif * PESO_OTIF,
        'pedidos_b2c': pedidos_b2c,
        'meta_total': meta_total,
        'prod_pct': prod_pct,
        'pedidos_por_persona': pedidos_por_persona,
        'meta_por_persona': meta_por_persona,
        'f_prod': f_prod,
        'aporta_prod': base * f_prod * PESO_PROD,
        'espiritu_mll_pct': espiritu_mll_pct,
        'f_esp': f_esp,
        'aporta_esp': base * f_esp * PESO_ESPIRITU,
        'factor_total': factor_total,
        'bono_devengado': round(bono, -2),
    }


# ============================================================
# RENDER TABS
# ============================================================
def _render_tab_resumen(ventas, nc, ppto, hoy, modo_meta, meta_manual,
                          mix_b2c, ticket_b2c, df_cfg):
    """Tab Resumen — TODO consolidado: KPIs, productividad explícita, evolución."""
    # ----------- SELECTOR DE MES + REFRESCAR -----------
    c_sel1, c_sel2, c_sel3 = st.columns([1, 1, 2])
    with c_sel1:
        anio_sel = st.selectbox("Año", [hoy.year - 1, hoy.year], index=1,
                                  key="resumen_anio")
    with c_sel2:
        mes_sel = st.selectbox("Mes", list(range(1, 13)),
                                index=hoy.month - 1, key="resumen_mes")
    with c_sel3:
        st.write("")
        if st.button("🔄 Refrescar desde Turso", use_container_width=False):
            st.cache_data.clear()
            st.rerun()

    cfg_dict = (df_cfg.set_index('mes').to_dict('index')
                if df_cfg is not None and not df_cfg.empty else {})
    mes_key = f"{anio_sel}-{mes_sel:02d}"
    cfg_mes = cfg_dict.get(mes_key, {})

    N_DEFAULT, BONO_P_DEFAULT = 3, 60_000

    n_personas = _safe_int(cfg_mes.get('n_personas'), 0)
    bono_persona = _safe_float(cfg_mes.get('bono_persona_clp'), 0)
    base_pozo = _safe_float(cfg_mes.get('base_clp'), 0)
    otif_input = _safe_float(cfg_mes.get('otif_pct'), None)
    espiritu_input = _safe_float(cfg_mes.get('espiritu_mll_pct'), None)

    # Aplicar defaults SIEMPRE (3 × $60k = $180k) — esa es la política
    if n_personas == 0:
        n_personas = N_DEFAULT
    if bono_persona == 0:
        bono_persona = BONO_P_DEFAULT
    if base_pozo == 0:
        base_pozo = n_personas * bono_persona

    pedidos_mes = _pedidos_b2c_mes(ventas, anio_sel, mes_sel)
    meta_mes = (meta_manual if meta_manual is not None
                else _meta_b2c_mes(ppto, anio_sel, mes_sel, mix_b2c, ticket_b2c))

    otif_use = otif_input if otif_input is not None else 0
    esp_use = espiritu_input if espiritu_input is not None else 0

    r = _calcular_bono_oficial(
        base=base_pozo, otif_pct=otif_use,
        pedidos_b2c=pedidos_mes, n_personas=n_personas,
        meta_total=meta_mes, espiritu_mll_pct=esp_use,
    )

    # ----------- BLOQUE 1: KPIs DEL MES -----------
    st.markdown(f"### 📅 KPIs del mes {mes_key}")
    c1, c2, c3, c4 = st.columns(4)

    otif_label = "OTIF (M-1)" + (" 📝" if otif_input is not None else " ⚠️ FALTA")
    c1.metric(otif_label, f"{otif_use:.1f}%",
              f"Objetivo >{OTIF_OBJETIVO}%",
              delta_color="off" if otif_use >= OTIF_OBJETIVO else "inverse",
              help="Cargado manual en 💵 Carga Bonos." if otif_input is not None
                   else "FALTA cargar — ve a 💵 Carga Bonos.")
    c2.metric("Productividad", f"{r['prod_pct']:.1f}%",
              f"Objetivo >{PROD_OBJETIVO}%",
              delta_color="off" if r['prod_pct'] >= PROD_OBJETIVO else "inverse")
    esp_label = "Espíritu MLL" + (" 📝" if espiritu_input is not None else " ⚠️ FALTA")
    c3.metric(esp_label, f"{esp_use:.0f}%", "Nota 0-100% jefe")
    c4.metric("💰 Bono devengado", f"${r['bono_devengado']:,.0f}",
              f"De pozo ${base_pozo:,.0f}")

    if otif_input is None or espiritu_input is None:
        faltantes = []
        if otif_input is None:
            faltantes.append("OTIF")
        if espiritu_input is None:
            faltantes.append("Espíritu MLL")
        st.warning(
            f"⚠️ Falta cargar **{' + '.join(faltantes)}** para {mes_key}. "
            f"Ese KPI cuenta como 0% mientras tanto. → 💵 Carga Bonos."
        )

    st.divider()

    # ----------- BLOQUE 2: PRODUCTIVIDAD DETALLE -----------
    st.markdown("### 📦 Productividad — detalle por persona")
    pedidos_pp_real = pedidos_mes / n_personas if n_personas else 0
    pedidos_pp_meta = meta_mes / n_personas if n_personas else 0
    falta_para_meta = max(0, meta_mes - pedidos_mes)
    falta_pp = max(0, pedidos_pp_meta - pedidos_pp_real)

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Pedidos B2C totales", f"{pedidos_mes:,}",
              f"de meta {int(meta_mes):,}")
    p2.metric(f"Meta por persona (÷{n_personas})", f"{pedidos_pp_meta:,.0f}")
    p3.metric("Real por persona", f"{pedidos_pp_real:,.0f}",
              f"{(pedidos_pp_real/pedidos_pp_meta*100) if pedidos_pp_meta else 0:.0f}% de meta",
              delta_color="off")
    p4.metric("Faltan para llegar a meta", f"{falta_para_meta:,.0f}",
              f"~{falta_pp:,.0f}/persona",
              delta_color="off" if falta_para_meta == 0 else "inverse")

    st.caption(
        f"Productividad % del bono = pedidos B2C / meta. Para ganar el 50% completo "
        f"hay que estar ≥ {RATIO_MAX:.0f}% de meta ({int(meta_mes):,} pedidos = "
        f"{pedidos_pp_meta:,.0f}/persona). Bajo {RATIO_MIN:.0f}% paga 0."
    )

    st.divider()

    # ----------- BLOQUE 3: DESGLOSE BONO -----------
    st.markdown("### 🧮 Desglose del bono")
    df_kpi = pd.DataFrame([
        {
            "KPI": "OTIF (mes cerrado M-1)",
            "Peso": f"{PESO_OTIF*100:.0f}%",
            "Objetivo": f">{OTIF_OBJETIVO}%",
            "Real": f"{otif_use:.1f}%",
            "Ratio paga": f"{r['f_otif']*100:.0f}%",
            "Aporta al bono": f"${r['aporta_otif']:,.0f}",
        },
        {
            "KPI": "Productividad Pedidos",
            "Peso": f"{PESO_PROD*100:.0f}%",
            "Objetivo": f">{PROD_OBJETIVO}%",
            "Real": f"{r['prod_pct']:.1f}%",
            "Ratio paga": f"{r['f_prod']*100:.0f}%",
            "Aporta al bono": f"${r['aporta_prod']:,.0f}",
        },
        {
            "KPI": "Espíritu MLL",
            "Peso": f"{PESO_ESPIRITU*100:.0f}%",
            "Objetivo": "SÍ",
            "Real": f"{esp_use:.0f}%",
            "Ratio paga": f"{r['f_esp']*100:.0f}%",
            "Aporta al bono": f"${r['aporta_esp']:,.0f}",
        },
        {
            "KPI": "**TOTAL**",
            "Peso": "**100%**",
            "Objetivo": "",
            "Real": "",
            "Ratio paga": f"**{r['factor_total']*100:.0f}%**",
            "Aporta al bono": f"**${r['bono_devengado']:,.0f}**",
        },
    ])
    st.dataframe(df_kpi, use_container_width=True, hide_index=True)

    # ----------- BLOQUE 4: DIAGNÓSTICO -----------
    with st.expander("🔍 ¿Qué hay cargado en Turso para este mes?"):
        if not cfg_mes:
            st.error(f"❌ NO hay ningún registro para **{mes_key}** en Turso.")
        else:
            diag = pd.DataFrame([{
                'Campo': 'n_personas', 'Valor': cfg_mes.get('n_personas'),
                'Usado en cálculo': n_personas,
            }, {
                'Campo': 'bono_persona_clp', 'Valor': cfg_mes.get('bono_persona_clp'),
                'Usado en cálculo': f"${bono_persona:,.0f}",
            }, {
                'Campo': 'base_clp', 'Valor': cfg_mes.get('base_clp'),
                'Usado en cálculo': f"${base_pozo:,.0f}",
            }, {
                'Campo': 'otif_pct', 'Valor': cfg_mes.get('otif_pct'),
                'Usado en cálculo': f"{otif_use:.1f}%",
            }, {
                'Campo': 'espiritu_mll_pct', 'Valor': cfg_mes.get('espiritu_mll_pct'),
                'Usado en cálculo': f"{esp_use:.0f}%",
            }, {
                'Campo': 'bono_pagado_real_clp', 'Valor': cfg_mes.get('bono_pagado_real_clp'),
                'Usado en cálculo': '—',
            }])
            st.dataframe(diag, use_container_width=True, hide_index=True)
            st.caption(
                "Si ves NaN/None en 'Valor' pero esperabas tener cargado el campo, "
                "re-guarda el mes en 💵 Carga Bonos. Luego presiona 🔄 Refrescar arriba."
            )

    # ----------- EVOLUCIÓN MENSUAL: Meta vs Real, Prod% y OTIF% -----------
    st.divider()
    st.markdown(f"### 📈 Evolución mensual — Productividad y OTIF ({anio_sel})")
    st.caption(
        f"12 meses del año (real + futuro proyectado por PPTO). "
        f"Objetivos: Productividad ≥ {PROD_OBJETIVO}% · OTIF ≥ {OTIF_OBJETIVO}%."
    )

    evo_rows = []
    for mm in range(1, 13):
        ped = _pedidos_b2c_mes(ventas, anio_sel, mm)
        meta = (meta_manual if meta_manual is not None
                else _meta_b2c_mes(ppto, anio_sel, mm, mix_b2c, ticket_b2c))
        prod_pct = (ped / meta * 100) if meta > 0 else 0
        cfg_m = cfg_dict.get(f"{anio_sel}-{mm:02d}", {})
        otif_m = _safe_float(cfg_m.get('otif_pct'), None)
        es_futuro = (anio_sel > hoy.year) or (anio_sel == hoy.year and mm > hoy.month)
        es_mes_actual = (anio_sel == hoy.year and mm == hoy.month)
        evo_rows.append({
            'Mes': f"{anio_sel}-{mm:02d}",
            'mes_num': mm,
            'Estado': '🔮 Futuro' if es_futuro else ('⏳ En curso' if es_mes_actual else '✅ Cerrado'),
            'Pedidos B2C': ped,
            'Meta B2C': int(meta),
            'Productividad %': round(prod_pct, 1),
            'OTIF % (M-1)': round(otif_m, 1) if otif_m is not None else None,
            '_es_futuro': es_futuro,
            '_es_actual': es_mes_actual,
        })
    df_evo = pd.DataFrame(evo_rows)

    # Tabla compacta con semáforo (sin penalizar meses futuros o en curso parciales)
    def _fmt_prod(row):
        v = row['Productividad %']
        if row['_es_futuro']:
            return f"meta {row['Meta B2C']:,} pedidos"
        if row['_es_actual']:
            return f"{v:.1f}% (parcial)"
        return f"{v:.1f}%" + (" 🟢" if v >= PROD_OBJETIVO else " 🔴")

    def _fmt_otif(row):
        v = row['OTIF % (M-1)']
        if v is None:
            return "— sin cargar" if not row['_es_futuro'] else "—"
        return f"{v:.1f}%" + (" 🟢" if v >= OTIF_OBJETIVO else " 🔴")

    show_evo = df_evo.copy()
    show_evo['Productividad %'] = show_evo.apply(_fmt_prod, axis=1)
    show_evo['OTIF % (M-1)'] = show_evo.apply(_fmt_otif, axis=1)
    show_evo['Pedidos B2C'] = show_evo.apply(
        lambda r: "—" if r['_es_futuro'] else f"{r['Pedidos B2C']:,}", axis=1)
    show_evo['Meta B2C'] = show_evo['Meta B2C'].apply(lambda x: f"{x:,}")
    show_evo = show_evo.drop(columns=['mes_num', '_es_futuro', '_es_actual'])
    st.dataframe(show_evo, use_container_width=True, hide_index=True)

    # Gráfico líneas — solo Productividad real + OTIF cargada (futuro queda en NaN para no engañar)
    chart_data = df_evo.copy()
    chart_data.loc[chart_data['_es_futuro'], 'Productividad %'] = None
    chart_df = chart_data.set_index('Mes')[['Productividad %', 'OTIF % (M-1)']]
    st.line_chart(chart_df, height=320)
    st.caption(
        f"📊 Productividad real (cerrada o en curso) y OTIF cargada manualmente. "
        f"Los meses futuros muestran la meta en la tabla pero no se grafican como real."
    )


def _render_tab_config(hoy):
    """Tab Config — carga manual mensual con OTIF y Espíritu MLL."""
    st.markdown("### 💵 Cargar bono mensual")
    st.caption(
        "Define **OTIF del mes anterior** + **Espíritu MLL** del mes. "
        "El pozo está fijo en **3 personas × $60.000 = $180.000/mes** "
        "(según política UnionX). OTIF se mide contra mes cerrado: en mayo se evalúa abril."
    )

    df_cfg = _load_bonos_config()

    # Defaults fijos (política UnionX)
    N_PERSONAS_DEFAULT = 3
    BONO_PERSONA_DEFAULT = 60_000

    with st.form("form_bono_cfg"):
        c1, c2 = st.columns([1, 1])
        with c1:
            anio = st.selectbox("Año", [hoy.year - 1, hoy.year, hoy.year + 1],
                                 index=1)
        with c2:
            mes_n = st.selectbox("Mes", list(range(1, 13)), index=hoy.month - 1)
        mes_key = f"{anio}-{mes_n:02d}"
        mes_anterior = f"{anio}-{mes_n-1:02d}" if mes_n > 1 else f"{anio-1}-12"
        st.caption(f"Bono del mes: **{mes_key}** · OTIF se evalúa contra mes cerrado: **{mes_anterior}**")

        # Pre-cargar si existe — robusto a NaN
        existing = df_cfg[df_cfg['mes'] == mes_key]
        if not existing.empty:
            row = existing.iloc[0]
            prev_n = _safe_int(row.get('n_personas'), N_PERSONAS_DEFAULT)
            prev_bono_p = _safe_float(row.get('bono_persona_clp'), BONO_PERSONA_DEFAULT)
            prev_otif = _safe_float(row.get('otif_pct'), 98.0)
            prev_esp = _safe_float(row.get('espiritu_mll_pct'), 100.0)
            prev_pagado = _safe_float(row.get('bono_pagado_real_clp'), 0)
            prev_obs = row.get('observacion') or ''
        else:
            prev_n = N_PERSONAS_DEFAULT
            prev_bono_p = BONO_PERSONA_DEFAULT
            prev_otif = 98.0
            prev_esp = 100.0
            prev_pagado = 0
            prev_obs = ''

        # Pozo fijo según política UnionX (3 × $60k = $180k)
        st.markdown("**🎯 Pozo target — fijo por política**")
        c3, c4, c5 = st.columns(3)
        with c3:
            st.metric("Personas en facturación", str(N_PERSONAS_DEFAULT))
        with c4:
            st.metric("Bono/persona target", f"${BONO_PERSONA_DEFAULT:,}")
        with c5:
            pozo_calc = N_PERSONAS_DEFAULT * BONO_PERSONA_DEFAULT
            st.metric("💰 Pozo total target", f"${pozo_calc:,.0f}")

        # Permitir override en expander (raro pero por flexibilidad)
        with st.expander("⚙️ ¿Cambiar pozo este mes? (excepcional)"):
            n_personas = st.number_input(
                "Personas (default 3)", 1, 50, prev_n, 1,
                help="Solo cambiar si en este mes la dotación fue distinta."
            )
            bono_persona = st.number_input(
                "Bono/persona CLP (default $60.000)", 0, 2_000_000,
                int(prev_bono_p), 10_000,
            )
            if (n_personas, bono_persona) != (N_PERSONAS_DEFAULT, BONO_PERSONA_DEFAULT):
                st.warning(
                    f"⚠️ Override activo: {n_personas} × ${bono_persona:,.0f} "
                    f"= ${n_personas * bono_persona:,.0f} (no default)"
                )

        st.divider()
        st.markdown(f"**📊 KPIs del mes**")
        c6, c7 = st.columns(2)
        with c6:
            otif_in = st.number_input(
                f"OTIF (%) — medido en {mes_anterior}",
                0.0, 100.0, prev_otif, 0.1,
                help=f"OTIF del mes cerrado anterior. Objetivo >{OTIF_OBJETIVO}%. Ratio pagable 90-100%."
            )
        with c7:
            esp_in = st.slider(
                "Espíritu MLL (%)",
                0, 100, int(prev_esp), 5,
                help="Nota del jefe entre 0% y 100%. Define qué % del 10% se paga."
            )

        st.divider()
        st.markdown("**💵 Cierre del mes (opcional)**")
        pagado_in = st.number_input(
            "Bono total pagado real (CLP)",
            0, 50_000_000, int(prev_pagado), 25_000,
            help="Suma de lo que se pagó efectivamente al equipo. Llenar al cierre."
        )
        obs_in = st.text_input("Observación", prev_obs,
                                placeholder="Ej: Bonus extra por sobrecumplimiento")

        submitted = st.form_submit_button("💾 Guardar / Actualizar", type="primary")
        if submitted:
            ok = _save_bono_config(
                mes_key, n_personas, bono_persona,
                otif_pct=otif_in, espiritu_mll_pct=float(esp_in),
                bono_pagado_real_clp=pagado_in if pagado_in > 0 else None,
                observacion=obs_in,
            )
            if ok:
                st.success(
                    f"✅ Guardado **{mes_key}**: {n_personas} pers × ${bono_persona:,.0f} "
                    f"= pozo ${pozo_calc:,.0f} · OTIF {otif_in:.1f}% · "
                    f"Espíritu {esp_in}%"
                )
                st.cache_data.clear()
                st.rerun()

    st.divider()
    st.markdown("**📋 Config cargada en Turso:**")
    if df_cfg.empty:
        st.info("Aún no hay config persistida en Turso.")
    else:
        # Diagnóstico: campos faltantes por mes
        faltantes_check = []
        for _, row in df_cfg.iterrows():
            falta = []
            if pd.isna(row.get('n_personas')) or row.get('n_personas') in (None, 0):
                falta.append('n_personas')
            if pd.isna(row.get('otif_pct')) or row.get('otif_pct') is None:
                falta.append('otif')
            if pd.isna(row.get('espiritu_mll_pct')) or row.get('espiritu_mll_pct') is None:
                falta.append('espíritu')
            if falta:
                faltantes_check.append(f"{row['mes']}: falta {', '.join(falta)}")
        if faltantes_check:
            with st.expander(f"⚠️ {len(faltantes_check)} mes(es) con campos incompletos"):
                for f in faltantes_check:
                    st.write(f"- {f}")
                st.caption("Re-guarda esos meses con todos los campos para que el cálculo sea preciso.")
        show = df_cfg.copy()
        show['n_personas'] = show['n_personas'].apply(lambda x: f"{int(x)}" if pd.notna(x) else "—")
        show['bono_persona_clp'] = show['bono_persona_clp'].apply(
            lambda x: f"${x:,.0f}" if pd.notna(x) else "—")
        show['base_clp'] = show['base_clp'].apply(lambda x: f"${x:,.0f}")
        show['otif_pct'] = show['otif_pct'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
        show['espiritu_mll_pct'] = show['espiritu_mll_pct'].apply(
            lambda x: f"{x:.0f}%" if pd.notna(x) else "—")
        show['bono_pagado_real_clp'] = show['bono_pagado_real_clp'].apply(
            lambda x: f"${x:,.0f}" if pd.notna(x) and x else "—")
        show = show.rename(columns={
            'mes': 'Mes', 'n_personas': 'N',
            'bono_persona_clp': 'Bono/persona', 'base_clp': 'Pozo target',
            'otif_pct': 'OTIF M-1', 'espiritu_mll_pct': 'Espíritu',
            'bono_pagado_real_clp': 'Pagado real', 'observacion': 'Obs.',
        })
        st.dataframe(show, use_container_width=True, hide_index=True)


def _render_tab_roadmap():
    """Tab Roadmap H0/H1/H2/H3 con modelo oficial OTIF/Prod/Espíritu."""
    st.markdown("### 🛣️ Roadmap del módulo Bonos Facturación")
    st.caption(
        "Versión completa: `docs/BONOS_FACTURACION_ROADMAP.md` · "
        "**Modelo oficial UnionX: OTIF 40% / Productividad 50% / Espíritu MLL 10%**"
    )

    st.markdown("#### 🎯 Decisiones tomadas")
    st.success("""
- ✅ **Scope:** solo pedidos B2C
- ✅ **Tipo de bono:** pozo grupal — N personas × bono por persona
- ✅ **Distribución:** manual por el jefe
- ✅ **Fórmula oficial:** OTIF 40% + Productividad 50% + Espíritu MLL 10%
- ✅ **OTIF:** medido contra mes cerrado (M-1). En mayo se evalúa abril.
- ✅ **Productividad:** pedidos B2C / N personas, contra meta PPTO. Objetivo >90%.
- ✅ **Espíritu MLL:** nota 0-100% del jefe (ratio 0-100% del componente 10%).
- ✅ **Ratio pagable OTIF/Prod:** 90-100% (bajo 90 no paga, sobre 100 cap a 100).
""")

    st.markdown("#### 📅 Fases")
    fases = [
        {
            "Fase": "🟢 H0 — HOY",
            "Pieza": "Pozo grupal, productividad real (pedidos B2C/N), OTIF manual, Espíritu MLL manual, bono devengado mensual, histórico YTD, alarmas cuello botella WMS",
            "Dónde se ve": "Tabs Resumen / Pozo / Histórico + Alertas Negocio",
            "Meta": "OTIF >98% · Productividad >90%",
            "Estado": "✅ Operativo",
        },
        {
            "Fase": "🟡 H1 — 2-4 semanas",
            "Pieza": "**OTIF automatizado** desde fuente real (¿WMS? ¿Odoo entregados a tiempo?), alarma 'mes va bajo bono' al día 20, plantilla bulk de carga histórica",
            "Dónde se ve": "Tab Resumen (OTIF auto) + Alertas + Tab Carga (botón bulk)",
            "Meta": "Cero carga manual de OTIF",
            "Estado": "🟡 Pendiente definir fuente OTIF",
        },
        {
            "Fase": "🟠 H2 — 1-3 meses",
            "Pieza": "Espíritu MLL formalizado (rúbrica con sub-KPIs sumables), aprobación mensual + export PDF planilla, bloqueo edición tras cierre",
            "Dónde se ve": "Tab Carga (rúbrica), Tab Cierre Mensual (nuevo)",
            "Meta": "Cero discusión post-cierre",
            "Estado": "⏳ Pendiente",
        },
        {
            "Fase": "🔵 H3 — 3-6 meses",
            "Pieza": "Forecast pedidos B2C (Prophet directo, no Método C), dashboard externo equipo, vinculación con NPS/Helpdesk para Espíritu MLL data-driven",
            "Dónde se ve": "Tab Resumen + pantalla operativa",
            "Meta": "Bonos predictivos · awareness equipo",
            "Estado": "⏳ Pendiente",
        },
    ]
    st.dataframe(pd.DataFrame(fases), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("#### 🔄 Flujo mensual")
    st.markdown(f"""
1. **Inicio de mes** → tab **💵 Carga Bonos**: N personas + bono/persona + OTIF mes anterior + Espíritu MLL.
2. **Durante el mes** → **📊 Resumen** y **👥 Pozo grupal** para ver avance.
   - Sabes temprano si productividad va bajo {PROD_OBJETIVO}% y vas a perder ese 50%.
3. **Cierre de mes** → pozo devengado según los 3 KPIs cumplidos.
4. **Jefe reparte** el pozo manualmente entre el equipo.
5. **Registrar pagado real** en **💵 Carga Bonos** para reconciliar.
6. **📈 Histórico** queda con track YTD devengado vs pagado.
""")

    st.markdown("#### ❓ Pregunta abierta")
    st.warning("""
**¿De dónde sacamos el OTIF automatizado en H1?**

Opciones:
- WMS Odoo (despachos cumplidos en fecha)
- Couriers (tracking entregado dentro del SLA prometido)
- Sistema interno tipo "PostExpress" si lo hay

Mientras tanto, OTIF se carga manual cada mes en la tab 💵 Carga Bonos.
""")


def render():
    st.title("💰 Bonos — Facturación")
    st.caption(
        "Modelo oficial UnionX: **OTIF 40% + Productividad 50% + Espíritu MLL 10%** · "
        "Scope solo B2C · Pozo grupal · Distribución manual por jefe."
    )

    hoy = date.today()

    # ----------- SIDEBAR (solo meta) -----------
    with st.sidebar:
        st.markdown("### ⚙️ Meta de productividad")
        st.caption(
            "La meta de pedidos B2C contra la que se mide productividad. "
            "Por default sale del PPTO 2026 (Método C calibrado YTD)."
        )
        modo_meta = st.radio("Origen meta", ["PPTO (Método C)", "Manual"])
        if modo_meta == "Manual":
            meta_manual = st.number_input("Meta pedidos B2C", 0, 100_000, 14_000, 500)
            mix_b2c, ticket_b2c = MIX_B2C_DEFAULT, TICKET_B2C_DEFAULT
        else:
            meta_manual = None
            mix_b2c = st.number_input("Mix B2C asumido (%)", 50.0, 95.0, 76.6, 0.5) / 100
            ticket_b2c = st.number_input("Ticket B2C (CLP)", 10_000, 60_000, 25_791, 500)

        st.divider()
        st.markdown("### 📐 Pesos del bono")
        st.markdown(f"""
- **OTIF:** {PESO_OTIF*100:.0f}% (objetivo >{OTIF_OBJETIVO}%)
- **Productividad:** {PESO_PROD*100:.0f}% (objetivo >{PROD_OBJETIVO}%)
- **Espíritu MLL:** {PESO_ESPIRITU*100:.0f}% (SÍ/NO)

Ratio pagable: {RATIO_MIN:.0f}-{RATIO_MAX:.0f}%
        """)
        st.caption("⚙️ Pesos hardcoded según política UnionX. Cambiarlos requiere edición en código.")

    # ----------- CARGA DATOS -----------
    ventas = _load_ventas_year(hoy.year)
    nc = _load_nc()
    ppto = _load_ppto()
    df_cfg = _load_bonos_config()

    if ventas.empty:
        st.error("Sin datos de ventas para el año actual.")
        return

    # ----------- TABS (simplificado: solo Resumen / Carga / Roadmap) -----------
    tab_res, tab_cfg, tab_road = st.tabs([
        "📊 Resumen", "💵 Carga Bonos", "🛣️ Roadmap",
    ])

    with tab_res:
        _render_tab_resumen(ventas, nc, ppto, hoy, modo_meta, meta_manual,
                             mix_b2c, ticket_b2c, df_cfg)
    with tab_cfg:
        _render_tab_config(hoy)
    with tab_road:
        _render_tab_roadmap()
