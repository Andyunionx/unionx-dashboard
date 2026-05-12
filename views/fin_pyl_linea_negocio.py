"""
Vista P&L por Línea de Negocio — App Finanzas.

Construye P&L completo (Venta → COGS → Mg Bruto → GAV asignado → EBIT → ROI)
para cada línea de negocio cruzando:
  - P&L consolidado del archivo (Planificación Financiera)
  - Distribución a canales del archivo Analisis_Contribucion_2026_V06.xlsx
  - Drivers de prorrateo configurables por CC

Estado actual: 🟡 PARCIAL — usa la distribución del archivo de Análisis de
Contribución que ya tenemos. Cuando llegue el Drive de control de gestión
presupuestaria, se podrá refinar con drivers manuales.
"""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views._fin_data import pyl

PROJECT_ROOT = Path(__file__).parent.parent
CONTRIB_FILE = PROJECT_ROOT / "data" / "planillas" / "Analisis_Contribucion_2026_V06.xlsx"


@st.cache_data(ttl=600)
def _cargar_contribucion() -> pd.DataFrame:
    """Lee la hoja principal del Análisis de Contribución por canal/línea."""
    if not CONTRIB_FILE.exists():
        return pd.DataFrame()
    try:
        # Intentar varias hojas comunes
        for sheet in ["Detalle", "Resumen", "Sheet1", "P&L"]:
            try:
                df = pd.read_excel(CONTRIB_FILE, sheet_name=sheet)
                if not df.empty:
                    return df
            except Exception:
                continue
    except Exception:
        pass
    return pd.DataFrame()


def render():
    with st.sidebar:
        st.markdown("### 📈 **P&L por LN**")
        st.caption("Margen por línea de negocio")
        st.divider()

    st.title("📈 P&L por Línea de Negocio")
    st.caption(
        "Margen y rentabilidad por línea: Recíbelo · Blue Express · "
        "Grupo Eter · Control Aportes (o las que correspondan)"
    )

    df_pyl = pyl()
    df_contrib = _cargar_contribucion()

    if df_pyl.empty:
        st.warning("⏳ Sin datos. Correr `python extract_finanzas_planificacion.py`.")
        return

    st.info(
        "🟡 **Vista parcial — Iteración 3.**\n\n"
        "Este P&L por línea de negocio se construye cruzando 3 fuentes:\n\n"
        "1. ✅ **P&L consolidado** del archivo Planificación Financiera (cargado)\n"
        f"2. ⏳ **Distribución a canales** del archivo `Analisis_Contribucion_2026_V06.xlsx` "
        f"({'cargado' if not df_contrib.empty else 'pendiente de revisar estructura'})\n"
        "3. ⏳ **Drivers manuales de prorrateo** por CC (pendiente: vendrá del "
        "Drive de control de gestión que vas a conectar esta semana)\n\n"
        "**Próximo paso:** definir contigo cómo se mapean los CCs (4101-XX, 4201-XX) "
        "a cada línea de negocio. Hay 2 opciones:\n"
        "- **Driver manual %** por CC (ej: arriendo → 60% Recíbelo · 30% B.Express · 10% Eter)\n"
        "- **Prorrateo automático** por ventas / pedidos del canal"
    )

    # Mostrar la data que SÍ tenemos del Análisis de Contribución
    if not df_contrib.empty:
        st.markdown("### 📋 Distribución actual cargada (referencia)")
        st.caption(
            f"Hoja leída de `{CONTRIB_FILE.name}` · "
            f"{len(df_contrib)} filas · {len(df_contrib.columns)} columnas"
        )
        st.dataframe(df_contrib.head(20), use_container_width=True, height=380)
    else:
        st.warning(
            f"⚠️ No se pudo cargar `{CONTRIB_FILE.name}`. "
            "Cuando esté el archivo de distribución por canal actualizado, esta vista "
            "se completa automáticamente."
        )

    st.divider()

    # ─── Stub: Estructura propuesta del P&L por LN ──────────────────────
    st.markdown("### 🏗️ Estructura propuesta del P&L por Línea de Negocio")
    st.markdown(
        "Cuando se conecten las 3 fuentes, esta vista mostrará para cada LN:\n\n"
        "| Línea P&L | Recíbelo | B. Express | G. Eter | Control Apt | Total |\n"
        "|---|---:|---:|---:|---:|---:|\n"
        "| Ventas | $X | $X | $X | $X | $X |\n"
        "| Costos Directos | -$X | -$X | -$X | -$X | -$X |\n"
        "| **Margen Bruto** | $X | $X | $X | $X | $X |\n"
        "| Comisiones canal | -$X | -$X | -$X | -$X | -$X |\n"
        "| Logística | -$X | -$X | -$X | -$X | -$X |\n"
        "| **Margen Contribución** | $X | $X | $X | $X | $X |\n"
        "| GAV asignado (driver) | -$X | -$X | -$X | -$X | -$X |\n"
        "| **EBIT por línea** | $X | $X | $X | $X | $X |\n"
        "| **ROI %** | X% | X% | X% | X% | X% |\n"
    )

    st.divider()

    # ─── Mientras tanto: gráfico de margen contribución consolidado ─────
    st.markdown("### 📊 Margen Contribución consolidado (mientras llega la distribución)")

    df_mc = df_pyl[
        df_pyl["linea"].str.contains("Margen Contribución", na=False, case=False)
    ].copy().sort_values("fecha").tail(24)
    df_ing = df_pyl[
        df_pyl["linea"].str.contains("Ingresos por Ventas", na=False, case=False)
    ].copy().sort_values("fecha").tail(24)

    if not df_mc.empty and not df_ing.empty:
        merged = df_mc.merge(
            df_ing[["fecha", "valor"]].rename(columns={"valor": "ingreso"}),
            on="fecha", how="inner",
        )
        merged["mc_pct"] = merged["valor"] / merged["ingreso"] * 100

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=merged["fecha"], y=merged["valor"],
            name="MC absoluto (M CLP)",
            marker_color="#16A34A",
            yaxis="y",
            hovertemplate="%{x|%b %Y}<br>MC: $%{y:,.0f} M<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=merged["fecha"], y=merged["mc_pct"],
            name="MC %",
            mode="lines+markers",
            line=dict(color="#7C3AED", width=3),
            marker=dict(size=8),
            yaxis="y2",
            hovertemplate="%{x|%b %Y}<br>MC %: %{y:.1f}%<extra></extra>",
        ))
        fig.update_layout(
            height=350,
            xaxis=dict(title="Mes"),
            yaxis=dict(title="M CLP", tickformat=",.0f"),
            yaxis2=dict(title="MC %", overlaying="y", side="right",
                         tickformat=".0f", showgrid=False),
            hovermode="x unified",
            margin=dict(t=20, b=40, l=70, r=70),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=1.05, x=0),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f"Margen Contribución consolidado últimos {len(merged)} meses. "
            f"Meta UnionX 2026-2028: ≥35%."
        )
