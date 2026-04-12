"""
╔══════════════════════════════════════════════════════════════════════╗
║        SMART TEACHER — Recherche Historique (Elasticsearch)        ║
║                                                                      ║
║  Indexe et recherche dans l'historique des transcriptions :         ║
║    - Toutes les questions posées par les étudiants                  ║
║    - Toutes les réponses du professeur IA                           ║
║    - Recherche full-text multilingue                                ║
║    - Agrégations par cours, étudiant, date                         ║
║                                                                      ║
║  Si Elasticsearch non dispo → fallback PostgreSQL (LIKE query)     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os
import time
import logging
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

log = logging.getLogger("SmartTeacher.Search")

ES_HOST     = os.getenv("ELASTICSEARCH_HOST", "http://localhost:9200")   # ex: http://localhost:9200
ES_USER     = os.getenv("ELASTICSEARCH_USER", "")
ES_PASSWORD = os.getenv("ELASTICSEARCH_PASSWORD", "")
ES_INDEX    = "smart_teacher_transcripts"


@dataclass
class TranscriptEntry:
    session_id:   str
    student_id:   str  = ""
    course_id:    str  = ""
    course_title: str  = ""
    language:     str  = "fr"
    role:         str  = "student"   # student | teacher
    text:         str  = ""
    subject:      str  = ""
    timestamp:    float = 0.0

    def to_doc(self) -> dict:
        d = asdict(self)
        d["@timestamp"] = datetime.utcfromtimestamp(self.timestamp or time.time()).isoformat() + "Z"
        return d


class TranscriptSearcher:
    """
    Indexe les transcriptions et permet la recherche full-text.
    Fallback PostgreSQL si Elasticsearch absent.
    """

    def __init__(self):
        self._es = None
        self._use_es = False
        self._memory_index: list[TranscriptEntry] = []  # fallback mémoire
        self._init_es()

    def _init_es(self):
        if not ES_HOST:
            log.info("🔍 Elasticsearch non configuré → recherche en mémoire")
            return
        try:
            from elasticsearch import Elasticsearch
            kwargs: dict = {"hosts": [ES_HOST]}
            if ES_USER:
                kwargs["basic_auth"] = (ES_USER, ES_PASSWORD)
            # ⬇️ Ajouter timeout rapide pour fallback si Elasticsearch non dispo
            self._es = Elasticsearch(**kwargs, request_timeout=2)
            if self._es.ping(request_timeout=2):
                self._ensure_index()
                self._use_es = True
                log.info("✅ Elasticsearch connecté : %s", ES_HOST)
            else:
                log.info("ℹ️ Elasticsearch ping failed → recherche en mémoire")
        except ImportError:
            log.info("ℹ️ elasticsearch-py non installé → recherche en mémoire")
        except Exception as e:
            log.info("ℹ️ Elasticsearch non dispo (%s) → recherche en mémoire", e)

    def _ensure_index(self):
        """Crée l'index avec le bon mapping si absent."""
        if self._es.indices.exists(index=ES_INDEX):
            return
        self._es.indices.create(index=ES_INDEX, body={
            "settings": {
                "number_of_shards":   1,
                "number_of_replicas": 0,
                "analysis": {
                    "analyzer": {
                        "multilang": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase", "asciifolding"],
                        }
                    }
                }
            },
            "mappings": {
                "properties": {
                    "session_id":   {"type": "keyword"},
                    "student_id":   {"type": "keyword"},
                    "course_id":    {"type": "keyword"},
                    "course_title": {"type": "text",    "analyzer": "multilang"},
                    "language":     {"type": "keyword"},
                    "role":         {"type": "keyword"},
                    "text":         {"type": "text",    "analyzer": "multilang"},
                    "subject":      {"type": "keyword"},
                    "@timestamp":   {"type": "date"},
                }
            }
        })
        log.info("📋 Index Elasticsearch créé : %s", ES_INDEX)

    # ── Indexation ────────────────────────────────────────────────────────

    def index(self, entry: TranscriptEntry) -> bool:
        """Indexe une entrée de transcription."""
        if not entry.timestamp:
            entry.timestamp = time.time()

        if self._use_es:
            try:
                self._es.index(index=ES_INDEX, document=entry.to_doc())
                return True
            except Exception as e:
                log.info("ℹ️ ES index error (%s) → fallback mémoire", e)
                self._use_es = False

        # Fallback mémoire (garder les 5000 derniers)
        self._memory_index.append(entry)
        if len(self._memory_index) > 5000:
            self._memory_index.pop(0)
        return True

    def index_interaction(self, session_id: str, student_q: str, teacher_a: str,
                          language: str = "fr", course_id: str = "",
                          course_title: str = "", subject: str = "") -> None:
        """Raccourci pour indexer question + réponse en un appel."""
        ts = time.time()
        self.index(TranscriptEntry(
            session_id=session_id, language=language,
            course_id=course_id, course_title=course_title,
            role="student", text=student_q, subject=subject, timestamp=ts,
        ))
        self.index(TranscriptEntry(
            session_id=session_id, language=language,
            course_id=course_id, course_title=course_title,
            role="teacher", text=teacher_a, subject=subject, timestamp=ts + 0.001,
        ))

    # ── Recherche ─────────────────────────────────────────────────────────

    def search(self, query: str, language: str = "", course_id: str = "",
               role: str = "", limit: int = 20) -> list[dict]:
        """
        Recherche full-text dans les transcriptions.
        Retourne les résultats triés par pertinence.
        """
        if self._use_es:
            return self._es_search(query, language, course_id, role, limit)
        return self._memory_search(query, language, course_id, role, limit)

    def _es_search(self, query, language, course_id, role, limit) -> list[dict]:
        must = [{"multi_match": {
            "query": query,
            "fields": ["text^3", "course_title^2", "subject"],
            "type": "best_fields",
        }}]
        filters = []
        if language: filters.append({"term": {"language": language}})
        if course_id: filters.append({"term": {"course_id": course_id}})
        if role: filters.append({"term": {"role": role}})

        body = {
            "query": {"bool": {"must": must, "filter": filters}},
            "sort":  [{"@timestamp": "desc"}],
            "size":  limit,
            "highlight": {"fields": {"text": {}}},
        }
        try:
            r = self._es.search(index=ES_INDEX, body=body)
            results = []
            for hit in r["hits"]["hits"]:
                doc = hit["_source"]
                doc["_score"]     = hit["_score"]
                doc["_highlight"] = hit.get("highlight", {}).get("text", [])
                results.append(doc)
            return results
        except Exception as e:
            log.info("ℹ️ ES search error (%s) → fallback mémoire", e)
            self._use_es = False
            return self._memory_search(query, language, course_id, role, limit)

    def _memory_search(self, query, language, course_id, role, limit) -> list[dict]:
        q = query.lower()
        results = []
        for entry in reversed(self._memory_index):
            if q not in entry.text.lower():
                continue
            if language and entry.language != language:
                continue
            if course_id and entry.course_id != course_id:
                continue
            if role and entry.role != role:
                continue
            results.append(entry.to_doc())
            if len(results) >= limit:
                break
        return results

    def get_session_history(self, session_id: str) -> list[dict]:
        """Retourne tout l'historique d'une session."""
        if self._use_es:
            try:
                r = self._es.search(index=ES_INDEX, body={
                    "query": {"term": {"session_id": session_id}},
                    "sort":  [{"@timestamp": "asc"}],
                    "size":  500,
                })
                return [h["_source"] for h in r["hits"]["hits"]]
            except Exception:
                pass
        return [asdict(e) for e in self._memory_index if e.session_id == session_id]

    def get_stats(self) -> dict:
        """Statistiques globales sur les transcriptions indexées."""
        if self._use_es:
            try:
                r = self._es.count(index=ES_INDEX)
                return {"backend": "elasticsearch", "total": r["count"],
                        "index": ES_INDEX, "host": ES_HOST}
            except Exception:
                pass
        return {"backend": "memory", "total": len(self._memory_index),
                "note": "Configurez ELASTICSEARCH_HOST pour la persistance"}


# Singleton
_searcher: Optional[TranscriptSearcher] = None

def get_searcher() -> TranscriptSearcher:
    global _searcher
    if _searcher is None:
        _searcher = TranscriptSearcher()
    return _searcher
