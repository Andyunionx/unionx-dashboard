"""
Vista Centro de Costos — App Contabilidad.

Flujo:
  1. Subir libro de compras (Excel SII) → carpeta libros_compras/
  2. Mantener actualizado memoria_cuentas.xlsx (RUT proveedor → cuenta + CC)
  3. Subir cartolas bancarias para conciliar pagos
  4. Procesar (correr extractor) → genera lista de movimientos LISTOS para Odoo
  5. Pendientes (sin mapping) → agregar al Excel memoria
  6. Aplicar a Odoo (botón con confirmación, próxima iteración)
"""
import io
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views._cont_data import (
    cc_movimientos_procesados, cc_pendientes_revision, cc_resumen,
    listar_libros_compras, listar_cartolas_cc, memoria_existe,
    fmt_clp, fmt_clp_m,
)


def render():
    with st.sidebar:
        st.markdown("### 📊 **Centro de Costos**")
        st.caption("Libro compras · Cuenta contable · Cartolas")
        st.divider()

    st.title("📊 Centro de Costos — Libro de Compras")
    st.caption(
        "Digitalización del libro de compras en Odoo: cruce con memoria de "
        "cuentas contables y cartolas bancarias"
    )

    df_listos = cc_movimientos_procesados()
    df_pendientes = cc_pendientes_revision()
    res = cc_resumen()

    # ─── ESTADO DEL FLUJO ─────────────────────────────────────────────────
    st.markdown("### 📋 Estado actual")
    estado_cols = st.columns(4)
    estado_cols[0].metric(
        "Libros compras",
        f"{res.get('libros_compras_archivos', 0)} archivos",
        f"{res.get('lineas_libro_compras', 0):,} líneas",
    )
    estado_cols[1].metric(
        "Memoria cuentas",
        "✅ Cargada" if memoria_existe() else "⚠️ Falta",
        f"{res.get('memoria_mappings', 0)} mappings",
    )
    estado_cols[2].metric(
        "Cartolas",
        f"{res.get('cartolas_archivos', 0)} archivos",
        f"{res.get('movimientos_cartola', 0):,} movs",
    )
    estado_cols[3].metric(
        "Listos para Odoo",
        f"{res.get('listos_para_odoo', 0):,}",
        f"Pendientes: {res.get('pendientes_revision', 0):,}",
    )

    if res.get("generado_en"):
        st.caption(f"🕒 Última corrida: {res['generado_en'][:19]}")

    st.divider()

    # ─── UPLOADERS ─────────────────────────────────────────────────────
    st.markdown("### 📤 Uploaders")
    up_cols = st.columns(3)

    with up_cols[0]:
        st.markdown("##### 📒 Libro de Compras (SII)")
        st.caption("Excel descargado del SII (formato F29 / libro electrónico)")
        f1 = st.file_uploader("Subir libro compras",
                               type=["xlsx", "xls"],
                               key="up_libro",
                               accept_multiple_files=True)
        if f1:
            for archivo in f1:
                dest = Path("data/contabilidad/centro_costos/libros_compras") / archivo.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archivo.read())
                st.success(f"✅ {archivo.name}")
        st.markdown("**Archivos:**")
        for f in listar_libros_compras():
            st.caption(f"• {f.name}")

    with up_cols[1]:
        st.markdown("##### 🧠 Memoria Cuentas Contables")
        st.caption(
            "Excel con: RUT Proveedor · Razón Social · Cuenta Contable · "
            "Centro Costo · Tipo"
        )
        f2 = st.file_uploader("Subir memoria_cuentas.xlsx",
                               type=["xlsx"],
                               key="up_memoria")
        if f2:
            dest = Path("data/contabilidad/centro_costos/memoria_cuentas.xlsx")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(f2.read())
            st.success("✅ memoria_cuentas.xlsx actualizada")
            st.cache_data.clear()
        if memoria_existe():
            st.caption("✅ memoria_cuentas.xlsx cargada")
        else:
            st.warning("⚠️ Falta cargar el Excel de memoria")

    with up_cols[2]:
        st.markdown("##### 🏦 Cartolas Bancarias")
        st.caption("Para cruzar pagos a proveedores")
        f3 = st.file_uploader("Subir cartola",
                               type=["xlsx", "csv"],
                               key="up_cartola_cc",
                               accept_multiple_files=True)
        if f3:
            for archivo in f3:
                dest = Path("data/contabilidad/centro_costos/cartolas_bancarias") / archivo.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archivo.read())
                st.success(f"✅ {archivo.name}")
        st.markdown("**Cartolas:**")
        for f in listar_cartolas_cc():
            st.caption(f"• {f.name}")

    if st.button("🔄 Procesar (regenerar parquets)", type="primary"):
        st.info(
            "Para regenerar manualmente, correr en terminal:\n"
            "```\npython extract_contabilidad_cc.py\n```\n"
            "El cron `sync_contabilidad.yml` también lo procesa cada 6h."
        )

    st.divider()

    # ─── KPIs MONTOS ─────────────────────────────────────────────────────
    st.markdown("### 💰 Distribución por Centro de Costo")
    by_cc = res.get("monto_por_centro_costo", {})
    if by_cc:
        df_cc = pd.DataFrame([
            {"Centro Costo": k, "Monto": v} for k, v in by_cc.items()
        ]).sort_values("Monto", ascending=False)

        fig = go.Figure(go.Bar(
            x=df_cc["Centro Costo"], y=df_cc["Monto"],
            marker_color="#7C3AED",
            text=[fmt_clp_m(v) for v in df_cc["Monto"]],
            textposition="outside",
        ))
        fig.update_layout(
            height=320,
            xaxis=dict(title="Centro de Costo"),
            yaxis=dict(title="Monto CLP", tickformat=",.0f"),
            margin=dict(t=20, b=40, l=70, r=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos de centros de costo todavía. Subí libro + memoria.")

    # Top cuentas contables
    top_ct = res.get("top_15_cuentas_contables", [])
    if top_ct:
        st.markdown("##### Top 15 cuentas contables")
        df_ct = pd.DataFrame(top_ct)
        df_ct["Monto"] = df_ct["monto"].apply(fmt_clp)
        st.dataframe(df_ct[["cuenta", "Monto"]].rename(columns={"cuenta": "Cuenta"}),
                     use_container_width=True, hide_index=True, height=280)

    st.divider()

    # ─── TABS LISTOS vs PENDIENTES ─────────────────────────────────────
    tab1, tab2 = st.tabs([
        f"✅ Listos para Odoo ({len(df_listos)})",
        f"⏳ Pendientes — sin cuenta contable ({len(df_pendientes)})",
    ])

    with tab1:
        if df_listos.empty:
            st.info("Sin movimientos listos. Subí libro de compras y asegurate "
                    "que la memoria tenga los RUTs.")
        else:
            cols_show = [c for c in ["fecha", "tipo_doc", "folio", "razon_social",
                                       "rut_proveedor", "monto_total",
                                       "cuenta_contable", "centro_costo",
                                       "tipo_gasto", "pagado_en_cartola"]
                          if c in df_listos.columns]
            df_disp = df_listos[cols_show].copy()
            if "monto_total" in df_disp.columns:
                df_disp["monto_total"] = df_disp["monto_total"].apply(fmt_clp)
            st.dataframe(df_disp, use_container_width=True, hide_index=True, height=420)

            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df_listos.to_excel(w, sheet_name="Listos", index=False)
            st.download_button(
                f"📥 Descargar Excel para revisión final ({len(df_listos):,} líneas)",
                data=buf.getvalue(),
                file_name=f"cc_listos_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            st.info(
                "🟡 **Próximo paso (Iteración 2):** botón **Aplicar a Odoo** que "
                "crea los `account.move` de proveedor automáticamente con la "
                "cuenta + CC asignados. Por seguridad, requiere confirmación "
                "explícita y muestra preview antes de escribir."
            )

    with tab2:
        if df_pendientes.empty:
            st.success("✅ Todos los movimientos tienen cuenta contable asignada")
        else:
            st.warning(
                f"⚠️ {len(df_pendientes)} líneas sin mapping. "
                "Agregar los RUTs faltantes al Excel **memoria_cuentas.xlsx** "
                "y volver a procesar."
            )
            cols_show = [c for c in ["fecha", "tipo_doc", "folio", "razon_social",
                                       "rut_proveedor", "monto_total"]
                          if c in df_pendientes.columns]
            df_disp = df_pendientes[cols_show].copy()
            if "monto_total" in df_disp.columns:
                df_disp["monto_total"] = df_disp["monto_total"].apply(fmt_clp)
            st.dataframe(df_disp, use_container_width=True, hide_index=True, height=420)

            # Sugerencia: bajar Excel de pendientes para completar
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                # Dejar columnas vacías para que Andrés/contadora complete
                df_pend_export = df_pendientes.copy()
                if "rut_proveedor" in df_pend_export.columns:
                    df_pend_export = df_pend_export.drop_duplicates("rut_proveedor")
                cols_export = ["rut_proveedor", "razon_social"]
                df_pend_export = df_pend_export[
                    [c for c in cols_export if c in df_pend_export.columns]
                ].copy()
                df_pend_export["cuenta_contable"] = ""
                df_pend_export["centro_costo"] = ""
                df_pend_export["tipo_gasto"] = ""
                df_pend_export.to_excel(w, sheet_name="Por completar", index=False)
            st.download_button(
                "📥 Descargar pendientes para completar (sumar a memoria_cuentas.xlsx)",
                data=buf.getvalue(),
                file_name=f"cc_pendientes_completar_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
