# Plexis V2 — Model Responsibility Architecture

## 1. Overview and Philosophy
The core philosophy of the Plexis V2 model architecture is **strict role separation**. In previous generations of AI applications, a single monolithic LLM was often tasked with handling everything from intent classification to data extraction, code generation, and chat. This leads to high latency, expensive token consumption, and an increased risk of hallucination (as the model loses focus across disparate tasks).

In Plexis V2, **every model has a clearly defined responsibility.** No model randomly performs multiple unrelated jobs. We pair the specific cognitive profile of a model (e.g., fast classification vs. deep reasoning) with the task that requires it.

## 2. Current Architecture

### 2.1. Conversation Model
The Conversation Model is responsible for all direct user interaction that requires natural language reasoning, empathy, education, or explanation. 

**Primary:** Groq (Llama 3.3 70B)
**First Fallback:** Gemini Flash
**Second Fallback:** Mistral Small 3.x

**Responsibilities:**
- General conversation and casual dialogue
- Greetings and onboarding
- Explanations of complex analytical concepts
- Dataset summaries (e.g., explaining a schema to a user)
- Answering follow-up questions about previously analyzed data
- Report writing and summarization
- Educational responses and clarifications
- Maintaining context across multi-turn conversations

**Reasoning:**
For user-facing dialogue, conversation quality, empathy, and contextual reasoning matter significantly more than sub-second latency. Llama 3.3 70B excels at nuanced reasoning, tone control, and dialogue management, making it the ideal primary engine for the Conversation Pipeline.

### 2.2. Router Model
The Router Model operates entirely behind the scenes. It acts as the intelligence layer for the Master Router (when lightweight heuristics fail to reach a high confidence threshold). 

**Primary:** Mistral Medium 3.5
**First Fallback:** Gemini Flash
**Second Fallback:** Mistral Small

**Responsibilities:**
- Intent understanding (What is the user trying to accomplish?)
- Semantic classification of normalized queries
- Pipeline routing (Which engine should handle this request?)
- Request decomposition (Breaking a complex query into sub-tasks)
- Task categorization (e.g., Aggregation vs. Filtering vs. Visualization)
- Confidence estimation for ambiguous queries

**Reasoning:**
Router requests are highly structured, extremely small, and require strict adherence to output schemas (e.g., returning a JSON routing object). The Router needs specialized intelligence, fast time-to-first-token (TTFT), and the ability to strictly follow system prompts without generating conversational filler. Mistral Medium 3.5 is highly optimized for instruction following and structured output, making it perfect for this non-conversational routing layer.

### 2.3. Planner Model
*(Currently remains unchanged from legacy implementation, pending future upgrade)*

**Responsibilities:**
- Converts natural language analytical requests into executable structured plans (e.g., pandas operations, SQL queries).
- Bridges the gap between intent and execution.

*Future Planner Improvements:* 
The planner will eventually be transitioned to a specialized code-generation model (e.g., CodeLlama or specialized Gemini variants) with a strict sandbox validation feedback loop to ensure generated plans are syntactically and logically sound before execution.

---

## 3. Future Architecture & Scalability

As Plexis scales to become a comprehensive AI platform, the following specialized models will be integrated into the ecosystem. The Router will be upgraded to detect these intents and dispatch them accordingly.

### 3.1. Vision & OCR Model
- **Role:** Understand visual data (charts, screenshots, scanned PDFs).
- **Responsibility:** Extracting tabular data from images, reading handwritten notes, or interpreting user-uploaded charts to answer questions about visual trends.

### 3.2. Speech Model
- **Role:** Voice-to-text and intent parsing.
- **Responsibility:** Allowing mobile or desktop users to query their datasets via voice. This model will transcribe the audio and immediately feed the text into the Query Normalization pipeline.

### 3.3. Report Generation Model
- **Role:** Long-form, highly structured document creation.
- **Responsibility:** When a user requests a "Monthly Sales Summary," this model will take the raw JSON output from the Execution Engine and format it into a beautiful, markdown-rich, multi-page report.

### 3.4. Embedding Model & Reranker
- **Role:** Semantic search and Retrieval-Augmented Generation (RAG).
- **Responsibility:** Embedding massive datasets, historical reports, or documentation to allow for blazing-fast semantic search. The reranker will ensure the most relevant chunks are fed into the Conversation or Planner models.

### 3.5. Code Generation Model
- **Role:** Advanced script and macro generation.
- **Responsibility:** Writing custom Python/pandas scripts, SQL queries, or frontend visualization code (e.g., Recharts configurations) dynamically based on the dataset schema.

## 4. Implementation Strategy
To support this architecture, the `ProviderEngine` (built in Phase 2) will be expanded. Instead of a single model registry, we will implement **Task-Based Registries**. When the system needs to route a request, it will call:
`provider_engine.generate(task='routing', ...)` 
The engine will inherently know to use Mistral Medium 3.5. When it needs to chat, it will call:
`provider_engine.generate(task='conversation', ...)` 
This abstraction completely decouples the application logic from the underlying LLM provider, allowing us to swap models seamlessly as better, cheaper, or faster options hit the market.
