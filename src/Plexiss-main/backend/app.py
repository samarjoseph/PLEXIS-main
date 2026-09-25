"""Flask application factory."""
import logging
from flask import Flask
from flask_cors import CORS
from config import Config
from core.middleware import init_middleware, setup_logging
from core.errors import register_error_handlers
from api.health import health_bp
from api.datasets import datasets_bp
from api.chat import chat_bp

def create_app() -> Flask:
    """Create and configure the Flask application."""
    Config.validate()
    
    app = Flask(__name__)
    
    CORS(app, origins=Config.CORS_ORIGINS, supports_credentials=True)
    
    setup_logging(Config.LOG_LEVEL)
    init_middleware(app)
    register_error_handlers(app)
    
    app.register_blueprint(health_bp)
    app.register_blueprint(datasets_bp)
    app.register_blueprint(chat_bp)
    
    logger = logging.getLogger()
    logger.info("Plexis backend initialized")
    
    return app
