"""views/planning/descarga_reporte.py
Página de descarga del reporte mensual de planificación.
"""
from pathlib import Path
import streamlit as st

_PLANIF_DIR = Path(__file__).parent.parent.parent / 'data' / 'planificacion'


def render():
    st.title("📁 Descarga Reporte Planificación")
    st.caption("Reporte Excel mensual de análisis de planificación.")

    excels = sorted(_PLANIF_DIR.glob('analisis_planificacion_*.xlsx'), reverse=True)

    if not excels:
        st.warning("No hay reportes disponibles en `data/planificacion/`.")
        return

    for f in excels:
        label = f.stem.replace('analisis_planificacion_', '').upper()
        with open(f, 'rb') as fh:
            st.download_button(
                f"⬇️ Análisis Planificación {label}",
                data=fh.read(),
                file_name=f.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
