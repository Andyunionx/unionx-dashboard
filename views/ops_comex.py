"""
Vista COMEX — Embarques activos, lead time, costo aterrizaje.

Estado: STUB inicial. Datos vendrán de:
  - Agente COMEX Gmail (PI/PL/OHNSO procesados, en agente-comex/data/output/)
  - Sheet maestro de embarques (manual hoy, automático H2)
  - Odoo (purchase.order para PO confirmadas)
"""
import streamlit as st


def render():
    st.title("🚢 COMEX — Embarques activos")
    st.caption(
        "Plan Estratégico 2026-2028 · Lead time ≤75 días · Costo aterrizaje ↓8-10% YoY · "
        "Fill rate ≥97% · Cobertura cambiaria ≥50%"
    )

    st.info("🔧 **En construcción** — primera versión disponible próximamente.")

    st.divider()

    st.markdown("### 📋 KPIs planificados según el Plan Estratégico")

    kpis_planificados = [
        ("Lead time puerta a puerta", "≤ 75 días Shenzhen / ≤ 65 días Ningbo", "🟠 Esperando datos de embarques"),
        ("Costo aterrizaje USD/CBM", "↓ 8-10% YoY", "🟠 Esperando agente COMEX export"),
        ("% Precisión costeo pre vs post", "≤ 3% desviación", "🟡 Calculable (output skill comex-workflow)"),
        ("Fill rate proveedor", "≥ 97%", "🔴 Sin medir aún"),
        ("Cumplimiento ETA ±7 días", "≥ 90%", "🔴 Sin medir aún"),
        ("Rotación inventario en tránsito", "≥ 5x al año", "🟡 Calculable desde Odoo"),
        ("% Embarques con incidencias aduaneras", "≤ 10%", "🔴 Sin medir aún"),
        ("Cobertura cambiaria", "≥ 50% PO confirmadas", "🔴 Manual"),
    ]

    import pandas as pd
    df = pd.DataFrame(kpis_planificados, columns=["KPI", "Meta", "Estado"])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    st.markdown("### 🛣️ Roadmap COMEX")
    st.markdown("""
- **🟢 Hoy:** agente Gmail detecta PI/PL de Steven y dispara cotización a Vicente
- **🟡 H1 (próximas semanas):**
  - Conectar output del agente al dashboard (cada PI procesada genera fila)
  - Sheet maestro de embarques con timeline (PO → Embarque → ETA → Llegada bodega)
  - Costo aterrizaje USD/CBM por embarque (de la skill comex-workflow)
- **🟠 H2 (3-6 meses):** Tracking forwarder (Seimex API si tiene)
- **🟠 H2:** Política de cobertura cambiaria con tracker
- **🔵 H3:** Multi-proveedor (Vietnam, India, México) y diversificación
    """)
