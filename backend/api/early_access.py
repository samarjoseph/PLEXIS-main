"""Early Access API."""
import logging
from flask import Blueprint, request, jsonify
from typing import Tuple, Any

from config import Config

logger = logging.getLogger(__name__)

early_access_bp = Blueprint('early_access', __name__, url_prefix='/api/early-access')

@early_access_bp.route('', methods=['POST'])
def submit_early_access() -> Tuple[Any, int]:
    if not Config.DATABASE_URL:
        # Fallback for dev mode
        return jsonify({'message': 'Submitted (dev mode without DB)'}), 200

    data = request.get_json(silent=True) or {}
    email = data.get('email')
    
    if not email:
        return jsonify({'error': 'Email is required'}), 400

    # Clean input
    email = str(email).strip().lower()
    role = str(data.get('role', '')).strip()[:100]
    idea = str(data.get('idea', '')).strip()[:2000]
    
    # Safely get features array
    selected_features = data.get('selected_features', [])
    if not isinstance(selected_features, list):
        selected_features = []
    selected_features = [str(f)[:100] for f in selected_features][:20]

    try:
        from db.session import db_session
        from db.models.early_access import EarlyAccessSubmission
        import re

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({'error': 'Invalid email address'}), 400

        with db_session() as db:
            # Check for existing
            existing = db.query(EarlyAccessSubmission).filter(EarlyAccessSubmission.email == email).first()
            if existing:
                # Prevent obvious duplicates, just return success.
                return jsonify({'message': 'Already submitted'}), 200

            submission = EarlyAccessSubmission(
                email=email,
                role=role if role else None,
                selected_features=selected_features if selected_features else None,
                idea=idea if idea else None,
                status="new"
            )
            db.add(submission)
            db.commit()

        return jsonify({'message': 'Success'}), 200
    except Exception as e:
        logger.error(f"Early access submission failed: {e}")
        return jsonify({'error': 'Internal server error'}), 500


def require_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        admin_key = getattr(Config, 'ADMIN_SECRET_KEY', None)
        import os
        if not admin_key:
            admin_key = os.getenv('ADMIN_SECRET_KEY')
            
        if not admin_key:
            return jsonify({'error': 'Admin access is not configured. Set ADMIN_SECRET_KEY in backend/.env.'}), 403
            
        auth_header = request.headers.get('Authorization')
        if not auth_header or auth_header != f"Bearer {admin_key}":
            return jsonify({'error': 'Unauthorized access'}), 401
            
        return f(*args, **kwargs)
    return decorated_function

@early_access_bp.route('/admin/submissions', methods=['GET'])
@require_admin
def get_submissions() -> Tuple[Any, int]:
    if not Config.DATABASE_URL:
        return jsonify({'submissions': []}), 200

    try:
        from db.session import db_session
        from db.models.early_access import EarlyAccessSubmission
        
        with db_session() as db:
            submissions = db.query(EarlyAccessSubmission).order_by(EarlyAccessSubmission.created_at.desc()).all()
            result = []
            for sub in submissions:
                result.append({
                    'id': str(sub.id),
                    'email': sub.email,
                    'role': sub.role,
                    'selected_features': sub.selected_features,
                    'idea': sub.idea,
                    'status': sub.status,
                    'created_at': sub.created_at.isoformat() if sub.created_at else None
                })
        return jsonify({'submissions': result}), 200
    except Exception as e:
        logger.error(f"Admin submissions fetch failed: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@early_access_bp.route('/admin/submissions/<submission_id>', methods=['PATCH'])
@require_admin
def update_submission(submission_id: str) -> Tuple[Any, int]:
    if not Config.DATABASE_URL:
        return jsonify({'message': 'Updated (dev mode)'}), 200

    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    
    if new_status not in ['new', 'reviewed', 'contacted']:
        return jsonify({'error': 'Invalid status'}), 400

    try:
        from db.session import db_session
        from db.models.early_access import EarlyAccessSubmission
        
        with db_session() as db:
            submission = db.query(EarlyAccessSubmission).filter(EarlyAccessSubmission.id == submission_id).first()
            if not submission:
                return jsonify({'error': 'Not found'}), 404
                
            submission.status = new_status
            db.commit()
            
        return jsonify({'message': 'Success'}), 200
    except Exception as e:
        logger.error(f"Admin submission update failed: {e}")
        return jsonify({'error': 'Internal server error'}), 500
