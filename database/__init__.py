"""Database package for Smart Teacher.

The persistence layer now lives in the package files under `database.core`,
`database.models`, and `database.repositories`.
"""

from database.core import (
    database_engine,
    database_session_factory,
    create_database_tables,
    get_database_session,
    test_database_connection,
)
from database.models import (
    Base,
    Student,
    Course,
    Chapter,
    Section,
    Concept,
    LearningSession,
    Interaction,
    LearningEvent,
    StudentProfile,
    StudentMistake,
    RAGChunk,
    SystemLog,
    PerformanceMetric,
    LLMCache,
)
from database.repositories import (
    create_student_account,
    create_course_record,
    save_course_with_structure,
    fetch_course_record,
    fetch_course_with_structure,
    list_all_courses,
    remove_course_record,
    create_learning_session_record,
    fetch_learning_session_record,
    update_learning_session_state,
    finish_learning_session,
    record_interaction,
    fetch_session_statistics,
    record_learning_event,
)
