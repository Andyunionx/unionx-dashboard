"""
Vista Costo Operativo Total — port simplificado del módulo de eerr-finanzas.

Lee la planilla de Costo Operativo + factores configurables.
"""
import streamlit as st


def render():
    st.title("💰 Costo Operativo Total")
    st.caption(
        "Plan Estratégico · Costo / pedido ↓ 10-15% YoY · Costo logístico / venta 8-12%"
    )

    st.info(
        "🔧 **En migración.** El módulo de Costo Operativo Total existe en `eerr-finanzas/` "
        "(página Fulfillment Tab 5). Próxima iteración: portarlo acá con la misma lógica "
        "(estimación P&L + factores + uploader detallado por terceros + análisis vs benchmark mercado)."
    )

    st.divider()

    st.markdown("### 📋 Lo que se va a portar")
    st.markdown("""
**Modo dual:**
- 📊 **Estimado P&L:** lee del archivo de Planificación Financiera y aplica factores
  - Sueldos: 50% atribuible (configurable)
  - Arriendo Megacentro: 70%
  - Capacitación: 50%
  - Depreciación/Amortización: 100%
  - Variables (flete, insumos, movilización, comisiones GC): 100%
- 📥 **Detalle por terceros:** uploader Excel donde RRHH/Contabilidad cargan valores reales

**Análisis automático:**
- Comparación vs benchmarks Plan UnionX (8-14% costo/venta · 50-65% variable)
- Recomendaciones heurísticas con prioridad 🔴🟡🟢
- Top conceptos + evolución mensual

Documentación completa en `data/uploaders/templates/` y módulo `costo_operativo_uploader.py`.
    """)

    st.divider()

    st.markdown("### 🛣️ Roadmap Costo Operativo")
    st.markdown("""
- **🟢 H1 hoy** (en `eerr-finanzas/`):
  - Modo estimado P&L con factores configurables
  - Template Excel descargable
  - Análisis vs benchmarks + recomendaciones automáticas
- **🟡 H1 próximo:** Portar el módulo a esta app de Operaciones
- **🟠 H2-H3 (6-18m):** Cuentas analíticas en Odoo (Operaciones / Comercial / Admin)
  → costo operativo automático sin uploader manual
- **🔵 H3:** Forecast predictivo de costo operativo basado en venta proyectada
    """)
