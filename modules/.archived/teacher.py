"""
╔══════════════════════════════════════════════════════════════════════╗
║        SMART TEACHER — Module Présentateur de Cours v2             ║
║                                                                      ║
║  AMÉLIORATIONS v2 :                                                  ║
║    ✅ Quiz génériques par chapitre                                    ║
║    ✅ Phrases de transition adaptées à tous les cours                ║
║    ✅ Découpage en phrases amélioré                                   ║
║    ✅ Concepts présentés avec vocabulaire oral                        ║
║    ✅ ScriptGenerator enrichi : formules orales (pas LaTeX)         ║
║    ✅ CourseLoader.from_chapters() pour les chapitres numérotés      ║
║    ✅ Timeout de sécurité par section (évite les boucles infinies)   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, AsyncGenerator

log = logging.getLogger("SmartTeacher.Teacher")

# Timeout par section (secondes) — évite les blocages
SECTION_TIMEOUT = 180


# ══════════════════════════════════════════════════════════════════════
#  STRUCTURES
# ══════════════════════════════════════════════════════════════════════

@dataclass
class Concept:
    term:        str
    definition:  str
    example:     str  = ""
    concept_type: str = "definition"   # definition|algorithm|metric|formula


@dataclass
class Section:
    title:       str
    content:     str
    concepts:    list[Concept] = field(default_factory=list)
    duration_s:  int = 120
    slide_idx:   int | None = None


@dataclass
class Chapter:
    title:      str
    sections:   list[Section] = field(default_factory=list)
    chapter_idx: int = 0    # Index du chapitre


@dataclass
class Course:
    title:    str
    subject:  str
    language: str
    level:    str
    chapters: list[Chapter] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════
#  GÉNÉRATEUR DE SCRIPTS — GÉNÉRIQUE
# ══════════════════════════════════════════════════════════════════════

class ScriptGenerator:
    """
    Génère les scripts de présentation adaptés à la langue et au niveau.
    Adapté à n'importe quel domaine de cours.
    """

    # ── Introductions / transitions ───────────────────────────────────
    INTROS = {
        "en": {
            "course":   "Welcome! Today we are studying {title}. "
                        "This is a Master's level course. "
                        "Feel free to interrupt me anytime with a question.",
            "chapter":  "Now let's move to Chapter {order}: {title}.",
            "section":  "In this part, we will cover: {title}. {content}",
            "concept":  "A key concept to remember: {term}. {definition} "
                        "For example: {example}",
            "quiz":     "Quick check before we continue: {question}",
            "transition_next":  "Alright, let's move on.",
            "transition_recap": "Let me briefly recap: ",
            "resume":   "As I was explaining, ",
            "end_section":  "That covers this section. Any questions?",
            "end_chapter":  "Excellent! We have finished Chapter {title}.",
            "end_course":   "Congratulations! You have completed {title}. "
                            "Feel free to ask any questions about what we covered.",
        },
        "fr": {
            "course":   "Bonjour ! Aujourd'hui nous étudions {title}. "
                        "Il s'agit d'un cours de niveau Master. "
                        "N'hésitez pas à m'interrompre si vous avez des questions.",
            "chapter":  "Passons au chapitre {order} : {title}.",
            "section":  "Dans cette partie, nous allons voir : {title}. {content}",
            "concept":  "Un concept clé à retenir : {term}. {definition} "
                        "Par exemple : {example}",
            "quiz":     "Avant de continuer, une petite question : {question}",
            "transition_next":  "Très bien, passons à la suite.",
            "transition_recap": "Pour résumer rapidement : ",
            "resume":   "Comme je l'expliquais, ",
            "end_section":  "Voilà pour cette section. Des questions ?",
            "end_chapter":  "Excellent ! Nous avons terminé le chapitre {title}.",
            "end_course":   "Félicitations ! Vous avez terminé {title}.",
        },
        "ar": {
            "course":   "مرحباً! اليوم ندرس {title}. لا تترددوا في مقاطعتي.",
            "chapter":  "ننتقل إلى الفصل {order}: {title}.",
            "section":  "في هذا الجزء سنتناول: {title}. {content}",
            "concept":  "مفهوم أساسي: {term}. {definition} مثال: {example}",
            "quiz":     "سؤال سريع: {question}",
            "transition_next":  "لننتقل إلى الجزء التالي.",
            "resume":   "كما كنت أشرح، ",
            "end_section":  "هذا كل شيء لهذا الجزء. هل لديكم أسئلة؟",
        },
    }

    # ── Quiz génériques par chapitre ─────────────────────────────────
    # Organisés par chapter_idx pour les cours structurés
    QUIZ_BY_CHAPTER = {
        "en": {
            1: [
                "Can you explain the main idea of this chapter in your own words?",
                "What are the three most important concepts in this chapter?",
                "Can you give a simple example related to this chapter?",
            ],
            2: [
                "What is the difference between the main concepts introduced here?",
                "Can you name three ideas we studied in this chapter?",
                "How would you apply one concept from this chapter in practice?",
            ],
            3: [
                "What is the difference between the approaches discussed in this chapter?",
                "Can you name two methods or tools mentioned here?",
                "Why is this chapter important before moving to the next topic?",
            ],
            4: [
                "What are the main strategies discussed in this chapter?",
                "How do you explain the key process covered here?",
                "What is the difference between the two ideas introduced in this section?",
            ],
            5: [
                "What is the difference between the methods presented here?",
                "Can you explain why the concept in this chapter matters?",
                "Why is this topic important for the overall course?",
            ],
            6: [
                "What is the difference between the two techniques presented here?",
                "How does the method explained in this chapter help evaluation?",
                "What does the main result from this chapter tell us?",
            ],
            7: [
                "What is the main difference between the methods discussed here?",
                "How would you choose between the approaches introduced in this chapter?",
                "What is one practical use of the idea explained here?",
            ],
            0: [
                "Can you explain {term} in your own words?",
                "What is the purpose of {term} in this course?",
                "Can you give a real-world application of {term}?",
            ],
        },
        "fr": {
            1: [
                "Pouvez-vous expliquer l'idée principale de ce chapitre ?",
                "Quels sont les trois concepts les plus importants vus ici ?",
                "Pouvez-vous donner un exemple simple lié à ce chapitre ?",
            ],
            2: [
                "Quelle est la différence entre les concepts principaux présentés ici ?",
                "Pouvez-vous nommer trois idées étudiées dans ce chapitre ?",
                "Comment appliqueriez-vous un concept de ce chapitre en pratique ?",
            ],
            3: [
                "Quelle est la différence entre les approches discutées dans ce chapitre ?",
                "Citez deux méthodes ou outils mentionnés ici.",
                "Pourquoi ce chapitre est-il important avant de passer à la suite ?",
            ],
            4: [
                "Quelles sont les stratégies principales présentées dans ce chapitre ?",
                "Comment expliquez-vous le processus clé vu ici ?",
                "Quelle est la différence entre les deux idées introduites dans cette section ?",
            ],
            5: [
                "Quelle est la différence entre les méthodes présentées ici ?",
                "Expliquez pourquoi le concept de ce chapitre est important.",
                "Pourquoi ce sujet est-il important pour le cours dans son ensemble ?",
            ],
            6: [
                "Quelle est la différence entre les deux techniques présentées ici ?",
                "Comment la méthode expliquée dans ce chapitre aide-t-elle à évaluer ?",
                "Que nous indique le résultat principal de ce chapitre ?",
            ],
            7: [
                "Quelle est la principale différence entre les méthodes discutées ici ?",
                "Comment choisiriez-vous entre les approches introduites dans ce chapitre ?",
                "Quel est un usage concret de l'idée expliquée ici ?",
            ],
            0: [
                "Pouvez-vous expliquer {term} avec vos propres mots ?",
                "Quel est le rôle de {term} dans ce cours ?",
            ],
        },
    }

    def get(self, lang: str, key: str, **kwargs) -> str:
        lang = lang[:2].lower()
        templates = self.INTROS.get(lang, self.INTROS["en"])
        template  = templates.get(key, self.INTROS["en"].get(key, ""))
        try:
            return template.format(**kwargs)
        except KeyError:
            return template

    def get_quiz_for_chapter(self, lang: str, chapter_idx: int = 0) -> str:
        """Retourne une question quiz adaptée au chapitre en cours."""
        lang = lang[:2].lower()
        by_ch = self.QUIZ_BY_CHAPTER.get(lang, self.QUIZ_BY_CHAPTER["en"])
        questions = by_ch.get(chapter_idx, by_ch.get(0, ["Can you summarize what we just covered?"]))
        # Rotation selon le temps pour ne pas toujours poser la même question
        idx = int(time.time()) % len(questions)
        return questions[idx]

    def get_quiz(self, lang: str, subject: str, term: str, chapter_idx: int = 0) -> str:
        """Retourne une question générique adaptée au chapitre ou au terme."""
        if chapter_idx:
            q = self.get_quiz_for_chapter(lang, chapter_idx)
            if "{term}" in q:
                return q.format(term=term)
            return q

        generic = {
            "en": f"Can you explain {term} in your own words?",
            "fr": f"Pouvez-vous expliquer {term} avec vos propres mots ?",
            "ar": f"هل يمكنك شرح {term} بكلماتك الخاصة؟",
        }
        return generic.get(lang[:2].lower(), generic["en"])


# ══════════════════════════════════════════════════════════════════════
#  PRÉSENTATEUR DE COURS
# ══════════════════════════════════════════════════════════════════════

class CoursePresenter:
    """
    Présente un cours section par section avec gestion des interruptions.
    Optimisé pour les cours structurés en chapitres et sections.
    """

    def __init__(
        self,
        course:   Course,
        language: str = "en",
        level:    str = "université",
        voice_engine = None,
    ):
        self.course   = course
        self.language = language[:2].lower()
        self.level    = level
        self.voice    = voice_engine
        self.script   = ScriptGenerator()

        self.chapter_idx   = 0
        self.section_idx   = 0
        self.char_position = 0

        self._interrupted = False
        self._finished    = False
        self._paused      = False

        log.info(f"📖 CoursePresenter : {course.title} | {language} | {level}")

    # ── Contrôle ──────────────────────────────────────────────────────
    def interrupt(self):
        self._interrupted = True
        log.info("⚡ Interruption")

    def pause(self):
        self._paused = True
        log.info("⏸️  Pause")

    def resume_playback(self):
        self._paused = False
        self._interrupted = False
        log.info("▶️  Reprise")

    def reset_interrupt(self):
        self._interrupted = False

    @property
    def is_finished(self) -> bool:
        return self._finished

    @property
    def current_chapter(self) -> Chapter | None:
        if self.chapter_idx < len(self.course.chapters):
            return self.course.chapters[self.chapter_idx]
        return None

    @property
    def current_section(self) -> Section | None:
        ch = self.current_chapter
        if ch and self.section_idx < len(ch.sections):
            return ch.sections[self.section_idx]
        return None

    @property
    def current_position(self) -> dict:
        return {
            "chapter":    self.chapter_idx,
            "section":    self.section_idx,
            "char":       self.char_position,
            "chapter_title":  self.current_chapter.title if self.current_chapter else "",
            "section_title":  self.current_section.title if self.current_section else "",
        }

    # ── Navigation ────────────────────────────────────────────────────
    def next_section(self):
        chapter = self.course.chapters[self.chapter_idx]
        if self.section_idx < len(chapter.sections) - 1:
            self.section_idx  += 1
        elif self.chapter_idx < len(self.course.chapters) - 1:
            self.chapter_idx  += 1
            self.section_idx   = 0
        else:
            self._finished = True
        self.char_position = 0
        log.info(f"➡️  Section suivante : ch{self.chapter_idx} sec{self.section_idx}")

    def prev_section(self):
        if self.section_idx > 0:
            self.section_idx -= 1
        elif self.chapter_idx > 0:
            self.chapter_idx -= 1
            chapter = self.course.chapters[self.chapter_idx]
            self.section_idx = len(chapter.sections) - 1
        self.char_position = 0
        log.info(f"⬅️  Section précédente : ch{self.chapter_idx} sec{self.section_idx}")

    def goto(self, chapter_idx: int, section_idx: int):
        self.chapter_idx   = chapter_idx
        self.section_idx   = section_idx
        self.char_position = 0

    # ── Génération audio ──────────────────────────────────────────────
    async def _speak(self, text: str) -> tuple[bytes | None, float]:
        if not self.voice or not text.strip():
            return None, 0.0
        audio, duration, _, _, _ = await self.voice.generate_audio_async(
            text, language_code=self.language
        )
        return audio, duration

    # ── Présentation ──────────────────────────────────────────────────
    async def present_intro(self) -> AsyncGenerator:
        text  = self.script.get(self.language, "course", title=self.course.title)
        audio, _ = await self._speak(text)
        yield audio, text, "intro"

    async def present_current_section(self) -> AsyncGenerator:
        """
        Présente la section courante complète.
        Yield : (audio_bytes, text, event_type)
        """
        self.reset_interrupt()

        chapter = self.course.chapters[self.chapter_idx]
        section = chapter.sections[self.section_idx]
        ch_idx  = getattr(chapter, "chapter_idx", 0)

        # ── Intro chapitre (si première section) ──────────────────────
        if self.section_idx == 0 and self.char_position == 0:
            text  = self.script.get(
                self.language, "chapter",
                order=self.chapter_idx + 1,
                title=chapter.title,
            )
            audio, _ = await self._speak(text)
            yield audio, text, "chapter_intro"
            if self._interrupted:
                yield None, "", "interrupted"
                return

        # ── Titre de section ──────────────────────────────────────────
        if self.char_position == 0:
            intro_text = self.script.get(
                self.language, "section",
                title=section.title, content=""
            ).split(".")[0] + "."
            audio, _ = await self._speak(intro_text)
            yield audio, intro_text, "section_intro"
            if self._interrupted:
                yield None, "", "interrupted"
                return

        # ── Contenu principal ─────────────────────────────────────────
        content   = section.content
        remaining = content[self.char_position:]
        sentences = self._split_sentences(remaining)

        chars_spoken = self.char_position
        section_start = time.time()

        for sentence in sentences:
            # Timeout de sécurité
            if time.time() - section_start > SECTION_TIMEOUT:
                log.warning("⏱️  Timeout section — passage à la suivante")
                break

            if self._interrupted or self._paused:
                self.char_position = chars_spoken
                yield None, "", "interrupted"
                return

            if not sentence.strip():
                chars_spoken += len(sentence)
                continue

            audio, _ = await self._speak(sentence)
            chars_spoken += len(sentence)
            yield audio, sentence, "content"
            await asyncio.sleep(0.2)

        self.char_position = 0

        # ── Concepts clés ─────────────────────────────────────────────
        for concept in section.concepts:
            if self._interrupted:
                yield None, "", "interrupted"
                return

            # Présentation orale adaptée au type
            if concept.concept_type == "algorithm":
                prefix = {
                    "en": f"Now, the {concept.term} algorithm. ",
                    "fr": f"Maintenant, l'algorithme {concept.term}. ",
                    "ar": f"الآن، خوارزمية {concept.term}. ",
                }.get(self.language, f"Now, {concept.term}. ")
            elif concept.concept_type == "metric":
                prefix = {
                    "en": f"An important metric: {concept.term}. ",
                    "fr": f"Une métrique importante : {concept.term}. ",
                    "ar": f"مقياس مهم: {concept.term}. ",
                }.get(self.language, f"Metric: {concept.term}. ")
            else:
                prefix = ""

            text  = self.script.get(
                self.language, "concept",
                term=concept.term,
                definition=concept.definition,
                example=concept.example or "",
            )
            if prefix:
                text = prefix + text

            audio, _ = await self._speak(text)
            yield audio, text, "concept"
            await asyncio.sleep(0.4)

        # ── Fin de section ────────────────────────────────────────────
        if not self._interrupted:
            text  = self.script.get(self.language, "end_section")
            audio, _ = await self._speak(text)
            yield audio, text, "end_section"

    async def present_resume(self) -> AsyncGenerator:
        """Reprend la présentation avec une phrase de transition."""
        self.reset_interrupt()
        text  = self.script.get(self.language, "resume")
        audio, _ = await self._speak(text)
        yield audio, text, "resume"
        async for result in self.present_current_section():
            yield result

    async def present_quiz(self) -> AsyncGenerator:
        """Pose un quiz adapté au chapitre courant."""
        chapter = self.course.chapters[self.chapter_idx]
        ch_idx  = getattr(chapter, "chapter_idx", 0)
        section = chapter.sections[self.section_idx]

        question = self.script.get_quiz_for_chapter(self.language, chapter_idx=ch_idx)

        # Fallback sur concept si disponible
        if not question and section.concepts:
            question = self.script.get_quiz(
                self.language, self.course.subject,
                section.concepts[0].term, ch_idx
            )
        if not question:
            return

        audio, _ = await self._speak(question)
        yield audio, question, "quiz"

    # ── Utilitaires ───────────────────────────────────────────────────
    def _split_sentences(self, text: str) -> list[str]:
        """
        Découpe le texte en phrases.
        Préserve les abréviations courantes :
        e.g., i.e., Fig., vs., etc., PCA., SVM., k-NN.
        """
        import re

        # Protéger les abréviations connues
        protected = text
        abbrevs = [
            "e.g.", "i.e.", "vs.", "Fig.", "Eq.", "Def.",
            "k-NN", "k-nn", "SVM.", "PCA.", "KNN.", "CNN.",
            "Dr.", "Prof.", "M2.", "M1.", "approx.",
        ]
        placeholders: dict[str, str] = {}
        for i, abbr in enumerate(abbrevs):
            ph = f"__ABBR{i}__"
            placeholders[ph] = abbr
            protected = protected.replace(abbr, ph)

        # Découper sur les fins de phrases
        raw_sentences = re.split(r'(?<=[.!?])\s+', protected.strip())

        # Restaurer les abréviations
        sentences = []
        for s in raw_sentences:
            for ph, abbr in placeholders.items():
                s = s.replace(ph, abbr)
            s = s.strip()
            if s:
                sentences.append(s)

        # Regrouper les phrases trop courtes avec la suivante
        result = []
        buffer = ""
        for s in sentences:
            buffer += s + " "
            if len(buffer) >= 90:
                result.append(buffer.strip())
                buffer = ""
        if buffer.strip():
            result.append(buffer.strip())

        return result

    def get_progress(self) -> dict:
        total_sections = sum(len(ch.sections) for ch in self.course.chapters)
        done_sections  = sum(
            len(self.course.chapters[i].sections)
            for i in range(self.chapter_idx)
        ) + self.section_idx

        pct = round(done_sections / total_sections * 100) if total_sections else 0
        chapter = self.course.chapters[self.chapter_idx]
        section = chapter.sections[self.section_idx]

        return {
            "percent":        pct,
            "chapter":        chapter.title,
            "chapter_idx":    self.chapter_idx + 1,
            "chapter_order": getattr(chapter, "chapter_idx", self.chapter_idx + 1),
            "chapter_total":  len(self.course.chapters),
            "section":        section.title,
            "section_idx":    self.section_idx + 1,
            "section_total":  len(chapter.sections),
            "finished":       self._finished,
        }


# ══════════════════════════════════════════════════════════════════════
#  CHARGEUR DE COURS
# ══════════════════════════════════════════════════════════════════════

class CourseLoader:
    """
    Charge un cours depuis différentes sources.
    Méthodes génériques pour les chapitres numérotés.
    """

    @staticmethod
    def from_dict(data: dict) -> Course:
        chapters = []
        for ch_data in data.get("chapters", []):
            ch_idx = ch_data.get("chapter_idx", 0) or ch_data.get("order", 0)
            sections = []
            for sec_data in ch_data.get("sections", []):
                concepts = [
                    Concept(
                        term=c["term"],
                        definition=c.get("definition", ""),
                        example=c.get("example", ""),
                        concept_type=c.get("type", "definition"),
                    )
                    for c in sec_data.get("concepts", [])
                ]
                sections.append(Section(
                    title=sec_data["title"],
                    content=sec_data.get("content", ""),
                    concepts=concepts,
                    duration_s=sec_data.get("duration_s", 120),
                ))
            chapters.append(Chapter(
                title=ch_data["title"],
                sections=sections,
                chapter_idx=ch_idx,
            ))

        return Course(
            title=data["title"],
            subject=data.get("subject", "general"),
            language=data.get("language", "en"),
            level=data.get("level", "université"),
            chapters=chapters,
        )

    @staticmethod
    def from_chapters(chapters_dict: dict[int, dict]) -> Course:
        """
        Crée un cours complet depuis un dict de chapitres numérotés.
        chapters_dict = {1: {...}, 2: {...}, ...}
        """
        all_chapters = []

        for ch_idx in sorted(chapters_dict.keys()):
            ch_data = chapters_dict[ch_idx]
            ch_title = ch_data.get("chapter_title") or ch_data.get("title") or f"Chapter {ch_idx}"

            sections = []
            for inner_ch in ch_data.get("chapters", []):
                for sec_data in inner_ch.get("sections", []):
                    concepts = [
                        Concept(
                            term=c["term"],
                            definition=c.get("definition", ""),
                            example=c.get("example", ""),
                            concept_type=c.get("type", "definition"),
                        )
                        for c in sec_data.get("concepts", [])
                    ]
                    sections.append(Section(
                        title=sec_data["title"],
                        content=sec_data.get("content", ""),
                        concepts=concepts,
                        duration_s=sec_data.get("duration_s", 120),
                    ))

            if sections:
                all_chapters.append(Chapter(
                    title=ch_title,
                    sections=sections,
                    chapter_idx=ch_idx,
                ))

        return Course(
            title="Generic Course",
            subject="general",
            language="en",
            level="université",
            chapters=all_chapters,
        )

    @staticmethod
    def from_text(title: str, text: str, language: str = "en",
                  subject: str = "general", level: str = "université") -> Course:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        sections   = []
        for i, para in enumerate(paragraphs):
            lines = para.split("\n")
            sec_title   = lines[0][:80] if lines else f"Part {i+1}"
            sec_content = "\n".join(lines[1:]).strip() if len(lines) > 1 else para
            sections.append(Section(title=sec_title, content=sec_content or para))

        chapter = Chapter(title=title, sections=sections)
        return Course(title=title, subject=subject, language=language,
                      level=level, chapters=[chapter])

    @staticmethod
    async def from_database(course_id: str, db) -> Optional[Course]:
        try:
            from database.crud import get_course_with_structure
            import uuid
            db_course = await get_course_with_structure(db, uuid.UUID(course_id))
            if not db_course:
                return None

            chapters = []
            for ch in db_course.chapters:
                sections = []
                for sec in ch.sections:
                    concepts = [
                        Concept(
                            term=c.term,
                            definition=c.definition or "",
                            example=c.example or "",
                            concept_type=getattr(c, "concept_type", "definition"),
                        )
                        for c in sec.concepts
                    ]
                    sections.append(Section(
                        title=sec.title,
                        content=sec.content or "",
                        concepts=concepts,
                        duration_s=sec.duration_s or 120,
                    ))
                chapters.append(Chapter(
                    title=ch.title,
                    sections=sections,
                    chapter_idx=getattr(ch, "chapter_idx", 0),
                ))

            return Course(
                title=db_course.title,
                subject=db_course.subject or "general",
                language=db_course.language or "en",
                level=db_course.level or "université",
                chapters=chapters,
            )
        except Exception as exc:
            log.error(f"❌ Chargement cours DB : {exc}")
            return None

    @staticmethod
    def demo_course(language: str = "en") -> Course:
        """Cours de démonstration générique."""
        return CourseLoader.from_dict({
            "title":    "Generic Demonstration Course",
            "subject":  "general",
            "language": language,
            "level":    "université",
            "chapters": [
                {
                    "title": "Introduction",
                    "order": 1,
                    "chapter_idx": 1,
                    "sections": [
                        {
                            "title":   "What is the topic?",
                            "content": (
                                "A course topic is a subject that combines ideas, methods, and examples. "
                                "The goal is to understand the main concepts clearly. "
                                "We use a simple explanation first, then connect it to practical use."
                            ),
                            "duration_s": 90,
                            "concepts": [
                                {
                                    "term": "Core idea",
                                    "definition": "The main idea or principle that helps organize the lesson.",
                                    "example": "A clear definition that the student can remember.",
                                    "type": "definition",
                                }
                            ],
                        },
                        {
                            "title":   "Main ideas in context",
                            "content": (
                                "A subject can include several related concepts, methods, and examples. "
                                "The important part is to compare them clearly and explain how they fit together. "
                                "A good explanation stays simple, concrete, and useful for revision."
                            ),
                            "duration_s": 90,
                            "concepts": [
                                {
                                    "term": "Comparison",
                                    "definition": "A way to see similarities and differences between ideas.",
                                    "example": "Comparing two chapters to understand what each one adds.",
                                    "type": "definition",
                                }
                            ],
                        },
                    ],
                },
                {
                    "title": "Key Concepts",
                    "order": 2,
                    "chapter_idx": 2,
                    "sections": [
                        {
                            "title":   "Types of ideas",
                            "content": (
                                "In any course we can distinguish several types of information. "
                                "Some content is structured, some is unstructured, and some is mixed. "
                                "Understanding the form of the content helps choose the right explanation."
                            ),
                            "duration_s": 90,
                            "concepts": [
                                {
                                    "term": "Structure",
                                    "definition": "The way information is organized inside a chapter or lesson.",
                                    "example": "A lesson divided into definition, example, and summary.",
                                    "type": "definition",
                                }
                            ],
                        },
                    ],
                },
            ],
        })