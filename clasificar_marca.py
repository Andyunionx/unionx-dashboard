"""Clasificacion canonica de marca propia + normalizacion de estado_sku (IN/OUT).

Fuente de verdad de la regla de negocio (confirmada por Andres 15-jun-2026):
  MARCA PROPIA (13) = Lhotse, Simplit, Levo, Xroad, Dynamo (TL), Bandu, T-Care,
  UMA, Goya, ITEK, Bluecare, Klip Klap, Melollevo (incl. MelollevoMed).
  Todo el resto = "Otras marcas" (proveedores nacionales).

Antes tipo_marca se copiaba del campo "Estado marca" de la Matriz (In/Out),
que quedaba crudo en datos nuevos. Ahora se deriva de la MARCA, que es la
fuente confiable.
"""
import unicodedata

# 13 marcas propias, normalizadas (lowercase, sin acentos, sin guiones ni espacios)
MARCAS_PROPIAS = {'lhotse', 'simplit', 'levo', 'xroad', 'dynamo', 'bandu', 'tcare',
                  'uma', 'goya', 'itek', 'bluecare', 'klipklap', 'melollevo'}


def _norm(s) -> str:
    s = str(s).lower().strip().replace('-', '').replace(' ', '')
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


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
