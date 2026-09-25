"""Request middleware and logging configuration."""
import time
import uuid
import logging
import json
from flask import g, request, current_app, Response
from typing import Any, Dict
from config import Config

class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""
    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        
        if hasattr(record, 'request_id'):
            log_data['request_id'] = record.request_id
        if hasattr(record, 'method'):
            log_data['method'] = record.method
        if hasattr(record, 'path'):
            log_data['path'] = record.path
        if hasattr(record, 'status'):
            log_data['status'] = record.status
        if hasattr(record, 'duration_ms'):
            log_data['duration_ms'] = record.duration_ms
            
        return json.dumps(log_data)

def setup_logging(log_level: str) -> None:
    """Configures structured JSON logging."""
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    handler = logging.StreamHandler()
    formatter = JSONFormatter()
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def init_middleware(app: Any) -> None:
    """Registers before_request and after_request hooks."""
    
    @app.before_request
    def before_request() -> None:
        g.start_time = time.time()
        g.request_id = str(uuid.uuid4())

    @app.after_request
    def after_request(response: Response) -> Response:
        duration_ms = (time.time() - g.start_time) * 1000 if hasattr(g, 'start_time') else 0
        request_id = g.request_id if hasattr(g, 'request_id') else 'unknown'
        
        response.headers['X-Request-ID'] = request_id
        
        logger = logging.getLogger()
        logger.info(
            "Request completed",
            extra={
                'request_id': request_id,
                'method': request.method,
                'path': request.path,
                'status': response.status_code,
                'duration_ms': round(duration_ms, 2)
            }
        )
        
        return response
