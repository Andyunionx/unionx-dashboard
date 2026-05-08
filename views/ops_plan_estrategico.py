"""
Vista Plan Estratégico — Roadmap H1/H2/H3 + KPIs corporativos consolidados.

Es la "guía de viaje" del equipo Ops dentro del Plan UnionX 2026-2028.
"""
import streamlit as st


def render():
    st.title("📋 Plan Estratégico Operaciones 2026-2028")
    st.caption("Plan Unificado · Operaciones + Finanzas/Admin · Doble rol de la Gerencia")

    st.divider()

    # ============ Objetivos macro ============
    st.markdown("### 🎯 Pilares estratégicos")
    pilares = [
        ("🟢 Rentabilidad", "EBITDA ≥ 12% · Margen contribución ≥ 35%"),
        ("💧 Liquidez", "CCC ≤ 90 días · Deuda/EBITDA ≤ 3.0x"),
        ("📈 Crecimiento", "Ingresos +25% YoY"),
        ("⚡ Eficiencia operacional", "Costo/pedido ↓15% · Devoluciones ≤5%"),
        ("🎯 Marca y cliente", "Marcas propias ≥40% · NPS ≥50"),
    ]
    for icon_name, meta in pilares:
        st.markdown(f"- **{icon_name}** — {meta}")

    st.divider()

    # ============ Horizontes ============
    st.markdown("### 🛣️ Roadmap por horizonte")

    h1, h2, h3 = st.tabs(["🟢 H1 (0-6m) — Quick wins", "🟡 H2 (6-18m) — Capacidades", "🔵 H3 (18-24m+) — Madurez"])

    with h1:
        st.markdown("**Objetivo:** estabilizar la operación, generar visibilidad y obtener mejoras de margen sin grandes inversiones.")
        st.markdown("""
| Área | Iniciativa | Owner |
|---|---|---|
| Finanzas | Cash flow rolling 13 semanas conectado a PO COMEX | Finanzas |
| Finanzas | Costeo real por canal (e-com vs B2B) y por categoría | Finanzas |
| Fulfillment | Análisis ABC de SKUs por valor y rotación | Operaciones |
| Fulfillment | Liquidación estructurada de inventario obsoleto | Operaciones / Comercial |
| Fulfillment | Cycle count semanal y cierre de diferencias mayores | Operaciones |
| Post-venta | Clasificación causa raíz de devoluciones | Operaciones |
| SAC | Página self-service de tracking + FAQ robusto | SAC / TI |
| COMEX | Estandarizar pre-costeo y maestra de importaciones | COMEX / Finanzas |
| COMEX | Política mínima de cobertura cambiaria sobre PO | Finanzas / COMEX |
| Logística | Renegociación tarifas courier y mix proveedores | Operaciones |
| Procesos | Documentación SOP de los 10 procesos críticos | Operaciones |
        """)

    with h2:
        st.markdown("**Objetivo:** invertir en capacidades sistémicas y de proceso que permitan escalar sin sumar costo proporcional.")
        st.markdown("""
| Área | Iniciativa | Owner |
|---|---|---|
| Tecnología | Implementación data warehouse + BI corporativo | TI / Finanzas |
| Tecnología | PIM para maestro único de productos | TI / Comercial |
| Tecnología | Integración WMS-ERP-OMS-CS punta a punta | TI / Operaciones |
| Fulfillment | Robustecer WMS con cycle counting y picking optimizado | Operaciones / TI |
| Fulfillment | Forecast de demanda por SKU con ABC/XYZ | Operaciones / Comercial |
| Fulfillment | Slotting dinámico y rediseño del flujo en bodega | Operaciones |
| SAC | Helpdesk omnicanal (Zendesk/Freshdesk) | SAC / TI |
| Comercial | Plataforma B2B dedicada | Comercial / TI |
| Finanzas | Diversificar fuentes financiamiento (factoring, confirming) | Finanzas |
| Finanzas | Cierre contable ≤ 5 días hábiles | Finanzas |
        """)

    with h3:
        st.markdown("**Objetivo:** consolidar la operación como activo competitivo, capacidad real de absorber crecimiento.")
        st.markdown("""
| Área | Iniciativa | Owner |
|---|---|---|
| COMEX | Diversificación geográfica proveedores (Vietnam, India, México) | COMEX |
| Comercial | Marcas propias maduras (≥40% ventas) | Comercial / Marketing |
| Tecnología | Modelo predictivo demanda con ML | TI / Operaciones |
| Operaciones | Posible expansión regional (Perú/Colombia) o multi-bodega | Gerencia General |
| Operaciones | Capacidad bodega +40% sin sumar HC proporcional | Operaciones |
| Operaciones | Automatización selectiva (impresión, sorteo, picking ayudado) | Operaciones / TI |
        """)

    st.divider()

    # ============ Áreas con doble rol ============
    st.markdown("### 👤 Áreas bajo gestión directa")
    st.markdown("""
1. **Comercio Exterior / Importaciones** (COMEX)
2. **Fulfillment y Control de Inventario**
3. **Post-venta y Logística Inversa**
4. **Servicio al Cliente (SAC)**
5. **Logística (Despacho y Última Milla)**
6. **Finanzas y Administración** *(transversal)*

> 💡 Las áreas Comercial, Marketing y Tecnología NO reportan acá pero impactan capital de trabajo, costo por pedido y rentabilidad. La gerencia tiene voz formal en sus comités.
    """)
