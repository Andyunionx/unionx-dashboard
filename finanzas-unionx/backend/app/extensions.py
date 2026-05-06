"""
Extensiones de Flask inicializadas sin la aplicación
"""
from flask_caching import Cache
from flask_cors import CORS

# Cache en RAM
cache = Cache()

# CORS para desarrollo
cors = CORS()

# Scheduler para auto-refresh en background (se inicializa en run.py si es necesario)
scheduler = None
