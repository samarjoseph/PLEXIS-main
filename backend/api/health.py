"""Health check API blueprint."""
import datetime
from flask import Blueprint, jsonify

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
