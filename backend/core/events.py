from __future__ import annotations
import logging
import time
from typing import Callable, Dict, List, Any, Type, TypeVar
from pydantic import BaseModel, Field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class BaseEvent(BaseModel):
    """Base class for all events in the Plexis Event-Driven Architecture."""
    event_version: str = Field(default="1.0")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str | None = None
    
    @property
    def event_name(self) -> str:
        return self.__class__.__name__

# Lifecycle Events
class LifecycleEvent(BaseEvent):
    subsystem: str = "Unknown"
    message: str | None = None

class Started(LifecycleEvent): pass
class Completed(LifecycleEvent): 
    duration_ms: int | None = None
class Failed(LifecycleEvent): 
    error: str
class WarningEvent(LifecycleEvent): pass
class Recovered(LifecycleEvent): 
    recovery_strategy: str

# Domain Events
class ProviderFailedEvent(BaseEvent):
    provider: str
    error: str

class ProviderSwitchedEvent(BaseEvent):
    from_provider: str
    to_provider: str

class ProviderCalledEvent(BaseEvent):
    provider: str
    model: str
    latency_ms: float

class ProviderRecovered(BaseEvent):
    provider_name: str
    model_name: str
    recovery_strategy: str

class DKOInvalidated(BaseEvent):
    dataset_fingerprint: str

class ContextCompiled(BaseEvent):
    dko_fingerprint: str
    context_type: str
    token_budget: int | None = None

class ContextCacheHit(BaseEvent):
    cache_key: str

class ContextCacheMiss(BaseEvent):
    cache_key: str

class ModelSelected(BaseEvent):
    provider_name: str
    model_name: str
    latency_score: float
    health_score: float
    cost_score: float
    capability_match: float

class FallbackTriggered(BaseEvent):
    failed_model: str
    fallback_model: str
    level: int

# App Specific Events
class DatasetUploadedEvent(BaseEvent):
    filename: str

class DatasetLoadedEvent(BaseEvent):
    filename: str
    rows: int
    columns: int

class DatasetIntelligenceCompleteEvent(BaseEvent):
    filename: str
    domain: str

class DatasetProfiledEvent(BaseEvent):
    filename: str
    dataset_id: str

class PipelineStartedEvent(BaseEvent):
    request_id: str

class PipelineFinishedEvent(BaseEvent):
    request_id: str
    duration_ms: float
    success: bool
    steps_completed: int

class EngineSelectedEvent(BaseEvent):
    request_id: str
    engine_type: str
    confidence: float

class EngineCompletedEvent(BaseEvent):
    request_id: str
    duration_ms: float

class IntentClassifiedEvent(BaseEvent):
    request_id: str
    intent: str
    confidence: float

TEvent = TypeVar('TEvent', bound=BaseEvent)
EventCallback = Callable[[TEvent], None]

class EventBus:
    """A strongly typed, synchronous event bus for EDA."""
    
    def __init__(self) -> None:
        self._listeners: Dict[str, List[Callable[[Any], None]]] = {}

    def subscribe(self, event_type: Type[TEvent], callback: EventCallback[TEvent]) -> None:
        """Subscribe a strongly typed callback to a specific event type."""
        event_name = event_type.__name__
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        self._listeners[event_name].append(callback)

    def unsubscribe(self, event_type: Type[TEvent], callback: EventCallback[TEvent]) -> None:
        """Unsubscribe a callback from an event type."""
        event_name = event_type.__name__
        if event_name in self._listeners:
            try:
                self._listeners[event_name].remove(callback)
            except ValueError:
                pass

    def publish(self, event: BaseEvent) -> None:
        """Publish an event, calling all subscribed listeners with defensive execution and detailed logging."""
        listeners = self._listeners.get(event.event_name, [])
        if not listeners:
            logger.info(f"No subscribers registered for {event.event_name}")
            return
            
        start_time = time.time()
        logger.info(f"[EVENT]\nPublishing: {event.event_name}\nSubscribers: {len(listeners)}")
        for callback in listeners:
            try:
                callback(event)
            except Exception as e:
                logger.error(
                    f"Subscriber {callback.__name__} failed for event {event.event_name}\n"
                    f"Error: {e}",
                    exc_info=True
                )
        duration_ms = (time.time() - start_time) * 1000
        logger.info(f"Completed in {duration_ms:.2f}ms")

    def clear(self) -> None:
        """Remove all listeners."""
        self._listeners.clear()

# Global event bus instance (should ideally be injected via DI)
event_bus = EventBus()
