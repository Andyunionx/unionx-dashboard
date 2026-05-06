"""
Configuración de la aplicación Flask
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar .env del directorio padre (UNION X - IA)
PARENT_ENV = Path(__file__).parent.parent.parent.parent / ".env"
load_dotenv(str(PARENT_ENV))

# Rutas absolutas
BASE_DIR = Path(__file__).parent.parent.parent.parent  # UNION X - IA/
PARENT_PROJECT = BASE_DIR


class Config:
    """Configuración base"""
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-unionx-2026')
    DEBUG = False

    # Flask-Caching
    CACHE_TYPE = 'SimpleCache'
    CACHE_DEFAULT_TIMEOUT = 7200  # 2 horas (los datos expiran y fuerzan refresh)

    # CORS
    CORS_ORIGINS = ['http://localhost:5173', 'http://localhost:3000']

    # Odoo XML-RPC
    ODOO_URL = 'https://unionxb2b.odoo.com'
    ODOO_DB = 'bmya-innovatek-sh-prd-6981800'
    ODOO_USER = 'andres@grupoeter.cl'
    ODOO_PASSWORD = os.getenv('ANDRES_ODOO_PASSWORD', '')

    # Maestra de Ventas (SQLite) — usar copia local si existe para mejor rendimiento
    _LOCAL_DB = Path(os.path.expanduser('~/Desktop/finanzas-unionx-app/maestra_ventas.db'))
    MAESTRA_DB_PATH = _LOCAL_DB if _LOCAL_DB.exists() else PARENT_PROJECT / 'data/db/maestra_ventas.db'

    # Rutas a archivos de entrada (planillas locales)
    PLANILLAS_DIR = PARENT_PROJECT / 'data/planillas'
    MAESTRA_CANALES = PLANILLAS_DIR / 'Maestra Canales.xlsx'
    MATRIZ_PRODUCTOS = PLANILLAS_DIR / 'Matriz productos.xlsx'
    MOCKUP_RAW_Y = PLANILLAS_DIR / 'Mockup raw Y.xlsx'

    # Validar que las rutas existen
    REQUIRED_FILES = {
        'Maestra Canales': MAESTRA_CANALES,
        'Matriz Productos': MATRIZ_PRODUCTOS,
        'Mockup Raw Y': MOCKUP_RAW_Y,
    }


class DevelopmentConfig(Config):
    """Configuración de desarrollo"""
    DEBUG = True
    FLASK_ENV = 'development'


class ProductionConfig(Config):
    """Configuración de producción"""
    DEBUG = False
    FLASK_ENV = 'production'
    CACHE_DEFAULT_TIMEOUT = 10800  # 3 horas en prod


class TestingConfig(Config):
    """Configuración de testing"""
    TESTING = True
    CACHE_TYPE = 'NullCache'  # Sin cache en tests


# Seleccionar config por entorno
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}


def get_config():
    """Obtiene la configuración según el entorno"""
    env = os.getenv('FLASK_ENV', 'development')
    return config.get(env, config['default'])
