"""
Clase base para servicios de extracción Odoo.
Cada nuevo dominio (COMEX, EERR, etc.) hereda de esta clase.
"""
from abc import ABC, abstractmethod
from typing import Dict, Callable, Optional
from app.core.odoo_client import OdooClient


class BaseOdooService(ABC):
    """
    Clase base abstracta para servicios que extraen datos de Odoo.

    Todos los servicios deben implementar:
    - extract(): Extrae datos de Odoo
    - apply_filters(): Aplica filtros en memoria

    Esto permite que el JobManager funcione con cualquier servicio sin cambios.
    """

    def __init__(self, odoo_client: OdooClient):
        self.odoo = odoo_client

    @abstractmethod
    def extract(self, **kwargs) -> Dict:
        """
        Extrae datos de Odoo.

        Puede ser lento (30-90 segundos). Se ejecuta en un Thread.

        Args:
            **kwargs: Parámetros específicos del servicio
                    (para ventas: periodo_inicio, periodo_fin)

        Returns:
            Dict con los datos extraídos y resumidos.
            Estructura esperada:
            {
                'data': DataFrame,
                'resumenes': {
                    'canal': DataFrame,
                    'linea': DataFrame,
                    'categoria': DataFrame,
                    'bodega': DataFrame
                },
                'metadata': {
                    'total_ordenes': int,
                    'total_lineas': int,
                    'periodo': str
                }
            }
        """
        pass

    @abstractmethod
    def apply_filters(self, data: Dict, **kwargs) -> Dict:
        """
        Aplica filtros en memoria sin re-query a Odoo.

        Debe ser rápido (< 200ms).

        Args:
            data: Data dict retornado por extract()
            **kwargs: Parámetros de filtro (canal=, categoria=, bodega=)

        Returns:
            Data dict con datos filtrados y KPIs recalculados
        """
        pass

    def _progress_callback(self, progress: int, label: str, callback: Optional[Callable] = None):
        """
        Helper para actualizar progreso. Override en subclases si es necesario.
        """
        if callback:
            callback(progress, label)
