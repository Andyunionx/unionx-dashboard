# Auditoría Inventario Contable vs Valorización Física — Julio 2026

**Estado:** v4 (22-jul) — diagnóstico definitivo con hallazgo REG SALDO + Fase 0 cuantificada · reunión con Víctor pendiente
**Respaldos (`data/outputs/`):** `FASE0_Conciliacion_PI_completa.xlsx` · `FASE0_Internacion_sobre_stock.xlsx` · `Recuentos_inventario_2026_detalle.xlsx` · `Conciliacion_transito_PI_v2.xlsx` · `AUDITORIA_Inventario_Diagnostico_Final.xlsx` · `MEMO_Auditoria_Inventario_v2.docx` (obsoleto en 2 puntos, ver v4)
**Plan aprobado:** `~/.claude/plans/ok-en-paralelo-quiero-cosmic-wombat.md` (Fases 0-4)

---

## El problema
GAP contable (111001+111008) vs físico: **$569,2M al 31-may (cerrado, 210215=$0)** / $560,3M al 30-jun. Estructural, no timing (probado en mes cerrado). Triangulación: capas AVCO $1.061M ≈ replay físico $1.099-1.115M (±$54M metodológico, réplica validada bodega×bodega vs CSV Victor) vs contable $1.621M → **la medición física es sólida; el problema vive en la construcción del mayor.**

## Diagnóstico definitivo (v4)

### 1. HALLAZGO REG SALDO — dónde están las ganancias de recuento ($213,7M)
Las ganancias de recuento ene-mar (D:111001/H:210215) no cuadraban contra facturas reales. El **1-abr-2026** se regularizaron con dos asientos fuera de ciclo:
- **MISCE/2026/04/0077 "REG SALDO STEVEN": D:210215 / H:210208 $113.039.121** → pasivo Steven INFLADO sin factura de respaldo
- **MISCE/2026/04/0078 "REG SALDO": D:210215 / H:1101016 Pago ML $98.800.747** → activo Pago ML REBAJADO
- Suman $211,8M ≈ ganancias $213,7M (**calce 99,1%**). Confirmar con papel de trabajo de Victor.
- **Asiento pareado rediseñado** (condicional): `D:210208 $113,0M + D:1101016 $98,8M + D:111001 $1,9M / H:111008 $191,9M / H:4443116 $21,8M`. **111001 no se toca** (las ganancias siguen dentro, igual que el físico). El saldo deudor de Steven ($251,4M) incluye este crédito sin base → recalcular su posición real.

### 2. 111008 ($293,8M) — composición probada
Pérdidas recuento $191,9M estacionadas como activo + ciclo fulfillment ~$103M (de eso $74,5M ya expensado contra 111001 en MISCE/2026/01/0012+02/0051). Cuenta muerta desde 7-abr.
**Corte fulfillment vs Victor:** él cuantifica $132,2M "salidas Full duplicadas". Mi descomposición de los OUT de 111008 por modalidad del pedido (2026): normal $228,1M / fbm $182,6M / **fbc $103,5M** / sin_pedido $90,2M / fbf $68,5M. Mi corte ($74,5+28,5=103M) ≈ fbc exacto. Cuadrar definición con su papel de trabajo.

### 3. 111001 (exceso +$275,4M al 31-may) — mecanismo y localización
El mayor se construye por vía manual paralela (la barrida $1.424M/2026 revierte las recepciones del módulo). Fase 0.2 ejecutada CON LA COMPARACIÓN CORRECTA (Andrés 22-jul: la OC en Odoo se carga al costo INTERNADO — mercadería + internación del costeo COMEX):
- **DIF A (Recibido Odoo vs Total carpeta = internado est. vs internado real): mediana −0,7% en 42 PIs → el circuito trazable CUADRA al peso.**
- **DIF B (Recibido vs Traspaso GL): +$11,8M en 39 PIs** — marginal.
- **Bulto SIN código PI: $823,4M** (ene-feb 2026 + era 2025) → **el exceso de 111001 NO está en las PIs trazables; está acá y en la era 2024-2025 sin carpetas** (69 PIs). Pedir a Victor el per-PI (MISCE/2026/01/0062, 02/0072, etc.).
- Génesis confirmada: régimen dual Nubox/Bsale (gap mar-24 $14M → dic-24 $272M), Victor lo reconoce.
- Archivo: `FASE0_Conciliacion_PI_v2_DIFAB.xlsx`.

### 3b. REVISIÓN COMPLETA con premisas validadas (22-jul, sugerencia Andrés) — `REVISION_COMPLETA_PIs.xlsx`
Casos 0924/0228/0818 auditados con USD reales de Andrés revelaron 3 patrones → chequeo sistemático a las 118 PIs:
- **16 OK** (circuito sano al peso) · **2 parciales** · **12 REVISAR CARPETA** con defecto específico: patrón-0228 (col15=Odoo pero fila COSTO errada: 0228 −$15,6M, 0207, 0312) · valores DUPLICADOS entre carpetas (0818, 0330, 0801, 0228) · carpeta >4% sobre Odoo/flete doble (1013, 1201, 0105, 1026) · TC fuera de rango (0901).
- **P00571 sin referencia corregida en Odoo** (→25TP0924PI, con OK Andrés): 0924 CALZA (+$0,5M), no era anomalía.
- **RESUELTO (22-jul tarde): las 25 OC sin referencia quedaron en 10 por $22,2M (solo menores).** Vía correo (3: P00255→24TP0907, P00310→24TP1114, P00333→24TP1218) + conocimiento de Andrés (9 grandes 2024: P00234→24TP0806, P00198→0711, P00190→0624, P00247→0829, P00192→0725, P00248→0822, P00266→0915, P00342→1216, P00203→0830; + P00604→25TP1118, P00353→PI0124 RED DRAGON, P00286→mixta 0919/1129 aéreo-marítimo a separar). **La era 2024 pasó de intrazable a conciliable.**
- Hallazgos colaterales: OC con NOMBRES DUPLICADOS en Odoo (P00255/P00310/P00342/P00353 tienen gemelos) — cuidado en análisis por nombre; P00353 con PROVEEDOR MAL ASIGNADO (dice Topwill, es Red Dragon).
- Conclusión: Odoo sale bien parado (calza contra USD reales); los defectos están en las CARPETAS Excel (papel de trabajo del traspaso) y en la falta de referencias 2024.

### 4. Internación (Fase 0.1) — CORREGIDO: no hay colchón de base
La OC/módulo YA valoriza al costo internado (verificado: DIF A mediana −0,7%). **No existe diferencia de base legítima GL-vs-módulo por internación** — mi estimación anterior ($30-60M de colchón) queda invalidada. → Residuo a castigar en Fase 3: banda **$200-270M** (el exceso de 111001 menos lo que el per-PI del bulto logre emparejar).

## Programa (fases del plan aprobado)
- **Fase 1** — Asientos composición: pareado rediseñado (REG SALDO) + fulfillment $74,5M + remanente (corte a cuadrar). EERR ≈ neutro. 111008 → 0 y desactivar.
- **Fase 2** — ELIMINADA como revalorización (la OC ya carga internado). Queda solo verificar que el costeo COMEX→OC capture internación real (DIF A outliers).
- **Fase 3** — Toma física general + regularización del residuo (**$200-270M estimado**) contra resultados/CPC según auditor externo.
- **Fase 4** — Corte de fuente: facturas→210215 vía OC, cero manuales en 111001/111006/111008, monitor mensual, checklist cierre.

## Preguntas quirúrgicas para Victor (reunión)
1. **¿Qué respaldo tienen MISCE/2026/04/0077 y 0078 (REG SALDO $211,8M)?** ← define el pareado
2. Per-PI del bulto de traspasos sin código ($823,4M: ene 0062, feb 0072 y era 2025)
3. Outliers de DIF A (estimado vs real por PI, pocos casos — el circuito trazable cuadra mediana −0,7%)
4. Papel de trabajo de sus $132,2M "salidas Full" (mi fbc = $103,5M)
5. ¿Contra qué se cancela la base CIF de la DIN? (pendiente de v3)
6. Casos recepción ≠ precio OC: 26TP0130 (−$8,9M), 26TP0123 (−$1,9M)

## Pendientes
- [ ] Enviar respuesta consolidada a Victor (borrador listo, espera OK Andrés)
- [ ] Reunión → confirmar REG SALDO → postear Fase 1 (NADA sin OK Andrés)
- [ ] Toma física con Gerardo (árbitro final)
- [ ] Monitor mensual contable-vs-capas (script existe, agendar)
