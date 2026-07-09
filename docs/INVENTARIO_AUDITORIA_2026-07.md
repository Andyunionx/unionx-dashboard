# Auditoría Inventario Contable vs Valorización Física — Julio 2026

**Estado:** diagnóstico cerrado 9-jul-2026 · reunión con Víctor pendiente (semana del 13-jul)
**Respaldos (Drive, `data/outputs/`):** `AUDITORIA_Inventario_Diagnostico_Final.xlsx` (9 hojas) · `MEMO_Auditoria_Inventario_v2.docx` · `PI_recepcionadas_2025_2026.xlsx`
**Comunicaciones:** memo v1 enviado 8-jul (OBSOLETO, tesis corregidas) · respuesta completa con diagnóstico v2 enviada 9-jul en el hilo (ID Gmail 19f4470fdec37403). Reunión comprometida "próxima semana sin falta".

---

## El problema

Al 31-jul-2026, familia inventario contable vs realidad física:

| Cuenta | Saldo contable | Respaldo físico | Sobrante |
|--------|---------------:|----------------:|---------:|
| 111001 Mercadería Nacional | $1.372,9M | $1.092,9M (capas AVCO) | +$280M (neto*) |
| 111008 Inventario Reservado | $294,9M | $0 | +$294,9M |
| 111006 Importación en Tránsito | $274,9M | ~$0 (cero OC pendientes) | +$274,9M |
| **Total** | **$1.942,7M** | **$1.092,9M** | **≈ +$850M bruto** |

\* El +$280M de 111001 es un neto que esconde dos des-reconocimientos (−$213,7M ganancias recuento barridas + −$74,5M fulfillment) que enmascaran un exceso real de ~$570M por el circuito compras/importaciones.

El gap 111001+111008 ($577M) nació en Odoo: mar-2024 partió en $14M y creció sostenido. **No esconde una pérdida masiva** — es desorden de ruteo contable de la transición de procesos. Correcciones con efecto EERR: ≈ +$22M a favor (recuentos) y máx −$28M (remanente fulfillment).

## Diagnóstico por componente (todo verificado a nivel de asiento)

### 1. 111001 — exceso +$301,6M (visible) sobre físico
- **Facturas de compra debitan 111001/111006 directo** en vez de limpiar la provisión 210215: +$338,9M histórico solo diario Compras Nacionales. Las facturas que limpian 210215 correctamente colapsaron: 2024 $421M → 2025 $295M → 2026 **$25M**.
- Víctor compensa con **barrida mensual** de 210215 contra 111001 (deja la provisión en $0 cada cierre — verificado: cero todos los meses hasta may-26). Mayormente timing; cierres may/jun pendientes.
- Ajustes de módulo sin capa: +$35,2M.

### 2. 111008 — $294,9M, formado 100% en 2026, cuenta MUERTA desde 7-abr
Las 2 categorías que apuntaban a ella (All/Saleable, All/Expenses) fueron migradas en abril: 0 productos, 0 movimientos desde 8-abr. Nada la limpia automáticamente. Tres orígenes:

**a) Ajustes de recuento $191,9M — NO es merma.** Recuentos ene-feb (toma anual 8-9 ene: Danilo, Gerardo, Andrés) bajaron stock D:111008/H:111001. La pata POSITIVA de los mismos recuentos (+$213,7M) entró H:210215 **y fue barrida hacia 111001 dentro de las barridas mensuales ene-may** → 111001 quedó des-reconocido $213,7M de mercadería que sí existe. Neto real recuentos: **+$21,8M a favor**. Patrón = corrección de mezcla de SKU (ej. familia GOYA completa el 21-ene en ambas direcciones).
Asiento pareado corregido (ya NO toca 210215):
`D:111001 $213,7M / H:111008 $191,9M / H:4443116 $21,8M`

**b) Costo fulfillment $74,5M ya reconocido pero descargado de cuenta equivocada** (hipótesis de Andrés, confirmada). Circuito: pedidos fbc quedan "a facturar" (marketplace liquida después); OUT descuenta stock (debitaba 111008); costo se reconoce con asiento manual mensual (D:41410109). Evolución del asiento de Víctor: ene-feb contra **111001** (estilo antiguo; MISCE/2026/01/0012 $35,1M + MISCE/2026/02/0051 $39,4M) → mar contra 111008 (correcto) → abr-jun reclasif. desde 41410101. En ene-feb el OUT ya había llevado ese costo a 111008 → doble descuento de 111001.
Corrección: `D:111001 / H:111008 $74,5M` — **EERR $0**. Remanente ~$28,5M por conciliar vs liquidaciones (solo lo no calzado va a costo).
Backlog asociado: 17.180 pedidos ene-abr "a facturar", $446M venta neta, 96% fbc (ML $318,5M / Falabella $85,2M / Paris $21,6M). Persona del circuito: **Gerardo**.

**c) Limpiezas ya aplicadas −$76,5M + evento ZZ-DUPLICADO enero (refacturación $2.780M, neto −$3,9M, neutro).**

### 3. 210215 Facturas por Recibir — composición saldo −$256,7M
= junio −$175,1M (exacto al número de Víctor) + julio −$81,6M. **Puro timing** de cierres pendientes; las ganancias de recuento ya no están (barridas). La barrida de mayo fue $224.422.695 = el número que Víctor cita como "importaciones de mayo" — su método estima ingresos mensuales con el saldo de 210215, que mezclaba ganancias de recuento (explica su descuadre de "$30M").

### 4. 111006 Tránsito — $274,9M HUÉRFANO (hallazgo 9-jul)
Las **110 OC de importación desde 2025 están TODAS recepcionadas — cero pendientes**. No hay mercadería en el agua (en Odoo) que respalde el saldo. Venía de $490,8M (dic-25), Víctor lo bajó a $274,9M, pero es un piso sin respaldo. Causa probable: facturas DTE codificadas a mano a 111006 sin vínculo a OC + traspasos que no emparejan 1:1. **Punto más grande pendiente**: o hay documentación de embarques fuera de Odoo, o se reversa contra el circuito de compras.

### Cross-checks clave
- Recepciones importación (módulo, por PI): 2025 $1.796,9M / 2026 $1.117,2M — 86 PI, listado en `PI_recepcionadas_2025_2026.xlsx` (Víctor lo pidió; se lo enviamos). Cotejo correcto es **por PI, no por mes** (documento vs recepción física).
- Traspasos manuales tránsito→inventario desde 2025: $2.927,8M ≈ costo internado $2.914,1M (calza 0,5%).
- Barridas 2026 ene-may $1.635,9M: contrapartidas H:111001 $1.424,1M + **H:210208 Steven $113,0M + H:1101016 Pago ML $98,8M (revisar en reunión)**.

## Agenda reunión con Víctor (semana 13-jul)

1. **Secuencia del paquete de asientos** — todo en el mismo cierre para que el gap baje de una vez y no haya peak intermedio (la reclasif. fulfillment sola SUBE el gap visible de 111001 de $301,6M a $376,1M):
   pareado recuentos + reclasif. fulfillment $74,5M + remanente ~$28M + barridas jun/jul normales.
2. Mostrar composición de sus barridas ene-may (arrastraron las ganancias de recuento).
3. **Tránsito 111006**: respaldo documental de los $274,9M o plan de reversa. Dato duro: 0 OC pendientes.
4. Contrapartidas raras de barridas (Steven $113M / Pago ML $98,8M).
5. Fix estructural: facturas → 210215 (vincular factura↔OC/recepción); elimina barrida manual y doble conteo.
6. Post-limpieza: cerrar y desactivar 111008; inventario físico como árbitro del residual.

## Pendientes
- [ ] Actualizar planilla + memo con hallazgos 9-jul (210215/asiento pareado corregido + tránsito huérfano)
- [ ] Cruzar 111006 vs data COMEX (`data/comex/transito_sheet.parquet`) para descartar embarques en el agua sin OC
- [ ] Reunión Víctor → paquete de asientos (NADA se postea sin aprobación de Andrés)
- [ ] Validación Gerardo/Danilo: familias grandes de recuentos (GOYA, proyectores LV, espumador) — SKU-mix vs merma real
- [ ] Victor cierra EERR esta semana; único punto candidato pre-cierre: remanente ~$28M fulfillment
