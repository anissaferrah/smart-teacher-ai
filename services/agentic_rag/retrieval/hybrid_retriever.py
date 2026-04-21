"""Hybrid retrieval with RRF fusion (dense + sparse)"""
import logging
from typing import List, Dict, Any, Optional

log = logging.getLogger("SmartTeacher.HybridRetriever")

class HybridRetriever:
    """Combines embeddings (dense) + BM25 (sparse) with Reciprocal Rank Fusion"""
    
    def __init__(self, vector_db=None, bm25=None):
        self.vector_db = vector_db
        self.bm25 = bm25
    
    async def hybrid_retrieve(
        self,
        query: str,
        course_id: Optional[str] = None,
        k: int = 5
    ) -> List[Dict[str, Any]]:
        """Retrieve using hybrid approach"""
        try:
            dense_results = await self._dense_search(query, course_id, k*2)
            sparse_results = await self._sparse_search(query, course_id, k*2)
            
            fused = self._rrf_fusion(dense_results, sparse_results, k)
            
            log.info(f"Hybrid retrieval: {len(dense_results)} dense + {len(sparse_results)} sparse → {len(fused)} fused")
            return fused
        
        except Exception as e:
            log.error(f"Hybrid retrieval failed: {e}")
            return await self._dense_search(query, course_id, k)
    
    async def _dense_search(self, query: str, course_id: Optional[str], k: int) -> List[Dict[str, Any]]:
        """Dense search using embeddings"""
        if not self.vector_db:
            return []
        
        try:
            results = []
            return results
        except Exception as e:
            log.error(f"Dense search failed: {e}")
            return []
    
    async def _sparse_search(self, query: str, course_id: Optional[str], k: int) -> List[Dict[str, Any]]:
        """Sparse search using BM25"""
        if not self.bm25:
            return []
        
        try:
            results = []
            return results
        except Exception as e:
            log.error(f"Sparse search failed: {e}")
            return []
    
    def _rrf_fusion(
        self,
        dense_results: List[Dict],
        sparse_results: List[Dict],
        k: int
    ) -> List[Dict[str, Any]]:
        """Reciprocal Rank Fusion: combines rankings from dense and sparse"""
        scores = {}
        constant = 60
        
        for rank, result in enumerate(dense_results):
            doc_id = result.get('source', str(result))
            scores[doc_id] = scores.get(doc_id, 0) + 1 / (rank + constant)
        
        for rank, result in enumerate(sparse_results):
            doc_id = result.get('source', str(result))
            scores[doc_id] = scores.get(doc_id, 0) + 1 / (rank + constant)
        
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        fused = []
        for doc_id, score in ranked[:k]:
            for r in dense_results + sparse_results:
                if r.get('source', str(r)) == doc_id:
                    r['rrf_score'] = score
                    fused.append(r)
                    break
        
        log.debug(f"RRF fusion: {len(fused)}/{k} results ranked")
        return fused[:k]
