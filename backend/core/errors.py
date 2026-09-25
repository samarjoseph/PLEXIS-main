"""Plexis error definitions and handlers."""
from typing import Dict, Any, Optional

class PlexisError(Exception):
    """Base error class for Plexis exceptions."""
    
    def __init__(self, message: str, status_code: int = 500, payload: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload or {}

class ValidationError(PlexisError):
    """Raised when request data is invalid."""
    
    def __init__(self, message: str, payload: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=400, payload=payload)

class NotFoundError(PlexisError):
    """Raised when a requested resource is not found."""
    
    def __init__(self, message: str, payload: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=404, payload=payload)

class ProviderError(PlexisError):
    """Raised when an external provider (e.g., LLM) fails."""
    
    def __init__(self, message: str, payload: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=502, payload=payload)

def register_error_handlers(app) -> None:
    """Register error handlers with the Flask application."""
    from flask import jsonify, g
    
    @app.errorhandler(PlexisError)
    def handle_plexis_error(error: PlexisError):
        response = {
            "error": error.message,
            "status": error.status_code,
            "request_id": getattr(g, "request_id", None)
        }
        if error.payload:
            response.update(error.payload)
        return jsonify(response), error.status_code

    @app.errorhandler(404)
    def handle_not_found(error):
        return jsonify({
            "error": "Not Found",
            "status": 404,
            "request_id": getattr(g, "request_id", None)
        }), 404

    @app.errorhandler(500)
    def handle_internal_error(error):
        return jsonify({
            "error": "Internal Server Error",
            "status": 500,
            "request_id": getattr(g, "request_id", None)
        }), 500
