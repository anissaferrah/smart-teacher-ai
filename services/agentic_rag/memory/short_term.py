"""Short-term memory for recent conversation exchanges"""
import logging
from typing import List, Optional
from datetime import datetime
from services.agentic_rag.schemas import ConversationExchange

log = logging.getLogger("SmartTeacher.ShortTermMemory")

class ShortTermMemory:
    """Stores last 5 conversation exchanges"""
    
    def __init__(self, max_exchanges: int = 5):
        self.max_exchanges = max_exchanges
        self.exchanges: List[ConversationExchange] = []
    
    def add_exchange(self, query: str, answer: str, confusion_detected: bool = False, confusion_type: Optional[str] = None):
        """Add an exchange to memory"""
        exchange = ConversationExchange(
            student_query=query,
            ai_answer=answer,
            timestamp=datetime.now(),
            confusion_detected=confusion_detected,
            confusion_type=confusion_type
        )
        self.exchanges.append(exchange)
        
        if len(self.exchanges) > self.max_exchanges:
            self.exchanges.pop(0)
        
        log.info(f"Added exchange (total: {len(self.exchanges)})")
    
    def get_context(self) -> str:
        """Get formatted context from recent exchanges"""
        if not self.exchanges:
            return ""
        
        context = "Recent conversation:\n"
        for i, ex in enumerate(self.exchanges[-3:], 1):
            context += f"{i}. Q: {ex.student_query}\n   A: {ex.ai_answer[:100]}...\n"
        
        return context
    
    def clear(self):
        """Clear all exchanges"""
        self.exchanges = []
        log.info("Short-term memory cleared")
