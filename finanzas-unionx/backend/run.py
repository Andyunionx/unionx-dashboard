"""
Punto de entrada del servidor Flask.

Uso:
    python run.py          # Desarrollo (debug=True)
    python run.py prod     # Producción (debug=False)
"""
import sys
import os
from pathlib import Path

# Agregar el directorio backend al PATH para que encuentre el módulo 'app'
sys.path.insert(0, str(Path(__file__).parent))

from app import create_app
from apscheduler.schedulers.background import BackgroundScheduler


def main():
    """Crea y ejecuta la aplicación Flask"""
    env = sys.argv[1] if len(sys.argv) > 1 else 'development'
    os.environ['FLASK_ENV'] = env

    app = create_app()

    # Iniciar scheduler para auto-refresh programado si es necesario después
    scheduler = BackgroundScheduler(daemon=True)
    # Por ahora no programamos nada, pero el scheduler está disponible si lo necesitamos
    # scheduler.add_job(func=refresh_job, trigger="cron", hour=9, minute=0)
    # scheduler.start()

    port = 5001  # Cambiar a 5001 para evitar conflictos
    print(f"\n{'='*80}")
    print(f" UNION X FINANZAS - Dashboard Backend")
    print(f"{'='*80}")
    print(f" Entorno: {env}")
    print(f" URL: http://localhost:{port}")
    print(f" API: http://localhost:{port}/api")
    print(f"{'='*80}\n")

    app.run(debug=(env == 'development'), port=port, threaded=True)


if __name__ == '__main__':
    main()
