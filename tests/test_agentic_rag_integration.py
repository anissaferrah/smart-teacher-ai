"""Integration test for Phase 1B - Agentic RAG"""
import pytest
import asyncio
from services.agentic_rag.orchestrator import AgenticRAGOrchestrator, AgenticRAGState


class MockLLM:
    """Mock LLM for testing"""
    async def agenerate(self, messages, temperature=0.7, max_tokens=100):
        system_prompt = ""
        user_prompt = ""
        if messages:
            system_prompt = str(messages[0].get("content", "")).lower()
            if len(messages) > 1:
                user_prompt = str(messages[1].get("content", "")).lower()

        class Response:
            content = "This is a test response about the query."

        if "clarification assistant" in system_prompt or "clear_to_proceed" in system_prompt:
            Response.content = "CLEAR_TO_PROCEED"
        elif "clarify" in user_prompt and "question" in user_prompt:
            Response.content = "CLEAR_TO_PROCEED"
        elif "query rewriter" in system_prompt or "rewrite" in system_prompt:
            Response.content = "Explain photosynthesis in plants and its role in energy conversion."
        elif "answer quality validator" in system_prompt or "validate" in user_prompt:
            Response.content = "CONFIDENCE: 0.85\nFEEDBACK: good\nREADY: YES"
        elif "expert tutor" in system_prompt or "provide a clear answer" in user_prompt:
            Response.content = "Photosynthesis converts light energy into chemical energy using light reactions and the Calvin cycle."
        elif "answer aggregator" in system_prompt or "merge the sub-answers" in user_prompt:
            Response.content = "Photosynthesis converts light energy into chemical energy using light reactions and the Calvin cycle."
        return Response()


class MockRAG:
    """Mock RAG for testing"""
    async def retrieve_chunks(self, query, k=5, course_id=None):
        return [
            {"content": "Sample educational content 1", "source": "chapter_1"},
            {"content": "Sample educational content 2", "source": "chapter_2"},
        ]


@pytest.mark.asyncio
async def test_orchestrator_initialization():
    """Test orchestrator initializes correctly"""
    llm = MockLLM()
    rag = MockRAG()
    orchestrator = AgenticRAGOrchestrator(llm, rag)
    
    assert orchestrator.query_rewriter is not None
    assert orchestrator.query_clarifier is not None
    assert orchestrator.retriever is not None
    assert orchestrator.reasoner is not None
    assert orchestrator.reflection is not None


@pytest.mark.asyncio
async def test_pipeline_execution():
    """Test full pipeline execution"""
    llm = MockLLM()
    rag = MockRAG()
    orchestrator = AgenticRAGOrchestrator(llm, rag)
    
    result = await orchestrator.answer_question(
        query="What is photosynthesis?",
        course_id="bio101",
        language="en"
    )
    
    assert "answer" in result
    assert "confidence" in result
    assert result["mode"] == "agentic"
    assert result["sources"]


if __name__ == "__main__":
    print("Running Phase 1B integration tests...")
    pytest.main([__file__, "-v"])
