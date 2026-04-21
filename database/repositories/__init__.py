"""Human-readable repository aliases for database operations.

These names are the clearer API to use in new code. They map to the existing
CRUD implementation so the application keeps the same behavior.
"""

from .crud import (
    create_student as create_student_account,
    create_course as create_course_record,
    create_course_with_structure as save_course_with_structure,
    get_course as fetch_course_record,
    get_course_with_structure as fetch_course_with_structure,
    get_all_courses as list_all_courses,
    delete_course as remove_course_record,
    create_learning_session as create_learning_session_record,
    get_session as fetch_learning_session_record,
    update_session_state as update_learning_session_state,
    end_session as finish_learning_session,
    log_interaction as record_interaction,
    get_session_stats as fetch_session_statistics,
    log_learning_event as record_learning_event,
)

# Backward-compatible aliases for legacy imports still used across the app.
create_student = create_student_account
create_course = create_course_record
create_course_with_structure = save_course_with_structure
get_course = fetch_course_record
get_course_with_structure = fetch_course_with_structure
get_all_courses = list_all_courses
delete_course = remove_course_record
create_learning_session = create_learning_session_record
get_session = fetch_learning_session_record
update_session_state = update_learning_session_state
end_session = finish_learning_session
log_interaction = record_interaction
get_session_stats = fetch_session_statistics
log_learning_event = record_learning_event
