"""Integration test for Phase 1B - Agentic RAG"""
import pytest
import asyncio
from services.agentic_rag.orchestrator import AgenticRAGOrchestrator, AgenticRAGState


class MockLLM:
    """Mock LLM for testing"""
    async def agenerate(self, messages, temperature=0.7, max_tokens=100):
        class Response:
            content = "This is a test response about the query."
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


if __name__ == "__main__":
    print("Running Phase 1B integration tests...")
    pytest.main([__file__, "-v"])
