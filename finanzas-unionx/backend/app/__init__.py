"""
Factory para crear la aplicación Flask.
Inicializa extensiones, blueprints y configuración.
"""
from flask import Flask
from app.config import get_config
from app.extensions import cache, cors, scheduler


def create_app(config=None):
    """
    Crea y configura la aplicación Flask.

    Args:
        config: Objeto Config (si no se proporciona, usa get_config())

    Returns:
        Flask app configurada
    """
    app = Flask(__name__)

    # Configuración
    if config is None:
        config = get_config()
    app.config.from_object(config)

    # Inicializar extensiones
    cache.init_app(app)
    cors.init_app(app, origins=app.config['CORS_ORIGINS'])

    # Registrar blueprints
    _register_blueprints(app)

    # Comandos CLI
    _register_commands(app)

    return app


def _register_blueprints(app):
    """Registra todos los blueprints"""
    from app.api.health import health_bp
    from app.api.jobs import jobs_bp
    from app.api.ventas import ventas_bp
    from app.api.stock import stock_bp
    from app.api.maestra import maestra_bp

    app.register_blueprint(health_bp, url_prefix='/api')
    app.register_blueprint(jobs_bp, url_prefix='/api/jobs')
    app.register_blueprint(ventas_bp, url_prefix='/api/ventas')
    app.register_blueprint(stock_bp, url_prefix='/api/stock')
    app.register_blueprint(maestra_bp, url_prefix='/api/maestra')


def _register_commands(app):
    """Registra comandos CLI útiles"""
    import click

    @app.cli.command()
    def test():
        """Ejecuta tests (placeholder)"""
        click.echo("Tests not implemented yet")

    @app.cli.command()
    def init():
        """Inicializa la aplicación"""
        click.echo("App initialized")

    @app.shell_context_processor
    def make_shell_context():
        """Context para `flask shell`"""
        return {
            'cache': cache,
            'scheduler': scheduler,
        }
