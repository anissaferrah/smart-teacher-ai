"""LangGraph Workflow for 5-stage agentic RAG"""
import logging
from services.agentic_rag.agents.query_rewriter import QueryRewriter
from services.agentic_rag.agents.query_clarifier import QueryClarifier
from services.agentic_rag.agents.retriever_agent import RetrieverAgent
from services.agentic_rag.agents.reasoner_agent import ReasonerAgent
from services.agentic_rag.agents.reflection_agent import ReflectionAgent

log = logging.getLogger("SmartTeacher.Workflow")

class AgenticRAGWorkflow:
    """5-stage workflow with conditional routing"""
    
    def __init__(self, llm, rag, hybrid_retriever=None, short_term_memory=None, long_term_memory=None):
        self.llm = llm
        self.rag = rag
        self.hybrid_retriever = hybrid_retriever
        self.rewriter = QueryRewriter(llm)
        self.clarifier = QueryClarifier(llm)
        self.retriever = RetrieverAgent(rag, hybrid_retriever)
        self.reasoner = ReasonerAgent(llm, short_term_memory, long_term_memory)
        self.reflection = ReflectionAgent(llm)
        log.info("Workflow initialized with 5 agents")

    async def execute_pipeline(self, state):
        """Execute all stages sequentially"""
        log.info("→ Stage 1: Rewrite")
        state.rewritten_query = await self.rewriter.rewrite(state.query)
        
        log.info("→ Stage 2: Clarify")
        needs_clarif, clarif_q = await self.clarifier.check_clarity(state.rewritten_query)
        if needs_clarif:
            state.needs_clarification = True
            state.clarification_question = clarif_q
            return state
        
        log.info("→ Stage 3: Retrieve")
        state.retrieved_chunks = await self.retriever.retrieve(state.rewritten_query, k=5)
        
        log.info("→ Stage 4: Reason")
        state.draft_answer = await self.reasoner.reason(state.rewritten_query, state.retrieved_chunks)
        
        log.info("→ Stage 5: Reflect")
        state.final_answer, state.confidence, state.loop_count = await self.reflection.reflect_and_refine(
            state.draft_answer, state.retrieved_chunks, state.rewritten_query
        )
        
        return state
