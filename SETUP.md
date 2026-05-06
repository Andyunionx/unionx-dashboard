# Agente COMEX Gmail - Setup

## Requisitos previos
- Python 3.10+
- Cuenta de Gmail con acceso

## Paso 1: Instalar dependencias

```bash
cd "Steven Comex"
pip install -r requirements.txt
```

## Paso 2: Configurar Gmail API

### 2.1 Crear proyecto en Google Cloud
1. Ir a https://console.cloud.google.com/
2. Crear proyecto nuevo: **"COMEX Agent"**
3. En **APIs & Services > Library**, buscar y habilitar **Gmail API**

### 2.2 Crear credenciales OAuth
1. Ir a **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth client ID**
3. Si pide configurar pantalla de consentimiento:
   - User Type: **External**
   - App name: "COMEX Agent"
   - Agregar tu email como test user
4. Application type: **Desktop app**
5. Descargar el JSON
6. Guardarlo como `config/credentials.json`

### 2.3 Autenticarse
```bash
python setup_gmail.py
```
Se abrirá el navegador para autorizar. Esto genera `config/token.json`.

## Paso 3: Configurar el agente

Editar `config/config.yaml`:

```yaml
senders:
  proveedor: "topwillsteven@163.com"
  demanda: "felipe@unionx.cl"
  forwarder: "tu_forwarder@email.com"  # <-- AGREGAR
```

## Paso 4: Ejecutar

```bash
# Monitor continuo (polling cada 2 min)
python main.py

# Escaneo único
python main.py --scan

# Ver historial
python main.py --status
```

## Cómo funciona

```
Gmail                          Agente
  │                              │
  │  Email de topwillsteven      │
  │  con PI + PL adjuntos        │
  ├─────────────────────────────→│
  │                              │ Detecta: COMEX Workflow
  │                              │ Descarga PI + PL
  │                              │ Deduce puerto (SZ/NB/DHL)
  │  Email al forwarder          │
  │←─────────────────────────────│ Solicita tarifa de flete
  │                              │
  │                              │ Construye Tarifas_COMEX.xlsx
  │                              │ Ejecuta costeo
  │                              │
  │                              │ ⏸ PIDE VALIDACIÓN
  │                              │ → "¿Pre-costeo correcto?"
  │                              │
  │                              │ Si OK → Actualiza Maestra
  │                              │ → Genera email de análisis
  │                              │
  │  Email de topwillsteven      │
  │  con OHNSO adjunto           │
  ├─────────────────────────────→│
  │                              │ Detecta: OHNSO (guarda pendiente)
  │                              │
  │  Email de felipe@unionx      │
  │  "shipping plan JUL 26"      │
  ├─────────────────────────────→│
  │                              │ Detecta: Demanda
  │                              │ Combina OHNSO + Demanda
  │                              │ Ejecuta Shipping Plan
  │                              │
  │                              │ ⏸ PIDE VALIDACIÓN
  │                              │ → "¿Shipping Plan correcto?"
```
