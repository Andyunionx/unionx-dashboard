# Auditoría Inventario Contable vs Valorización Física — Julio 2026

**Estado:** diagnóstico cerrado 9-jul-2026 (v3: circuito importaciones mapeado completo) · reunión con Víctor pendiente (semana del 13-jul)
**Respaldos (Drive, `data/outputs/`):** `AUDITORIA_Inventario_Diagnostico_Final.xlsx` · `MEMO_Auditoria_Inventario_v2.docx` · `PI_recepcionadas_2025_2026.xlsx` · `CONCILIACION_PI_transito.xlsx` (estructura; llaves pendientes)
**Comunicaciones:** memo v1 (8-jul, OBSOLETO) · diagnóstico v2 enviado 9-jul en el hilo (Gmail 19f4470fdec37403) · Victor pidió corte al 31-may → hecho, ver §Corte.

---

## El problema

| Cuenta | Saldo (31-may cerrado) | Respaldo físico | Miga atrapada |
|--------|----------------------:|----------------:|--------------:|
| 111001 Mercadería Nacional | $1.488,4M | $1.213,0M (capas AVCO) | +$275,4M |
| 111008 Inventario Reservado | $293,8M | $0 (cuenta muerta desde 7-abr) | +$293,8M |
| 111006 Importación en Tránsito | $267,7M | ~$0 (cero OC pendientes al 6-jul) | +$267,7M |
| 210208 Steven (pasivo en DEUDOR) | +$251,4M | — | **explicado: anticipos legítimos** |

**GAP 111001+111008 = $569,2M al 31-may (mes cerrado, 210215=$0).** No esconde pérdida masiva: es valor **desubicado** entre cuentas de balance por un circuito manual triple, no valor destruido.

## Corte al 31-may (pedido de Victor — validado)

Victor objetó usar jun/jul (facturas Topwill sin contabilizar). Rehecho al 31-may: **GAP $569,2M ≈ jul $577M → el gap es estructural, NO timing de cierre**. Esto invalidó la estimación previa "residual ~$45M post-cierres": al 31-may las barridas están hechas, 210215=$0, y el exceso de 111001 igual es $275,4M. Los cierres de jun/jul NO van a arreglar el gap.

## El circuito real de una importación (mapeado 9-jul)

El valor CIF entra a contabilidad por **TRES vías** por cada embarque:

```
1. DIN Tesorería:          D:111006 (base CIF)  +  D:111302 (IVA ✓ bien separado)  / H:210201-TGR
2. Reconocimiento manual:  D:111006                                                 / H:210208 Steven
3. Recepción del módulo:   D:111001                                                 / H:210215 Provisión  (+capa física)
```

Topwill NO factura por Odoo (invoice_ids de las OC = vacío; pasivo manual vía 210208). Luego **cuatro cancelaciones manuales**: traspasos (D:111001/H:111006), barridas (D:210215/H:111001), cancelación del pasivo fantasma DIN (210201-TGR: $4.679M debitados vía Misc/bancos/anticipos, saldo TGR hoy −$43M ✓), y pagos reales a Steven. El mismo peso se anota y desanota ~3 veces a mano cada mes → las migas netas de ese churn son el gap.

- DIN → 111006: 2024 $862,6M / 2025 $1.667,1M / 2026 $1.170,1M (total $3.699,8M)
- Reconocimientos Steven → 111006: $2.338,7M (2025-26)
- Módulo → 111001: $2.914,1M (86 PI, 2025-26)
- Hipótesis IVA capitalizado: **DESCARTADA** (DIN separa 19% a 111302 correctamente; ej. DIN 2400370871: $85,3M base + $16,2M IVA)
- 210208 Steven deudor $251,4M: **EXPLICADO** — anticipos may-jun 2026 (OPP/FCI/COMEX USD 344k venc. nov-dic + Ebury $58M) para el plan de embarque septiembre. Cuenta cicla en ~0 históricamente.

## Diagnóstico por componente

### 1. 111001 — exceso +$275,4M (al 31-may)
Facturas/DIN debitando inventario directo + traspasos/barridas descalzados. Fix estructural: proceso (facturas→210215 vinculadas a OC) + conciliación por PI del legado. Módulo sin capa: +$35,4M.

### 2. 111008 — $293,8M, muerta desde 7-abr. Tres orígenes (sin cambios):
- **a) Recuentos $191,9M — NO es merma**: pata positiva $213,7M fue a 210215 y las barridas ene-may la absorbieron hacia 111001 → 111001 quedó des-reconocido. Neto recuentos **+$21,8M A FAVOR**. Asiento pareado (NO toca 210215): `D:111001 $213,7M / H:111008 $191,9M / H:4443116 $21,8M`.
- **b) Fulfillment $74,5M ya reconocido contra 111001** (MISCE/2026/01/0012 + 02/0051; hipótesis de Andrés confirmada): `D:111001 / H:111008 $74,5M`, EERR $0. Remanente ~$28,5M conciliar vs liquidaciones. Circuito: pedidos fbc quedan "a facturar", marketplace liquida después; persona: **Gerardo**. Backlog 17.180 pedidos ene-abr, 96% fbc (ML $318M/Fala $85M).
- **c)** Limpiezas ya hechas −$76,5M + evento ZZ enero neutro.

### 3. 111006 — $274,9M huérfano (jul)
Cero OC de importación pendientes. Débitos: DIN base CIF + reconocimientos Steven + agencias/fletes (~$150M legítimos). Se empareja contra las entradas dobles por embarque (conciliación por PI).

### 4. 210215 — composición saldo jul −$256,7M
= jun −$175,1M (número exacto de Victor ✓) + jul −$81,6M. Puro timing. Barridas 2026: ene $362M/feb $440M/mar $293M/abr $316M/may $224,4M (=el número que Victor cita de "importaciones mayo" — su método de estimación ES la barrida, y mezclaba las ganancias de recuento → su descuadre de $30M). Facturas que limpian 210215 correctamente colapsaron: 2024 $421M → 2026 $25M.

## La solución (3 capas)

**A. Cortar la fuente:** facturas de compra → 210215 vinculadas a OC/recepción (muere barrida+traspaso); fletes/DIN base vía landed costs; regla de oro: cero asientos manuales contra 111001/111006/111008.
**B. Limpiar el legado:** (1) asientos 111008 ya diseñados → cuenta a 0 y desactivar, EERR ≈ neutro; (2) **conciliación por PI** (86 embarques: DIN + reconocimiento Steven + módulo + traspaso) → asigna el residuo de 111001/111006 a: capas subvaloradas (se corrige módulo), anticipos (balance), o resultado (residuo del residuo); (3) inventario físico → asiento de rebase final.
**C. Blindaje:** monitor mensual contable-vs-capas automático + checklist de cierre (210215=0, gap≤umbral).

**Nada se concilia contra patrimonio** — las contrapartidas viven dentro del circuito (111001↔111006↔210208↔210215↔111008). EERR conocido: +$21,8M a favor, máx −$28,5M.

**Conciliación por PI — estado:** estructura construida (`CONCILIACION_PI_transito.xlsx`); bloqueo = las llaves no están en Odoo (DIN sin código PI, traspasos por bulto, Steven sin factura). Llaves disponibles: data COMEX (Seimex referencia por PI, OHNSO) + planilla de traspasos de Victor.

## Agenda reunión con Víctor (semana 13-jul)

1. **Pregunta quirúrgica #1: ¿contra qué se cancela la base CIF de la DIN?** (los ~$60-85M/mes que entran a 111006 vía DIN además del reconocimiento Steven). Si la cancelación no cubre 100%, ahí se fabrica el gap.
2. **Confirmar anticipos Steven** $251,4M (pre-validado como legítimo: OPP/FCI/COMEX + Ebury para plan sept).
3. Pedir su **planilla de traspasos** (mapping PI↔asiento) → destranca la conciliación por embarque.
4. Secuencia del **paquete de asientos** en un solo cierre (pareado + fulfillment + remanente + barridas jun/jul) para que el gap baje de una vez (la reclasif. fulfillment sola SUBE el gap visible de 111001 — mala óptica si va aislada).
5. Mostrar composición de barridas ene-may (arrastraron las ganancias de recuento).
6. Fix estructural Capa A + cerrar/desactivar 111008 + inventario físico como árbitro.

## Pendientes
- [ ] Conciliación por PI con llaves COMEX + planilla Victor (post-reunión)
- [ ] Actualizar planilla Excel con hoja "Circuito importaciones" y corte 31-may
- [ ] Reunión Víctor → paquete de asientos (NADA se postea sin aprobación de Andrés)
- [ ] Validación Gerardo/Danilo: familias grandes de recuentos (GOYA, proyectores LV, espumador)
- [ ] Único candidato pre-cierre EERR: remanente ~$28,5M fulfillment
- [ ] Monitor mensual contable-vs-capas (Capa C) — script existe, falta agendar
