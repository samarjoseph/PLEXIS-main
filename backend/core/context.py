"""Execution context for request pipeline."""
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

@dataclass
class PipelineStage:
    """Record of a single pipeline stage execution."""
    name: str
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None

@dataclass
class ExecutionContext:
    """Carries all metadata through the request pipeline."""
    # Request identity
    request_id: str = ''
    message: str = ''
    
    # Session
    session_id: str = ''
    
    # Identity
    user_id: Optional[Any] = None        # Resolved DB user UUID
    chat_id: Optional[Any] = None        # Resolved DB chat UUID
    
    # Dataset
    dataset_id: Optional[str] = None
    dataset_filename: Optional[str] = None
    dataset_fingerprint: Optional[str] = None
    schema_fingerprint: Optional[str] = None
    dataset_profile: Optional[Dict[str, Any]] = None
    schema_profile: Optional[List[Dict]] = None
    column_profiles: Optional[Dict[str, Dict]] = None
    # DatasetKnowledgeObject — populated from DatasetEntry.dko during pipeline
    dko: Optional[Any] = None
    
    # Conversation
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    
    # Pipeline trace
    trace: List[PipelineStage] = field(default_factory=list)
    
    # Normalization
    normalized_query: str = ''
    extracted_entities: List[str] = field(default_factory=list)
    operations: List[str] = field(default_factory=list)
    possible_columns: List[str] = field(default_factory=list)
    filters: List[Dict[str, str]] = field(default_factory=list)
    ambiguity_score: float = 0.0
    
    # Routing payload
    route_payload: Optional[Dict[str, Any]] = None
    
    # Classification (populated downstream)
    intent: Optional[str] = None
    confidence: float = 0.0

    # Workspace state — populated from request body by pipeline
    workspace_state: Optional[Dict[str, Any]] = None
    workspace_action: Optional[Dict[str, Any]] = None
    # Natural language summary of workspace state (produced by WorkspaceInterpreter)
    workspace_summary: str = ''
    
    # Timing
    pipeline_started_at: float = field(default_factory=time.time)
    
    def start_stage(self, name: str) -> PipelineStage:
        """Begin tracking a pipeline stage."""
        stage = PipelineStage(name=name, started_at=time.time())
        self.trace.append(stage)
        return stage
    
    def complete_stage(self, stage: PipelineStage, success: bool = True, error: Optional[str] = None) -> None:
        """Mark a pipeline stage as completed."""
        stage.completed_at = time.time()
        stage.duration_ms = (stage.completed_at - stage.started_at) * 1000
        stage.success = success
        stage.error = error
    
    def total_pipeline_ms(self) -> float:
        """Total pipeline duration in milliseconds."""
        return (time.time() - self.pipeline_started_at) * 1000
    
    def trace_summary(self) -> List[Dict[str, Any]]:
        """Return a summary of all pipeline stages for logging."""
        return [
            {'name': s.name, 'duration_ms': round(s.duration_ms, 2), 'success': s.success}
            for s in self.trace
        ]
