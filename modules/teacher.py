"""
╔══════════════════════════════════════════════════════════════════════╗
║        SMART TEACHER — Module Présentateur de Cours v2             ║
║                                                                      ║
║  AMÉLIORATIONS v2 :                                                  ║
║    ✅ Quiz spécialisés Data Mining (par chapitre ch1..ch7)           ║
║    ✅ Phrases de transition spécifiques au domaine informatique      ║
║    ✅ Découpage en phrases amélioré (préserve les abréviations DM)   ║
║    ✅ Concepts DM : présentation avec algorithme + complexité        ║
║    ✅ ScriptGenerator enrichi : formules orales (pas LaTeX)         ║
║    ✅ CourseLoader.from_dm_dict() pour les chapitres ch1..ch7        ║
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
    chapter_idx: int = 0    # 1-7 pour DM


@dataclass
class Course:
    title:    str
    subject:  str
    language: str
    level:    str
    chapters: list[Chapter] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════
#  GÉNÉRATEUR DE SCRIPTS — SPÉCIALISÉ DATA MINING
# ══════════════════════════════════════════════════════════════════════

class ScriptGenerator:
    """
    Génère les scripts de présentation adaptés à la langue et au niveau.
    Spécialisé pour le domaine Data Mining / Informatique (M2).
    """

    # ── Introductions / transitions ───────────────────────────────────
    INTROS = {
        "en": {
            "course":   "Welcome! Today we are studying {title}. "
                        "This is a Master's level course on Data Mining. "
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
                        "Il s'agit d'un cours de Data Mining niveau Master. "
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

    # ── Quiz spécialisés DM par chapitre ─────────────────────────────
    # Organisés par chapter_idx (1-7) pour le cours DM
    DM_QUIZ_BY_CHAPTER = {
        "en": {
            1: [  # Introduction
                "Can you explain the difference between Data Mining and Machine Learning?",
                "What are the three pillars of modern AI mentioned in this chapter?",
                "What does KDD stand for, and what is its purpose?",
            ],
            2: [  # Data, Dataset, Data Warehouse
                "What is the difference between a database and a data warehouse?",
                "Can you name three types of data attributes we studied?",
                "What is the difference between OLAP and OLTP?",
            ],
            3: [  # EDA
                "What is the difference between univariate and bivariate analysis?",
                "Can you name two visualization techniques used in EDA?",
                "Why is exploratory analysis important before applying ML algorithms?",
            ],
            4: [  # Data Cleaning
                "What are the main strategies to handle missing values?",
                "How do you detect and handle outliers in a dataset?",
                "What is the difference between normalization and standardization?",
            ],
            5: [  # Feature Engineering
                "What is the difference between feature selection and feature extraction?",
                "Can you explain what PCA does and why we use it?",
                "Why is feature engineering important for model performance?",
            ],
            6: [  # Supervised ML
                "What is the difference between classification and regression?",
                "How does cross-validation help evaluate a model?",
                "What does the AUC-ROC curve tell us about a classifier?",
            ],
            7: [  # Unsupervised ML
                "What is the main difference between k-means and hierarchical clustering?",
                "How do you choose the value of k in k-means?",
                "What is the Apriori algorithm used for?",
            ],
            0: [  # Generic DM
                "Can you explain {term} in your own words?",
                "What is the purpose of {term} in Data Mining?",
                "Can you give a real-world application of {term}?",
            ],
        },
        "fr": {
            1: [
                "Quelle est la différence entre le Data Mining et le Machine Learning ?",
                "Quels sont les trois piliers de l'IA moderne vus dans ce chapitre ?",
                "Que signifie KDD et quel est son objectif ?",
            ],
            2: [
                "Quelle est la différence entre une base de données et un entrepôt de données ?",
                "Pouvez-vous nommer trois types d'attributs de données ?",
                "Quelle est la différence entre OLAP et OLTP ?",
            ],
            3: [
                "Quelle est la différence entre l'analyse univariée et bivariée ?",
                "Citez deux techniques de visualisation utilisées en EDA.",
                "Pourquoi l'analyse exploratoire est-elle essentielle avant le ML ?",
            ],
            4: [
                "Quelles sont les stratégies principales pour gérer les valeurs manquantes ?",
                "Comment détecte-t-on et gère-t-on les outliers dans un dataset ?",
                "Quelle est la différence entre normalisation et standardisation ?",
            ],
            5: [
                "Quelle est la différence entre sélection et extraction de features ?",
                "Expliquez ce que fait la PCA et pourquoi on l'utilise.",
                "Pourquoi le feature engineering améliore les performances des modèles ?",
            ],
            6: [
                "Quelle est la différence entre classification et régression ?",
                "Comment la validation croisée aide-t-elle à évaluer un modèle ?",
                "Qu'est-ce que la courbe ROC-AUC nous indique sur un classifieur ?",
            ],
            7: [
                "Quelle est la principale différence entre k-means et le clustering hiérarchique ?",
                "Comment choisit-on la valeur de k dans k-means ?",
                "À quoi sert l'algorithme Apriori ?",
            ],
            0: [
                "Pouvez-vous expliquer {term} avec vos propres mots ?",
                "Quel est le rôle de {term} en Data Mining ?",
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

    def get_dm_quiz(self, lang: str, chapter_idx: int = 0) -> str:
        """Retourne une question quiz adaptée au chapitre DM en cours."""
        lang = lang[:2].lower()
        by_ch = self.DM_QUIZ_BY_CHAPTER.get(lang, self.DM_QUIZ_BY_CHAPTER["en"])
        questions = by_ch.get(chapter_idx, by_ch.get(0, ["Can you summarize what we just covered?"]))
        # Rotation selon le temps pour ne pas toujours poser la même question
        idx = int(time.time()) % len(questions)
        return questions[idx]

    def get_quiz(self, lang: str, subject: str, term: str, chapter_idx: int = 0) -> str:
        """Compatibilité API — préfère get_dm_quiz() pour DM."""
        if subject == "data_mining":
            q = self.get_dm_quiz(lang, chapter_idx)
            if "{term}" in q:
                return q.format(term=term)
            return q

        # Fallback générique
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
    Optimisé pour le domaine Data Mining.
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
        """Pose un quiz DM adapté au chapitre courant."""
        chapter = self.course.chapters[self.chapter_idx]
        ch_idx  = getattr(chapter, "chapter_idx", 0)
        section = chapter.sections[self.section_idx]

        question = self.script.get_dm_quiz(self.language, chapter_idx=ch_idx)

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
        Préserve les abréviations courantes en DM/CS :
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
            "chapter_dm_idx": getattr(chapter, "chapter_idx", self.chapter_idx + 1),
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
    Méthode spéciale pour les chapitres DM ch1..ch7.
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
            subject=data.get("subject", "data_mining"),
            language=data.get("language", "en"),
            level=data.get("level", "université"),
            chapters=chapters,
        )

    @staticmethod
    def from_dm_chapters(chapters_dict: dict[int, dict]) -> Course:
        """
        Crée un cours complet depuis le dict retourné par CourseBuilder.build_dm_course().
        chapters_dict = {1: {cours ch1}, 2: {cours ch2}, ..., 7: {cours ch7}}
        """
        from multimodal_rag import DM_CHAPTER_MAP
        all_chapters = []

        for ch_idx in sorted(chapters_dict.keys()):
            ch_data = chapters_dict[ch_idx]
            ch_title = DM_CHAPTER_MAP.get(f"ch{ch_idx}", ("Unknown", ch_idx))[0]

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
            title="Data Mining — M2 SII",
            subject="data_mining",
            language="en",
            level="université",
            chapters=all_chapters,
        )

    @staticmethod
    def from_text(title: str, text: str, language: str = "en",
                  subject: str = "data_mining", level: str = "université") -> Course:
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
                subject=db_course.subject or "data_mining",
                language=db_course.language or "en",
                level=db_course.level or "université",
                chapters=chapters,
            )
        except Exception as exc:
            log.error(f"❌ Chargement cours DB : {exc}")
            return None

    @staticmethod
    def demo_dm_course(language: str = "en") -> Course:
        """Cours DM de démonstration (ch1: Introduction, ch2: Data)."""
        return CourseLoader.from_dict({
            "title":    "Data Mining — M2 SII",
            "subject":  "data_mining",
            "language": language,
            "level":    "université",
            "chapters": [
                {
                    "title": "Introduction to Data Mining",
                    "order": 1,
                    "chapter_idx": 1,
                    "sections": [
                        {
                            "title":   "What is Data Mining?",
                            "content": (
                                "Data mining is the process of discovering patterns and extracting "
                                "useful knowledge from large datasets using statistics, mathematics, "
                                "and machine learning algorithms. "
                                "It goes beyond simply collecting data — it's about making sense of it "
                                "to drive informed decisions. "
                                "Data mining acts as a bridge between raw data and actionable knowledge."
                            ),
                            "duration_s": 90,
                            "concepts": [
                                {
                                    "term": "Knowledge Discovery in Databases (KDD)",
                                    "definition": "The overall process of extracting useful knowledge "
                                                  "from data, encompassing preprocessing, mining, and interpretation.",
                                    "example": "Discovering that customers who buy diapers also tend to buy beer.",
                                    "type": "definition",
                                }
                            ],
                        },
                        {
                            "title":   "AI vs Data Mining",
                            "content": (
                                "Artificial intelligence is the broader field that includes machine learning, "
                                "deep learning, and agentic systems. "
                                "Data mining is a subset that focuses specifically on extracting patterns "
                                "from existing datasets using algorithms like k-means, decision trees, "
                                "and association rule mining. "
                                "The three pillars of modern AI are data, algorithms, and hardware — "
                                "and data mining sits at the intersection of all three."
                            ),
                            "duration_s": 90,
                            "concepts": [
                                {
                                    "term": "Machine Learning",
                                    "definition": "A subset of AI where systems learn patterns from data "
                                                  "without being explicitly programmed.",
                                    "example": "A spam filter that learns to classify emails from examples.",
                                    "type": "definition",
                                }
                            ],
                        },
                    ],
                },
                {
                    "title": "Data, Dataset, Data Warehouse",
                    "order": 2,
                    "chapter_idx": 2,
                    "sections": [
                        {
                            "title":   "Types of Data",
                            "content": (
                                "In data mining we distinguish several types of data. "
                                "Structured data lives in relational databases with rows and columns. "
                                "Unstructured data includes text, images, and videos. "
                                "Semi-structured data like JSON or XML sits in between. "
                                "Understanding the data type is critical before choosing any algorithm."
                            ),
                            "duration_s": 90,
                            "concepts": [
                                {
                                    "term": "Data Warehouse",
                                    "definition": "A centralized repository that integrates data from "
                                                  "multiple sources, optimized for analytical queries.",
                                    "example": "A company's sales data warehouse that aggregates data "
                                               "from all regional offices for OLAP analysis.",
                                    "type": "definition",
                                }
                            ],
                        },
                    ],
                },
            ],
        })