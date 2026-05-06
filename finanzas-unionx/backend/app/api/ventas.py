"""
Endpoints del dashboard de ventas
"""
import threading
import uuid
from flask import Blueprint, request, jsonify, send_file
from flask_caching import Cache

from app.core.odoo_client import OdooClient
from app.core.job_manager import job_manager
from app.core.excel_builder import ExcelBuilder
from app.services.ventas_service import VentasService
from app.extensions import cache
from app.config import Config

ventas_bp = Blueprint('ventas', __name__)

# Cache global para datos (se llena con cada extracción exitosa)
_cached_data = {}


@ventas_bp.route('/refresh', methods=['POST'])
def refresh_ventas():
    """
    POST /api/ventas/refresh
    Lanza un job de extracción de Odoo.

    Body:
    {
      "periodo_inicio": "2026-04-01 00:00:00",
      "periodo_fin": "2026-04-30 23:59:59"
    }

    Response:
    {
      "job_id": "ventas_2026-04_abc123abc",
      "message": "Job iniciado"
    }
    Status: 202 Accepted
    """
    data = request.get_json() or {}
    periodo_inicio = data.get('periodo_inicio', '2026-04-01 00:00:00')
    periodo_fin = data.get('periodo_fin', '2026-04-30 23:59:59')

    # Generar job_id único
    job_id = f"ventas_{periodo_inicio[:7].replace('-', '')}_{ uuid.uuid4().hex[:8]}"

    # Crear job en estado PENDING
    job_manager.create_job(job_id)
    job_manager.start_job(job_id)

    # Lanzar extracción en background thread
    def run_extraction():
        try:
            # Crear clientes y servicios
            odoo = OdooClient(
                url=Config.ODOO_URL,
                db=Config.ODOO_DB,
                username=Config.ODOO_USER,
                password=Config.ODOO_PASSWORD
            )

            service = VentasService(odoo, Config.PLANILLAS_DIR)

            # Callback de progreso
            def progress_cb(pct, label):
                job_manager.update_progress(job_id, pct, label)

            # Extrae datos
            data = service.extract(
                periodo_inicio,
                periodo_fin,
                progress_callback=progress_cb
            )

            # Guarda en cache global
            _cached_data[job_id] = data

            # Marca job como DONE
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
        'message': 'Job iniciado. Usa GET /api/jobs/{job_id} para monitorear progreso.'
    }), 202


@ventas_bp.route('/data', methods=['GET'])
def get_ventas_data():
    """
    GET /api/ventas/data?periodo_inicio=...&periodo_fin=...&canal=...&categoria=...&bodega=...

    Retorna KPIs + 4 resúmenes (no el detalle de 10,000 líneas).
    Los datos deben haberse extraído antes con POST /refresh.

    Response:
    {
      "meta": { ... },
      "kpis": { ... },
      "resumenes": { ... },
      "filtros_disponibles": { ... }
    }
    """
    # Obtener parámetros de filtro
    canal = request.args.get('canal')
    categoria = request.args.get('categoria')
    bodega = request.args.get('bodega')

    # Buscar datos en cache
    if not _cached_data:
        return jsonify({'error': 'No hay datos extraídos. Usa POST /api/ventas/refresh primero'}), 400

    # Usar el último dataset extraído
    data = list(_cached_data.values())[-1]

    # Aplicar filtros
    try:
        odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)
        service = VentasService(odoo, Config.PLANILLAS_DIR)
        filtered_data = service.apply_filters(data, canal=canal, categoria=categoria, bodega=bodega)
    except Exception as e:
        return jsonify({'error': f'Error aplicando filtros: {str(e)}'}), 500

    # Construir respuesta
    meta = filtered_data.get('metadata', {})
    meta['periodo'] = f"{meta.get('periodo_inicio', '').split(' ')[0]} / {meta.get('periodo_fin', '').split(' ')[0]}"

    resumenes = filtered_data.get('resumenes', {})

    return jsonify({
        'meta': meta,
        'kpis': filtered_data.get('kpis', {}),
        'resumenes': {
            'linea': resumenes.get('linea', pd.DataFrame()).to_dict('records'),
            'canal': resumenes.get('canal', pd.DataFrame()).to_dict('records'),
            'categoria': resumenes.get('categoria', pd.DataFrame()).to_dict('records'),
            'bodega': resumenes.get('bodega', pd.DataFrame()).to_dict('records'),
        },
        'filtros_disponibles': _get_filtros_disponibles(filtered_data['data'])
    }), 200


@ventas_bp.route('/export-excel', methods=['GET'])
def export_excel():
    """
    GET /api/ventas/export-excel?canal=...&categoria=...&bodega=...

    Descarga un Excel con 5 hojas (Ventas + 4 resúmenes).
    Usa los datos cacheados, aplica filtros y genera el Excel.

    Response: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    """
    canal = request.args.get('canal')
    categoria = request.args.get('categoria')
    bodega = request.args.get('bodega')

    # Obtener datos cacheados
    if not _cached_data:
        return jsonify({'error': 'No hay datos extraídos. Usa POST /api/ventas/refresh primero'}), 400

    data = list(_cached_data.values())[-1]

    # Aplicar filtros
    try:
        odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)
        service = VentasService(odoo, Config.PLANILLAS_DIR)
        filtered_data = service.apply_filters(data, canal=canal, categoria=categoria, bodega=bodega)
    except Exception as e:
        return jsonify({'error': f'Error aplicando filtros: {str(e)}'}), 500

    # Construir Excel
    try:
        df_ventas = filtered_data['data']
        resumenes = filtered_data['resumenes']

        excel_bytes = ExcelBuilder.build(
            df_ventas,
            resumenes.get('linea'),
            resumenes.get('canal'),
            resumenes.get('categoria'),
            resumenes.get('bodega'),
            data['metadata'].get('periodo_nombre', 'reporte')
        )

        # Enviar como descarga
        periodo_nombre = data['metadata'].get('periodo_nombre', 'reporte')
        filename = f"reporte_ventas_{periodo_nombre}.xlsx"

        return send_file(
            excel_bytes,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        return jsonify({'error': f'Error generando Excel: {str(e)}'}), 500


@ventas_bp.route('/filtros', methods=['GET'])
def get_filtros_disponibles():
    """
    GET /api/ventas/filtros

    Retorna las opciones disponibles para filtros:
    - Canales
    - Categorías
    - Bodegas

    Útil para llenar dropdowns en el frontend.

    Response:
    {
      "canales": ["Mercado Libre", "Falabella", ...],
      "categorias": ["Electrohogar", "Tecnología", ...],
      "bodegas": ["Fulfillment", "Warehouse Unionx"]
    }
    """
    if not _cached_data:
        return jsonify({'error': 'No hay datos extraídos. Usa POST /api/ventas/refresh primero'}), 400

    data = list(_cached_data.values())[-1]
    return jsonify(_get_filtros_disponibles(data['data'])), 200


def _get_filtros_disponibles(df) -> dict:
    """Helper: extrae listas de opciones únicas para filtros"""
    return {
        'canales': sorted(df['Canal'].dropna().unique().tolist()),
        'categorias': sorted(df['Categoría macro'].dropna().unique().tolist()),
        'bodegas': sorted(df['Bodega Origen'].dropna().unique().tolist()),
    }


# Importar pandas al final para evitar circular imports
import pandas as pd
