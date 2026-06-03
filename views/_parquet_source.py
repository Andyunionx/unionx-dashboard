"""
Opción C reutilizable: leer parquet desde GitHub Raw (URL) si PARQUET_BASE_URL
está seteado (env o st.secrets), con fallback al archivo local del checkout.

Por qué: si la app lee solo el parquet local del checkout, queda "pegada" en el
dato hasta que Streamlit redespliegue (poco confiable). Leyendo desde GitHub Raw
con el cache TTL de cada loader, la app refresca sin depender del redeploy.
"""
import os
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent


def parquet_base_url() -> str:
    """URL base (GitHub Raw) si está configurada, vía env o st.secrets. '' si no."""
    v = os.environ.get('PARQUET_BASE_URL', '')
    if not v:
        try:
            v = str(st.secrets.get('PARQUET_BASE_URL', '') or '')
        except Exception:
            v = ''
    return v.rstrip('/')


def read_parquet_smart(local_path) -> pd.DataFrame:
    """Lee un parquet desde la URL (si PARQUET_BASE_URL) o local. Fallback a local
    si la URL falla. Devuelve DataFrame vacío si no existe en ningún lado."""
    local_path = Path(local_path)
    base = parquet_base_url()
    if base:
        try:
            rel = local_path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
            return pd.read_parquet(f"{base}/{rel}")
        except Exception:
            pass  # cae a local
    if not local_path.exists():
        return pd.DataFrame()
    return pd.read_parquet(local_path)
