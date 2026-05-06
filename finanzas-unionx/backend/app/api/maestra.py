"""
Endpoints de la Maestra de Ventas (SQLite)
"""
import io
from flask import Blueprint, request, jsonify, send_file
from app.config import Config
from app.services.maestra_service import MaestraService

maestra_bp = Blueprint('maestra', __name__)


def _get_service():
    return MaestraService(Config.MAESTRA_DB_PATH)


def _get_params():
    return {
        'fecha_desde': request.args.get('fecha_desde'),
        'fecha_hasta': request.args.get('fecha_hasta'),
        'canal': request.args.get('canal'),
        'marca': request.args.get('marca'),
        'categoria': request.args.get('categoria'),
        'tipo_negocio': request.args.get('tipo_negocio'),
        'kam': request.args.get('kam'),
        'bodega': request.args.get('bodega'),
    }


@maestra_bp.route('/data', methods=['GET'])
def get_data():
    """
    GET /api/maestra/data
    Retorna KPIs + resúmenes para los filtros aplicados.
    """
    try:
        svc = _get_service()
        params = _get_params()
        return jsonify({
            'kpis': svc.get_kpis(params),
            'canales': svc.get_resumen_canales(params),
            'categorias': svc.get_resumen_categorias(params),
            'tipo_negocio': svc.get_resumen_tipo_negocio(params),
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@maestra_bp.route('/filtros', methods=['GET'])
def get_filtros():
    """
    GET /api/maestra/filtros
    Retorna opciones disponibles para cada filtro.
    """
    try:
        svc = _get_service()
        return jsonify(svc.get_filtros()), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@maestra_bp.route('/tendencia', methods=['GET'])
def get_tendencia():
    """
    GET /api/maestra/tendencia
    Serie temporal mensual.
    """
    try:
        svc = _get_service()
        params = _get_params()
        return jsonify(svc.get_tendencia(params)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@maestra_bp.route('/detalle', methods=['GET'])
def get_detalle():
    """
    GET /api/maestra/detalle?page=1&page_size=50&sort_by=venta_bruta&sort_order=desc&search=...
    Detalle paginado de transacciones.
    """
    try:
        svc = _get_service()
        params = _get_params()
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 50))
        sort_by = request.args.get('sort_by', 'venta_bruta')
        sort_order = request.args.get('sort_order', 'desc')
        search = request.args.get('search')
        return jsonify(svc.get_detalle(params, page, page_size, sort_by, sort_order, search)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@maestra_bp.route('/export-excel', methods=['GET'])
def export_excel():
    """
    GET /api/maestra/export-excel
    Descarga Excel con datos filtrados.
    """
    try:
        svc = _get_service()
        params = _get_params()
        df = svc.export_dataframe(params)

        output = io.BytesIO()
        with __import__('pandas').ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Maestra Ventas')
        output.seek(0)

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='maestra_ventas.xlsx'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@maestra_bp.route('/top-skus', methods=['GET'])
def get_top_skus():
    """
    GET /api/maestra/top-skus?limit=20
    Top SKUs por venta bruta.
    """
    try:
        svc = _get_service()
        params = _get_params()
        limit = int(request.args.get('limit', 20))
        return jsonify(svc.get_top_skus(params, limit)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@maestra_bp.route('/por-bodega', methods=['GET'])
def get_por_bodega():
    """
    GET /api/maestra/por-bodega
    Resumen por bodega.
    """
    try:
        svc = _get_service()
        params = _get_params()
        return jsonify(svc.get_resumen_bodegas(params)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@maestra_bp.route('/tendencia-diaria', methods=['GET'])
def get_tendencia_diaria():
    """
    GET /api/maestra/tendencia-diaria
    Tendencia por día.
    """
    try:
        svc = _get_service()
        params = _get_params()
        return jsonify(svc.get_tendencia_diaria(params)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@maestra_bp.route('/comparativa', methods=['GET'])
def get_comparativa():
    """
    GET /api/maestra/comparativa
    Comparativa últimos 7 días vs 7 días anteriores.
    """
    try:
        svc = _get_service()
        return jsonify(svc.get_comparativa_semanal()), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@maestra_bp.route('/matriz', methods=['GET'])
def get_matriz():
    """
    GET /api/maestra/matriz?limit=15
    Matriz canal × tipo de negocio.
    """
    try:
        svc = _get_service()
        params = _get_params()
        limit = int(request.args.get('limit', 15))
        return jsonify(svc.get_matriz_canal_negocio(params, limit)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =================== YoY (Year-over-Year) ===================

@maestra_bp.route('/yoy/kpis', methods=['GET'])
def get_kpis_yoy():
    """KPIs TY vs LY del periodo solicitado (default: mes en curso)."""
    try:
        svc = _get_service()
        params = _get_params()
        return jsonify(svc.get_kpis_yoy(params)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@maestra_bp.route('/yoy/tendencia-mensual', methods=['GET'])
def get_tendencia_mensual_yoy():
    """12 meses TY vs LY."""
    try:
        svc = _get_service()
        return jsonify(svc.get_tendencia_mensual_yoy()), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@maestra_bp.route('/yoy/tendencia-diaria', methods=['GET'])
def get_tendencia_diaria_yoy():
    """Día a día TY vs LY del mes solicitado (default: mes actual)."""
    try:
        svc = _get_service()
        anio = request.args.get('anio')
        mes = request.args.get('mes')
        anio = int(anio) if anio else None
        mes = int(mes) if mes else None
        return jsonify(svc.get_tendencia_diaria_yoy(anio, mes)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@maestra_bp.route('/yoy/por-canal', methods=['GET'])
def get_por_canal_yoy():
    """Por canal con TY, LY y var %."""
    try:
        svc = _get_service()
        params = _get_params()
        return jsonify(svc.get_por_canal_yoy(params)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@maestra_bp.route('/yoy/top-skus', methods=['GET'])
def get_top_skus_yoy():
    """Top SKUs con var YoY."""
    try:
        svc = _get_service()
        params = _get_params()
        limit = int(request.args.get('limit', 20))
        return jsonify(svc.get_top_skus_yoy(params, limit)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =================== Health & Descarga RAW ===================

@maestra_bp.route('/health', methods=['GET'])
def get_health():
    """Estado de la última sincronización."""
    try:
        svc = _get_service()
        return jsonify(svc.health()), 200
    except Exception as e:
        return jsonify({'error': str(e), 'estado': 'falla'}), 500


@maestra_bp.route('/download/raw', methods=['GET'])
def descargar_raw():
    """Descarga RAW Excel 40 columnas. Args: desde=YYYY-MM-DD, hasta=YYYY-MM-DD."""
    try:
        svc = _get_service()
        desde = request.args.get('desde')
        hasta = request.args.get('hasta')
        if not desde or not hasta:
            return jsonify({'error': 'desde y hasta son requeridos (YYYY-MM-DD)'}), 400
        df = svc.descargar_raw(desde, hasta)

        output = io.BytesIO()
        with __import__('pandas').ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='RAW')
        output.seek(0)
        nombre = f'Raw_ventas_Y_{desde}_{hasta}.xlsx'
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=nombre
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500
