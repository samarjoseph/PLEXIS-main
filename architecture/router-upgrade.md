# Plexis V2 — Master Router Upgrade Architecture

## 1. Overview and Philosophy
The current router implementation in Plexis is a first-generation design. It relies primarily on static keyword matching and regex heuristics. While functional, it represents a bottleneck for future intelligence. 

We are upgrading to a **Hybrid Semantic Router**. 
We do NOT want pure keyword matching (too rigid, fails on synonyms) nor do we want 100% LLM routing (too slow, expensive, and unnecessary for simple intents). The hybrid approach ensures that high-confidence intents are routed instantly using heuristics and semantic embeddings, while ambiguous or highly complex requests escalate to the LLM (Router Model) for validation.

## 2. Router Pipeline Architecture

Every incoming request will flow through a strict, deterministic sequence:

**Incoming request**
↓
**Normalization** *(Cleans intent, extracts entities — see `query-normalization.md`)*
↓
**Semantic understanding** *(Embedding vector search against known intent clusters)*
↓
**Lightweight heuristics** *(Regex & keyword matching for ultra-fast, obvious intents)*
↓
**Intent confidence scoring** *(Calculates confidence from semantics + heuristics)*
↓
**LLM validation** *(ONLY invoked when confidence is below the escalation threshold)*
↓
**Final route assignment** *(Packages the execution payload)*
↓
**Execution Engine Dispatch**

## 3. Supported Intents
The upgraded router must identify a broad spectrum of capabilities, including:
- General conversation
- Dataset upload
- Data analysis
- Aggregation (e.g., sum, average, total)
- Sorting (e.g., top, bottom, highest)
- Filtering (e.g., where age > 30)
- Visualization (e.g., chart, plot)
- Report generation
- Follow-up question (requires conversation memory)
- Conversation memory request (recalling previous turns)
- *Future:* Web search
- *Future:* Code generation
- *Future:* Report editing
- *Future:* OCR & Image understanding
- *Future:* SQL generation
- *Future:* Plugin dispatch
- *Future:* Workflow automation

## 4. Structured Output Format
Regardless of how the intent is determined (Heuristics, Embeddings, or LLM), the router must output a strictly typed, standard JSON payload. This payload dictates exactly how downstream engines execute the request.

```json
{
    "intent": "aggregation",
    "confidence": 0.92,
    "execution_type": "synchronous",
    "requires_dataset": true,
    "requires_llm": false,
    "requires_planner": true,
    "requires_context": true,
    "requires_memory": false,
    "estimated_cost": "low",
    "estimated_latency": "under_1s",
    "reasoning": "Semantic search matched 'average' to aggregation cluster. Dataset is present."
}
```

### Field Definitions:
- `intent`: The specific classification (e.g., "data_analysis", "visualization").
- `confidence`: Float between 0.0 and 1.0 representing certainty.
- `execution_type`: "synchronous" (blocks until complete), "asynchronous" (returns task ID for long-running reports), or "stream" (for conversation).
- `requires_dataset`: Boolean indicating if the active dataset context must be injected.
- `requires_llm`: Boolean indicating if a heavy LLM (Conversation/Planner) is needed downstream.
- `requires_planner`: Boolean indicating if this is an analytical request requiring the planner to generate code.
- `requires_context`: Boolean indicating if schema profiles and column stats are needed.
- `requires_memory`: Boolean indicating if previous conversation turns are needed to answer (e.g., "What about the second one?").
- `estimated_cost`: Categorical ("free", "low", "high") used for budget limits and rate limiting.
- `estimated_latency`: Categorical expectation ("under_1s", "under_5s", "async") to inform UI loading states.
- `reasoning`: Developer debug string explaining *why* the router made this choice.

## 5. Confidence-Driven Escalation
Cost and latency optimization are paramount. The router is fundamentally **confidence driven**.

- **High Confidence (e.g., > 0.85):**
  If normalization + heuristics + semantic embeddings yield a high confidence score, the router assigns the route immediately. **No expensive LLM call is made.**
  *Example:* Request: "Hi!" -> Heuristics score 0.99 for `conversation`. Fast path taken.

- **Low Confidence (e.g., < 0.85):**
  If the request is highly ambiguous or complex, it is escalated to the Mistral Medium 3.5 Router Model. The LLM analyzes the normalized query and outputs the structured JSON payload.
  *Example:* Request: "Can you take the things from yesterday and make them look good?" -> LLM validation determines this is a visualization request needing memory.

## 6. Long-Term Scalability
The router is designed as an isolated, extensible microservice within the backend.
- **Learned Routing:** In future versions, we will capture user corrections (e.g., user asks for a chart, router sends to analysis, user corrects to visualization). This feedback loop will fine-tune the semantic embeddings without changing the codebase.
- **Plugin Ecosystem:** New engines (e.g., Web Search) can register their intents and embedding clusters with the router dynamically at startup. The router does not need to be hardcoded to know about the new engine; it simply queries the engine registry.
