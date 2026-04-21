"""Context compression for token management"""
import logging
from typing import List, Dict, Any, Optional

log = logging.getLogger("SmartTeacher.ContextCompressor")

class ContextCompressor:
    """Compresses conversation history to fit token limits"""
    
    def __init__(self, llm=None, token_limit: int = 3000):
        self.llm = llm
        self.token_limit = token_limit
    
    async def compress_if_needed(self, history: List[Dict[str, Any]], current_tokens: int) -> List[Dict[str, Any]]:
        """Compress history if approaching token limit"""
        if current_tokens < self.token_limit:
            return history
        
        try:
            log.info(f"Compressing history ({current_tokens} tokens > {self.token_limit} limit)")
            
            if len(history) > 5:
                history = history[-5:]
            
            if self.llm and len(history) > 3:
                pass
            
            log.info(f"Compression complete ({len(history)} exchanges retained)")
            return history
        
        except Exception as e:
            log.error(f"Compression failed: {e}")
            return history[-3:]
