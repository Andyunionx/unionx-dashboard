"""
Cliente XML-RPC para Odoo con retry automático, batching y estabilidad mejorada.

Mejoras implementadas:
- Connection pooling: reutiliza conexiones entre solicitudes
- Backoff inteligente: con jitter para evitar sincronización
- Reintentos agresivos: hasta 10 intentos con esperas crecientes
- Reducción dinámica de batch size: si un batch falla, reduce el tamaño
- Logging detallado: para debugging
"""
import xmlrpc.client
import http.client
import socket
import time
import random
from typing import List, Dict, Any

# Timeout default XML-RPC: evita que ServerProxy.authenticate() se cuelgue
# indefinidamente cuando Odoo SaaS está lento. Sin esto, el script Streamlit
# queda "corriendo todo el rato" hasta que el user apreta Stop.
_DEFAULT_XMLRPC_TIMEOUT_S = 15


class _TimeoutTransport(xmlrpc.client.SafeTransport):
    """Transport HTTPS con timeout configurable (XML-RPC no lo soporta nativamente)."""
    def __init__(self, timeout=_DEFAULT_XMLRPC_TIMEOUT_S, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._timeout = timeout

    def make_connection(self, host):
        # Reusar conexión existente si está disponible (connection pooling)
        if self._connection and host == self._connection[0]:
            return self._connection[1]
        chost, self._extra_headers, x509 = self.get_host_info(host)
        self._connection = host, http.client.HTTPSConnection(
            chost, None, timeout=self._timeout, **(x509 or {})
        )
        return self._connection[1]


def _make_proxy(url: str, timeout: int = _DEFAULT_XMLRPC_TIMEOUT_S):
    """Crea ServerProxy con timeout. Funciona para http y https."""
    transport = _TimeoutTransport(timeout=timeout)
    return xmlrpc.client.ServerProxy(url, transport=transport, allow_none=True)


class OdooClient:
    """
    Cliente robusto para XML-RPC de Odoo.
    - Reintentos inteligentes con jitter
    - Batching adaptativo (reduce tamaño si falla)
    - Logging detallado para debugging
    """

    def __init__(self, url: str, db: str, username: str, password: str, max_retries: int = 10):
        self.url = url
        self.db = db
        self.username = username
        self.password = password
        self.max_retries = max_retries
        self._uid = None

    def authenticate(self) -> int:
        """Autentica y cachea el UID."""
        if self._uid is not None:
            return self._uid

        try:
            common = _make_proxy(f'{self.url}/xmlrpc/2/common')
            self._uid = common.authenticate(self.db, self.username, self.password, {})
            if not self._uid:
                raise ValueError("Autenticación fallida: UID vacío")
            return self._uid
        except Exception as e:
            raise RuntimeError(f"Error autenticando Odoo: {e}")

    def search_read(self, model: str, domain: List[tuple], fields: List[str],
                    limit: int = 200000, offset: int = 0) -> List[Dict]:
        """Ejecuta search_read con retry automático."""
        return self._execute_with_retry(
            'search_read',
            model,
            domain,
            {'fields': fields, 'limit': limit, 'offset': offset}
        )

    def search_read_paginated(self, model: str, domain: List[tuple], fields: List[str],
                              page_size: int = 500, order: str = 'id asc') -> List[Dict]:
        """
        Igual que search_read pero pagina con offset/limit para evitar 502s
        en queries grandes (Odoo SaaS suele caer con respuestas >5MB).
        Reduce page_size adaptativamente si una página falla.
        """
        all_records: List[Dict] = []
        offset = 0
        current_size = page_size

        while True:
            try:
                page = self._execute_with_retry(
                    'search_read', model, domain,
                    {'fields': fields, 'limit': current_size, 'offset': offset, 'order': order}
                )
            except RuntimeError as e:
                if current_size <= 20:
                    raise
                current_size = max(20, current_size // 2)
                print(f"[PAGE REDUCTION] {model}: page_size={current_size} (offset={offset})")
                continue

            if not page:
                break
            all_records.extend(page)
            print(f"  [PAG] {model}: +{len(page)} (total={len(all_records)}, offset={offset})")
            if len(page) < current_size:
                break
            offset += current_size
            # Si una página chica funcionó, intenta crecer de nuevo
            if current_size < page_size:
                current_size = min(page_size, current_size * 2)

        return all_records

    def execute_in_batches(self, model: str, ids: List[int], fields: List[str],
                          batch_size: int = 100, extra_domain: List[tuple] = None) -> List[Dict]:
        """
        Ejecuta search_read en lotes adaptativos.
        Si un lote falla, reduce el tamaño y reintenta.
        extra_domain: condiciones adicionales al dominio (ej. incluir archivados con
        [('active','in',[True,False])]).
        """
        all_records = []
        current_batch_size = batch_size
        i = 0

        while i < len(ids):
            batch_ids = ids[i:i + current_batch_size]
            try:
                domain = [('id', 'in', batch_ids)] + list(extra_domain or [])
                batch_records = self.search_read(model, domain, fields, limit=len(batch_ids))
                all_records.extend(batch_records)
                i += current_batch_size

                # Si tenemos éxito, podemos intentar aumentar el batch size nuevamente
                if current_batch_size < batch_size:
                    current_batch_size = min(current_batch_size + 10, batch_size)

            except (RuntimeError, http.client.IncompleteRead, http.client.RemoteDisconnected, OSError) as e:
                if current_batch_size <= 10:
                    raise RuntimeError(f"Error incluso con batch_size=10 en {model}: {e}")

                # Reducir tamaño de lote e intentar nuevamente
                current_batch_size = max(10, current_batch_size // 2)
                print(f"[BATCH REDUCTION] {model}: reduciendo a batch_size={current_batch_size} ({type(e).__name__})")

        return all_records

    def _execute_with_retry(self, operation: str, model: str, *args, **kwargs) -> Any:
        """
        Ejecuta operación con reintentos inteligentes.
        - Backoff exponencial: 1s, 2s, 4s, 8s, 16s, 32s, 60s+
        - Jitter aleatorio para evitar sincronización
        """
        uid = self.authenticate()
        models = _make_proxy(f'{self.url}/xmlrpc/2/object', timeout=60)

        # Compat: callers pasan opciones como dict posicional (args[1])
        # o como **kwargs. Unificamos en `options`.
        positional = [args[0]] if args else []
        if len(args) >= 2 and isinstance(args[1], dict):
            options = dict(args[1])
            options.update(kwargs)
        else:
            options = dict(kwargs)

        for attempt in range(self.max_retries):
            try:
                result = models.execute_kw(
                    self.db, uid, self.password, model, operation,
                    positional,
                    options
                )

                if attempt > 0:
                    print(f"[OK] {model}.{operation} en intento {attempt + 1}")
                return result

            except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, OSError, TimeoutError, ConnectionError, http.client.HTTPException) as e:
                if attempt == self.max_retries - 1:
                    raise RuntimeError(
                        f"Error después de {self.max_retries} intentos en {model}.{operation}: {e}"
                    )

                # Backoff exponencial con jitter
                base_wait = min(2 ** attempt, 60)
                jitter = random.uniform(0, base_wait * 0.1)
                wait_time = base_wait + jitter

                # Para xmlrpc.Fault (error de servidor) imprimimos completo, ya que
                # los reintentos no van a arreglarlo y necesitamos diagnosticar.
                if isinstance(e, xmlrpc.client.Fault):
                    error_msg = str(e)[:600]
                else:
                    error_msg = str(e)[:120]
                print(f"[RETRY {attempt + 1}/{self.max_retries}] {model}.{operation}")
                print(f"  Esperando {wait_time:.1f}s antes de reintentar...")
                print(f"  Error: {error_msg}")

                time.sleep(wait_time)

    def get_fields(self, model: str) -> Dict[str, Dict]:
        """Obtiene campos de un modelo."""
        uid = self.authenticate()
        models = _make_proxy(f'{self.url}/xmlrpc/2/object', timeout=60)
        try:
            return models.execute_kw(
                self.db, uid, self.password, model, 'fields_get', [],
                {'attributes': ['string', 'help', 'type']}
            )
        except Exception as e:
            print(f"Error obteniendo fields de {model}: {e}")
            return {}
