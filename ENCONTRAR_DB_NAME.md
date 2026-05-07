# Cómo Encontrar el Nombre de la Base de Datos en Odoo

## Método 1: Mediante Developer Tools (F12)

1. Abre: https://unionxb2b.odoo.com
2. Presiona **F12** (Developer Tools)
3. Ve a la pestaña **Network** (Red)
4. Inicia sesión con:
   - Email: andres@grupoeter.cl
   - Contraseña: <usar env var ANDRES_ODOO_PASSWORD>
5. Busca una petición que contenga `jsonrpc` o `execute_kw`
6. En la pestaña **Request** o **Response**, busca el campo `"db":` o `"database":`
7. El valor es el nombre que necesitas

---

## Método 2: Mirar la URL después de login

Después de iniciar sesión, mira la URL:
- A veces aparece como parámetro: `?database=nombreaqui`
- O en la ruta: `/web/database/nombreaqui`

---

## Método 3: Intentar variaciones comunes

Basándome en las URLs, probablemente sean:

**Para Producción (unionxb2b.odoo.com):**
```
- unionxb2b
- union_xb2b
- unionx
- union-x
```

**Para Test (test3-melollevo.odoo.com):**
```
- test3
- test3_melollevo
- test3-melollevo
- melollevo
- test
```

---

## Método 4: Usar el Database Selector

Algunos Odoo muestran un selector de BD en login:
- Si ves un dropdown/combobox al iniciar sesión, ahí verás los nombres disponibles

---

## Una vez lo encuentres:

Actualiza `odoo_config.json` y ejecuta:
```bash
python odoo_connection.py
```

Si aún así no funciona, déjame saber exactamente qué ves en los pasos 1-7.
