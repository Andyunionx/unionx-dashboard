# 🤖 Agente EERR Mensual — Diseño (stand-by hasta EERR mayo)

> **Para retomar cuando llegue el próximo EERR de Víctor** (probable
> primera o segunda semana de junio 2026 según patrón histórico).
> Self-contained: este doc reemplaza tener que redescubrir todo.

---

## 🎯 Sumario

Agente nuevo que automatiza el flujo manual que hoy hace Andrés cada mes:

1. **Detectar** mail de Víctor con EERR (2 cuentas: `@grupoeter.cl` antes,
   `@unionx.cl` ahora).
2. **Parsear** el adjunto Excel (hoja `EERR INOVATEK`) → cuentas + montos del mes.
3. **Mapear** cuentas Víctor → cuentas Planificación Financiera vía `Maestra EERR.xlsx`.
4. **Insertar** en hoja `Fcst EERR` del archivo `Planificación Financiera 2026.xlsx`
   (con preview + OK humano antes de escribir).
5. **Analizar** vs Metas / PPTO / Año Anterior + recomendaciones.
6. **Reportar** ejecutivo Word + Excel con branding UnionX.
7. **Mailear** a `martin@grupoeter.cl` + `erich@grupoeter.cl` (CC Andrés).

---

## 📥 Patrón de envío de Víctor (scrapeado 25-may-2026)

**44 mails de Víctor con EERR identificados en historial**, frecuencia 1-3 por mes.

| Sender | Período |
|---|---|
| `victor@grupoeter.cl` | hasta enero 2026 |
| `victor@unionx.cl` | desde feb 2026 (actual) |

**Patrón de subject** (regex):
```
^(Re: )?(Envio |envio |Adjunto |Corregida )?EE\.?RR
```

Matchea: `EERR abril 2026`, `Envio EERR ...`, `EERR actualizado`,
`Re: EERR ...`, `Corregida EERR (provisión facturas)`, etc.

**Patrón de adjunto:** `NN EE.RR MES AÑO.xlsx` (ej: `04 EE.RR ABRIL 2026.xlsx`).

**Múltiples mails por mes** → tomar el más reciente (correcciones reemplazan).

---

## 📁 Archivos involucrados

| Path | Rol | Notas |
|---|---|---|
| Mail Víctor (Gmail) | Input | Bot Gmail ya configurado |
| `data/finanzas/Maestra EERR.xlsx` | Mapping cuentas | **31 cuentas** mapeadas (col `CODIGO CUENTA` + `Cuenta Planificación Financiera` + `Cuenta EERR`). ⚠️ Solo 1 cuenta 4101-XX (costos directos) — incompleta para esa sección |
| `data/planillas/Planificación Financiera 2026.xlsx` | Destino | Hoja `Fcst EERR` (col B=código, col C=nombre, cols D+=meses) |
| `data/eerr/01 EE.RR Enero 2026.xlsx` | Histórico local | Para ver formato sin tocar abril (ya cargado, NO TOCAR) |
| `data/eerr/02 EE.RR Febrero 2026.xlsx` | Histórico local | Formato confirmado: hoja `EERR INOVATEK` (1011f x 51c) |

---

## 🗺️ Estructura hoja `Fcst EERR` (destino)

```
Col A: vacía
Col B: código cuenta (4101-XX, 4201-XX, 4291-01)
Col C: nombre cuenta
Col D-O: meses Ene-Dic (probable, confirmar al ejecutar)

Filas clave:
  9      Ingreso de explotación (venta) ← directo del EERR
  11     Costo de explotación             ← directo del EERR
  13     Margen de explotación            ← FÓRMULA — no tocar
  18-26  Costos directos 4101-XX          ← mapeo via Maestra
  28     Margen de contribución           ← FÓRMULA — no tocar
  30-31  % Margen / % Comisión            ← FÓRMULAS
  33-69  GAV 4201-XX y 4291-XX            ← mapeo via Maestra
  71     TOTAL GAV                        ← FÓRMULA — no tocar
  73     RESULTADO operacional            ← FÓRMULA — no tocar
  78+    Otros ingresos / egresos no operacionales ← del EERR
```

---

## 🤖 Arquitectura del agente

```
agente-eerr-mensual/                   🆕
├── main.py
├── config/
│   ├── config.yaml                    # destinos mail, regla mes-1
│   └── maestra_overrides.yaml         # mapeos manuales para cuentas no en Maestra Excel
├── src/
│   ├── detector_mail.py               # 1. buscar mail más reciente Victor
│   ├── parser_eerr.py                 # 2. abrir Excel, hoja EERR INOVATEK, col mes-1
│   ├── mapeador.py                    # 3. cruce con Maestra
│   ├── preview.py                     # 4. mostrar mapping + esperar OK
│   ├── insertador_planilla.py         # 5. escribir Fcst EERR sin tocar fórmulas
│   ├── analizador.py                  # 6. vs Metas/PPTO/AA + recomendaciones
│   ├── render_reporte.py              # 7. Word + Excel branding UnionX
│   └── notificador.py                 # 8. borrador Gmail a Martín + Erich
├── logs/                              # qué EERR se procesó cuándo
└── tmp/                               # adjuntos descargados
```

---

## 🔄 Flujo end-to-end (9 pasos)

```
[1] DETECTAR mail nuevo en Gmail
[2] DESCARGAR adjunto a tmp/
[3] PARSER hoja "EERR INOVATEK" — columna del mes objetivo
[4] MAPEO contra Maestra EERR (N:1 = suma)
[5] PREVIEW — ⚠️ esperar OK humano antes de escribir
[6] BACKUP + INSERCIÓN en Fcst EERR (NO tocar fórmulas)
[7] ANÁLISIS comparativo (Metas, PPTO, AA, KT, recomendaciones)
[8] REPORTE Word + Excel con branding UnionX
[9] MAIL borrador en Gmail a Martín + Erich, CC Andrés
```

---

## ❓ 5 decisiones de diseño pendientes (cerrar cuando llegue mayo)

| # | Pregunta | Recomendación |
|---|---|---|
| 1 | Trigger: manual / auto-confirmación / auto-puro | **Auto con confirmación** (cron detecta + avisa, vos confirmás) |
| 2 | Quién aprueba antes de escribir planilla | **Solo Andrés** post-incidente cobranza |
| 3 | Mail a Martín/Erich: auto / borrador / manual | **Borrador en Gmail** (reusa MCP que ya anda) |
| 4 | Maestra EERR incompleta para 4101-XX | **Match por nombre + flag al user** las que faltan; ir completando la maestra paralelamente |
| 5 | Skill `reporte-financiero-gerencial` v1.3 actual | **Invocar** desde el agente (no duplicar lógica) |

---

## ⚠️ Riesgos identificados (post-incidente cobranza)

| Riesgo | Mitigación |
|---|---|
| Pisar data como en agente cobranza | Preview con OK humano + Drive history como backup automático |
| Cuentas EERR sin mapping en Maestra | Threshold: si monto > X CLP, bloquea hasta resolver. Si chico, va a "Otros" |
| Cambio formato Excel Víctor | Validación schema antes de procesar (existe hoja `EERR INOVATEK`, cols esperadas) |
| Mail enviado sin revisar | Modo dry-run primer run (no manda, solo borrador en tu Gmail) |
| Múltiples correcciones mismo mes | Log mes-by-mes → tomar más reciente, evitar doble run |

---

## 🗓️ Plan de implementación (5 fases)

| Fase | Qué | Cuándo |
|---|---|---|
| **1** | Esqueleto: detector + parser + mapeador. Output: tabla console. | Cuando llegue EERR mayo |
| **2** | Preview + escritura controlada + backup. Probar con mayo. | Día siguiente |
| **3** | Analizador + reporte Word/Excel (reusa skill v1.3) | Día siguiente |
| **4** | Notificador modo borrador Gmail | Día siguiente |
| **5** | Activación cron diaria con confirmación | Cuando los 4 anteriores estén validados |

---

## 🚦 Cómo retomar

**Cuando llegue el mail "EERR mayo 2026" de Víctor:**

```
Hola Claude, llegó el EERR de mayo. Retomemos el agente
siguiendo docs/EERR_AGENTE_DISENO_2026-05.md.

Empezá por Fase 1 (detector + parser + mapeador), modo solo console,
sin tocar la planilla todavía. Confirmemos las 5 decisiones pendientes
con el archivo real en mano.
```

Y yo:
1. Leo este doc
2. Bajo el mail nuevo de Víctor
3. Inspecciono el Excel para confirmar formato
4. Te pido las 5 decisiones
5. Codeo Fase 1

---

# 🏦 Extensión: Balance mensual (mismo agente, modo Balance)

Análisis post-25-may: el flujo Balance comparte ~80% con el EERR. Se hace
UN SOLO agente con 2 modos en lugar de 2 agentes separados.

## Patrón mail Balance

Mismo sender (`victor@unionx.cl`), subject típico `balance al DD de MES AÑO`.
Último ejemplo: 21-may-2026 "balance al 30 de abril 2026".

## Archivo Balance Víctor — estructura

`NN BALANCE MES AÑO.xlsx` con 5 hojas:
- **`Balance Clasificado`** ← la importante (64f x 22c, vista ejecutiva)
- `PRESTAMOS COMERCIALES`
- `Balance acumulado`
- `BALANCE DEL MES`
- `HOJA TRABAJO`

## Mapeo 1:1 — NO requiere Maestra externa

A diferencia del EERR, el Balance es **copy-paste fila a fila**:

| Cuenta | Fila Víctor (`Balance Clasificado`) | Fila Planificación (`Ref Balances`) |
|---|---|---|
| Caja y equivalente | 6 | 6 |
| Existencias | 7 | 7 |
| CxC comerciales | 8 | 8 |
| Anticipo proveedor | 9 | 9 |
| Otras CxC | 10 | 10 |
| Impuestos por recuperar | 11 | 11 |
| Interés diferido | 12 | 12 |
| Impuesto diferido | 13 | 13 |
| Anticipo sueldos | 14 | 14 |
| Otros | 15 | 15 |
| Propiedades (oficina) | 19 | 19 |
| Equipos (vehículos) | 20 | 20 |
| Depreciación Acumulada | 21 | 21 |
| CxP comerciales | 28 | 28 |
| Sueldos x pagar | 29 | 29 |
| Anticipo clientes / Provisiones | 30 | 30 |
| Deuda financiera | 31 | 31 |
| Préstamos socios | 32 | 32 |
| Deuda Revolving | 33 | 33 |
| Impuestos por pagar | 34 | 34 |
| Capital emitido | 38 | 38 |
| Utilidad acumulada | 39 | 39 |
| Utilidad del ejercicio | 40 | 40 |
| Dividendos pagados | 41 | 41 |

Filas Total (16, 22, 24, 35, 42, 44) = fórmulas, NO escribir.

## Reporte Balance (skill v1.3 Escenario 2)

Genera Reporte de Situación Financiera con:
- Estructura del Balance (Activos / Pasivos / Patrimonio)
- Ratios de Liquidez y Solvencia (Razón Corriente, Prueba Ácida,
  Endeudamiento, Deuda/Patrimonio, Cobertura)
- Capital de Trabajo (Schedule)
- Recomendaciones

## Arquitectura unificada (revisada 25-may)

```
agente-finanzas-mensual/                   🆕 reemplaza agente-eerr-mensual
├── main.py                                # detector + router (EERR vs Balance)
├── config/
│   ├── config.yaml
│   ├── maestra_eerr_overrides.yaml        # solo modo EERR
│   └── balance_mapping.yaml               # 1:1 fijo (modo Balance)
├── src/
│   ├── detector_mail.py                   # común
│   ├── parser_eerr.py                     # modo EERR
│   ├── parser_balance.py                  # modo Balance
│   ├── mapeador_eerr.py                   # modo EERR (con Maestra Excel)
│   ├── mapeador_balance.py                # modo Balance (mapping interno fijo)
│   ├── preview.py                         # común
│   ├── insertador_planilla.py             # común (sabe escribir ambas hojas)
│   ├── analizador.py                      # común — bifurca según modo
│   ├── render_reporte.py                  # común — bifurca según modo (v1.3)
│   └── notificador.py                     # común
└── logs/
```

## Mes envío estimado del Balance

Por el patrón histórico, Víctor manda **el balance del mes anterior alrededor del
día 17-21 del mes siguiente** (abril 30 → mail del 21-may). Es ~5 días después
del EERR. Eso permite procesar EERR primero (semana 2) y Balance después
(semana 3) en cada ciclo mensual.

---

_Última actualización: 25-may-2026 — extensión modo Balance._
