# Agente Odoo - UnionX

Asistente que monitorea Gmail, detecta dudas/solicitudes Odoo, las clasifica,
ejecuta la solucion (con safety layer) y genera borrador de respuesta.

Tambien incluye un **auditor on-demand** que analiza modulos Odoo segun
calidad de datos, configuracion, automatizaciones, eficiencia y escalabilidad.

## Estructura

```
agente-odoo/
├── main.py                       # Punto de entrada (modo monitor / scan / status)
├── config/
│   ├── config.yaml               # Config principal (modo executor, entorno Odoo)
│   ├── triggers.yaml             # Keywords para detectar mails Odoo
│   └── allowed_actions.yaml      # WHITELIST del executor
├── src/
│   ├── email_watcher.py          # Polling Gmail (reusa GmailClient de agente-comex)
│   ├── intent_classifier.py      # Claude API: clasifica el mail en un intent
│   ├── odoo_query.py             # Wrapper Odoo (reusa OdooClient finanzas-unionx)
│   ├── draft_builder.py          # Genera borrador HTML en Gmail Drafts
│   ├── orchestrator.py           # Pega todo el flujo
│   ├── executor/
│   │   ├── dispatcher.py         # Whitelist + dry-run + audit log
│   │   └── actions/
│   │       └── sii_status_fix.py # Primer accion: fix DTE rechazado en Odoo
│   └── auditor/
│       └── module_auditor.py     # Auditor por modulo
├── scripts/
│   └── run_audit.py              # Auditor on-demand
└── data/
    ├── odoo_actions_log.jsonl    # Audit trail del executor
    └── audit_history/            # Reportes del auditor
```

## Setup

```bash
# 1. Dependencias
pip install -r requirements.txt

# 2. ANTHROPIC_API_KEY en el entorno
export ANTHROPIC_API_KEY="..."

# 3. El token Gmail se reusa de agente-comex (no requiere setup adicional)
#    Si no existe, ejecutar: python ../agente-comex/setup_gmail.py
```

## Uso

```bash
# Modo monitor (polling continuo cada 2 min)
python main.py

# Escaneo unico (procesa pendientes y termina)
python main.py --scan

# Ver ultimas acciones registradas
python main.py --status

# Auditor on-demand
python scripts/run_audit.py                  # todos los modulos
python scripts/run_audit.py Contabilidad     # solo uno
```

## Safety layer

El executor tiene 3 reglas duras antes de tocar Odoo:

1. **Whitelist** (`config/allowed_actions.yaml`): solo intents pre-aprobados ejecutan.
   Si un mail llega con un intent fuera de whitelist, el agente solo genera
   borrador en modo "consulta" (con datos pero sin acciones).

2. **Dry-run obligatorio**: antes de escribir en Odoo, simula y registra el plan.
   Por defecto `execute_mode: false` -> nunca ejecuta, solo simula y crea borrador.

3. **Audit trail JSONL** (`data/odoo_actions_log.jsonl`): cada accion (simulada
   o real) queda registrada con before/after para revision o rollback.

Para activar ejecucion real: en `config/config.yaml` -> `executor.execute_mode: true`.
Cada accion ademas puede requerir `require_human_confirmation: true` para
forzar dry-run aunque execute_mode este activo.

## Caso de prueba: SII status fix

Mail de Yohana (4-may-2026):
> "tenemos 5 documentos que estan en odoo como rechazados pero si estan
>  aceptados en el SII, como podemos cambiar el estado en odoo?"

Flujo esperado:
1. Watcher detecta keywords `sii`, `rechazad`, `cambiar el estado`.
2. Classifier identifica intent `sii_status_fix`.
3. Executor lista los 5 docs en dry-run (no toca Odoo).
4. Draft Builder crea borrador en Gmail con tabla de los 5 docs.
5. Andres revisa, valida, y si confirma -> activa `execute_mode: true` y reprocesa.

## Ambientes

`config/config.yaml -> odoo.environment` controla a que Odoo se conecta:
- `test`: https://test3-melollevo.odoo.com (default mientras se valida)
- `produccion`: https://unionxb2b.odoo.com (cambiar solo cuando este OK)
