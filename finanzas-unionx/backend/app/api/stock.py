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
from app.config import Config

stock_bp = Blueprint('stock', __name__)

# Cache global para datos de stock
_cached_stock_data = {}


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
