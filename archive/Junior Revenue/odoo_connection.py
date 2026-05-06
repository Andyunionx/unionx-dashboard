"""
Conexión a Odoo Producción y Test
Soporte para Andrés Browne - Union X
Usa XML-RPC (protocolo nativo de Odoo)
"""

import xmlrpc.client
import json
from typing import Dict, List, Any, Optional


class OdooConnection:
    """Cliente para conectar a servidores Odoo via XML-RPC"""

    def __init__(self, url: str, username: str, password: str, db_name: str):
        """
        Inicializa conexión a Odoo

        Args:
            url: URL base del servidor Odoo (ej: https://unionxb2b.odoo.com)
            username: Email del usuario (ej: andres@unionx.cl)
            password: Contraseña
            db_name: Nombre de la base de datos (OBLIGATORIO)
        """
        self.url = url.rstrip('/')
        self.username = username
        self.password = password
        self.db_name = db_name
        self.uid = None

        # XML-RPC endpoints
        self.common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def login(self) -> bool:
        """Autentica el usuario y obtiene el UID"""
        try:
            self.uid = self.common.authenticate(
                self.db_name,
                self.username,
                self.password,
                {}
            )

            if self.uid:
                print(f"[OK] Autenticacion exitosa - UID: {self.uid}")
                return True
            else:
                print("[ERROR] Autenticacion fallida - UID no obtenido")
                return False

        except Exception as e:
            print(f"[ERROR] Error de conexion: {e}")
            return False

    def call_kw(self, model: str, method: str, args: List = None, kwargs: Dict = None) -> Any:
        """
        Llama a un método Odoo usando XML-RPC

        Args:
            model: Nombre del modelo (ej: 'sale.order')
            method: Nombre del método (ej: 'search_read')
            args: Argumentos posicionales
            kwargs: Argumentos con nombre

        Returns:
            Resultado de la llamada
        """
        if not self.uid:
            print("[ERROR] No autenticado. Ejecuta login() primero")
            return None

        args = args or []
        kwargs = kwargs or {}

        try:
            result = self.models.execute_kw(
                self.db_name,
                self.uid,
                self.password,
                model,
                method,
                args,
                kwargs
            )
            return result

        except Exception as e:
            print(f"[ERROR] Error en llamada a {model}.{method}: {e}")
            return None

    def search(self, model: str, domain: List = None, limit: int = None) -> List[int]:
        """
        Busca registros en un modelo

        Args:
            model: Nombre del modelo
            domain: Filtros [[field, operator, value], ...]
            limit: Límite de resultados

        Returns:
            Lista de IDs encontrados
        """
        domain = domain or []
        kwargs = {}
        if limit:
            kwargs["limit"] = limit

        return self.call_kw(model, "search", [domain], kwargs) or []

    def read(self, model: str, ids: List[int], fields: List[str] = None) -> List[Dict]:
        """
        Lee registros específicos

        Args:
            model: Nombre del modelo
            ids: Lista de IDs
            fields: Campos a leer (None = todos)

        Returns:
            Lista de diccionarios con los datos
        """
        kwargs = {}
        if fields:
            kwargs["fields"] = fields

        return self.call_kw(model, "read", [ids], kwargs) or []

    def create(self, model: str, values: Dict) -> Optional[int]:
        """Crea un nuevo registro"""
        return self.call_kw(model, "create", [values])

    def write(self, model: str, ids: List[int], values: Dict) -> bool:
        """Actualiza registros existentes"""
        return self.call_kw(model, "write", [ids, values])

    def search_read(self, model: str, domain: List = None, fields: List[str] = None, limit: int = None) -> List[Dict]:
        """
        Busca y lee registros en una sola llamada (más eficiente)

        Args:
            model: Nombre del modelo
            domain: Filtros [[field, operator, value], ...]
            fields: Campos a leer
            limit: Límite de resultados

        Returns:
            Lista de diccionarios con los datos
        """
        domain = domain or []
        kwargs = {}
        if fields:
            kwargs["fields"] = fields
        if limit:
            kwargs["limit"] = limit

        return self.call_kw(model, "search_read", [domain], kwargs) or []


# ============================================================================
# EJEMPLO DE USO
# ============================================================================

if __name__ == "__main__":

    # Conexión a PRODUCCIÓN
    print("=" * 60)
    print("CONECTANDO A ODOO PRODUCCIÓN")
    print("=" * 60)

    odoo_prod = OdooConnection(
        url="https://unionxb2b.odoo.com",
        username="andres@grupoeter.cl",
        password="ROTATED-2026-05-07",
        db_name="union-xb2b"
    )

    if odoo_prod.login():
        print("\n[OK] Conexion a produccion exitosa\n")

        # Ejemplo: Buscar últimas 5 órdenes de venta
        try:
            orders = odoo_prod.search_read(
                "sale.order",
                domain=[],
                fields=["name", "partner_id", "amount_total", "state"],
                limit=5
            )
            if orders:
                print("Ultimas ordenes encontradas:")
                for order in orders:
                    print(f"  - {order['name']}: {order['amount_total']} ({order['state']})")
        except Exception as e:
            print(f"No se pudo leer ordenes: {e}")

    # Conexión a TEST
    print("\n" + "=" * 60)
    print("CONECTANDO A ODOO TEST")
    print("=" * 60)

    odoo_test = OdooConnection(
        url="https://test3-melollevo.odoo.com",
        username="andres@grupoeter.cl",
        password="ROTATED-2026-05-07",
        db_name="test3-melollevo"
    )

    if odoo_test.login():
        print("\n[OK] Conexion a test exitosa\n")
