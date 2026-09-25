"""Plexis response utilities."""
from typing import Dict, Any, Tuple, Optional, List

def success_response(
    answer: str,
    source: Optional[str] = None,
    provider: Optional[str] = None,
    dataset_info: Optional[Dict[str, Any]] = None,
    chart_data: Optional[Dict[str, Any]] = None,
    web_success: Optional[bool] = None,
    sources: Optional[List[Any]] = None,
    citations: Optional[List[Any]] = None,
    **extra: Any
) -> Dict[str, Any]:
    """
    Format a successful response dictionary matching frontend expectations.
    """
    response: Dict[str, Any] = {"answer": answer}
    
    if source is not None:
        response["source"] = source
    if provider is not None:
        response["provider"] = provider
    if dataset_info is not None:
        response["dataset_info"] = dataset_info
    if chart_data is not None:
        response["chart_data"] = chart_data
    if web_success is not None:
        response["web_success"] = web_success
    if sources is not None:
        response["sources"] = sources
    if citations is not None:
        response["citations"] = citations
        
    response.update(extra)
    return response

def error_response(message: str, status_code: int = 500, request_id: Optional[str] = None) -> Tuple[Dict[str, Any], int]:
    """
    Format an error response tuple for Flask.
    """
    response: Dict[str, Any] = {
        "error": message,
        "status": status_code
    }
    
    if request_id is not None:
        response["request_id"] = request_id
        
    return response, status_code
