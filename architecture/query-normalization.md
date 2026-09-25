# Plexis V2 — Query Normalization Architecture

## 1. Overview and Philosophy
Query Normalization represents one of the most critical architectural upgrades in Plexis V2. 

Before ANY request reaches the router or downstream LLMs, it must pass through the normalization pipeline. Natural language is inherently messy—users make typos, use informal abbreviations, leverage synonyms, and structure sentences poorly. If raw, messy queries are fed directly into the system, routing accuracy plummets and hallucination rates soar.

The normalization pipeline is responsible for **cleaning user intent** without changing it. It standardizes language to make it predictable and easily digestible for the downstream AI pipeline.

## 2. The Power of Normalization
Normalization acts as a translation layer between human unpredictability and systemic precision. 

**Examples of Normalization in Action:**
- *Raw:* `who got highest marks`
  *Normalized:* `Find the student with the maximum marks.`
- *Raw:* `topper`
  *Normalized:* `Find the highest scoring student.`
- *Raw:* `largest profit`
  *Normalized:* `Find maximum value in Profit column.`
- *Raw:* `lowest attendance kid`
  *Normalized:* `Find student with minimum attendance.`
- *Raw:* `most expensive product`
  *Normalized:* `Find product with highest price.`

By mapping chaotic inputs to standard templates (`Find [Entity] with [Aggregation] [Column]`), the Router and Planner pipelines experience drastically improved accuracy.

## 3. Standardization Scope
The normalization pipeline handles the following structural corrections:
- **Synonyms & Terminology:** Standardizing math/analytical terms (e.g., mapping "average", "avg", "mean" to "mean").
- **Grammar & Syntax:** Correcting broken English or formatting.
- **Pluralization:** Standardizing plural vs. singular forms based on context.
- **Abbreviations:** Expanding common business abbreviations (e.g., "YTD" -> "Year to Date", "ROI" -> "Return on Investment").
- **Typographical Errors:** Correcting misspellings, capitalization errors, extra spaces, and punctuation.
- **Style Variations:** Flattening different writing styles into a neutral, analytical instruction format.

**Crucial Constraint:** Normalization must NEVER alter the fundamental intent of the user's query.

## 4. Entity & Operation Extraction
Beyond cleaning text, the normalization pipeline performs lightweight Named Entity Recognition (NER) and syntactic parsing to build context for the router.

It identifies:
- **Potential Column Names:** Matches nouns against the active dataset schema.
- **Possible Operations:** Identifies intent verbs (e.g., sort, group, filter, plot).
- **Filters:** Extracts conditional constraints (e.g., "over 50", "in New York").
- **Temporal References:** Identifies dates and times (e.g., "last month", "Q3 2023").
- **Numeric References:** Extracts explicit targets (e.g., "top 5", "> 1000").
- **Entities & Targets:** Determines the subject of the query.
- **Aggregations:** Identifies math operations (e.g., max, min, sum).
- **Ambiguity Detection:** Flags queries that lack necessary context.

## 5. Structured Output Payload
The normalization pipeline outputs a strictly defined object. This payload replaces the raw string throughout the rest of the execution context.

```json
{
    "normalized_query": "Find maximum value in Profit column.",
    "extracted_entities": ["student", "marks"],
    "operations": ["find", "maximum"],
    "possible_columns": ["Profit", "Revenue"],
    "filters": [
        {"type": "temporal", "value": "2023"}
    ],
    "confidence": 0.94,
    "ambiguity_score": 0.1,
    "notes": "User used informal term 'topper', mapped to 'highest scoring student'."
}
```

### Field Definitions:
- `normalized_query`: The cleaned, grammatically correct, standardized string that will be passed to downstream LLMs.
- `extracted_entities`: Array of key nouns or subjects identified in the text.
- `operations`: Array of intended actions (e.g., "sort", "aggregate", "visualize").
- `possible_columns`: Array of strings representing suspected dataset column names (used to assist the Planner).
- `filters`: Array of constraint objects (temporal, numeric, categorical) that restrict the dataset.
- `confidence`: Float (0-1) indicating how certain the normalizer is that it accurately translated the intent.
- `ambiguity_score`: Float (0-1) indicating how vague the request is (e.g., "make it better" has a high ambiguity score). If this score is too high, the Router may immediately default to the Conversation Engine to ask for clarification.
- `notes`: Developer debug string explaining the transformations applied.

## 6. Long-Term Vision & AI Pipeline Integration

### 6.1. The Future Pipeline Flow
The holistic AI execution pipeline flows as follows:

**User Input** 
↓ 
**Normalization** *(Cleans intent, extracts schema hints, scores ambiguity)*
↓ 
**Router** *(Assigns execution engine based on normalized intent & confidence)*
↓ 
**Context Injection** *(Fetches dataset profiles, relevant schema, and conversation memory)*
↓ 
**Planner** *(If required: Generates Python/SQL execution plan)*
↓ 
**Execution Engine** *(Runs code in a secure sandbox, generates raw JSON data)*
↓ 
**LLM (Conversation/Report)** *(Formats raw JSON into human-readable text, markdown, or reports)*
↓ 
**Response Formatter** *(Constructs final API payload with charts and citations)*
↓ 
**Frontend**

### 6.2. System Placements
- **Caching:** Implemented at the Normalization layer (identical raw queries yield identical normalized outputs) and post-Execution (identical plans on identical dataset fingerprints yield identical results).
- **Logging & Metrics:** Occurs at every stage transition via the `ExecutionContext.trace`. We track TTFT (Time To First Token), pipeline stage durations, and router accuracy.
- **Provider Fallback & Retries:** Handled entirely within the `ProviderEngine` wrapper, shielding the pipeline logic from API outages.
- **Rate Limiting:** Applied at the Gateway (before Normalization) based on Session ID and IP.
- **Validation & Security:** Input validation occurs pre-normalization. Code sandbox validation occurs in the Execution Engine. Prompt injection defenses sit between Normalization and Routing.
- **Conversation Memory:** Managed by the pipeline orchestrator; injected specifically at the Context Injection phase only when the Router signals `requires_memory`.

### 6.3. Platform Evolution
By isolating Normalization from Routing and Execution, Plexis ensures that improvements to language understanding do not require rewrites of the code generation logic. 
In the future, we will build regression testing datasets against the normalization layer, measuring exactly how accurately raw user slang maps to our internal vocabulary. This is the foundation of a robust, hallucination-resistant AI platform.
