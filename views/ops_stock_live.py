"""
Vista Stock LIVE — foco OPERACIONAL (app Operaciones).

Diferencia con la mirada comercial de la app Ventas:
  - SKUs duplicados (capital atado / riesgo error picking)
  - Tasa de uso de posiciones (activas / dormidas / vacías)
  - Alertas operacionales heurísticas
  - Ranking posiciones más activas (slotting)

Datos en vivo desde Odoo via cuenta servicio OPS_ODOO_USER.
Cache 5 min.
"""
from datetime import datetime

import pandas as pd
import streamlit as st

from views._ops_stock_helper import (
    skus_duplicados,
    uso_posiciones,
    alertas_operacionales,
    ranking_posiciones_actividad,
)
from views.shared import cached_stock


def _kpi_card_simple(label: str, value: str, sub: str = "", color: str = "#1F4E79") -> str:
    return f"""<div style="background:white;border-radius:12px;padding:16px 18px;text-align:center;
        box-shadow:0 1px 3px rgba(0,0,0,0.08);border:1px solid #E2E8F0;height:100%;">
        <div style="font-size:0.7rem;color:#64748B;text-transform:uppercase;letter-spacing:0.8px;font-weight:600;margin-bottom:4px;">{label}</div>
        <div style="font-size:1.5rem;font-weight:700;color:{color};line-height:1.2;">{value}</div>
        <div style="font-size:0.7rem;color:#94A3B8;margin-top:2px;">{sub}</div>
    </div>"""


def render():
    with st.sidebar:
        st.markdown("### 📦 **Stock Operacional**")
        st.caption("Vista WMS · Foco logística")
        st.markdown("---")
        if st.button("🔄 Refrescar Odoo", use_container_width=True, type="primary", key="ops_stock_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.title("📦 Stock LIVE — Vista Operacional")
    st.caption("Foco WMS: duplicaciones, tasa uso posiciones, alertas operativas · Cache 5 min")

    tabs = st.tabs([
        "🚦 Resumen",
        "🔄 SKUs duplicados",
        "📍 Uso de posiciones",
        "🔁 Rotación",
        "⚠️ Alertas operacionales",
    ])

    # ============================================================
    # TAB 1 — RESUMEN
    # ============================================================
    with tabs[0]:
        with st.spinner("Consultando Odoo (puede tomar 30-60s la 1ra vez)…"):
            stock_data = cached_stock()
            dup = skus_duplicados(min_ubicaciones=2)
            uso = uso_posiciones(dias=7)
            alertas = alertas_operacionales()

        df_skus = stock_data.get("skus") if stock_data else None
        kpis = stock_data.get("kpis", {}) if stock_data else {}
        ocup = stock_data.get("ocupacion", {}) if stock_data else {}

        c1, c2, c3 = st.columns(3)
        n_skus = kpis.get("n_skus", 0)
        c1.markdown(_kpi_card_simple("SKUs activos", f"{n_skus:,}",
                                      f"${kpis.get('valor_total', 0)/1e6:,.1f}M valor", "#1F4E79"),
                    unsafe_allow_html=True)

        n_dup = dup.get("total", 0)
        valor_dup = dup.get("valor_total", 0)
        c2.markdown(_kpi_card_simple("SKUs duplicados", f"{n_dup:,}",
                                      f"${valor_dup/1e6:,.1f}M en >1 ubicación",
                                      "#EA580C" if n_dup > 50 else "#1F4E79"),
                    unsafe_allow_html=True)

        ocup_pct = ocup.get("pct", 0)
        ocup_color = "#DC2626" if ocup_pct > 90 else ("#EA580C" if ocup_pct > 80 else "#16A34A")
        c3.markdown(_kpi_card_simple("Ocupación CA1/Stock", f"{ocup_pct}%",
                                      f"{ocup.get('occupied', 0)} / {ocup.get('total', 0)} posiciones",
                                      ocup_color),
                    unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        c4, c5, c6 = st.columns(3)
        if uso.get("valor"):
            v = uso["valor"]
            c4.markdown(_kpi_card_simple("Posiciones activas (7d)",
                                          f"{v.get('activas', 0)}",
                                          f"{v.get('pct_activas', 0)*100:.0f}% del total",
                                          "#16A34A"),
                        unsafe_allow_html=True)
            c5.markdown(_kpi_card_simple("Posiciones dormidas",
                                          f"{v.get('dormidas', 0)}",
                                          f"Stock pero sin mov >30d",
                                          "#EA580C" if v.get('dormidas', 0) > 30 else "#94A3B8"),
                        unsafe_allow_html=True)
            c6.markdown(_kpi_card_simple("Posiciones vacías",
                                          f"{v.get('vacias', 0)}",
                                          f"Disponibles para asignar",
                                          "#1F4E79"),
                        unsafe_allow_html=True)
        else:
            c4.warning("Sin datos de uso de posiciones")

        st.markdown("<br>", unsafe_allow_html=True)

        c7, c8, c9 = st.columns(3)
        n_quiebre = kpis.get("n_quiebre_critico", 0)
        c7.markdown(_kpi_card_simple("Críticos / Quiebre", f"{n_quiebre}",
                                      "< 30 días stock o sin stock con demanda", "#DC2626"),
                    unsafe_allow_html=True)
        n_sobre = kpis.get("n_sobrestock", 0)
        c8.markdown(_kpi_card_simple("Sobrestock", f"{n_sobre}",
                                      "> 180 días con venta", "#1F4E79"),
                    unsafe_allow_html=True)
        n_sin = kpis.get("n_sin_venta", 0)
        c9.markdown(_kpi_card_simple("Sin venta 30d", f"{n_sin}",
                                      "Candidatos a liquidación", "#94A3B8"),
                    unsafe_allow_html=True)

        st.divider()

        # Resumen de alertas
        if alertas:
            st.markdown("### ⚠️ Alertas activas")
            for a in alertas[:5]:
                sev = a.get("severidad", "")
                if sev == "CRITICA":
                    st.error(f"🔴 **{a.get('tipo')}** · {a.get('mensaje')}")
                elif sev == "ALTA":
                    st.warning(f"🟡 **{a.get('tipo')}** · {a.get('mensaje')}")
                else:
                    st.info(f"🔵 **{a.get('tipo')}** · {a.get('mensaje')}")
        else:
            st.success("✅ Sin alertas operacionales activas")

    # ============================================================
    # TAB 2 — SKUs DUPLICADOS
    # ============================================================
    with tabs[1]:
        st.markdown("### 🔄 SKUs en múltiples ubicaciones físicas")
        st.caption(
            "Detectar SKUs duplicados ayuda a: (1) reducir errores de picking, "
            "(2) consolidar capital atado, (3) liberar posiciones para nuevos embarques."
        )

        col_n1, col_n2 = st.columns([1, 3])
        with col_n1:
            min_ubic = st.selectbox("Filtrar ≥ ubicaciones", [2, 3, 4, 5], index=0, key="dup_minloc")
        with col_n2:
            st.markdown(f"**Total SKUs con ≥{min_ubic} ubicaciones:** {dup.get('total', 0):,} · "
                        f"**Valor total:** ${dup.get('valor_total', 0)/1e6:,.1f}M")

        if dup.get("error"):
            st.warning(f"⚠️ {dup['error']}")
        elif dup.get("valor"):
            data = [d for d in dup["valor"] if d["n_ubicaciones"] >= min_ubic]
            rows = []
            for d in data[:200]:
                rows.append({
                    "SKU": d["sku"][:60],
                    "# Ubicaciones": d["n_ubicaciones"],
                    "Qty Total": f"{d['qty_total']:,.0f}",
                    "Valor": f"${d['valor']/1e3:,.0f} K",
                    "Ubicaciones": " · ".join(d["ubicaciones"][:5]),
                    "Sugerencia consolidar": d["principal"],
                })
            if rows:
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True, height=520)
                st.caption(f"Mostrando {len(rows)} de {len(data)}. Ordenado por valor descendente.")
            else:
                st.info("Sin SKUs con ese filtro.")
        else:
            st.info("Sin datos.")

    # ============================================================
    # TAB 3 — USO DE POSICIONES
    # ============================================================
    with tabs[2]:
        st.markdown("### 📍 Tasa de uso de posiciones (CA1/Stock)")
        st.caption(
            "Activas = movimientos en últimos 7d · Dormidas = stock sin movimientos >30d · "
            "Vacías = disponibles para asignar"
        )

        if uso.get("error"):
            st.warning(f"⚠️ {uso['error']}")
        elif uso.get("valor"):
            v = uso["valor"]
            det = uso.get("detalle", {})

            # Sub-tabs por tipo
            sub_tabs = st.tabs([
                f"🟢 Activas ({v['activas']})",
                f"🟠 Dormidas ({v['dormidas']})",
                f"⚪ Vacías ({v['vacias']})",
                f"🔥 Más movimientos (30d)",
            ])

            with sub_tabs[0]:
                if det.get("activas"):
                    st.dataframe(pd.DataFrame(det["activas"]).rename(
                        columns={"nombre": "Posición", "n_skus": "SKUs"}
                    ).drop(columns=["location_id"]),
                    use_container_width=True, hide_index=True, height=400)
                else:
                    st.info("Sin datos")

            with sub_tabs[1]:
                if det.get("dormidas"):
                    st.warning(f"💡 Estas {v['dormidas']} posiciones tienen stock pero sin movimientos en >30d. "
                               "Candidatas a consolidación o liquidación.")
                    st.dataframe(pd.DataFrame(det["dormidas"]).rename(
                        columns={"nombre": "Posición", "n_skus": "SKUs"}
                    ).drop(columns=["location_id"]),
                    use_container_width=True, hide_index=True, height=400)
                else:
                    st.success("✅ Sin posiciones dormidas")

            with sub_tabs[2]:
                if det.get("vacias"):
                    st.dataframe(pd.DataFrame(det["vacias"]).rename(
                        columns={"nombre": "Posición", "n_skus": "SKUs"}
                    ).drop(columns=["location_id"]),
                    use_container_width=True, hide_index=True, height=400)
                else:
                    st.warning("⚠️ Sin posiciones vacías — bodega saturada")

            with sub_tabs[3]:
                ranking = ranking_posiciones_actividad(dias=30, top_n=30)
                if ranking:
                    st.markdown("**Top posiciones con más movimientos en los últimos 30 días.**")
                    st.caption("Estas son las posiciones 'calientes' — los SKUs A (alta rotación) deberían estar cerca del área de packing.")
                    st.dataframe(pd.DataFrame(ranking),
                                 use_container_width=True, hide_index=True, height=520)
                else:
                    st.info("Sin datos de movimientos")

    # ============================================================
    # TAB 4 — ROTACIÓN
    # ============================================================
    with tabs[3]:
        st.markdown("### 🔁 Rotación detallada")
        st.caption("Rotación = veces que el stock se renueva en el período · Calculada sobre venta diaria")

        if df_skus is not None and len(df_skus) > 0:
            df_r = df_skus.copy()

            # KPIs
            r30_avg = df_r[df_r["Rot 30d Uds"] > 0]["Rot 30d Uds"].mean()
            r90_avg = df_r[df_r["Rot 90d Uds"] > 0]["Rot 90d Uds"].mean()

            cr1, cr2, cr3 = st.columns(3)
            cr1.metric("Rotación promedio 30d", f"{r30_avg:.2f}x" if pd.notna(r30_avg) else "—")
            cr2.metric("Rotación promedio 90d", f"{r90_avg:.2f}x" if pd.notna(r90_avg) else "—")
            top_categorias = df_r.groupby("Categoria")["Rot 30d Uds"].mean().nlargest(1)
            if len(top_categorias):
                cr3.metric("Top categoría rotación", f"{top_categorias.index[0]}",
                           delta=f"{top_categorias.values[0]:.2f}x")

            st.divider()

            # Top movers
            st.markdown("#### 🚀 Top 20 movers (mayor rotación 30d)")
            top_movers = df_r[df_r["Vta 30d Qty"] > 0].nlargest(20, "Rot 30d Uds")[
                ["SKU", "Producto", "Categoria", "Qty", "Vta 30d Qty", "Rot 30d Uds", "Rot 90d Uds", "Semaforo"]
            ]
            st.dataframe(top_movers, use_container_width=True, hide_index=True)

            st.markdown("#### 🐢 Bottom movers (sin venta 30d, con stock)")
            bottom = df_r[(df_r["Vta 30d Qty"] == 0) & (df_r["Qty"] > 0)].nlargest(20, "Valor")[
                ["SKU", "Producto", "Categoria", "Qty", "Vta 90d Qty", "Valor", "Semaforo"]
            ]
            st.dataframe(bottom, use_container_width=True, hide_index=True)
        else:
            st.warning("Sin datos de SKUs")

    # ============================================================
    # TAB 5 — ALERTAS
    # ============================================================
    with tabs[4]:
        st.markdown("### ⚠️ Alertas operacionales (heurísticas automáticas)")
        st.caption("Generadas en cada refresh basadas en stock + movimientos + duplicaciones")

        if not alertas:
            st.success("✅ Sin alertas activas")
        else:
            for a in alertas:
                sev = a.get("severidad", "")
                if sev == "CRITICA":
                    icon = "🔴"
                    container = st.error
                elif sev == "ALTA":
                    icon = "🟡"
                    container = st.warning
                else:
                    icon = "🔵"
                    container = st.info
                with st.container(border=True):
                    container(f"{icon} **{a.get('tipo', '?')}** · {a.get('mensaje', '')}")
                    if a.get("accion"):
                        st.caption(f"💡 {a['accion']}")
