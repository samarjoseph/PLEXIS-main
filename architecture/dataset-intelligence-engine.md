# Dataset Intelligence Engine
## Architecture & Design Document

> **Status:** Active Development  
> **Version:** 1.0  
> **Subsystem:** `backend/dataset_intelligence/`  
> **Author:** Plexis Architecture Team  

---

## 1. Purpose

The Dataset Intelligence Engine (DIE) is a dedicated backend subsystem responsible for transforming a raw, uploaded dataset into a rich, reusable knowledge object. This knowledge object is consumed by every major Plexis subsystem — the Planner, Router, Conversation Engine, Chart Engine, and Report Generator — without any of them needing to re-analyze the raw data.

The goal is to answer the question: **"What does this dataset mean?"** — automatically, before the user asks their first question.

---

## 2. Design Philosophy

### Python Calculates. LLMs Explain.

This is the single most important constraint of this subsystem.

- **Python** performs all deterministic analysis (statistics, quality scoring, relationship detection).
- **The LLM** receives only a compact metadata summary — never raw rows, never a full DataFrame.
- This guarantees scalability, determinism, cost-efficiency, and reproducibility.

### One Object. Shared Everywhere.

Instead of every subsystem independently querying and analyzing the dataset, the Dataset Intelligence Engine builds a single `DatasetKnowledgeObject` (DKO). This object is the authoritative source of truth about the dataset and is passed freely between all consumers.

### One Execution Per Upload.

All expensive operations happen once, at upload time. The resulting DKO is serialized and cached using a `schema_fingerprint` key. Future requests reuse the cached DKO instantly.

---

## 3. Module Responsibilities

| Module | Responsibility |
|---|---|
| `models.py` | All dataclasses: `ColumnSchema`, `ColumnStats`, `QualityReport`, `DataInsight`, `DatasetKnowledgeObject`, etc. |
| `utils.py` | Shared helpers: safe casts, entropy, skewness labels, outlier detection, fingerprinting. |
| `schema_intelligence.py` | Classifies every column into a rich semantic type beyond just `dtype`. |
| `statistical_intelligence.py` | Computes full statistical profiles for numeric, categorical, and datetime columns. |
| `quality_intelligence.py` | Detects all forms of data quality issues and produces a `DataQualityScore`. |
| `relationship_intelligence.py` | Discovers correlations, hierarchies, groupings, KPIs, and foreign keys. |
| `semantic_intelligence.py` | Maps columns to high-level analytical concepts (Metric, Dimension, Identifier, etc.). |
| `domain_detector.py` | Infers the dataset's business domain with confidence scoring. |
| `capability_detector.py` | Determines which analysis types the dataset supports. |
| `question_predictor.py` | Predicts the top questions a user is most likely to ask. |
| `insight_engine.py` | Generates prioritized, human-readable insights from deterministic findings. |
| `knowledge_synthesizer.py` | Merges all stage outputs into the unified `DatasetKnowledgeObject`. |
| `llm_dataset_narrator.py` | Makes a single LLM call to generate the human narrative over the structured summary. |
| `dataset_memory_builder.py` | Serializes the DKO for storage in session/dataset memory. |
| `cache_manager.py` | Manages fingerprint-keyed disk persistence of DKO objects. |
| `dataset_intelligence_engine.py` | The top-level orchestrator that runs the full pipeline. |

---

## 4. Execution Pipeline

```
DatasetIntelligenceEngine.analyze(df, filename)
  │
  ├── [Stage 1]  SchemaIntelligenceStage      → ColumnSchema[]
  ├── [Stage 2]  StatisticalIntelligenceStage → ColumnStats{}
  ├── [Stage 3]  QualityIntelligenceStage     → QualityReport
  ├── [Stage 4]  RelationshipIntelligenceStage→ RelationshipMap
  ├── [Stage 5]  SemanticIntelligenceStage    → SemanticMap
  ├── [Stage 6]  DomainDetector               → DomainResult
  ├── [Stage 7]  CapabilityDetector           → CapabilitySet
  ├── [Stage 8]  QuestionPredictor            → PredictedQuestion[]
  ├── [Stage 9]  InsightEngine                → DataInsight[]
  ├── [Stage 10] KnowledgeSynthesizer         → DatasetKnowledgeObject (pre-narrative)
  ├── [Stage 11] LLMDatasetNarrator           → DatasetNarrative
  └── [Stage 12] KnowledgeSynthesizer.finalize→ DatasetKnowledgeObject (complete)
                       │
                       └──→ CacheManager.save(fingerprint, DKO)
                       └──→ DatasetMemoryBuilder.store(session_id, DKO)
```

Each stage is independently instantiated. No stage imports another stage. All inter-stage data flows through the orchestrator.

---

## 5. Dataset Knowledge Object (DKO)

The DKO is the primary output of this subsystem. It is a structured, serializable Python dataclass.

```python
@dataclass
class DatasetKnowledgeObject:
    # Identity
    fingerprint: str
    dataset_name: str
    analyzed_at: str

    # Schema
    columns: List[ColumnSchema]
    row_count: int
    column_count: int

    # Statistical profiles
    column_stats: Dict[str, ColumnStats]

    # Quality
    quality: QualityReport

    # Relationships
    relationships: RelationshipMap

    # Semantics
    semantics: SemanticMap

    # Domain
    domain: DomainResult

    # Capabilities
    capabilities: CapabilitySet

    # Predicted user questions
    predicted_questions: List[PredictedQuestion]

    # Prioritized insights
    insights: List[DataInsight]

    # LLM-generated narrative
    narrative: DatasetNarrative

    # Derived convenience properties
    metrics: List[str]          # column names classified as Metric
    dimensions: List[str]       # column names classified as Dimension
    time_columns: List[str]     # column names classified as Time
    identifiers: List[str]      # column names classified as Identifier

    # Readiness scores
    analysis_readiness_score: float  # 0–100
    data_quality_score: float        # 0–100
```

---

## 6. Caching Strategy

The cache key is a **schema fingerprint**: a deterministic hash of `(sorted column names, dtypes, row_count)`.

The DKO is serialized to JSON and stored at `backend/data/intelligence_cache/<fingerprint>.json`.

On any upload, the engine first checks the cache:
- **Cache hit**: Returns the DKO instantly. No Python computation. No LLM call.
- **Cache miss**: Runs the full pipeline and saves the result.

This guarantees expensive analysis never runs twice for the same dataset schema.

---

## 7. Integration Points

| Consumer | What It Uses |
|---|---|
| `api/datasets.py` (upload endpoint) | Calls `DatasetIntelligenceEngine.analyze()`, stores DKO on `DatasetEntry` |
| `engines/conversation.py` | Reads `DKO.narrative`, `DKO.predicted_questions`, `DKO.domain` for context |
| `engines/analysis.py` (future) | Reads `DKO.capabilities`, `DKO.metrics`, `DKO.dimensions` to validate plans |
| `engines/planner.py` (future) | Reads `DKO.predicted_questions` and `DKO.insights` to bootstrap suggestions |
| `engines/chart.py` (future) | Reads `DKO.capabilities` and `DKO.semantics` to determine chart types |
| `engines/report.py` (future) | Reads the full DKO for structured report generation |
| Frontend (`/api/datasets/active`) | Receives `DKO.to_frontend_dict()` for the Intelligence Dashboard |

---

## 8. Scalability

- **Large datasets (1M+ rows):** All statistical operations use pandas vectorized operations. No Python loops over rows.
- **Sampling:** For datasets > 100,000 rows, statistical and quality stages operate on a stratified random sample of 50,000 rows. The schema stage always uses the full schema.
- **Memory:** The engine never holds a copy of the DataFrame — it operates on the passed reference and releases it when done.
- **Caching:** DKOs are stored compressed on disk. Memory footprint per DKO is negligible.

---

## 9. Future Extension Points

The pipeline is designed to be extended without modifying existing stages:

- Add a **FairnessIntelligence** stage for bias detection in ML datasets.
- Add a **TemporalIntelligence** stage for deep time-series forecasting readiness.
- Add a **TextIntelligence** stage for NLP analysis of free-text columns.
- Add a **PIIDetector** stage for privacy compliance.
- Add a **MLReadiness** stage scoring datasets for supervised/unsupervised learning.

Each new stage simply adds to the DKO and registers with the orchestrator.

---
