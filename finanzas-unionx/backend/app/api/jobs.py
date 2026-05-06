"""
Endpoints para monitorear estado de jobs de extracción
"""
from flask import Blueprint, jsonify

from app.core.job_manager import job_manager

jobs_bp = Blueprint('jobs', __name__)


@jobs_bp.route('/<job_id>', methods=['GET'])
def get_job_status(job_id):
    """
    GET /api/jobs/{job_id}
    Retorna el estado actual de un job

    Response:
    {
      "job_id": "ventas_2026-04_abc123",
      "status": "RUNNING",           // PENDING | RUNNING | DONE | ERROR
      "progress": 60,                // 0-100
      "progress_label": "Extrayendo facturas...",
      "started_at": "2026-04-13T10:01:00",
      "finished_at": null,
      "error": null
    }
    """
    status = job_manager.get_status(job_id)

    if status is None:
        return jsonify({'error': f'Job {job_id} no existe'}), 404

    return jsonify(status), 200


@jobs_bp.route('/all', methods=['GET'])
def get_all_jobs():
    """
    GET /api/jobs/all
    Retorna todos los jobs (para debugging)
    """
    return jsonify(job_manager.get_all_jobs()), 200
