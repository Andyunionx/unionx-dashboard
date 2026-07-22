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
El mayor se construye por vía manual paralela (la barrida $1.424M/2026 revierte las recepciones del módulo). Fase 0.2 ejecutada:
- **Traspasos GL CON código PI: $2.084,8M** (46 PIs) → donde hay data completa, la carga manual calza o difiere 2-4% BAJO el módulo (TC de registro — pregunta a Victor).
- **Bulto SIN código PI: $823,4M** (ene-feb 2026 + era 2025) → **acá se esconde el exceso**; pedir a Victor el per-PI de esos asientos (MISCE/2026/01/0062, 02/0072, etc.).
- 69 PIs de 2024-mediados 2025 no están en sus carpetas (su archivo cubre desde ~oct-2025 efectivamente).
- Génesis confirmada: régimen dual Nubox/Bsale (gap mar-24 $14M → dic-24 $272M), Victor lo reconoce.

### 4. Internación sobre stock (Fase 0.1) — el colchón legítimo es MENOR
Carpetas Victor: mercadería $2.244,1M / internación $131,7M → **ratio real 5,9%** (no 10-15%). Internación estimada sobre stock actual: **$30,8M piso / ~$60M techo teórico**. → El residuo a castigar en Fase 3 CRECE respecto al estimado inicial: banda **$180-250M**.

## Programa (fases del plan aprobado)
- **Fase 1** — Asientos composición: pareado rediseñado (REG SALDO) + fulfillment $74,5M + remanente (corte a cuadrar). EERR ≈ neutro. 111008 → 0 y desactivar.
- **Fase 2** — Landed costs + revalorización capas por internación ($30-60M).
- **Fase 3** — Toma física general + regularización del residuo (**$180-250M estimado**) contra resultados/CPC según auditor externo.
- **Fase 4** — Corte de fuente: facturas→210215 vía OC, cero manuales en 111001/111006/111008, monitor mensual, checklist cierre.

## Preguntas quirúrgicas para Victor (reunión)
1. **¿Qué respaldo tienen MISCE/2026/04/0077 y 0078 (REG SALDO $211,8M)?** ← define el pareado
2. Per-PI del bulto de traspasos sin código ($823,4M: ene 0062, feb 0072 y era 2025)
3. ¿Qué TC usa al registrar mercadería? (difs sistemáticas 2-4% bajo módulo)
4. Papel de trabajo de sus $132,2M "salidas Full" (mi fbc = $103,5M)
5. ¿Contra qué se cancela la base CIF de la DIN? (pendiente de v3)
6. Casos recepción ≠ precio OC: 26TP0130 (−$8,9M), 26TP0123 (−$1,9M)

## Pendientes
- [ ] Enviar respuesta consolidada a Victor (borrador listo, espera OK Andrés)
- [ ] Reunión → confirmar REG SALDO → postear Fase 1 (NADA sin OK Andrés)
- [ ] Toma física con Gerardo (árbitro final)
- [ ] Monitor mensual contable-vs-capas (script existe, agendar)
