"""Normalización canónica de nombres de canal.

Reglas únicas para todos los scripts de carga (Drive→Turso, sync Odoo,
auditorías). Mantenida en sync con ventas_service.py CANAL_CANONICO.

Casos cubiertos:
  - Capitalización: 'Sp Digital' → 'SP Digital'
  - Variantes Chile: 'Mercado Libre Chile' → 'Mercado Libre'
  - Aliases: 'sawa', 'SAWA' → 'Sawa'

Uso:
    from _canal_normalize import normalizar_canal
    canal_clean = normalizar_canal('Sp Digital')  # → 'SP Digital'
"""
from __future__ import annotations

import pandas as pd


CANAL_CANONICO = {
    'sp digital': 'SP Digital',
    'exporunning': 'ExpoRunning',
    'sawa': 'Sawa',
    'mercado libre chile': 'Mercado Libre',
    'el volcan': 'El Volcán',
    'el volcán': 'El Volcán',
    'union x b2b': 'UnionX B2B',
    'unionxb2b': 'UnionX B2B',
    'union x web': 'UnionX web',
    'unionxweb': 'UnionX web',
}


def normalizar_canal(canal) -> str:
    """Devuelve el nombre canónico del canal. Idempotente.

    Si el canal no está en la tabla, lo devuelve trimmed sin más cambios.
    """
    if canal is None:
        return ''
    s = str(canal).strip()
    key = s.lower()
    return CANAL_CANONICO.get(key, s)


def normalizar_columna_canal(df: pd.DataFrame, col: str = 'canal') -> pd.DataFrame:
    """Aplica `normalizar_canal` a una columna del DataFrame (in-place)."""
    if col not in df.columns:
        return df
    df[col] = df[col].astype(str).apply(normalizar_canal)
    return df
