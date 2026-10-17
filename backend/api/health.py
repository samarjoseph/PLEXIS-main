"""Health check and provider diagnostics API blueprint."""
import datetime
from flask import Blueprint, jsonify
from providers.diagnostics import provider_diagnostics

health_bp = Blueprint('health', __name__, url_prefix='/api')

@health_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "plexis-backend",
        "version": "2.0.0",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    })

@health_bp.route('/health/providers', methods=['GET'])
def provider_health():
    """Diagnostic status for LLM providers, roles, and credential pools."""
    report = provider_diagnostics.get_diagnostics_report()
    return jsonify({
        "status": "ok",
        "service": "plexis-backend",
        "diagnostics": report
    })
