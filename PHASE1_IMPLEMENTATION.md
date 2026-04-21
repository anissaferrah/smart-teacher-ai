# Phase 1 Implementation Roadmap - File by File

## 🗺️ Current Smart Teacher Structure vs New Architecture

### EXISTING FILES (Keep & possibly modify)

```
KEEP AS IS:
├── config.py                    ← Just add RAG_MODE flag
├── services/app_state.py        ← Add agentic services
├── modules/ai/llm.py            ← Use as is
├── modules/ai/transcriber.py    ← Use as is
├── database/models/             ← Use as is
├── api/health.py                ← Use as is
└── handlers/session_manager.py  ← Use as is

MODIFY:
├── api/search.py                ← Route through orchestrator
├── handlers/audio_pipeline.py   ← Use orchestrator
└── .env                          ← Add RAG_MODE flag
```

---

## 🆕 NEW FILES TO CREATE (Phase 1)

### FOLDER STRUCTURE

```
services/agentic_rag/
├── __init__.py
├── orchestrator.py              ← PHASE 1 CORE
├── agents/
│   ├── __init__.py
│   ├── query_rewriter.py        ← PHASE 1 (Repo 1)
│   ├── query_clarifier.py       ← PHASE 1 (Repo 1)
│   ├── retriever_agent.py       ← PHASE 1 (Repo 1)
│   ├── reasoner_agent.py        ← PHASE 1 (Repo 1 + Repo 2)
│   └── reflection_agent.py      ← PHASE 1 (Repo 2)
├── memory/
│   ├── __init__.py
│   ├── short_term.py            ← PHASE 1 (Repo 2)
│   └── long_term.py             ← PHASE 1 (Repo 2)
├── retrieval/
│   ├── __init__.py
│   ├── dual_embeddings.py       ← PHASE 1 (Repo 1)
│   └── chunk_aggregator.py      ← PHASE 1 (Repo 1)
└── utils/
    ├── __init__.py
    └── state_manager.py         ← PHASE 1 (Repo 2)
```

---

## 📋 Phase 1 - 5 FILES TO CREATE IMMEDIATELY

| # | File | Size | From | Priority | Depends On |
|---|---|---|---|---|---|
| 1 | `services/agentic_rag/orchestrator.py` | 300 lines | Repo 2 | 🔴 CRITICAL | config.py |
| 2 | `services/agentic_rag/agents/query_rewriter.py` | 80 lines | Repo 1 | 🔴 CRITICAL | llm.py |
| 3 | `services/agentic_rag/agents/query_clarifier.py` | 80 lines | Repo 1 | 🔴 CRITICAL | llm.py |
| 4 | `services/agentic_rag/agents/retriever_agent.py` | 150 lines | Repo 1 | 🔴 CRITICAL | multimodal_rag.py |
| 5 | `services/agentic_rag/agents/reasoner_agent.py` | 200 lines | Repo 1 + 2 | 🔴 CRITICAL | llm.py, memory |

**Then:**
| 6 | `services/agentic_rag/memory/short_term.py` | 80 lines | Repo 2 | 🟡 HIGH | Python stdlib |
| 7 | `services/agentic_rag/agents/reflection_agent.py` | 100 lines | Repo 2 | 🟡 HIGH | llm.py |
| 8 | `services/agentic_rag/retrieval/dual_embeddings.py` | 120 lines | Repo 1 | 🟡 HIGH | multimodal_rag.py |

---

## 🔧 MODIFICATIONS TO EXISTING FILES

### 1️⃣ `config.py` - Add 2 lines

**Location:** Line 68 (after RAG_ENABLED)

```python
RAG_MODE: str = os.getenv("RAG_MODE", "classic")  # "classic" or "agentic"
AGENTIC_MAX_LOOPS: int = int(os.getenv("AGENTIC_MAX_LOOPS", "3"))
```

---

### 2️⃣ `services/app_state.py` - Add 10 lines

**Location:** After line 46 (after all existing services)

```python
# ─── Agentic RAG (Phase 1) ───────────────────────────────────
# Will be initialized when agentic_rag module is ready
agentic_rag_executor = None  # Placeholder, will initialize after Phase 1

def init_agentic_rag():
    """Initialize agentic RAG services (called after Phase 1 complete)"""
    global agentic_rag_executor
    from services.agentic_rag.orchestrator import AgenticRAGOrchestrator
    
    agentic_rag_executor = AgenticRAGOrchestrator(
        llm=language_brain,
        rag=knowledge_retrieval_engine,
        short_term_memory=None,  # Will add in Phase 2
        long_term_memory=None,   # Will add in Phase 2
    )
```

---

### 3️⃣ `api/search.py` - Modify 3 sections

**OLD (Line 28-36):**
```python
chunks_with_scores = knowledge_retrieval_engine.retrieve_chunks(question, k=Config.RAG_NUM_RESULTS, course_id=course_id)

llm_start = __import__("time").time()
ai_response, _ = knowledge_retrieval_engine.generate_final_answer(
    chunks_with_scores,
    question=question,
    history=history,
    language=language,
)
llm_time = __import__("time").time() - llm_start
```

**NEW:**
```python
import time
llm_start = time.time()

# Route based on RAG_MODE
if Config.RAG_MODE == "agentic":
    # Use agentic RAG (Phase 1)
    response = await agentic_rag_executor.answer_question(
        query=question,
        course_id=course_id,
        history=history,
        language=language,
    )
    ai_response = response["answer"]
    rag_mode = "agentic"
else:
    # Use classic RAG (existing)
    chunks_with_scores = knowledge_retrieval_engine.retrieve_chunks(
        question, k=Config.RAG_NUM_RESULTS, course_id=course_id
    )
    ai_response, _ = knowledge_retrieval_engine.generate_final_answer(
        chunks_with_scores,
        question=question,
        history=history,
        language=language,
    )
    rag_mode = "classic"

llm_time = time.time() - llm_start
```

---

### 4️⃣ `.env` - Add 2 lines

```bash
# RAG Mode configuration
RAG_MODE=classic           # "classic" or "agentic"
AGENTIC_MAX_LOOPS=3        # Number of refinement loops
```

---

## 📝 PHASE 1 CODE FILES

### FILE 1: `services/agentic_rag/__init__.py`

```python
"""Agentic RAG - Multi-stage reasoning pipeline using Repo 1 + Repo 2"""

__version__ = "1.0.0"
__author__ = "Smart Teacher Team"
```

---

### FILE 2: `services/agentic_rag/orchestrator.py` (CORE - 300 lines)

```python
"""
Agentic RAG Orchestrator - Main controller for multi-stage pipeline.
Based on Repo 2 (LangGraph patterns) + Repo 1 (4-stage flow).
"""

import logging
import time
from typing import Optional
from dataclasses import dataclass

from config import Config

log = logging.getLogger("SmartTeacher.AgenticRAG")


@dataclass
class AgenticRAGState:
    """Pipeline state tracking (Repo 2 pattern)"""
    query: str
    rewritten_query: str = ""
    needs_clarification: bool = False
    clarification_question: str = ""
    retrieved_chunks: list = None
    draft_answer: str = ""
    final_answer: str = ""
    confidence: float = 0.0
    reasoning_trace: dict = None
    loop_count: int = 0
    

class AgenticRAGOrchestrator:
    """
    Orchestrates the 5-stage agentic RAG pipeline.
    
    Pipeline (Repo 1):
    1. Query Rewriter   - Improve clarity
    2. Query Clarifier  - Check ambiguity
    3. Retriever Agent  - Search chunks
    4. Reasoner Agent   - Multi-agent thinking (with Repo 2 memory)
    5. Reflection Agent - Validate & refine (Repo 2)
    """
    
    def __init__(self, llm, rag, short_term_memory=None, long_term_memory=None):
        """Initialize orchestrator with services."""
        self.llm = llm
        self.rag = rag
        self.short_term_memory = short_term_memory
        self.long_term_memory = long_term_memory
        self.max_loops = Config.AGENTIC_MAX_LOOPS
        
        # Will import agents after Phase 1
        self.query_rewriter = None
        self.query_clarifier = None
        self.retriever = None
        self.reasoner = None
        self.reflection = None
        
        log.info("✅ AgenticRAGOrchestrator initialized")
    
    async def answer_question(
        self,
        query: str,
        course_id: Optional[str] = None,
        history: Optional[list] = None,
        language: str = "fr",
        student_profile: Optional[dict] = None,
    ) -> dict:
        """
        Execute full agentic RAG pipeline.
        
        Args:
            query: User question
            course_id: Course context
            history: Conversation history
            language: Language code
            student_profile: Student info (Phase 2)
            
        Returns:
            {
                "answer": str,
                "confidence": float,
                "reasoning": dict,
                "sources": list,
                "mode": "agentic",
                "metrics": {"total_time": float, "stages": dict}
            }
        """
        
        total_start = time.time()
        state = AgenticRAGState(query=query)
        metrics = {}
        
        try:
            # STAGE 1: Query Rewriting (Repo 1)
            log.info(f"→ Stage 1/5: Query Rewriter")
            stage_start = time.time()
            
            state.rewritten_query = await self._stage_rewrite(query)
            log.info(f"  Rewritten: '{state.rewritten_query}'")
            
            metrics["rewrite_time"] = time.time() - stage_start
            
            # STAGE 2: Query Clarification (Repo 1)
            log.info(f"→ Stage 2/5: Query Clarifier")
            stage_start = time.time()
            
            needs_clarif, clarif_q = await self._stage_clarify(state.rewritten_query)
            state.needs_clarification = needs_clarif
            state.clarification_question = clarif_q
            
            if needs_clarif:
                log.warning(f"  ⚠️ Clarification needed: {clarif_q}")
                return {
                    "answer": f"I need clarification: {clarif_q}",
                    "confidence": 0.2,
                    "reasoning": {"needs_clarification": True},
                    "sources": [],
                    "mode": "agentic",
                    "metrics": {"total_time": time.time() - total_start, "stages": metrics}
                }
            
            metrics["clarify_time"] = time.time() - stage_start
            
            # STAGE 3: Retrieval (Repo 1)
            log.info(f"→ Stage 3/5: Retriever Agent")
            stage_start = time.time()
            
            state.retrieved_chunks = await self._stage_retrieve(
                state.rewritten_query, course_id
            )
            log.info(f"  Retrieved {len(state.retrieved_chunks)} chunks")
            
            metrics["retrieve_time"] = time.time() - stage_start
            
            # STAGE 4: Reasoning (Repo 1 + Repo 2)
            log.info(f"→ Stage 4/5: Reasoner Agent")
            stage_start = time.time()
            
            state.draft_answer = await self._stage_reason(
                state.rewritten_query,
                state.retrieved_chunks,
                history or [],
                student_profile or {}
            )
            log.info(f"  Draft answer generated ({len(state.draft_answer)} chars)")
            
            metrics["reason_time"] = time.time() - stage_start
            
            # STAGE 5: Reflection + Refinement Loop (Repo 2)
            log.info(f"→ Stage 5/5: Reflection Agent")
            stage_start = time.time()
            
            state.final_answer, state.confidence, state.loop_count = await self._stage_reflect(
                state.draft_answer,
                state.retrieved_chunks,
                state.rewritten_query
            )
            log.info(f"  Final answer confidence: {state.confidence:.2f} (refined {state.loop_count}x)")
            
            metrics["reflect_time"] = time.time() - stage_start
            
            # BUILD RESPONSE
            total_time = time.time() - total_start
            
            return {
                "answer": state.final_answer,
                "confidence": state.confidence,
                "reasoning": {
                    "rewritten_query": state.rewritten_query,
                    "refinement_loops": state.loop_count,
                    "needs_clarification": False,
                },
                "sources": [
                    {
                        "text": c.page_content[:200] if hasattr(c, 'page_content') else str(c)[:200],
                        "score": getattr(c, 'metadata', {}).get('score', 0.5)
                    }
                    for c in state.retrieved_chunks[:3]
                ],
                "mode": "agentic",
                "metrics": {
                    "total_time": total_time,
                    "stages": metrics,
                    "stage_breakdown": {
                        "rewrite": f"{metrics['rewrite_time']:.2f}s",
                        "clarify": f"{metrics['clarify_time']:.2f}s",
                        "retrieve": f"{metrics['retrieve_time']:.2f}s",
                        "reason": f"{metrics['reason_time']:.2f}s",
                        "reflect": f"{metrics['reflect_time']:.2f}s",
                    }
                }
            }
            
        except Exception as e:
            log.error(f"❌ Agentic RAG error: {e}")
            return {
                "answer": f"Error: {str(e)}",
                "confidence": 0.0,
                "reasoning": {"error": str(e)},
                "sources": [],
                "mode": "agentic",
                "metrics": {"total_time": time.time() - total_start, "error": True}
            }
    
    # STAGE IMPLEMENTATIONS (Placeholders - will import agents)
    
    async def _stage_rewrite(self, query: str) -> str:
        """Stage 1: Query Rewriter (Repo 1)"""
        if self.query_rewriter:
            return await self.query_rewriter.rewrite(query)
        # Fallback
        return query
    
    async def _stage_clarify(self, query: str) -> tuple:
        """Stage 2: Query Clarifier (Repo 1)"""
        if self.query_clarifier:
            return await self.query_clarifier.check_clarity(query)
        # Fallback
        return False, ""
    
    async def _stage_retrieve(self, query: str, course_id: Optional[str]) -> list:
        """Stage 3: Retriever Agent (Repo 1)"""
        if self.retriever:
            return await self.retriever.retrieve(query, course_id)
        # Fallback to existing RAG
        return self.rag.retrieve_chunks(query, k=5, course_id=course_id)
    
    async def _stage_reason(self, query: str, chunks: list, history: list, profile: dict) -> str:
        """Stage 4: Reasoner Agent (Repo 1 + Repo 2)"""
        if self.reasoner:
            return await self.reasoner.reason(query, chunks, history, profile)
        # Fallback
        answer, _ = self.rag.generate_final_answer(chunks, question=query, history=history)
        return answer
    
    async def _stage_reflect(self, draft: str, chunks: list, query: str) -> tuple:
        """Stage 5: Reflection Agent (Repo 2)"""
        if self.reflection:
            return await self.reflection.reflect_and_refine(draft, chunks, query, self.max_loops)
        # Fallback: no refinement
        return draft, 0.7, 0
```

---

### FILE 3: `services/agentic_rag/agents/query_rewriter.py` (80 lines - Repo 1)

```python
"""
Query Rewriter Agent - Stage 1 of agentic RAG.
Improves query clarity and specificity (Repo 1 pattern).
"""

import logging
from langchain_core.messages import HumanMessage

log = logging.getLogger("SmartTeacher.QueryRewriter")


class QueryRewriterAgent:
    """Rewrites queries to improve retrieval and reasoning."""
    
    def __init__(self, llm):
        self.llm = llm
    
    async def rewrite(self, query: str) -> str:
        """
        Rewrite query for better clarity.
        
        Example:
            Input:  "What is photosynthesis?"
            Output: "Explain the process of photosynthesis in plants, including the light-dependent and light-independent reactions"
        """
        
        prompt = f"""You are a query optimization expert. 
        
Your task: Rewrite this query to be more specific and clear for information retrieval.
- Add relevant context
- Be more specific
- Include learning intent
- Keep it concise

Original query: "{query}"

Rewritten query:"""
        
        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            rewritten = response.content.strip()
            
            # Clean up if LLM adds quotes
            if rewritten.startswith('"') and rewritten.endswith('"'):
                rewritten = rewritten[1:-1]
            
            log.info(f"Rewrite: '{query}' → '{rewritten}'")
            return rewritten
            
        except Exception as e:
            log.error(f"Query rewrite failed: {e}, returning original")
            return query
```

---

### FILE 4: `services/agentic_rag/agents/query_clarifier.py` (80 lines - Repo 1)

```python
"""
Query Clarifier Agent - Stage 2 of agentic RAG.
Checks if query is ambiguous and asks for clarification (Repo 1 pattern).
"""

import logging
from langchain_core.messages import HumanMessage

log = logging.getLogger("SmartTeacher.QueryClarifier")


class QueryClarifierAgent:
    """Detects ambiguous queries and asks for clarification."""
    
    def __init__(self, llm):
        self.llm = llm
    
    async def check_clarity(self, query: str) -> tuple:
        """
        Check if query needs clarification.
        
        Returns:
            (needs_clarification: bool, clarification_question: str)
        """
        
        prompt = f"""You are a clarification specialist.

Analyze this query for ambiguity or missing context:
"{query}"

Respond with:
1. NEEDS_CLARIFICATION: YES or NO
2. If YES, ask ONE specific clarifying question

Format:
NEEDS_CLARIFICATION: [YES/NO]
QUESTION: [your question if YES, or empty if NO]"""
        
        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            content = response.content.strip()
            
            lines = content.split('\n')
            needs_clarif = "YES" in content.upper()
            clarif_q = ""
            
            for line in lines:
                if line.startswith("QUESTION:"):
                    clarif_q = line.replace("QUESTION:", "").strip()
            
            if needs_clarif:
                log.info(f"Clarification needed: {clarif_q}")
            
            return needs_clarif, clarif_q
            
        except Exception as e:
            log.error(f"Clarity check failed: {e}")
            return False, ""
```

---

### FILE 5: `services/agentic_rag/agents/retriever_agent.py` (150 lines - Repo 1)

```python
"""
Retriever Agent - Stage 3 of agentic RAG.
Intelligent chunk retrieval with dual embeddings (Repo 1 + Repo 2 pattern).
"""

import logging
from typing import Optional, List

log = logging.getLogger("SmartTeacher.RetrieverAgent")


class RetrieverAgent:
    """Retrieves relevant chunks using intelligent strategies."""
    
    def __init__(self, rag, embedding_type: str = "dual"):
        """
        Initialize retriever.
        
        Args:
            rag: MultiModalRAG instance
            embedding_type: "semantic" | "keyword" | "dual" (Repo 1 strategy)
        """
        self.rag = rag
        self.embedding_type = embedding_type
    
    async def retrieve(
        self,
        query: str,
        course_id: Optional[str] = None,
        k: int = 5
    ) -> List:
        """
        Retrieve chunks using appropriate strategy.
        
        Strategies (Repo 1):
        - semantic:  Vector search (BAAI/bge-m3)
        - keyword:   BM25 keyword match
        - dual:      Combined (RRF fusion)
        """
        
        if self.embedding_type == "dual":
            return self._retrieve_dual(query, course_id, k)
        elif self.embedding_type == "semantic":
            return self._retrieve_semantic(query, course_id, k)
        else:
            return self._retrieve_keyword(query, course_id, k)
    
    def _retrieve_dual(self, query: str, course_id: Optional[str], k: int) -> List:
        """
        Dual retrieval: Semantic + Keyword (Repo 1 best practice).
        Uses RRF (Reciprocal Rank Fusion) to combine results.
        """
        
        # Semantic search
        semantic_results = self.rag.retrieve_chunks(
            query, k=k, course_id=course_id, strategy="vector"
        )
        
        # Keyword search
        keyword_results = self.rag.retrieve_chunks(
            query, k=k, course_id=course_id, strategy="bm25"
        )
        
        # Fuse using RRF
        fused = self._reciprocal_rank_fusion(semantic_results, keyword_results)
        
        log.info(f"Dual retrieval: {len(semantic_results)} semantic + {len(keyword_results)} keyword → {len(fused)} fused")
        
        return fused[:k]
    
    def _retrieve_semantic(self, query: str, course_id: Optional[str], k: int) -> List:
        """Semantic search only."""
        return self.rag.retrieve_chunks(query, k=k, course_id=course_id, strategy="vector")
    
    def _retrieve_keyword(self, query: str, course_id: Optional[str], k: int) -> List:
        """Keyword search only."""
        return self.rag.retrieve_chunks(query, k=k, course_id=course_id, strategy="bm25")
    
    def _reciprocal_rank_fusion(self, semantic_results: List, keyword_results: List) -> List:
        """
        Fuse two ranking lists using RRF (Repo 1 pattern).
        
        Formula: RRF(d) = sum(1 / (k + rank(d)))
        where k=60 (standard)
        """
        
        rrf_scores = {}
        k = 60
        
        # Score semantic results
        for rank, result in enumerate(semantic_results, 1):
            doc_id = self._get_doc_id(result)
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + 1 / (k + rank)
        
        # Score keyword results
        for rank, result in enumerate(keyword_results, 1):
            doc_id = self._get_doc_id(result)
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + 1 / (k + rank)
        
        # Sort by RRF score
        sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        
        # Reconstruct results list
        fused = []
        for doc_id, score in sorted_docs:
            # Find original result
            for result in semantic_results + keyword_results:
                if self._get_doc_id(result) == doc_id:
                    fused.append(result)
                    break
        
        return fused
    
    def _get_doc_id(self, result) -> str:
        """Extract document ID for deduplication."""
        if hasattr(result, 'metadata'):
            return result.metadata.get('id', str(result))
        return str(result)
```

---

### FILE 6: `services/agentic_rag/agents/reasoner_agent.py` (200 lines - Repo 1 + Repo 2)

```python
"""
Reasoner Agent - Stage 4 of agentic RAG.
Multi-agent reasoning with memory integration (Repo 1 + Repo 2).
"""

import logging
from typing import List, Optional, Dict
from langchain_core.messages import HumanMessage, SystemMessage

log = logging.getLogger("SmartTeacher.ReasonerAgent")


class ReasonerAgent:
    """
    Performs multi-step reasoning over retrieved chunks.
    Incorporates memory and student context (Repo 2 pattern).
    """
    
    def __init__(self, llm, short_term_memory=None, long_term_memory=None):
        self.llm = llm
        self.short_term_memory = short_term_memory
        self.long_term_memory = long_term_memory
    
    async def reason(
        self,
        query: str,
        chunks: List,
        history: List[Dict] = None,
        student_profile: Dict = None
    ) -> str:
        """
        Generate answer from chunks using multi-step reasoning.
        
        Args:
            query: Original question (rewritten)
            chunks: Retrieved context chunks
            history: Conversation history (Repo 2 memory)
            student_profile: Student info (Phase 2)
            
        Returns:
            str: Reasoning-based answer
        """
        
        # Build context from chunks (Repo 1)
        chunk_context = self._build_chunk_context(chunks)
        
        # Build memory context (Repo 2)
        memory_context = self._build_memory_context(history)
        
        # Build personalization context (Phase 2)
        profile_context = self._build_profile_context(student_profile)
        
        # System prompt for reasoning
        system_prompt = f"""You are an expert educational tutor using Smart Teacher.

CONTEXT FROM DOCUMENTS:
{chunk_context}

{memory_context}

{profile_context}

Your task: Answer the student's question thoroughly and clearly."""
        
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=query)
            ])
            
            answer = response.content.strip()
            log.info(f"Reasoning generated: {len(answer)} chars")
            return answer
            
        except Exception as e:
            log.error(f"Reasoning failed: {e}")
            return "Unable to generate reasoning at this time."
    
    def _build_chunk_context(self, chunks: List) -> str:
        """Build context string from chunks."""
        if not chunks:
            return "No relevant context found."
        
        context_parts = []
        for i, chunk in enumerate(chunks[:3], 1):  # Top 3
            content = chunk.page_content if hasattr(chunk, 'page_content') else str(chunk)
            context_parts.append(f"[Source {i}]\n{content[:500]}...\n")
        
        return "\n".join(context_parts)
    
    def _build_memory_context(self, history: Optional[List[Dict]]) -> str:
        """Build context from conversation history (Repo 2 memory)."""
        if not history:
            return ""
        
        recent = history[-4:] if len(history) > 4 else history  # Last 2 exchanges
        memory_str = "\nRECENT CONVERSATION:\n"
        for msg in recent:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")[:200]
            memory_str += f"{role}: {content}\n"
        
        return memory_str
    
    def _build_profile_context(self, profile: Optional[Dict]) -> str:
        """Build context from student profile (Phase 2 feature)."""
        if not profile:
            return ""
        
        return f"\nSTUDENT CONTEXT:\n- Learning level: {profile.get('level', 'unknown')}\n"
```

---

### FILE 7: `services/agentic_rag/agents/reflection_agent.py` (100 lines - Repo 2)

```python
"""
Reflection Agent - Stage 5 of agentic RAG.
Validates answer quality and refines if needed (Repo 2 pattern).
"""

import logging
from langchain_core.messages import HumanMessage, SystemMessage

log = logging.getLogger("SmartTeacher.ReflectionAgent")


class ReflectionAgent:
    """
    Reflects on generated answer and refines if quality is low.
    Self-correction mechanism (Repo 2 pattern).
    """
    
    def __init__(self, llm):
        self.llm = llm
    
    async def reflect_and_refine(
        self,
        draft_answer: str,
        chunks: list,
        original_query: str,
        max_loops: int = 3
    ) -> tuple:
        """
        Validate answer quality and refine if needed.
        
        Returns:
            (final_answer: str, confidence: float, refinement_count: int)
        """
        
        current_answer = draft_answer
        confidence = 0.7  # Default
        refinement_count = 0
        
        for loop in range(max_loops):
            # Evaluate quality
            quality_score, feedback = await self._evaluate_answer(
                current_answer, chunks, original_query
            )
            
            log.info(f"Loop {loop+1}: Quality score = {quality_score:.2f}")
            
            if quality_score >= 0.80:
                # Good enough
                confidence = quality_score
                log.info(f"✅ Answer quality acceptable")
                break
            
            if loop < max_loops - 1:
                # Refine
                log.info(f"🔄 Refining answer (feedback: {feedback[:50]}...)")
                current_answer = await self._refine_answer(
                    current_answer, feedback, chunks
                )
                refinement_count += 1
            else:
                confidence = quality_score
                log.info(f"⚠️ Max refinements reached, using current answer")
        
        return current_answer, confidence, refinement_count
    
    async def _evaluate_answer(self, answer: str, chunks: list, query: str) -> tuple:
        """
        Evaluate answer quality.
        
        Returns:
            (score: float [0-1], feedback: str)
        """
        
        prompt = f"""Evaluate this answer to the query:

QUERY: {query}

ANSWER: {answer}

Rate 0-100:
1. Is it accurate based on common knowledge?
2. Is it clear and well-structured?
3. Does it address the question fully?
4. Is the length appropriate?

Give a final score (0-100) and brief feedback.

Format:
SCORE: [0-100]
FEEDBACK: [specific suggestions]"""
        
        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            content = response.content.strip()
            
            # Extract score
            score = 70  # Default
            for line in content.split('\n'):
                if line.startswith("SCORE:"):
                    try:
                        score = int(line.split(":")[-1].strip())
                    except:
                        pass
            
            # Extract feedback
            feedback = ""
            for line in content.split('\n'):
                if line.startswith("FEEDBACK:"):
                    feedback = line.split(":", 1)[-1].strip()
            
            return score / 100, feedback
            
        except Exception as e:
            log.error(f"Evaluation failed: {e}")
            return 0.7, "Unable to evaluate"
    
    async def _refine_answer(self, answer: str, feedback: str, chunks: list) -> str:
        """Improve answer based on feedback."""
        
        prompt = f"""Based on feedback, improve this answer:

ORIGINAL: {answer[:300]}

FEEDBACK: {feedback}

Provide an improved version that addresses the feedback.
Keep it concise but complete."""
        
        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            return response.content.strip()
        except:
            return answer
```

---

### FILE 8: `services/agentic_rag/memory/short_term.py` (80 lines - Repo 2)

```python
"""
Short-term Memory - Session-based context (Repo 2 pattern).
"""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger("SmartTeacher.ShortTermMemory")


@dataclass
class MemoryItem:
    role: str        # "user" | "assistant"
    content: str
    timestamp: datetime


class ShortTermMemory:
    """
    Session memory for current conversation.
    Keeps last N exchanges (default: 5).
    """
    
    def __init__(self, max_items: int = 10):
        self.messages = deque(maxlen=max_items)
    
    def add(self, role: str, content: str):
        """Add message to memory."""
        item = MemoryItem(
            role=role,
            content=content,
            timestamp=datetime.now()
        )
        self.messages.append(item)
        log.debug(f"Added {role} message: {len(content)} chars")
    
    def get_context(self) -> str:
        """Get formatted context for LLM."""
        if not self.messages:
            return ""
        
        context = "RECENT CONVERSATION:\n"
        for item in list(self.messages)[-4:]:  # Last 2 exchanges
            context += f"{item.role.upper()}: {item.content}\n"
        
        return context
    
    def clear(self):
        """Clear memory."""
        self.messages.clear()
    
    def get_history(self) -> list:
        """Get message history as list of dicts."""
        return [
            {"role": item.role, "content": item.content}
            for item in self.messages
        ]
```

---

## 🎬 PHASE 1 IMPLEMENTATION SEQUENCE

### Step 1: Create folder structure
```bash
mkdir -p services/agentic_rag/{agents,memory,retrieval,utils}
touch services/agentic_rag/__init__.py
```

### Step 2: Create core files in order
```
1. services/agentic_rag/__init__.py
2. services/agentic_rag/orchestrator.py       ← MOST IMPORTANT
3. services/agentic_rag/agents/__init__.py
4. services/agentic_rag/agents/query_rewriter.py
5. services/agentic_rag/agents/query_clarifier.py
6. services/agentic_rag/agents/retriever_agent.py
7. services/agentic_rag/agents/reasoner_agent.py
8. services/agentic_rag/agents/reflection_agent.py
9. services/agentic_rag/memory/__init__.py
10. services/agentic_rag/memory/short_term.py
```

### Step 3: Update existing files
```
1. config.py              (add 2 lines)
2. services/app_state.py  (add 10 lines)
3. api/search.py          (modify routing)
4. .env                   (add RAG_MODE flag)
```

### Step 4: Test
```python
# In app_state.py after initializing services:
from services.agentic_rag.orchestrator import AgenticRAGOrchestrator
agentic_executor = AgenticRAGOrchestrator(
    llm=language_brain,
    rag=knowledge_retrieval_engine
)
```

---

## ✅ SUCCESS CHECKLIST

- [ ] Folder structure created
- [ ] All 10 core files implemented
- [ ] config.py updated with RAG_MODE
- [ ] app_state.py updated
- [ ] api/search.py routing added
- [ ] .env has RAG_MODE=classic
- [ ] Can switch to RAG_MODE=agentic
- [ ] Tests pass without errors
- [ ] Response time 2-4 seconds

---

## 📝 NEXT: Phase 2 Setup

After Phase 1 works, Phase 2 adds:
```
- services/agentic_rag/memory/long_term.py
- services/agentic_rag/profiles/student_profile.py
- services/agentic_rag/profiles/profile_manager.py
- Personalized responses
```
