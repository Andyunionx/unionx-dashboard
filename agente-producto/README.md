# Agente Producto — ¿conviene comprar este producto?

Pedido de Sebastián Guzmán (9-oct-2026). Evalúa una cotización con todos sus costos (fábrica, logística, marketplace,
marketing, internación, capital) y entrega **COMPRAR / NEGOCIAR / NO COMPRAR**, el precio de compra objetivo, el ROI del
lote en 3 escenarios y el cruce con el Radar de Importaciones.

## Uso
```
python parametros.py                       # refresca parámetros (dólar del día, fletes Seimex, tasas del ROI) → parametros.json
python evaluar.py casos/mi_producto.json   # informe.md + resultado.json (otros agentes) + Excel con fórmulas en salidas/
python validar_excel.py casos/x.json       # comprueba Excel = Python
```
Datos críticos de la cotización: `precio_usd`, `qty`, `uds_ctn`, `cbm_ctn` y `pvp_iva` (o `sku_similar`). Lo demás tiene
supuesto por defecto y queda marcado. **Muy recomendable** `sku_similar` (un SKU nuestro parecido): de sus ventas reales salen
velocidad, precio real, mix de canales y comisiones. Sin velocidad ni SKU similar, el agente no da COMPRAR.
Para el radar: `{"tipo": "<tipo del radar>", "arancel": "8 dígitos", "palabras": ["MODELO", "40L"]}`; las palabras deben
ser específicas (modelo, capacidad, piezas): si aparecen en > 15% del tipo se consideran genéricas.

## Definiciones (las mismas de la empresa)
- **Costo internado** = motor de precosteo del agente COMEX (validado al peso contra `costear_embarque.calcular_costeo`).
- **Contribución, capital y EVA** = fórmulas del ROI por producto (costo de capital 9%). Marketing lineal 3% (Andrés 9-oct).
- **Decisión** (Andrés 9-oct): COMPRAR si el EVA del escenario conservador es positivo, la contribución base alcanza la de
  su categoría y el radar no muestra el mismo producto más barato (> 10%); NO COMPRAR si el EVA base no es positivo; si no, NEGOCIAR.
- **Radar**: importador inferido con nivel de evidencia; internado de la competencia = estimación. Solo coincidencias ALTA
  (mismo tipo, palabras específicas, precio comparable) pueden bloquear un COMPRAR.

## Archivos
`parametros.py` · `motor.py` · `radar_cruce.py` · `informe.py` · `excel_evaluacion.py` · `evaluar.py` · `validar_excel.py` · `casos/`

## Pendiente (Fase 2 y 3)
- Fase 2: recibir la cotización por correo (PDF/Excel/foto), extraer los datos, pedir lo que falte y responder.
- Fase 3: comparar varias fábricas del mismo producto lado a lado.
