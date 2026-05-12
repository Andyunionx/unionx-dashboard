"""
Vista Cobranza — App Contabilidad.

Flujo:
  1. Carga documentos NO conciliados desde Odoo (extractor automático)
  2. Separa BOLETAS (cruzar con pagos portales) vs FACTURAS (cruzar con cartolas)
  3. Permite subir Excels de pagos / cartolas / NC manualmente
  4. Genera propuestas de conciliación (pendiente: aplicar a Odoo con confirmación)
  5. Reporte de CxC por aging y por cliente
"""
import io
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from views._cont_data import (
    documentos_no_conciliados, notas_credito, pedidos_venta, cobranza_resumen,
    listar_uploads_pagos_portales, listar_uploads_cartolas_cobranza,
    fmt_clp, fmt_clp_m,
)


def render():
    with st.sidebar:
        st.markdown("### 💰 **Cobranza**")
        st.caption("Documentos · Conciliación · CxC")
        st.divider()

    st.title("💰 Cobranza")
    st.caption(
        "Documentos NO conciliados · cruce con pagos portales/cartolas · "
        "validación NC · reporte CxC"
    )

    df_docs = documentos_no_conciliados()
    df_nc = notas_credito()
    df_so = pedidos_venta()
    res = cobranza_resumen()

    if df_docs.empty:
        st.warning(
            "⏳ Sin datos. Correr `python extract_contabilidad_cobranza.py` "
            "para cargar desde Odoo."
        )
        return

    st.caption(
        f"🕒 Generado: {res.get('generado_en','')[:19]} · "
        f"Fuente: {res.get('fuente','')} · "
        f"Ventana: últimos {res.get('ventana_dias',0)} días"
    )

    # ─── KPIs ─────────────────────────────────────────────────────────────
    st.divider()
    cols = st.columns(5)
    cols[0].metric(
        "Documentos pendientes",
        f"{res.get('total_documentos_pendientes', 0):,}",
    )
    cols[1].metric(
        "Monto pendiente",
        fmt_clp_m(res.get("total_monto_pendiente_clp", 0)),
    )
    by_tipo = res.get("monto_por_tipo", {})
    cols[2].metric("Boletas", fmt_clp_m(by_tipo.get("BOLETA", 0)))
    cols[3].metric("Facturas", fmt_clp_m(by_tipo.get("FACTURA", 0)))
    cols[4].metric("Notas crédito", f"{res.get('notas_credito_count', 0):,}")

    # ─── AGING ─────────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 📊 Aging cuentas por cobrar")

    by_aging = res.get("monto_por_aging", {})
    if by_aging:
        bucket_order = ["Vigente", "1-30 días", "31-60 días", "61-90 días",
                        "+90 días", "Sin fecha"]
        ord_buckets = [b for b in bucket_order if b in by_aging]
        valores = [by_aging[b] for b in ord_buckets]
        colors = ["#16A34A", "#84CC16", "#F59E0B", "#EA580C", "#DC2626", "#94A3B8"]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=ord_buckets, y=valores,
            marker_color=colors[: len(ord_buckets)],
            text=[fmt_clp_m(v) for v in valores],
            textposition="outside",
            hovertemplate="%{x}<br>%{customdata}<extra></extra>",
            customdata=[fmt_clp(v) for v in valores],
        ))
        fig.update_layout(
            height=320,
            xaxis=dict(title="Bucket"),
            yaxis=dict(title="Monto pendiente CLP", tickformat=",.0f"),
            margin=dict(t=20, b=40, l=70, r=20),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

    # ─── TOP DEUDORES ─────────────────────────────────────────────────
    st.markdown("### 🔝 Top 20 deudores")
    top = res.get("top_20_deudores", [])
    if top:
        df_top = pd.DataFrame(top)
        df_top["Monto pendiente"] = df_top["monto"].apply(fmt_clp)
        st.dataframe(
            df_top[["partner", "Monto pendiente"]].rename(
                columns={"partner": "Cliente"}),
            use_container_width=True, hide_index=True, height=400,
        )

    st.divider()

    # ─── TABS BOLETA vs FACTURA ─────────────────────────────────────────
    st.markdown("### 📄 Documentos pendientes — separados por tipo")
    tab_b, tab_f, tab_nc, tab_so = st.tabs([
        f"🧾 Boletas ({(df_docs['tipo']=='BOLETA').sum()})",
        f"📄 Facturas ({(df_docs['tipo']=='FACTURA').sum()})",
        f"↩️ Notas crédito ({len(df_nc)})",
        f"🛒 Pedidos venta ({len(df_so)})",
    ])

    def _tabla_docs(df, mostrar_pago_portal=False):
        if df.empty:
            st.info("Sin documentos en este tipo")
            return
        df = df.sort_values("monto_pendiente", ascending=False).copy()
        cols_show = ["documento", "fecha_emision", "fecha_vencimiento",
                      "dias_vencido", "bucket_aging", "partner_nombre",
                      "monto_total", "monto_pendiente", "estado_pago", "origen_so"]
        df_disp = df[cols_show].copy()
        df_disp["monto_total"] = df_disp["monto_total"].apply(fmt_clp)
        df_disp["monto_pendiente"] = df_disp["monto_pendiente"].apply(fmt_clp)
        df_disp.columns = ["Documento", "F. Emisión", "F. Vencim.", "Días venc.",
                            "Aging", "Cliente", "Total", "Pendiente",
                            "Estado", "Pedido SO"]
        st.dataframe(df_disp, use_container_width=True, hide_index=True, height=500)

        # Excel descarga
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, sheet_name="Pendientes", index=False)
        st.download_button(
            f"📥 Descargar {len(df):,} documentos (Excel)",
            data=buf.getvalue(),
            file_name=f"cobranza_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with tab_b:
        st.caption(
            "**Flujo boletas:** cruzar con pagos de portales (Mercado Pago, "
            "Webpay, Yuju, etc.). Subir el Excel del portal en la pestaña "
            "**📤 Uploaders** abajo."
        )
        _tabla_docs(df_docs[df_docs["tipo"] == "BOLETA"], mostrar_pago_portal=True)

    with tab_f:
        st.caption(
            "**Flujo facturas:** cruzar con cartolas bancarias (CxC pagadas "
            "por transferencia). Subir cartola en **📤 Uploaders** abajo."
        )
        _tabla_docs(df_docs[df_docs["tipo"] == "FACTURA"])

    with tab_nc:
        st.caption("Notas de crédito emitidas (validar contra drives de devolución)")
        _tabla_docs(df_nc)

    with tab_so:
        st.caption("Pedidos de venta vinculados a los documentos pendientes")
        if not df_so.empty:
            df_disp = df_so.copy()
            df_disp["monto_total"] = df_disp["monto_total"].apply(fmt_clp)
            df_disp.columns = [c.replace("_", " ").title() for c in df_disp.columns]
            st.dataframe(df_disp, use_container_width=True, hide_index=True, height=500)

    st.divider()

    # ─── UPLOADERS ─────────────────────────────────────────────────────
    st.markdown("### 📤 Uploaders — pagos portales / cartolas / NC")
    st.caption(
        "Subí los archivos. Quedan en `data/contabilidad/cobranza/` y se "
        "procesan en la próxima corrida. Más adelante se cruzarán automático "
        "con los documentos pendientes para generar propuestas de conciliación."
    )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("##### 💳 Pagos de portales (Boletas)")
        st.caption("Mercado Pago, Webpay, Yuju, Khipu, etc.")
        f1 = st.file_uploader(
            "Excel/CSV del portal",
            type=["xlsx", "csv"],
            key="up_portal",
            accept_multiple_files=True,
        )
        if f1:
            for archivo in f1:
                dest = (Path("data/contabilidad/cobranza/pagos_portales")
                        / archivo.name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archivo.read())
                st.success(f"✅ {archivo.name} guardado")

        st.markdown("**Archivos cargados:**")
        for f in listar_uploads_pagos_portales():
            st.caption(f"• {f.name}")

    with col2:
        st.markdown("##### 🏦 Cartolas bancarias (Facturas)")
        st.caption("Banco Santander, BCI, Estado, etc.")
        f2 = st.file_uploader(
            "Cartola Excel/CSV",
            type=["xlsx", "csv"],
            key="up_cartola",
            accept_multiple_files=True,
        )
        if f2:
            for archivo in f2:
                dest = (Path("data/contabilidad/cobranza/cartolas_bancarias")
                        / archivo.name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archivo.read())
                st.success(f"✅ {archivo.name} guardada")

        st.markdown("**Cartolas cargadas:**")
        for f in listar_uploads_cartolas_cobranza():
            st.caption(f"• {f.name}")

    st.divider()

    # ─── PROPUESTA CONCILIACIÓN ─────────────────────────────────────────
    st.markdown("### 🔄 Propuesta de conciliación")
    st.info(
        "🟡 **Próximo paso (cuando estén los uploaders cargados):**\n\n"
        "1. El extractor cruzará automáticamente:\n"
        "   - Boletas vs pagos portal (por monto + fecha + glosa)\n"
        "   - Facturas vs cartolas bancarias (por monto + fecha + RUT)\n"
        "2. Generará una tabla de **matches propuestos** con confianza %\n"
        "3. Vos revisás y aprobás → se aplica la conciliación en Odoo "
        "(`account.move.js_assign_outstanding_line`)\n"
        "4. Excel con los NO matcheados queda para revisión manual\n\n"
        "**Drives de devolución/NC:** cuando me pases las URLs los integro al cruce."
    )
