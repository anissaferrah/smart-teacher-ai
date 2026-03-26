"""
╔══════════════════════════════════════════════════════════════════════╗
║           SMART TEACHER — Module LLM v2 (Cerveau IA)              ║
║                                                                      ║
║  AMÉLIORATIONS v2 :                                                  ║
║    ✅ Prompt système spécialisé Data Mining / M2 (par langue)       ║
║    ✅ Contexte chapitre injecté dans chaque réponse                 ║
║    ✅ _clean_for_speech() amélioré : préserve acronymes DM          ║
║    ✅ present() adapté : intro DM-spécifique par chapitre           ║
║    ✅ ask() : contexte chapitre passé au système                    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import logging
import re
import time

from openai import OpenAI
from config import Config

log = logging.getLogger("SmartTeacher.LLM")

# Chapitres DM
DM_CHAPTERS = {
    1: "Introduction to Data Mining",
    2: "Data, Dataset, Data Warehouse",
    3: "Exploratory Data Analysis",
    4: "Data Cleaning & Preprocessing",
    5: "Feature Engineering",
    6: "Supervised Machine Learning",
    7: "Unsupervised Machine Learning",
}

# ── Prompts système — spécialisés Data Mining M2 ──────────────────────────────
_SYSTEM_PROMPTS = {
    "en": (
        "You are Smart Teacher, a highly experienced professor specializing in "
        "Data Mining, Machine Learning, and Artificial Intelligence. "
        "You are teaching a Master's level course (M2) at a university. "
        "You ALWAYS answer as if you are SPEAKING in class — never writing. "
        "Be concise (max 4 natural sentences) unless more detail is requested. "
        "Use precise technical terminology (k-means, SVM, AUC, Gini impurity, etc.) "
        "without dumbing it down. "
        "If a course context is provided, base your answer on it. "
        "NEVER use markdown, bullet points, or LaTeX. "
        "Write formulas in plain words: 'entropy equals minus sum of p log p'."
    ),
    "fr": (
        "Tu es Smart Teacher, un professeur expert en Data Mining, "
        "Machine Learning et Intelligence Artificielle. "
        "Tu enseignes un cours de niveau Master 2 à l'université. "
        "Tu réponds TOUJOURS comme si tu PARLAIS en cours — jamais comme un texte écrit. "
        "Sois concis (max 4 phrases naturelles) sauf si plus de détails sont demandés. "
        "Utilise la terminologie technique précise (k-means, SVM, AUC, Gini...). "
        "Si un contexte de cours est fourni, base ta réponse dessus. "
        "JAMAIS de markdown, listes, ni LaTeX. "
        "Les formules en clair : 'l'entropie égale moins la somme de p log p'."
    ),
    "ar": (
        "أنت Smart Teacher، أستاذ خبير في استخراج البيانات والتعلم الآلي. "
        "تدرّس مقرراً جامعياً من مستوى الماستر. "
        "أجب دائماً كما لو كنت تتحدث في الفصل الدراسي. "
        "كن موجزاً (4 جمل كحد أقصى). استخدم المصطلحات التقنية الدقيقة. "
        "لا markdown، لا LaTeX، لا قوائم. أجب فقط بالعربية."
    ),
}


class Brain:
    def __init__(self):
        self.client: OpenAI | None = None
        self.history: list[dict]   = []
        self.max_history_len       = Config.MAX_HISTORY_TURNS * 2

        if Config.OPENAI_API_KEY:
            try:
                self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
                log.info("✅ OpenAI connecté")
            except Exception as exc:
                log.error(f"❌ OpenAI init: {exc}")
        else:
            log.warning("⚠️  OPENAI_API_KEY absent — LLM désactivé")

    def clear_memory(self):
        self.history = []
        log.info("🧠 Mémoire effacée")

    def ask(
        self,
        question: str,
        course_context: str = "",
        reply_language: str | None = None,
        chapter_idx: int | None = None,
        chapter_title: str = "",
        section_title: str = "",
    ) -> tuple[str, float]:
        """
        Répond à une question de l'étudiant.

        NOUVEAU : chapter_idx injecté dans le prompt système
        pour contextualiser la réponse au chapitre en cours.
        """
        if not self.client:
            return "Le LLM n'est pas connecté.", 0.0

        start = time.time()
        lang  = (reply_language or "en").lower()[:2]
        system_content = _SYSTEM_PROMPTS.get(lang, _SYSTEM_PROMPTS["en"])

        # Contexte chapitre DM
        ch_ctx = ""
        if chapter_title:
            if lang == "en":
                ch_ctx = f"\nWe are currently in: '{chapter_title}'."
            elif lang == "fr":
                ch_ctx = f"\nNous sommes actuellement dans : '{chapter_title}'."
            else:
                ch_ctx = f"\nنحن الآن في : '{chapter_title}'."
            if section_title:
                ch_ctx += f" Section: '{section_title}'." if lang == "en" else \
                          f" Section : '{section_title}'."
        elif chapter_idx and chapter_idx in DM_CHAPTERS:
            ch_title = DM_CHAPTERS[chapter_idx]
            ch_ctx = f"\nWe are in Chapter {chapter_idx}: {ch_title}." if lang == "en" \
                     else f"\nNous sommes au Chapitre {chapter_idx} : {ch_title}."

        system_content += ch_ctx

        # Contexte RAG
        if course_context:
            sep = "─" * 40
            system_content += f"\n\n{sep}\nCOURSE CONTEXT:\n{course_context}\n{sep}"

        messages = (
            [{"role": "system", "content": system_content}]
            + self.history
            + [{"role": "user", "content": question}]
        )

        try:
            response = self.client.chat.completions.create(
                model=Config.GPT_MODEL,
                messages=messages,
                temperature=Config.GPT_TEMPERATURE,
                max_tokens=Config.GPT_MAX_TOKENS,
            )
            answer = self._clean_for_speech(response.choices[0].message.content)
            self.history.append({"role": "user",      "content": question})
            self.history.append({"role": "assistant", "content": answer})
            if len(self.history) > self.max_history_len:
                self.history = self.history[2:]
            duration = time.time() - start
            log.info(f"LLM ask | {duration:.2f}s | lang={lang} | {len(answer)} chars")
            return answer, duration
        except Exception as exc:
            log.error(f"❌ OpenAI error: {exc}")
            return "I'm having a technical issue. Please try again.", time.time() - start

    def present(
        self,
        section_content: str,
        language: str = "en",
        student_level: str = "université",
        chapter_idx: int | None = None,
        chapter_title: str = "",
        section_title: str = "",
    ) -> tuple[str, float]:
        """
        Présente une section de cours oralement.
        Contextualisé au chapitre DM courant.
        """
        if not self.client:
            return self._clean_for_speech(section_content), 0.0

        start = time.time()
        lang  = (language or "en").lower()[:2]

        # Contexte chapitre pour le prompt de présentation
        ch_ctx = ""
        if chapter_title:
            ch_ctx = f"\nThis content is from the chapter: '{chapter_title}'." if lang == "en" \
                     else f"\nCe contenu est du chapitre : '{chapter_title}'."
        elif chapter_idx and chapter_idx in DM_CHAPTERS:
            ch_ctx = f"\nChapter: {DM_CHAPTERS[chapter_idx]}."

        present_prompts = {
            "en": (
                "You are an experienced Data Mining professor presenting a lecture to M2 students. "
                "You receive raw course content and must PRESENT it out loud.\n\n"
                f"{ch_ctx}\n\n"
                "ABSOLUTE RULES:\n"
                "- Start naturally: 'In this section, we will look at...', 'Now let's discuss...'\n"
                "- NEVER read the text word for word. Rephrase in your own words.\n"
                "- ZERO markdown: no **, no #, no bullet points, no lists.\n"
                "- ZERO LaTeX: write math in plain words "
                "('entropy equals minus sum of p times log p').\n"
                "- Keep ALL technical DM/ML terms: k-means, SVM, AUC, Gini, etc.\n"
                "- Natural academic transitions: 'Now, what's important here is...', "
                "'Let me elaborate on...', 'This connects to...'\n"
                "- A concrete DM/ML example (not a generic daily-life analogy).\n"
                "- 6 to 10 natural sentences. Only in English."
            ),
            "fr": (
                "Tu es un professeur de Data Mining expérimenté qui présente un cours à des étudiants M2. "
                "Tu reçois le contenu brut d'une section et dois le PRÉSENTER à voix haute.\n\n"
                f"{ch_ctx}\n\n"
                "RÈGLES ABSOLUES :\n"
                "- Commence naturellement : 'Dans cette partie, nous allons voir...'\n"
                "- NE LIS JAMAIS le texte mot pour mot. Reformule avec tes propres mots.\n"
                "- ZÉRO markdown : pas de **, pas de #, pas de tirets, pas de listes.\n"
                "- ZÉRO LaTeX : formules en clair "
                "('l'entropie égale moins la somme de p fois log p').\n"
                "- Conserve TOUS les termes techniques DM/ML : k-means, SVM, AUC, Gini, etc.\n"
                "- Transitions académiques naturelles : 'Ce qui est important ici...', "
                "'Cela rejoint le concept de...'\n"
                "- Un exemple concret DM/ML (pas une analogie de la vie quotidienne générique).\n"
                "- 6 à 10 phrases naturelles. Uniquement en français."
            ),
            "ar": (
                "أنت أستاذ متخصص في استخراج البيانات تقدم محاضرة لطلاب الماستر.\n\n"
                f"{ch_ctx}\n\n"
                "قواعد مطلقة:\n"
                "- لا markdown، لا LaTeX، جمل طبيعية فقط.\n"
                "- احتفظ بالمصطلحات التقنية: k-means، SVM، AUC، Gini.\n"
                "- 6 إلى 10 جمل طبيعية. أجب فقط بالعربية."
            ),
        }

        # Ajustement selon le niveau
        level_hint = ""
        if student_level == "université" and lang == "en":
            level_hint = " Use precise technical terminology appropriate for Master's level students."
        elif student_level == "lycée" and lang == "en":
            level_hint = " Simplify slightly without losing technical accuracy."

        system_content = present_prompts.get(lang, present_prompts["en"]) + level_hint

        try:
            response = self.client.chat.completions.create(
                model=Config.GPT_MODEL,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user",   "content": f"Content to present:\n\n{section_content}"},
                ],
                temperature=0.7,
                max_tokens=700,
            )
            answer   = self._clean_for_speech(response.choices[0].message.content.strip())
            duration = time.time() - start
            log.info(f"LLM present | {duration:.2f}s | ch={chapter_idx} | {len(answer)} chars")
            return answer, duration
        except Exception as exc:
            log.error(f"❌ LLM present error: {exc}")
            return self._clean_for_speech(section_content), time.time() - start

    def chat(self, content: str, language: str = "en") -> str:
        """Alias rétrocompatible."""
        text, _ = self.present(section_content=content, language=language)
        return text

    def _clean_for_speech(self, text: str) -> str:
        """
        Supprime markdown et LaTeX pour la synthèse vocale.
        PRÉSERVE les acronymes DM : k-means, SVM, AUC, k-NN, etc.
        """
        # Protéger les acronymes importants avant le nettoyage
        protected_map: dict[str, str] = {}
        dm_terms = [
            "k-means", "k-NN", "k-nn", "t-SNE", "t-sne", "U-MAP", "u-map",
            "XGBoost", "LightGBM", "CatBoost",
        ]
        for i, term in enumerate(dm_terms):
            ph = f"__DM{i}__"
            if term.lower() in text.lower():
                protected_map[ph] = term
                text = re.sub(re.escape(term), ph, text, flags=re.IGNORECASE)

        # Nettoyage standard
        text = re.sub(r'\\\[.*?\\\]', '', text, flags=re.DOTALL)
        text = re.sub(r'\$\$.*?\$\$', '', text, flags=re.DOTALL)
        text = re.sub(r'\\\(.*?\\\)', '', text, flags=re.DOTALL)
        text = re.sub(r'\$[^$\n]+\$', '', text)
        text = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', text)
        text = re.sub(r'\\[a-zA-Z]+', '', text)
        text = re.sub(r'#{1,6}\s+', '', text)
        text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)
        text = re.sub(r'_{1,3}([^_\n]+)_{1,3}', r'\1', text)
        text = re.sub(r'^\s*[-•–—]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\d+[.)]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\\n|\\t|\\r', ' ', text)
        text = text.replace('\\', '')
        text = re.sub(r'```[^`]*```', '', text, flags=re.DOTALL)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'  +', ' ', text)

        # Restaurer les acronymes protégés
        for ph, term in protected_map.items():
            text = text.replace(ph, term)

        return text.strip()