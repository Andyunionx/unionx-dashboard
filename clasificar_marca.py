"""Clasificacion canonica de marca propia + normalizacion de estado_sku (IN/OUT).

Fuente de verdad de la regla de negocio (confirmada por Andres 15-jun-2026):
  MARCA PROPIA (13) = Lhotse, Simplit, Levo, Xroad, Dynamo (TL), Bandu, T-Care,
  UMA, Goya, ITEK, Bluecare, Klip Klap, Melollevo (incl. MelollevoMed).
  Todo el resto = "Otras marcas" (proveedores nacionales).

Antes tipo_marca se copiaba del campo "Estado marca" de la Matriz (In/Out),
que quedaba crudo en datos nuevos. Ahora se deriva de la MARCA, que es la
fuente confiable.
"""
import re
import unicodedata

# 14 marcas propias, normalizadas (lowercase, sin acentos, sin guiones ni espacios)
# Purito agregado 22-jul-2026 (OK Andrés): marca propia importada (pre-costeo CL04).
MARCAS_PROPIAS = {'lhotse', 'simplit', 'levo', 'xroad', 'dynamo', 'bandu', 'tcare',
                  'uma', 'goya', 'itek', 'bluecare', 'klipklap', 'melollevo', 'purito'}

# Nombre de despliegue por marca (para rellenar marca vacía inferida del nombre).
MARCA_DISPLAY = {
    'lhotse': 'Lhotse', 'simplit': 'Simplit', 'levo': 'Levo', 'xroad': 'Xroad',
    'dynamo': 'Dynamo', 'bandu': 'Bandu', 'tcare': 'T-Care', 'uma': 'UMA',
    'goya': 'Goya', 'itek': 'ITEK', 'bluecare': 'Bluecare', 'klipklap': 'Klip Klap',
    'melollevo': 'Melollevo', 'purito': 'Purito',
}

# Patrones (palabra completa) para detectar la marca dentro del nombre del producto.
_TOKEN_PATRONES = {
    'lhotse': r'lhotse', 'simplit': r'simplit', 'levo': r'levo', 'xroad': r'xroad',
    'dynamo': r'dynamo', 'bandu': r'bandu', 'tcare': r't[-\s]?care', 'uma': r'uma',
    'goya': r'goya', 'itek': r'itek', 'bluecare': r'blue\s?care',
    'klipklap': r'klip\s?klap', 'melollevo': r'melollevo', 'purito': r'purito',
}


def _norm(s) -> str:
    s = str(s).lower().strip().replace('-', '').replace(' ', '')
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def _norm_texto(s) -> str:
    """Como _norm pero conserva espacios/guiones (para búsqueda por palabra)."""
    s = str(s or '').lower()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def marca_desde_texto(texto) -> str:
    """Infiera la marca propia desde el nombre del producto (match por palabra
    completa). Devuelve el nombre de despliegue o '' si no hay match. Pensado para
    rellenar SOLO marca vacía — así no dependemos de que la Matriz esté al día."""
    t = _norm_texto(texto)
    if not t:
        return ''
    for key, pat in _TOKEN_PATRONES.items():
        if re.search(r'\b' + pat + r'\b', t):
            return MARCA_DISPLAY[key]
    return ''


def es_marca_propia(marca) -> bool:
    """True si la marca pertenece a las 13 marcas propias. Tolera variantes
    de capitalizacion/acento y sufijos cortos (ej. 'Dynamo TL', 'MelollevoMed')."""
    nm = _norm(marca)
    if not nm or nm in ('0', 'nan', 'none'):
        return False
    for p in MARCAS_PROPIAS:
        if nm == p or nm.startswith(p + ' ') or (nm.startswith(p) and len(nm) <= len(p) + 4):
            return True
    return False


def clasificar_tipo_marca(marca) -> str:
    """Devuelve 'Propia' u 'Otras marcas' segun la marca."""
    return 'Propia' if es_marca_propia(marca) else 'Otras marcas'


def normalizar_estado_sku(valor) -> str:
    """Normaliza estado_sku (IN/OUT del catalogo) a minuscula limpia.
    'In'/'IN'->'in', 'Out'->'out'. Valores espurios (0,1,vacio) -> ''."""
    v = str(valor).strip().lower()
    if v in ('in', 'out'):
        return v
    return ''
