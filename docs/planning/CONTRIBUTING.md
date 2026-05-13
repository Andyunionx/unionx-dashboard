# Cómo contribuir a la App de Planificación UnionX

Esta guía es para **terceros (consultores Supply Chain) que trabajan sobre el contenido de la app de Planificación** sin tocar la arquitectura compartida.

> **TL;DR**: trabajás solo dentro de `views/planning/` y `data/planificacion/`. Abrís PR contra `main`. El sistema valida automáticamente que no hayas tocado nada fuera de tu zona. Andrés revisa solo los cambios que toquen arquitectura.

---

## 1. Setup inicial (una sola vez)

### Requisitos
- Cuenta GitHub (gratis está bien)
- Git instalado
- Python 3.12+
- Editor de código (VSCode recomendado)

### Pasos

```bash
# 1. Clonar el repo (Andrés te debe haber agregado como collaborator antes)
git clone https://github.com/Andyunionx/unionx-dashboard.git
cd unionx-dashboard

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Levantar la app de Planificación localmente (opcional, para probar cambios)
streamlit run dashboard_planificacion.py
```

Para correr la app localmente necesitás los secrets de Streamlit Cloud — pedíselos a Andrés y los guardás en `.streamlit/secrets.toml` (que está en `.gitignore`, nunca lo subas).

---

## 2. Tu zona de trabajo

### ✅ Pueden modificar libremente

| Path | Para qué |
|---|---|
| `views/planning/*.py` | Módulos de la app: triada, compras, políticas, proveedores, negociación, etc. |
| `views/planning/contenido/*.md` | MDs que la app puede mostrar como contenido o documentación inline |
| `data/planificacion/*` | Datasets, templates, archivos MD de procesos |
| `extract_proveedores_master.py` | Extractor del maestro proveedores |
| `docs/planning/*.md` | Documentación interna de procesos de planning |

### ❌ NO pueden modificar

| Path | Por qué |
|---|---|
| `dashboard_planificacion.py` | Entry point — afecta navegación, auth, deploy |
| `views/shared.py`, `views/_ops_*` | Helpers compartidos con Ventas y Operaciones |
| `dashboard_ventas.py`, `dashboard_operaciones.py` | Otras apps |
| `finanzas-unionx/` | App Finanzas |
| `.github/` | Workflows + CODEOWNERS |
| `requirements.txt`, `.gitignore`, `auth_config.yaml`, `CLAUDE.md` | Configuración global |
| `extract_*.py` (excepto proveedores_master) | Pipelines de datos de otras apps |

Si necesitás algo de esos paths para que tu trabajo avance, **abrí un issue en GitHub** explicando qué y por qué — Andrés decide.

---

## 3. Flujo de trabajo (cada vez que hacés cambios)

```bash
# 1. Asegurate de partir de la versión más reciente de main
git checkout main
git pull origin main

# 2. Crear un branch descriptivo
git checkout -b planning/<tu-feature>
# ejemplos: planning/maestro-proveedores-v2
#           planning/agregar-modulo-roi-sku
#           planning/mejora-deteccion-drift

# 3. Hacer tus cambios SOLO en tu zona (sección 2)

# 4. Probar localmente
streamlit run dashboard_planificacion.py

# 5. Commit con mensaje claro
git add views/planning/...
git commit -m "Planning: <qué cambió y por qué>"

# 6. Subir el branch
git push origin planning/<tu-feature>

# 7. Abrir PR en GitHub:
#    - Title: corto, qué hiciste
#    - Description: explicar contexto, qué probaste, screenshots si aplica
#    - Asignar reviewer: Andyunionx (si tocaste algo fuera de tu zona)
```

### Qué pasa después del push

GitHub corre automáticamente las validaciones:
- ✅ Si tocaste solo tu zona → tu PR puede mergearse **sin esperar review** de Andrés (autorizado por CODEOWNERS).
- 🔒 Si tocaste algo fuera de tu zona → GitHub **bloquea el merge** hasta que Andrés apruebe.

Andrés recibe notificación de todos los PRs igual, pero solo bloquea los que tocan arquitectura.

---

## 4. Reglas de oro

1. **Branches descriptivos**: `planning/<accion>-<contexto>`, ej. `planning/agregar-cohorts-rotacion`.
2. **Un PR = un cambio coherente**. No mezclar features distintas en un mismo PR.
3. **Mensajes de commit en español**: empezar con "Planning: " seguido de qué cambió.
4. **Probar local antes de pushear**. La app de Planificación tiene 4 módulos principales (Triada, Compras, Políticas, etc.) — si tu cambio toca uno, validá que no rompiste los otros.
5. **Nunca commitear**:
   - `credentials.json`
   - `.env`
   - `.streamlit/secrets.toml`
   - Archivos personales o de prueba que no son código
6. **Nunca pushear directo a `main`**. Siempre PR.

---

## 5. Cómo agregar un módulo nuevo a la app

Si querés crear, por ejemplo, un módulo de "Análisis de ROI por SKU":

```python
# views/planning/roi_sku.py
"""Módulo: ROI por SKU."""
import streamlit as st

def render():
    st.title("📈 ROI por SKU")
    # ... tu lógica
```

Para que aparezca en la navegación del dashboard, **NO toques `dashboard_planificacion.py`** (eso es zona Andrés). En su lugar:

1. Abrí un issue en GitHub: "Agregar módulo X a la navegación"
2. Andrés agrega la entrada `st.Page(...)` y mergea.

---

## 6. Datos y archivos MD

### Cargar un MD descriptivo de proceso
- `docs/planning/proceso-<nombre>.md` para documentación interna (no se renderiza en la app)
- `views/planning/contenido/<nombre>.md` para MDs que la app puede leer y mostrar

### Cargar un parquet de datos
- `data/planificacion/<archivo>.parquet`
- Documentá el schema en `data/planificacion/<archivo>.template.md`

### Cargar credenciales o tokens
**Nunca al repo.** Pedile a Andrés que los agregue a los Streamlit Secrets de la app.

---

## 7. Si algo se rompe

1. **No pushear más**. Avisar a Andrés inmediatamente.
2. **Rollback**: Andrés puede hacer `git revert` del commit problemático.
3. **Streamlit Cloud redeploya solo** cuando se mergea a `main` — si algo está mal en producción, primero rollback en git y se redeploya en 1-2 min.

---

## 8. Canal de comunicación

- **Issues GitHub**: para todo lo que requiera decisión de Andrés (cambios fuera de tu zona, dudas técnicas, bugs).
- **Email / Slack**: para coordinar a alto nivel (qué próximo módulo construir, prioridades).

---

## 9. Recursos

- Repo: https://github.com/Andyunionx/unionx-dashboard
- App de Planificación (producción): pedile el link a Andrés
- Documentación Streamlit: https://docs.streamlit.io
- Documentación pandas: https://pandas.pydata.org/docs/

---

**Última actualización**: 2026-05-13
