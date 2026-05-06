# Pasos para Conectar a Odoo

## Problema Actual
Los nombres de las bases de datos no son correctos:
- Producción: `union-xb2b` ❌ (no existe)
- Test: `test3-melollevo` ❌ (no existe)

## Solución: Obtener los nombres correctos

### Opción 1: Desde la interfaz web (RECOMENDADO)

**Producción:**
1. Abre: https://unionxb2b.odoo.com
2. Inicia sesión con:
   - Email: andres@unionx.cl
   - Contraseña: ROTATED-2026-05-07
3. Una vez adentro, ve a **Configuración > Información del Sistema**
4. Busca "Database Name" o "Nombre de BD"
5. Copia el valor exacto

**Test:**
1. Abre: https://test3-melollevo.odoo.com
2. Inicia sesión con las mismas credenciales
3. Repite los pasos 3-5

### Opción 2: Desde la URL
Algunos servidores Odoo muestran el DB en la URL después de iniciar sesión:
- Busca algo como: `?database=<nombre_aqui>`

### Opción 3: Pregunta al administrador
Si no lo encuentras, pide al admin que confirme los nombres exactos.

---

## Una vez tengas los nombres:

1. Edita **odoo_config.json**
2. Reemplaza los valores en `db_name`
3. Guarda el archivo
4. Ejecuta nuevamente:
   ```bash
   python odoo_connection.py
   ```

---

## Formato esperado en odoo_config.json:

```json
{
  "produccion": {
    "url": "https://unionxb2b.odoo.com",
    "username": "andres@unionx.cl",
    "password": "ROTATED-2026-05-07",
    "db_name": "nombre_correcto_aqui"
  },
  "test": {
    "url": "https://test3-melollevo.odoo.com",
    "username": "andres@unionx.cl",
    "password": "ROTATED-2026-05-07",
    "db_name": "nombre_correcto_aqui"
  }
}
```

---

## Estado actual

| Componente | Estado |
|-----------|--------|
| XML-RPC Connection | ✓ Funcionando |
| Autenticación | ✓ Funciona (cuando DB correcta) |
| Lectura de datos | ✓ Disponible |
| Escritura de datos | ✓ Disponible |
| **DB Names** | ❌ Necesita corrección |

Una vez consigas los nombres correctos, todo debería funcionar perfectamente.
