# 🧠 Memoria del equipo cobranza

Esta carpeta es la **wiki versionada** del equipo. Es el lugar donde guardamos
todo lo que aprendemos sobre el flujo de cobranza para que ni vos, ni Andrés,
ni Claude se olviden de nada entre sesiones.

---

## ¿Por qué existe?

Antes, el conocimiento del flujo vivía:
- En la cabeza de Martín
- En mails sueltos
- En scripts Python del PC de Martín que solo él entiende
- En notas que se perdían

Ahora vive acá. Cuando alguien (vos, Andrés, Claude) abre Claude Code
apuntando a este repo, **lee automáticamente** estos archivos y arranca
ya sabiendo todo.

---

## 📂 Qué hay en esta carpeta

| Archivo | Para qué sirve | Quién lo edita |
|---|---|---|
| `README.md` (este) | Índice y reglas de uso | Andrés |
| `flujo_actualizacion_clientes.md` | Wiki técnica: partner_ids, particularidades de cada cliente, gotchas | **Víctor + Andrés** |
| `decisiones.md` | Log append-only de decisiones importantes (cron OFF, cambios, etc.) | Andrés (Víctor agrega notas) |
| `incidente_paris_2026-05.md` | Doc del incidente de mayo 2026 (Paris perdió data) | **Víctor completa qué se perdió** |

---

## ✍️ Cómo se actualiza (regla de oro)

**Nunca editás estos `.md` a mano.** Le pedís a Claude que los edite.

Flujo:

1. Descubrís algo nuevo (un partner cambió, un Excel tiene una hoja rara, etc.)
2. Abrís Claude Code en el repo
3. Le decís a Claude algo como:
   > "Agregá a `docs/memoria/flujo_actualizacion_clientes.md`, en la sección
   > de Paris, que ahora tiene un partner_id=999 para cuenta corporativa."
4. Claude edita el archivo
5. Vos hacés:
   ```powershell
   git add docs/memoria/
   git commit -m "memoria: nuevo partner corporativo Paris 999"
   git push
   ```
6. Listo. Toda futura sesión (la tuya, la de Andrés, el cron) lee ese dato.

---

## ❌ Qué NO va acá

- **Credenciales** (passwords, API keys, tokens). Esos van en GitHub Secrets
  o variables de entorno locales — nunca en archivos versionados.
- **Data de clientes** (Excel, CSV, JSON). Solo van rutas/referencias, no la data en sí.
- **Notas personales que no le sirven al equipo** ("acordarme de almorzar"). Esas van
  en tu memoria personal de Claude (`~/.claude/...`), no acá.

---

## 🤖 Cómo Claude lee esta carpeta

Cuando Claude Code arranca en el repo, automáticamente:
1. Lee `CLAUDE.md` de la raíz (contexto general del proyecto UnionX)
2. Cuando vos le pedís algo de cobranza, **busca** en `docs/memoria/` y `docs/`
   los archivos relevantes
3. Los lee y los usa para responder

No hay que "subir" nada a ningún lado. Es Git + Markdown. Punto.

---

## 🆘 Si dudás dónde guardar algo

| Tipo de información | Va en... |
|---|---|
| "Cómo funciona X cliente" | `flujo_actualizacion_clientes.md` |
| "Cambiamos esto el día tal" | `decisiones.md` |
| "Tal cosa salió mal y así lo arreglamos" | crear `incidente_<tema>_<fecha>.md` |
| "Cómo agregar un cliente nuevo" | (ya está en `docs/COMO_AGREGAR_CLIENTE.md`, no duplicar) |
| "Cómo funciona el código" | (ya está en `docs/FLUJO_COBRANZA_BOLETA.md`, no duplicar) |

Si no sabés dónde meterlo, le preguntás a Claude:
> "¿En qué archivo de `docs/memoria/` debería guardar esto?"

---

_Última actualización: 2026-05-26_
