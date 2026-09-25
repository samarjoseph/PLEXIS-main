"""Engine registry — maps intents to engines."""
import logging
from typing import Optional, Dict, List
from engines.base import BaseEngine

logger = logging.getLogger(__name__)

class EngineRegistry:
    """Registry of all available engines."""
    
    def __init__(self) -> None:
        self._engines: Dict[str, BaseEngine] = {}
        self._intent_map: Dict[str, str] = {}  # intent -> engine_name
    
    def register(self, engine: BaseEngine, intents: List[str]) -> None:
        """Register an engine for specific intents."""
        self._engines[engine.engine_name] = engine
        for intent in intents:
            self._intent_map[intent] = engine.engine_name
        logger.info(f"Registered engine '{engine.engine_name}' for intents: {intents}")
    
    def get_engine_for_intent(self, intent: str) -> Optional[BaseEngine]:
        """Get the engine registered for an intent."""
        engine_name = self._intent_map.get(intent)
        if engine_name:
            return self._engines.get(engine_name)
        return None
    
    def get_engine(self, name: str) -> Optional[BaseEngine]:
        """Get an engine by name."""
        return self._engines.get(name)
    
    def list_intents(self) -> List[str]:
        return list(self._intent_map.keys())

engine_registry = EngineRegistry()
