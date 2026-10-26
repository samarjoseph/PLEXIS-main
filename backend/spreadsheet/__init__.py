"""Spreadsheet package initialization."""
from .persistence import spreadsheet_history_manager, ConcurrencyConflictError

__all__ = ["spreadsheet_history_manager", "ConcurrencyConflictError"]
