# Memoria operativa — Cobranza

> Wiki versionada del equipo de cobranza. Lo que ponés acá tiene **historial
> de cambios** vía git, todos lo pueden ver, y queda como referencia para
> el agente de cobranza y para quien tome el rol mañana.

## Qué va acá

✅ **SÍ:**
- Cómo se hace tal proceso (descarga, conciliación, conciliación manual, etc.)
- Mapping de campos Odoo (`l10n_latam_document_type_id`, etc.)
- Casos especiales por cliente (ej: "MELI tiene 2 partner_ids, BOL es 16, FAC son 1586+90747")
- Troubleshooting de problemas comunes
- Cambios de proveedores / portales / bancos

❌ **NO:**
- Passwords, tokens, API keys → van a GitHub Secrets
- Datos personales / montos absolutos de clientes → mantenelo agregado
- Información sensible (NDA, contratos) → mantené en Drive privado

## Index

| Archivo | Qué describe |
|---|---|
| [`flujo_actualizacion_clientes.md`](flujo_actualizacion_clientes.md) | Cómo el agente actualiza los Excel de los 5 clientes principales (mapping de campos, hojas, fórmulas XLOOKUP) |
| _(agregá nuevos)_ | _(describí acá)_ |

## Cómo agregar una entrada nueva

Desde Claude Code en tu máquina, en el repo:

```
Quiero documentar <PROCESO>. Hacéme preguntas hasta sacar todo el detalle
y después generá docs/memoria/<slug>.md. Cuando esté, agregalo al index
de docs/memoria/README.md y abrí PR a main.
```
