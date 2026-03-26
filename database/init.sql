-- ============================================================================
-- Smart Teacher — Initialisation de la base de données PostgreSQL
-- ============================================================================
-- Ce script crée toutes les tables, indexes, et données de test.
-- Exécution: psql -U admin -d smart_teacher -f database/init.sql
-- ============================================================================

-- Supprimer les tables existantes (ordre inverse des dépendances)
DROP TABLE IF EXISTS interactions CASCADE;
DROP TABLE IF EXISTS learning_sessions CASCADE;
DROP TABLE IF EXISTS concepts CASCADE;
DROP TABLE IF EXISTS sections CASCADE;
DROP TABLE IF EXISTS chapters CASCADE;
DROP TABLE IF EXISTS courses CASCADE;

-- ============================================================================
-- 1. TABLE courses
-- ============================================================================
CREATE TABLE courses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    subject VARCHAR(50) NOT NULL DEFAULT 'general',
    language VARCHAR(5) NOT NULL DEFAULT 'fr',
    level VARCHAR(20) NOT NULL DEFAULT 'lycée',
    description TEXT,
    file_path VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index pour recherche rapide
CREATE INDEX idx_courses_subject ON courses(subject);
CREATE INDEX idx_courses_language ON courses(language);
CREATE INDEX idx_courses_level ON courses(level);
CREATE INDEX idx_courses_created_at ON courses(created_at DESC);

-- ============================================================================
-- 2. TABLE chapters
-- ============================================================================
CREATE TABLE chapters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    order_index INTEGER NOT NULL DEFAULT 0,
    summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_chapters_course_id ON chapters(course_id);
CREATE INDEX idx_chapters_order ON chapters(course_id, order_index);

-- ============================================================================
-- 3. TABLE sections
-- ============================================================================
CREATE TABLE sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id UUID NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    order_index INTEGER NOT NULL DEFAULT 0,
    content TEXT,  -- Texte ORIGINAL du cours (préservé mot pour mot)
    duration_s INTEGER DEFAULT 120,
    image_urls JSONB DEFAULT '[]'::jsonb,  -- Liste des URLs d'images associées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sections_chapter_id ON sections(chapter_id);
CREATE INDEX idx_sections_order ON sections(chapter_id, order_index);

-- Index pour recherche full-text sur le contenu
CREATE INDEX idx_sections_content_gin ON sections USING gin(to_tsvector('french', content));
CREATE INDEX idx_sections_content_gin_en ON sections USING gin(to_tsvector('english', content));
CREATE INDEX idx_sections_content_gin_ar ON sections USING gin(to_tsvector('arabic', content));

-- ============================================================================
-- 4. TABLE concepts
-- ============================================================================
CREATE TABLE concepts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    term VARCHAR(100) NOT NULL,
    definition TEXT,
    example TEXT,
    concept_type VARCHAR(20) DEFAULT 'definition',  -- definition, formula, theorem, example
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_concepts_section_id ON concepts(section_id);
CREATE INDEX idx_concepts_term ON concepts(term);

-- ============================================================================
-- 5. TABLE learning_sessions
-- ============================================================================
CREATE TABLE learning_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id VARCHAR(100) NOT NULL,
    course_id UUID REFERENCES courses(id) ON DELETE SET NULL,
    language VARCHAR(5) NOT NULL DEFAULT 'fr',
    level VARCHAR(20) NOT NULL DEFAULT 'lycée',
    state VARCHAR(20) NOT NULL DEFAULT 'IDLE',  -- IDLE, PRESENTING, LISTENING, PROCESSING, RESPONDING
    chapter_index INTEGER DEFAULT 0,
    section_index INTEGER DEFAULT 0,
    char_position INTEGER DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sessions_student_id ON learning_sessions(student_id);
CREATE INDEX idx_sessions_course_id ON learning_sessions(course_id);
CREATE INDEX idx_sessions_started_at ON learning_sessions(started_at DESC);
CREATE INDEX idx_sessions_state ON learning_sessions(state);

-- ============================================================================
-- 6. TABLE interactions
-- ============================================================================
CREATE TABLE interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES learning_sessions(id) ON DELETE CASCADE,
    student_id VARCHAR(100) NOT NULL,
    course_id UUID REFERENCES courses(id) ON DELETE SET NULL,
    type VARCHAR(20) NOT NULL DEFAULT 'qa',  -- qa, interrupt, navigation, quiz
    question TEXT,
    answer TEXT,
    language VARCHAR(5) DEFAULT 'fr',
    stt_time FLOAT DEFAULT 0.0,
    llm_time FLOAT DEFAULT 0.0,
    tts_time FLOAT DEFAULT 0.0,
    total_time FLOAT DEFAULT 0.0,
    kpi_ok INTEGER DEFAULT 0,  -- 1 si total_time < 5s
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_interactions_session_id ON interactions(session_id);
CREATE INDEX idx_interactions_student_id ON interactions(student_id);
CREATE INDEX idx_interactions_course_id ON interactions(course_id);
CREATE INDEX idx_interactions_created_at ON interactions(created_at DESC);
CREATE INDEX idx_interactions_type ON interactions(type);

-- ============================================================================
-- 7. TABLE student_profiles (optionnel, peut être géré par Redis)
-- ============================================================================
CREATE TABLE student_profiles (
    student_id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(100),
    language VARCHAR(5) DEFAULT 'fr',
    level VARCHAR(20) DEFAULT 'lycée',
    learning_style VARCHAR(20) DEFAULT 'mixed',  -- visual, auditory, mixed
    speech_rate FLOAT DEFAULT 1.0,
    detail_level VARCHAR(20) DEFAULT 'normal',   -- simple, normal, detailed
    total_sessions INTEGER DEFAULT 0,
    total_questions INTEGER DEFAULT 0,
    confusion_count INTEGER DEFAULT 0,
    avg_response_time FLOAT DEFAULT 0.0,
    difficult_topics JSONB DEFAULT '[]'::jsonb,
    mastered_topics JSONB DEFAULT '[]'::jsonb,
    asks_examples INTEGER DEFAULT 0,
    asks_repeat INTEGER DEFAULT 0,
    interruptions INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_profiles_language ON student_profiles(language);
CREATE INDEX idx_profiles_level ON student_profiles(level);

-- ============================================================================
-- 8. TABLE course_progress (suivi de progression)
-- ============================================================================
CREATE TABLE course_progress (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id VARCHAR(100) NOT NULL,
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    chapter_id UUID REFERENCES chapters(id) ON DELETE CASCADE,
    section_id UUID REFERENCES sections(id) ON DELETE CASCADE,
    completed BOOLEAN DEFAULT FALSE,
    score FLOAT,
    time_spent_s INTEGER DEFAULT 0,
    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    UNIQUE(student_id, course_id, chapter_id, section_id)
);

CREATE INDEX idx_progress_student_id ON course_progress(student_id);
CREATE INDEX idx_progress_course_id ON course_progress(course_id);
CREATE INDEX idx_progress_completed ON course_progress(student_id, course_id, completed);

-- ============================================================================
-- 9. TABLE quiz_attempts (quiz interactifs)
-- ============================================================================
CREATE TABLE quiz_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES learning_sessions(id) ON DELETE CASCADE,
    student_id VARCHAR(100) NOT NULL,
    course_id UUID REFERENCES courses(id) ON DELETE SET NULL,
    question TEXT NOT NULL,
    correct_answer TEXT,
    student_answer TEXT,
    is_correct BOOLEAN DEFAULT FALSE,
    concept_term VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_quiz_session_id ON quiz_attempts(session_id);
CREATE INDEX idx_quiz_student_id ON quiz_attempts(student_id);

-- ============================================================================
-- 10. TABLE feedback (retours étudiants)
-- ============================================================================
CREATE TABLE feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES learning_sessions(id) ON DELETE SET NULL,
    student_id VARCHAR(100) NOT NULL,
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_feedback_session_id ON feedback(session_id);
CREATE INDEX idx_feedback_created_at ON feedback(created_at DESC);

-- ============================================================================
-- FONCTIONS ET TRIGGERS
-- ============================================================================

-- Mise à jour automatique de updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_courses_updated_at
    BEFORE UPDATE ON courses
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_sessions_updated_at
    BEFORE UPDATE ON learning_sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_profiles_updated_at
    BEFORE UPDATE ON student_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- DONNÉES DE TEST (Cours de démonstration)
-- ============================================================================

-- Cours: Introduction aux Vecteurs
-- INSERT INTO courses (id, title, subject, language, level, description) VALUES
-- ('11111111-1111-1111-1111-111111111111', 'Introduction aux Vecteurs', 'math', 'fr', 'lycée', 
--  'Cours d''introduction aux vecteurs en mathématiques pour le niveau lycée.');

-- INSERT INTO chapters (id, course_id, title, order_index, summary) VALUES
-- ('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'Les Vecteurs', 1, 
--  'Définition et propriétés fondamentales des vecteurs.');

-- INSERT INTO sections (id, chapter_id, title, order_index, content, duration_s) VALUES
-- ('33333333-3333-3333-3333-333333333333', '22222222-2222-2222-2222-222222222222', 
--  'Définition d''un vecteur', 1,
--  'Un vecteur est un objet mathématique qui possède trois caractéristiques : une direction, un sens et une norme. On le représente par une flèche. Dans le plan, un vecteur est défini par ses coordonnées (x, y).',
--  90),
-- ('44444444-4444-4444-4444-444444444444', '22222222-2222-2222-2222-222222222222',
--  'Addition de vecteurs', 2,
--  'Pour additionner deux vecteurs u et v, on additionne leurs coordonnées. Si u = (x1, y1) et v = (x2, y2), alors u + v = (x1 + x2, y1 + y2). Géométriquement, c''est la règle du parallélogramme.',
--  90),
-- ('55555555-5555-5555-5555-555555555555', '22222222-2222-2222-2222-222222222222',
--  'Produit d''un vecteur par un scalaire', 3,
--  'Le produit d''un vecteur v = (x, y) par un scalaire k donne un vecteur k·v = (k·x, k·y). Si k > 0, le vecteur garde le même sens. Si k < 0, le sens s''inverse. La norme est multipliée par |k|.',
--  90);

-- INSERT INTO concepts (id, section_id, term, definition, example, concept_type) VALUES
-- ('66666666-6666-6666-6666-666666666666', '33333333-3333-3333-3333-333333333333',
--  'Vecteur', 'Objet mathématique défini par une direction, un sens et une norme.',
--  'Le vecteur v = (3, 4) a une norme de 5.', 'definition'),
-- ('77777777-7777-7777-7777-777777777777', '44444444-4444-4444-4444-444444444444',
--  'Addition vectorielle', 'Somme de deux vecteurs obtenue en additionnant leurs coordonnées.',
--  'u = (1, 2) + v = (3, 1) = (4, 3)', 'formula'),
-- ('88888888-8888-8888-8888-888888888888', '55555555-5555-5555-5555-555555555555',
--  'Multiplication scalaire', 'Produit d''un vecteur par un nombre réel.',
--  '2·(3, 4) = (6, 8)', 'formula');

-- -- Cours: Biologie Cellulaire (anglais)
-- INSERT INTO courses (id, title, subject, language, level, description) VALUES
-- ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Cell Biology', 'biology', 'en', 'university',
--  'Introduction to cell biology for university students.');

-- INSERT INTO chapters (id, course_id, title, order_index, summary) VALUES
-- ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'The Cell', 1,
--  'Structure and function of the cell.');

-- INSERT INTO sections (id, chapter_id, title, order_index, content, duration_s) VALUES
-- ('cccccccc-cccc-cccc-cccc-cccccccccccc', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
--  'The Cell Membrane', 1,
--  'The cell membrane is a biological membrane that separates the interior of all cells from the outside environment. It is selectively permeable to ions and organic molecules.',
--  120),
-- ('dddddddd-dddd-dddd-dddd-dddddddddddd', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
--  'Mitochondria', 2,
--  'Mitochondria are double-membrane-bound organelles found in most eukaryotic organisms. They generate most of the cell''s supply of adenosine triphosphate (ATP), used as a source of chemical energy.',
--  120);

-- INSERT INTO concepts (id, section_id, term, definition, example, concept_type) VALUES
-- ('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', 'cccccccc-cccc-cccc-cccc-cccccccccccc',
--  'Cell Membrane', 'A biological membrane that separates the interior of the cell from the outside environment.',
--  'The cell membrane is composed of a phospholipid bilayer.', 'definition'),
-- ('ffffffff-ffff-ffff-ffff-ffffffffffff', 'dddddddd-dddd-dddd-dddd-dddddddddddd',
--  'Mitochondria', 'Double-membrane-bound organelles that produce ATP.',
--  'Mitochondria are often called the "powerhouses of the cell".', 'definition');

-- ============================================================================
-- VUES UTILES
-- ============================================================================

-- Vue: Statistiques des cours
CREATE OR REPLACE VIEW course_stats AS
SELECT 
    c.id AS course_id,
    c.title,
    c.subject,
    c.language,
    c.level,
    COUNT(DISTINCT ch.id) AS chapters_count,
    COUNT(DISTINCT s.id) AS sections_count,
    COUNT(DISTINCT co.id) AS concepts_count,
    COUNT(DISTINCT ls.id) AS sessions_count,
    COUNT(DISTINCT i.id) AS interactions_count
FROM courses c
LEFT JOIN chapters ch ON ch.course_id = c.id
LEFT JOIN sections s ON s.chapter_id = ch.id
LEFT JOIN concepts co ON co.section_id = s.id
LEFT JOIN learning_sessions ls ON ls.course_id = c.id
LEFT JOIN interactions i ON i.course_id = c.id
GROUP BY c.id, c.title, c.subject, c.language, c.level;

-- Vue: Progression des étudiants
CREATE OR REPLACE VIEW student_progress_summary AS
SELECT 
    cp.student_id,
    c.title AS course_title,
    COUNT(DISTINCT cp.section_id) AS completed_sections,
    (SELECT COUNT(*) FROM sections s 
     JOIN chapters ch ON s.chapter_id = ch.id 
     WHERE ch.course_id = cp.course_id) AS total_sections,
    ROUND(COUNT(DISTINCT cp.section_id) * 100.0 / 
          NULLIF((SELECT COUNT(*) FROM sections s 
                  JOIN chapters ch ON s.chapter_id = ch.id 
                  WHERE ch.course_id = cp.course_id), 0), 1) AS completion_pct,
    MAX(cp.last_accessed) AS last_activity
FROM course_progress cp
JOIN courses c ON c.id = cp.course_id
WHERE cp.completed = TRUE
GROUP BY cp.student_id, c.title, cp.course_id;

-- ============================================================================
-- FIN DU SCRIPT
-- ============================================================================