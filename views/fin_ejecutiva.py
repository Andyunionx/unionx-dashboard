"""
Vista Ejecutiva — App Finanzas.

Landing con 5 cards de pilares estratégicos del Plan UnionX 2026-2028:
  💰 Rentabilidad · 💧 Liquidez · 📈 Crecimiento · ⚡ Eficiencia · 🎯 Marca/Cliente

Cada card: KPI central + meta + semáforo + click → drill-down a la página detalle.

Estado: 🟡 Stub — pendiente conectar KPIs.
"""
import streamlit as st


def render():
    with st.sidebar:
        st.markdown("### 📊 **Vista Ejecutiva**")
        st.caption("5 pilares estratégicos")
        st.divider()

    st.title("📊 Vista Ejecutiva — Plan UnionX 2026-2028")
    st.caption(
        "Pantalla de control para Andrés/CEO: cada pilar en un vistazo, "
        "con drill-down al detalle correspondiente."
    )

    st.info(
        "🟡 **Vista en construcción.** Próximos pasos al definir contenido:\n\n"
        "**5 cards (1 por pilar):**\n"
        "1. 💰 **Rentabilidad** — EBITDA % YTD vs meta ≥12%\n"
        "2. 💧 **Liquidez** — CCC días vs meta ≤90 (DIO+DSO−DPO desde Odoo)\n"
        "3. 📈 **Crecimiento** — Var % ingresos YoY YTD vs meta ≥25%\n"
        "4. ⚡ **Eficiencia** — Margen contrib YTD vs meta ≥35%\n"
        "5. 🎯 **Marca/Cliente** — Repeat customer rate vs meta ≥25%\n\n"
        "Cada card: valor actual · meta · semáforo (🟢/🟡/🔴) · tendencia 6m · "
        "botón 'Ver detalle' → navega a la página correspondiente."
    )

    cols = st.columns(5)
    for col, (icono, nombre, meta) in zip(cols, [
        ("💰", "Rentabilidad", "EBITDA ≥12%"),
        ("💧", "Liquidez", "CCC ≤90d"),
        ("📈", "Crecimiento", "+25% YoY"),
        ("⚡", "Eficiencia", "Margen ≥35%"),
        ("🎯", "Marca/Cliente", "Repeat ≥25%"),
    ]):
        with col:
            st.markdown(
                f"""<div style="background:#F8FAFC;border-radius:12px;padding:24px 16px;
                text-align:center;border:1px dashed #94A3B8;">
                <div style="font-size:2rem;">{icono}</div>
                <div style="font-size:0.75rem;color:#64748B;text-transform:uppercase;
                letter-spacing:0.5px;font-weight:600;margin:6px 0;">{nombre}</div>
                <div style="font-size:1.4rem;font-weight:700;color:#94A3B8;">—</div>
                <div style="font-size:0.7rem;color:#94A3B8;margin-top:6px;">{meta}</div>
                </div>""",
                unsafe_allow_html=True,
            )
