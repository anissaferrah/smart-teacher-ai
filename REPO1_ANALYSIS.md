# Repo 1 Component Analysis for Smart Teacher

## Overview
This document maps components from **GiovanniPasq/agentic-rag-for-dummies** that should be integrated into Smart Teacher's Phase 1+ implementation.

---

## ✅ Already Incorporated (Phase 1 Foundation)

### 1. **5-Stage Pipeline Architecture** ✅
- **Repo 1 Pattern**: Query Rewriter → Clarifier → Retriever → Reasoner → Reflection
- **Smart Teacher**: Implemented in `orchestrator.py`
- **Status**: Core structure in place, agents to be implemented

### 2. **Orchestrator State Machine** ✅
- **Repo 1 Pattern**: LangGraph-style state tracking
- **Smart Teacher**: `AgenticRAGState` dataclass tracks state through pipeline
- **Status**: Foundation complete, nodes to be implemented

### 3. **Configuration-Driven Pipeline** ✅
- **Repo 1 Pattern**: RAG_MODE switching (classic vs. agentic)
- **Smart Teacher**: Config.RAG_MODE and Config.AGENTIC_MAX_LOOPS added
- **Status**: Configuration flags ready

---

## ❌ MISSING Critical Components (Phase 1 Must-Have)

### 1. **System Prompts for Each Stage** ❌
**Repo 1 Implementation:**
```python
# Repo 1 uses 7 system prompts for different stages
SUMMARIZATION_PROMPT      # For document chunking context
REWRITE_PROMPT           # For query enhancement  
ORCHESTRATION_PROMPT     # For multi-agent coordination
CLARIFICATION_PROMPT     # For ambiguity detection
COMPRESSION_PROMPT       # For token-based memory
FALLBACK_PROMPT          # For retrieval failures
AGGREGATION_PROMPT       # For final synthesis
```

**Smart Teacher Action:**
- **Create**: `services/agentic_rag/prompts.py`
- **Define**: 7 system prompts adapted for educational domain
- **Example**: 
  ```python
  REWRITE_PROMPT = """
  You are an educational query optimizer.
  Improve clarity while preserving pedagogical intent.
  Example: "photo" → "photosynthesis in plants"
  """
  ```

### 2. **LangGraph Node Definitions** ❌
**Repo 1 Implementation:**
- Each stage is a LangGraph node with input/output validation
- Nodes use Pydantic models for state
- Conditional edges route based on state (e.g., if needs_clarification, ask user)

**Smart Teacher Action:**
- **Create**: `services/agentic_rag/nodes.py`
- **Define**: 5 node functions (one per stage)
- **Each node**:
  ```python
  async def node_rewrite(state: AgenticRAGState) -> dict:
      # Process, update state
      state.rewritten_query = await rewriter.rewrite(state.query)
      return {"rewritten_query": state.rewritten_query}
  ```

### 3. **Conditional Edge Routing** ❌
**Repo 1 Implementation:**
```python
workflow.add_conditional_edges(
    "clarifier_node",
    route_clarification,  # Function that returns next node name
    {
        "ask_user": "end_node",
        "proceed": "retriever_node"
    }
)
```

**Smart Teacher Action:**
- **Create**: Functions in `services/agentic_rag/graph/workflow.py`
- **Route clarifier output** → ask user or proceed
- **Route retriever output** → if no chunks, fallback; else proceed

### 4. **Pydantic State Models** ❌
**Repo 1 Implementation:**
```python
class QueryState(BaseModel):
    query: str
    rewritten_query: str
    needs_clarification: bool
    retrieved_chunks: List[Document]
    # ... etc

class ToolCall(BaseModel):
    tool_name: str
    parameters: dict
```

**Smart Teacher Action:**
- **Create**: `services/agentic_rag/schemas.py`
- **Define**: Pydantic models for validation
- **Use**: In nodes for type safety

### 5. **Tool Definitions (For Agents)** ❌
**Repo 1 Implementation:**
```python
tools = {
    "search_web": Tool(...),
    "calculator": Tool(...),
    "knowledge_base": Tool(...)
}
```

**Smart Teacher Action:**
- **Create**: `services/agentic_rag/tools.py`
- **Define tools for educational domain**:
  - `search_knowledge_base(query)` → chunks
  - `get_student_confusion(topic)` → confusion data
  - `get_prerequisite_knowledge(topic)` → prerequisite chunks
  - `get_difficulty_level(topic)` → difficulty assessment

### 6. **Hybrid Retrieval with RRF Fusion** ❌
**Repo 1 Implementation:**
```python
# Dense retrieval (embeddings)
dense_results = await vector_db.search(query_embedding)
# Sparse retrieval (BM25)
sparse_results = await bm25.search(query)
# Reciprocal Rank Fusion
fused_results = rrf_fusion(dense_results, sparse_results)
```

**Smart Teacher Action:**
- **Create**: `services/agentic_rag/retrieval/hybrid.py`
- **Implement**:
  - Embedding-based search (already exists)
  - BM25 keyword search (Qdrant supports)
  - RRF fusion algorithm (normalized ranking)
- **File**: `services/agentic_rag/retrieval/hybrid_retriever.py` (100 lines)

### 7. **Context Compression** ❌
**Repo 1 Implementation:**
```python
# Tracks token usage across conversation
# If reaching limit, compress earlier context
compressed_context = compress_with_llm(context)
```

**Smart Teacher Action:**
- **Create**: `services/agentic_rag/memory/context_compressor.py`
- **Logic**:
  - Track cumulative tokens in history
  - If >3000 tokens (safety limit), compress oldest context
  - Use LLM to summarize while preserving key facts

### 8. **Memory Management (Short + Long Term)** ❌
**Repo 1 Implementation:**
```python
short_term_memory = ConversationMemory(max_turns=5)
long_term_memory = GraphMemory(vector_db)
```

**Smart Teacher Action:**
- **Create**: `services/agentic_rag/memory/short_term.py` (80 lines)
  - Store last 5 exchanges
  - Used for context in reasoning stage
- **Create**: `services/agentic_rag/memory/long_term.py` (100 lines)
  - Store summary per session
  - Link to student confusion patterns

### 9. **Human-in-the-Loop Clarification** ❌
**Repo 1 Implementation:**
```python
if needs_clarification:
    clarification_question = await clarifier.generate_question()
    # Return to user, wait for response
    user_response = await get_user_input()
    # Incorporate into next retrieval
```

**Smart Teacher Action:**
- **Option 1** (Simple): Return clarification in API response
  ```json
  {
    "needs_clarification": true,
    "question": "Are you asking about photosynthesis in plants or algae?",
    "suggested_answers": ["plants", "algae", "both"]
  }
  ```
- **Option 2** (Complex): WebSocket-based back-and-forth (Phase 2+)

### 10. **Multi-Agent Parallel Reasoning** ❌
**Repo 1 Implementation:**
```python
# Split complex queries into sub-queries
sub_queries = [
    "What is process X?",
    "What is process Y?",
    "How do X and Y relate?"
]
# Run agents in parallel
results = await asyncio.gather(*[agent.reason(q) for q in sub_queries])
# Aggregate results
final_answer = aggregate(results)
```

**Smart Teacher Action:**
- **Create**: `services/agentic_rag/agents/reasoner_agent.py` (200 lines)
- **Implement**: Sub-query splitting + parallel reasoning
- **Example for "photosynthesis"**:
  ```
  Sub-queries:
  1. Light-dependent reactions
  2. Light-independent reactions (Calvin cycle)
  3. Overall equation and products
  ```

### 11. **Self-Correction Loop** ❌
**Repo 1 Implementation:**
```python
for attempt in range(max_attempts):
    answer = await agent.reason()
    is_sufficient = await validator.check(answer, retrieved_chunks)
    if is_sufficient:
        return answer
    else:
        # Refine prompt or retrieve more chunks
        retrieved_chunks = await retriever.retrieve_more()
```

**Smart Teacher Action:**
- **Implement in**: `services/agentic_rag/agents/reflection_agent.py`
- **Logic**:
  1. Validate answer against retrieved chunks (relevance, coverage)
  2. If score <0.7, trigger refinement loop
  3. Loop up to `AGENTIC_MAX_LOOPS` (3) times
  4. Return best answer with confidence score

### 12. **LangGraph Workflow Assembly** ❌
**Repo 1 Implementation:**
```python
workflow = StateGraph(AgenticRAGState)
workflow.add_node("rewriter", node_rewrite)
workflow.add_node("clarifier", node_clarify)
workflow.add_edge("rewriter", "clarifier")
workflow.add_conditional_edges(
    "clarifier",
    route_clarification,
    {"ask_user": END, "proceed": "retriever"}
)
app = workflow.compile()
```

**Smart Teacher Action:**
- **Create**: `services/agentic_rag/graph/workflow.py` (150 lines)
- **Build**: Full LangGraph workflow with all 5 stages
- **Compile**: Into executable app
- **Integrate**: With orchestrator

### 13. **Observability / Tracing (Optional)** ❌
**Repo 1 Implementation:**
- Uses Langfuse for tracing agent decisions
- Records prompt/response pairs
- Analyzes retrieval quality

**Smart Teacher Action:**
- **Phase 2+**: Add Langfuse integration (optional)
- **For now**: Log to CSV (already exists)

---

## 🎯 Implementation Priority Matrix

| Component | Phase | Priority | Lines | Days |
|-----------|-------|----------|-------|------|
| System Prompts | 1 | 🔴 CRITICAL | 150 | 0.5 |
| Pydantic Schemas | 1 | 🔴 CRITICAL | 80 | 0.25 |
| Node Definitions | 1 | 🔴 CRITICAL | 200 | 0.5 |
| LangGraph Workflow | 1 | 🔴 CRITICAL | 150 | 0.75 |
| 5 Agent Implementations | 1 | 🔴 CRITICAL | 600 | 2 |
| Hybrid Retrieval | 1 | 🟠 HIGH | 100 | 0.5 |
| Memory Modules | 1 | 🟠 HIGH | 150 | 0.75 |
| Tool Definitions | 1 | 🟠 HIGH | 80 | 0.5 |
| Context Compression | 1 | 🟡 MEDIUM | 100 | 0.5 |
| Human-in-the-Loop | 2 | 🟡 MEDIUM | 50 | 0.5 |
| Observability | 2 | 🟢 LOW | 50 | 0.5 |

---

## 📋 Execution Plan: Phase 1B (Next 3 Days)

### Day 1: Foundation Files
```
services/agentic_rag/
├── prompts.py              # System prompts (7 total)
├── schemas.py              # Pydantic models
└── tools.py                # Tool definitions
```

### Day 2: Graph Assembly
```
services/agentic_rag/
├── agents/
│   ├── query_rewriter.py       # Stage 1
│   ├── query_clarifier.py      # Stage 2
│   ├── retriever_agent.py      # Stage 3 (with hybrid retrieval)
│   ├── reasoner_agent.py       # Stage 4 (with sub-query splitting)
│   └── reflection_agent.py     # Stage 5 (with self-correction)
└── graph/
    └── workflow.py              # LangGraph assembly
```

### Day 3: Memory + Integration
```
services/agentic_rag/
├── memory/
│   ├── short_term.py       # 5-exchange memory
│   ├── long_term.py        # Session summaries
│   └── compressor.py       # Token compression
├── retrieval/
│   └── hybrid_retriever.py # RRF fusion
└── update orchestrator.py to wire agents
```

---

## ✨ Summary: What to Add from Repo 1

| What | Where | Status |
|------|-------|--------|
| **System Prompts** (7 stages) | `services/agentic_rag/prompts.py` | ❌ TODO |
| **Pydantic Schemas** | `services/agentic_rag/schemas.py` | ❌ TODO |
| **LangGraph Nodes** (5 stages) | `services/agentic_rag/agents/*.py` | ❌ TODO |
| **LangGraph Workflow** | `services/agentic_rag/graph/workflow.py` | ❌ TODO |
| **Hybrid Retrieval (RRF)** | `services/agentic_rag/retrieval/hybrid_retriever.py` | ❌ TODO |
| **Memory Management** | `services/agentic_rag/memory/*.py` | ❌ TODO |
| **Tools for Education** | `services/agentic_rag/tools.py` | ❌ TODO |
| **Context Compression** | `services/agentic_rag/memory/compressor.py` | ❌ TODO |
| **Human-in-the-Loop** | Phase 2 (API integration) | ⏳ PHASE 2 |
| **Observability** | Phase 2 (Langfuse) | ⏳ PHASE 2 |

---

## 🚀 Ready to Start?

The Phase 1 foundation is complete. Phase 1B is ready to implement these components.

**Next Step**: Create `services/agentic_rag/prompts.py` with all 7 system prompts adapted for the educational domain.
