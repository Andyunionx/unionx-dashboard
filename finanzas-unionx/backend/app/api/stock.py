"""
Endpoints del dashboard de stock
"""
import threading
import uuid
from flask import Blueprint, request, jsonify
import pandas as pd

from app.core.odoo_client import OdooClient
from app.core.job_manager import job_manager
from app.services.stock_service import StockService
from app.services.stock_advanced_service import StockAdvancedService
from app.config import Config

stock_bp = Blueprint('stock', __name__)

# Cache global para datos de stock
_cached_stock_data = {}
# Cache especifico para extract_full (semaforo + ocupacion + rotacion)
_cached_advanced_data = {}


@stock_bp.route('/refresh', methods=['POST'])
def refresh_stock():
    """
    POST /api/stock/refresh
    Lanza un job de extracción de stock
    """
    job_id = f"stock_{uuid.uuid4().hex[:8]}"

    job_manager.create_job(job_id)
    job_manager.start_job(job_id)

    def run_extraction():
        try:
            odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)
            service = StockService(odoo, Config.PLANILLAS_DIR)

            def progress_cb(pct, label):
                job_manager.update_progress(job_id, pct, label)

            data = service.extract(progress_callback=progress_cb)
            _cached_stock_data[job_id] = data

            job_manager.mark_done(job_id)
            print(f"[SUCCESS] Job {job_id} completado")

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            job_manager.mark_error(job_id, error_msg)
            print(f"[ERROR] Job {job_id}: {error_msg}")

    thread = threading.Thread(target=run_extraction, daemon=True)
    thread.start()

    return jsonify({
        'job_id': job_id,
        'message': 'Job de stock iniciado'
    }), 202


@stock_bp.route('/data', methods=['GET'])
def get_stock_data():
    """
    GET /api/stock/data?bodega=...&categoria=...
    Retorna datos de stock filtrados
    """
    bodega = request.args.get('bodega')
    categoria = request.args.get('categoria')

    if not _cached_stock_data:
        return jsonify({'error': 'No hay datos extraídos. Usa POST /api/stock/refresh primero'}), 400

    data = list(_cached_stock_data.values())[-1]

    try:
        odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)
        service = StockService(odoo, Config.PLANILLAS_DIR)
        filtered_data = service.apply_filters(data, bodega=bodega, categoria=categoria)
    except Exception as e:
        return jsonify({'error': f'Error aplicando filtros: {str(e)}'}), 500

    df = filtered_data['data']
    resumenes = filtered_data['resumenes']

    return jsonify({
        'kpis': {
            'stock_total': int(df['Stock Disponible'].sum()),
            'valor_total': float(df['Valor Total'].sum()),
            'productos_activos': len(df),
            'stock_reservado': int(df['Stock Reservado'].sum()),
        },
        'resumenes': {
            'bodega': resumenes.get('bodega', pd.DataFrame()).to_dict('records'),
            'categoria': resumenes.get('categoria', pd.DataFrame()).to_dict('records'),
        },
        'filtros_disponibles': {
            'bodegas': sorted(df['Bodega'].dropna().unique().tolist()),
            'categorias': sorted(df['Categoría'].dropna().unique().tolist()),
        }
    }), 200


@stock_bp.route('/productos', methods=['GET'])
def get_productos_stock():
    """
    GET /api/stock/productos?bodega=...
    Retorna lista de productos con stock
    """
    bodega = request.args.get('bodega')

    if not _cached_stock_data:
        return jsonify({'error': 'No hay datos. Usa POST /api/stock/refresh primero'}), 400

    data = list(_cached_stock_data.values())[-1]
    df = data['data']

    if bodega:
        df = df[df['Bodega'] == bodega]

    # Top 20 productos por valor
    top_productos = df.nlargest(20, 'Valor Total')[['SKU', 'Producto', 'Stock Disponible', 'Valor Total', 'Bodega']]

    return jsonify({
        'productos': top_productos.to_dict('records')
    }), 200


# ============================================================================
# ENDPOINTS AVANZADOS (semaforo + ocupacion + rotacion)
# ============================================================================
@stock_bp.route('/advanced/refresh', methods=['POST'])
def refresh_stock_advanced():
    """
    POST /api/stock/advanced/refresh
    Lanza extraccion completa: stock + ventas 30d/90d + ocupacion CA1/Stock + semaforo
    """
    job_id = f"stock_adv_{uuid.uuid4().hex[:8]}"
    job_manager.create_job(job_id)
    job_manager.start_job(job_id)

    def run():
        try:
            odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)
            service = StockAdvancedService(odoo)

            def progress_cb(pct, label):
                job_manager.update_progress(job_id, pct, label)

            data = service.extract_full(progress_callback=progress_cb)
            _cached_advanced_data[job_id] = data
            # mantener solo ultimo
            for old in list(_cached_advanced_data.keys()):
                if old != job_id:
                    _cached_advanced_data.pop(old, None)

            job_manager.mark_done(job_id)
            print(f"[SUCCESS] Job advanced {job_id} completado")
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)}"
            job_manager.mark_error(job_id, err)
            print(f"[ERROR] Job advanced {job_id}: {err}")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    return jsonify({"job_id": job_id, "message": "Stock avanzado iniciado"}), 202


@stock_bp.route('/advanced/data', methods=['GET'])
def get_stock_advanced():
    """
    GET /api/stock/advanced/data?semaforo=&bodega=&categoria=&tipo=
    Retorna KPIs avanzados, ocupacion, semaforo, valor por bodega y SKUs filtrados.
    """
    if not _cached_advanced_data:
        return jsonify({"error": "Sin datos. POST /api/stock/advanced/refresh primero"}), 400

    data = list(_cached_advanced_data.values())[-1]

    # Filtros opcionales
    semaforo_f = request.args.get("semaforo")
    bodega_f = request.args.get("bodega")
    categoria_f = request.args.get("categoria")
    tipo_f = request.args.get("tipo")
    limit = int(request.args.get("limit", "200"))

    skus = data.get("skus", [])
    if semaforo_f:
        skus = [s for s in skus if s.get("Semaforo") == semaforo_f]
    if bodega_f:
        skus = [s for s in skus if bodega_f in (s.get("Bodega") or "")]
    if categoria_f:
        skus = [s for s in skus if s.get("Categoria") == categoria_f]

    # Filtros tipo se aplican sobre detalle, no sobre agregado por SKU
    detalle = data.get("detalle", [])
    if tipo_f:
        detalle = [d for d in detalle if d.get("Tipo") == tipo_f]

    return jsonify({
        "metadata": data.get("metadata"),
        "kpis": data.get("kpis"),
        "ocupacion": data.get("ocupacion"),
        "semaforo": data.get("semaforo"),
        "valor_bodega": data.get("valor_bodega"),
        "skus": skus[:limit],
        "skus_total_count": len(skus),
        "filtros_disponibles": {
            "semaforos": sorted({s.get("Semaforo") for s in data.get("skus", []) if s.get("Semaforo")}),
            "bodegas": sorted({s.get("Bodega") for s in data.get("skus", []) if s.get("Bodega")}),
            "categorias": sorted({s.get("Categoria") for s in data.get("skus", []) if s.get("Categoria")}),
            "tipos": sorted({d.get("Tipo") for d in data.get("detalle", []) if d.get("Tipo")}),
        }
    }), 200


@stock_bp.route('/advanced/ocupacion', methods=['GET'])
def get_ocupacion():
    """GET /api/stock/advanced/ocupacion - Solo datos de ocupacion CA1/Stock."""
    if not _cached_advanced_data:
        return jsonify({"error": "Sin datos. POST /api/stock/advanced/refresh primero"}), 400
    data = list(_cached_advanced_data.values())[-1]
    return jsonify(data.get("ocupacion", {})), 200


@stock_bp.route('/advanced/semaforo', methods=['GET'])
def get_semaforo():
    """GET /api/stock/advanced/semaforo - Solo distribucion semaforo + KPIs categoricos."""
    if not _cached_advanced_data:
        return jsonify({"error": "Sin datos. POST /api/stock/advanced/refresh primero"}), 400
    data = list(_cached_advanced_data.values())[-1]
    return jsonify({
        "kpis": data.get("kpis"),
        "distribucion": data.get("semaforo"),
    }), 200
