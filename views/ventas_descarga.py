"""Descarga RAW de ventas (Excel 41 columnas)."""
import io
from datetime import datetime

import pandas as pd
import streamlit as st

from views.shared import get_service


def render():
    st.title("⬇️ Descargar RAW de Ventas")
    st.caption("Excel con las 40 columnas RAW + columna 'Venta Neta' (sin IVA)")

    col_d1, col_d2 = st.columns([2, 1])
    with col_d1:
        rango_dl = st.date_input(
            "Período a descargar",
            value=(datetime.now().date().replace(day=1), datetime.now().date()),
            max_value=datetime.now().date(),
            format="YYYY-MM-DD",
            key="rango_dl",
        )

    if isinstance(rango_dl, tuple) and len(rango_dl) == 2:
        d1, d2 = rango_dl
        with col_d2:
            st.write("")
            if st.button("📥 Generar Excel", use_container_width=True, type="primary"):
                with st.spinner('Generando Excel...'):
                    df_raw = get_service().descargar_raw(d1.strftime('%Y-%m-%d'), d2.strftime('%Y-%m-%d'))
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as w:
                        df_raw.to_excel(w, index=False, sheet_name='RAW')
                    output.seek(0)

                    st.success(f"✅ {len(df_raw):,} filas listas para descargar")
                    st.download_button(
                        label=f"💾 Descargar Excel ({len(df_raw):,} filas)",
                        data=output,
                        file_name=f"Raw_ventas_Y_{d1}_{d2}.xlsx",
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        use_container_width=True,
                    )
