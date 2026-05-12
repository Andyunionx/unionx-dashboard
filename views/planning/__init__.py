"""App Planificación — módulos para planificar compras cruzando forecast,
stock, llegadas en tránsito, política de cobertura y flujo de caja.

Estructura:
- _core.py: lógica pura (posición de stock, requerimiento de compra, cobertura)
- _data_helpers.py: carga unificada de las fuentes (parquets locales + Turso)
- proveedores.py: maestro de proveedores (lee Drive cuando esté disponible)
- politicas.py: stock objetivo por categoría comercial
- triada.py: vista combinada stock + tránsito + demanda forecasteada
- compras.py: propuesta de compras priorizada
- negociacion.py: análisis histórico para mejorar negociaciones (volumen, EXW, cruzada)
- caja.py: hook a app finanzas (proyección caja vs requerimiento)
- liquidacion.py: SKUs candidatos a liquidación por sobre-stock
"""
