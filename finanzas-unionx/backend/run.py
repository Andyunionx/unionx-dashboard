"""
Punto de entrada del servidor Flask.

Uso:
    python run.py          # Desarrollo (debug=True)
    python run.py prod     # Producción (debug=False)
"""
import sys
import os
from datetime import datetime
from pathlib import Path

# Agregar el directorio backend al PATH para que encuentre el módulo 'app'
sys.path.insert(0, str(Path(__file__).parent))

from app import create_app
from apscheduler.schedulers.background import BackgroundScheduler


def refresh_stock_advanced_job():
    """Job programado: refresca el cache de stock avanzado (semaforo + ocupacion)."""
    try:
        from app.core.odoo_client import OdooClient
        from app.services.stock_advanced_service import StockAdvancedService
        from app.api.stock import _cached_advanced_data
        from app.config import Config

        ts = datetime.now().strftime('%H:%M:%S')
        print(f"[STOCK-LIVE {ts}] Iniciando refresh programado...")

        odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB, Config.ODOO_USER, Config.ODOO_PASSWORD)
        service = StockAdvancedService(odoo)
        data = service.extract_full(progress_callback=None)

        # Reemplazar cache (mantener solo el ultimo)
        job_id = f"scheduled_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        _cached_advanced_data.clear()
        _cached_advanced_data[job_id] = data

        ts2 = datetime.now().strftime('%H:%M:%S')
        n_skus = data.get("metadata", {}).get("total_skus", 0)
        print(f"[STOCK-LIVE {ts2}] OK - {n_skus} SKUs cacheados.")
    except Exception as e:
        print(f"[STOCK-LIVE ERROR] {type(e).__name__}: {e}")


def main():
    """Crea y ejecuta la aplicación Flask"""
    env = sys.argv[1] if len(sys.argv) > 1 else 'development'
    os.environ['FLASK_ENV'] = env

    app = create_app()

    # ========================================================================
    # SCHEDULER: refresh automatico de stock cada 5 minutos
    # ========================================================================
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        func=refresh_stock_advanced_job,
        trigger="interval",
        minutes=5,
        id="stock_live_refresh",
        next_run_time=datetime.now(),  # ejecutar al arrancar
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()

    port = 5001
    print(f"\n{'='*80}")
    print(f" UNION X FINANZAS - Dashboard Backend")
    print(f"{'='*80}")
    print(f" Entorno: {env}")
    print(f" URL: http://localhost:{port}")
    print(f" API: http://localhost:{port}/api")
    print(f" Stock LIVE: refresh automatico cada 5 minutos (APScheduler)")
    print(f"{'='*80}\n")

    try:
        app.run(debug=(env == 'development'), port=port, threaded=True, use_reloader=False)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == '__main__':
    main()
