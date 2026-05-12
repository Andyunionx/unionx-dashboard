"""Módulo: Cruce con app Finanzas (caja disponible para compras).

Stub. La app finanzas-unionx se está construyendo en paralelo. Cuando exponga
un endpoint de "caja proyectada por semana", este módulo lo consume y lo cruza
contra la propuesta de compras para detectar:

- Compras que exceden caja disponible en su semana
- Sugerencias de ajuste: reducir meses de cobertura, postergar PI no críticas,
  solicitar crédito proveedor extendido, etc.
"""
import streamlit as st


def render():
    st.title("💵 Caja vs Plan de Compras")
    st.caption("Cruce con app Finanzas — proyección de caja disponible vs requerimiento de compra.")

    st.warning(
        "**Pendiente de integración.** La app `finanzas-unionx` está en construcción. "
        "Cuando esté lista, este módulo consumirá su endpoint de caja proyectada."
    )

    st.markdown("### Esperando del backend `finanzas-unionx`:")
    st.markdown("""
    - **Endpoint** `GET /api/cashflow/proyeccion?semanas=12` que devuelva:
      ```json
      {
        "semanas": [
          {"semana_iso": "2026-W20", "saldo_inicial": 12000000, "ingresos": 50000000,
           "egresos_operativos": 35000000, "egresos_compras_comprometidas": 8000000,
           "saldo_proyectado": 19000000, "saldo_minimo_objetivo": 5000000}
        ]
      }
      ```
    - **Endpoint** `GET /api/cashflow/disponible_compras` que devuelva el CLP
      libre por semana para nuevas compras (después de operaciones y compromisos).
    """)

    st.markdown("### Lo que este módulo hará cuando esté conectado:")
    st.markdown("""
    1. **Valorizar la propuesta de compras** semana a semana (cantidad × costo_EXW × TC USD).
    2. **Confrontar con caja disponible** por semana.
    3. **Detectar semanas con déficit** y proponer ajustes:
       - Reducir meses de cobertura objetivo para SKUs no críticos
       - Negociar crédito proveedor extendido (input desde maestro proveedores)
       - Postergar PIs no urgentes a próxima ventana
       - Acelerar liquidación de sobre-stock para liberar caja
    """)

    st.divider()
    st.caption(
        "💡 Mientras tanto, el módulo *Propuesta de Compras* permite descargar el CSV "
        "para análisis manual de impacto en caja desde Excel/Sheets."
    )
