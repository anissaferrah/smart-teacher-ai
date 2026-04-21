"""Unified analytics event sink using ClickHouse.

This module provides a single point for all analytics events:
- Learning events (student interactions, QA, quizzes)
- Performance metrics (latency, resource usage)
- System events (errors, warnings, trace points)

All events are serialized to ClickHouse for long-term storage and analysis.
This replaces CSV logging and other ad-hoc metrics collection.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from infrastructure.config import settings
from infrastructure.logging import get_logger

log = get_logger(__name__)


class AnalyticsSink:
    """Unified sink for all analytics events to ClickHouse."""
    
    def __init__(self):
        """Initialize the analytics sink."""
        self.enabled = settings.analytics.clickhouse_enabled
        self.host = settings.analytics.clickhouse_host
        self.port = settings.analytics.clickhouse_port
        self.database = settings.analytics.clickhouse_db
        
        # Lazy-loaded ClickHouse client
        self._client = None
        
        if self.enabled:
            log.info(f"AnalyticsSink initialized (ClickHouse: {self.host}:{self.port}/{self.database})")
        else:
            log.warning("AnalyticsSink disabled - events will not be persisted")
    
    @property
    def client(self):
        """Lazy-load ClickHouse client."""
        if self._client is None and self.enabled:
            try:
                from clickhouse_driver import Client
                self._client = Client(host=self.host, port=self.port, database=self.database)
                log.info("ClickHouse client connected")
            except Exception as e:
                log.error(f"Failed to connect to ClickHouse: {e}")
                self._client = None
        return self._client
    
    def record(self, event_type: str, data: Dict[str, Any], session_id: Optional[str] = None) -> None:
        """Record an analytics event.
        
        Args:
            event_type: Type of event (e.g., 'learning_turn', 'latency', 'error')
            data: Event payload (dictionary of event-specific fields)
            session_id: Optional session ID for correlation
            
        Example:
            sink.record(
                'learning_turn',
                {
                    'question': 'What is photosynthesis?',
                    'answer': '...',
                    'language': 'fr',
                    'course_id': 'bio-101',
                    'stt_time_ms': 250,
                    'llm_time_ms': 1200,
                    'tts_time_ms': 800,
                    'confusion_detected': True,
                    'confusion_reason': 'incorrect terminology',
                },
                session_id='sess-123',
            )
        """
        try:
            timestamp = datetime.utcnow().isoformat()
            event = {
                'timestamp': timestamp,
                'event_type': event_type,
                'session_id': session_id,
                'data': json.dumps(data) if isinstance(data, dict) else data,
            }
            
            if self.enabled and self.client:
                # Insert into ClickHouse events table
                self._insert_event(event)
            else:
                # Fallback: just log the event
                log.debug(f"[ANALYTICS] {event_type}: {data}")
        
        except Exception as e:
            log.error(f"Failed to record analytics event: {e}")
    
    def record_learning_turn(
        self,
        session_id: str,
        question_text: str,
        answer_text: str,
        language: str,
        subject: str,
        course_id: Optional[str] = None,
        confusion_detected: bool = False,
        confusion_reason: str = "",
        stt_time_ms: float = 0.0,
        llm_time_ms: float = 0.0,
        tts_time_ms: float = 0.0,
        total_time_ms: float = 0.0,
        rag_chunks: int = 0,
        rag_score: float = 0.0,
        student_level: str = "",
        chapter_index: Optional[int] = None,
        section_index: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a learning interaction turn.
        
        Args:
            session_id: Session identifier
            question_text: Student's question/input
            answer_text: AI's response
            language: Language code (e.g., 'fr', 'en')
            subject: Subject area (e.g., 'math', 'history')
            course_id: Optional course identifier
            confusion_detected: Whether confusion was detected
            confusion_reason: Reason for confusion detection
            stt_time_ms: Speech-to-text processing time
            llm_time_ms: LLM response generation time
            tts_time_ms: Text-to-speech synthesis time
            total_time_ms: Total interaction time
            rag_chunks: Number of RAG documents retrieved
            rag_score: Average RAG relevance score
            student_level: Student proficiency level
            chapter_index: Course chapter index
            section_index: Course section index
            extra: Additional event-specific fields
        """
        data = {
            'question': question_text,
            'answer': answer_text,
            'language': language,
            'subject': subject,
            'course_id': course_id,
            'confusion_detected': confusion_detected,
            'confusion_reason': confusion_reason,
            'stt_time_ms': stt_time_ms,
            'llm_time_ms': llm_time_ms,
            'tts_time_ms': tts_time_ms,
            'total_time_ms': total_time_ms,
            'rag_chunks': rag_chunks,
            'rag_score': rag_score,
            'student_level': student_level,
            'chapter_index': chapter_index,
            'section_index': section_index,
        }
        if extra:
            data.update(extra)
        
        self.record('learning_turn', data, session_id=session_id)
    
    def record_latency(
        self,
        session_id: str,
        component: str,
        duration_ms: float,
        status: str = "ok",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record performance/latency metric.
        
        Args:
            session_id: Session identifier
            component: Component name (e.g., 'stt', 'llm', 'tts', 'rag')
            duration_ms: Duration in milliseconds
            status: Status (ok/timeout/error)
            metadata: Additional metadata
        """
        data = {
            'component': component,
            'duration_ms': duration_ms,
            'status': status,
        }
        if metadata:
            data.update(metadata)
        
        self.record('latency', data, session_id=session_id)
    
    def record_error(
        self,
        session_id: str,
        component: str,
        error_type: str,
        error_message: str,
        traceback: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record an error event.
        
        Args:
            session_id: Session identifier
            component: Component where error occurred
            error_type: Error class name
            error_message: Error message
            traceback: Full traceback if available
            metadata: Additional context
        """
        data = {
            'component': component,
            'error_type': error_type,
            'error_message': error_message,
            'traceback': traceback,
        }
        if metadata:
            data.update(metadata)
        
        self.record('error', data, session_id=session_id)
    
    def _insert_event(self, event: Dict[str, Any]) -> None:
        """Insert event into ClickHouse (internal method).
        
        Args:
            event: Event record
        """
        if not self.client:
            return
        
        try:
            # Ensure events table exists
            self._ensure_table()
            
            # Insert the event
            self.client.insert(
                'events',
                [
                    (
                        event['timestamp'],
                        event['event_type'],
                        event['session_id'],
                        event['data'],
                    )
                ],
                column_names=['timestamp', 'event_type', 'session_id', 'data'],
            )
        except Exception as e:
            log.error(f"Failed to insert event into ClickHouse: {e}")
    
    def _ensure_table(self) -> None:
        """Ensure events table exists in ClickHouse."""
        if not self.client:
            return
        
        try:
            self.client.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    timestamp DateTime,
                    event_type String,
                    session_id Nullable(String),
                    data String
                ) ENGINE = MergeTree()
                ORDER BY (timestamp, event_type)
            """)
        except Exception as e:
            log.error(f"Failed to create events table: {e}")
    
    def query_events(
        self,
        event_type: Optional[str] = None,
        session_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Query events from ClickHouse.
        
        Args:
            event_type: Filter by event type
            session_id: Filter by session ID
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            limit: Result limit
            
        Returns:
            List of events
        """
        if not self.client:
            return []
        
        try:
            filters = []
            if event_type:
                filters.append(f"event_type = '{event_type}'")
            if session_id:
                filters.append(f"session_id = '{session_id}'")
            if start_time:
                filters.append(f"timestamp >= '{start_time}'")
            if end_time:
                filters.append(f"timestamp <= '{end_time}'")
            
            where_clause = " AND ".join(filters) if filters else "1=1"
            
            query = f"""
                SELECT timestamp, event_type, session_id, data
                FROM events
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT {limit}
            """
            
            results = self.client.execute(query)
            return [
                {
                    'timestamp': row[0],
                    'event_type': row[1],
                    'session_id': row[2],
                    'data': json.loads(row[3]) if isinstance(row[3], str) else row[3],
                }
                for row in results
            ]
        except Exception as e:
            log.error(f"Failed to query events: {e}")
            return []


# Singleton instance
_analytics_sink: Optional[AnalyticsSink] = None


def get_analytics_sink() -> AnalyticsSink:
    """Get or create the global analytics sink.
    
    Returns:
        AnalyticsSink: Global singleton instance
    """
    global _analytics_sink
    if _analytics_sink is None:
        _analytics_sink = AnalyticsSink()
    return _analytics_sink


__all__ = [
    "AnalyticsSink",
    "get_analytics_sink",
]
