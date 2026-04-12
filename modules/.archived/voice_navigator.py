"""
╔══════════════════════════════════════════════════════════════════════╗
║        SMART TEACHER — Navigation Vocale v2                        ║
║                                                                      ║
║  AMÉLIORATIONS v2 :                                                  ║
║    ✅ Commandes de navigation par chapitre                          ║
║    ✅ Détection directe de numéro de chapitre (ch1..ch7)            ║
║    ✅ Navigation par titre de section (fuzzy matching)               ║
║    ✅ Commandes anglaises enrichies                                   ║
║    ✅ Réponses confirmant le chapitre ciblé                          ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import re
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

log = logging.getLogger("SmartTeacher.VoiceNav")

# Chapitres génériques
CHAPTERS = {
    1: "Introduction",
    2: "Data, Dataset, Data Warehouse",
    3: "Exploratory Data Analysis",
    4: "Data Cleaning & Preprocessing",
    5: "Feature Engineering",
    6: "Supervised Machine Learning",
    7: "Unsupervised Machine Learning",
}


class NavCommand(str, Enum):
    NEXT_SECTION    = "next_section"
    PREV_SECTION    = "prev_section"
    NEXT_CHAPTER    = "next_chapter"
    PREV_CHAPTER    = "prev_chapter"
    REPEAT          = "repeat"
    SLOWER          = "slower"
    FASTER          = "faster"
    EXPLAIN_AGAIN   = "explain_again"
    GIVE_EXAMPLE    = "give_example"
    PAUSE           = "pause"
    RESUME          = "resume"
    GOTO_TOPIC      = "goto_topic"
    GOTO_CHAPTER    = "goto_chapter"    # NOUVEAU : navigation directe ch1..ch7
    QUIZ            = "quiz"
    SUMMARY         = "summary"
    NONE            = "none"


@dataclass
class NavResult:
    command:      NavCommand
    topic:        Optional[str] = None     # pour GOTO_TOPIC
    chapter_idx:  Optional[int] = None     # pour GOTO_CHAPTER (1-7)
    raw_text:     str = ""
    confidence:   float = 1.0


class VoiceNavigator:
    """
    Analyse le texte transcrit et détecte les commandes de navigation.
    Optimisé pour la navigation dans des cours chapitrés.
    """

    PATTERNS = {
        "en": {
            NavCommand.NEXT_SECTION:  [
                r"next section", r"move on", r"let'?s? continue",
                r"go to the next", r"skip this", r"next part",
            ],
            NavCommand.PREV_SECTION:  [
                r"previous section", r"go back", r"last section",
                r"back to the previous",
            ],
            NavCommand.NEXT_CHAPTER:  [
                r"next chapter", r"skip to chapter", r"next topic",
                r"move to the next chapter",
            ],
            NavCommand.PREV_CHAPTER:  [
                r"previous chapter", r"last chapter", r"go back to chapter",
            ],
            NavCommand.GOTO_CHAPTER:  [
                # Numéro direct : "chapter 3", "ch3", "go to chapter 6"
                r"(?:go to |jump to |open )?chapter (\d)",
                r"\bch(\d)\b",
                # Par nom de chapitre DM
                r"(?:go to |open )?(?:the )?(introduction)",
                r"(?:go to |open )?(?:the )?(data warehouse|data,? dataset)",
                r"(?:go to |open )?(?:the )?(exploratory|eda)",
                r"(?:go to |open )?(?:the )?(data cleaning|preprocessing)",
                r"(?:go to |open )?(?:the )?(feature engineering)",
                r"(?:go to |open )?(?:the )?(supervised)",
                r"(?:go to |open )?(?:the )?(unsupervised)",
            ],
            NavCommand.REPEAT:        [
                r"repeat that", r"say that again", r"one more time",
                r"can you repeat", r"repeat please",
            ],
            NavCommand.SLOWER:        [
                r"slow(?:er)? down", r"speak slower", r"too fast",
                r"slow down please",
            ],
            NavCommand.FASTER:        [
                r"speed up", r"faster", r"speak faster",
            ],
            NavCommand.EXPLAIN_AGAIN: [
                r"(?:i )?don'?t understand", r"i'?m confused",
                r"explain again", r"not clear", r"can you clarify",
                r"what do you mean", r"i'?m lost",
            ],
            NavCommand.GIVE_EXAMPLE:  [
                r"give(?: me)? an example", r"can you give an example",
                r"show me an example", r"example please",
                r"concrete example",
            ],
            NavCommand.PAUSE:         [
                r"^pause$", r"\bstop\b", r"^wait$", r"hold on",
            ],
            NavCommand.RESUME:        [
                r"continue", r"go on", r"resume", r"let'?s go",
                r"^go$", r"carry on", r"keep going",
            ],
            NavCommand.GOTO_TOPIC:    [
                r"go back to (.+)", r"explain (.+)",
                r"what is (.+)", r"tell me about (.+)",
                r"what'?s? (.+)\??$",
            ],
            NavCommand.QUIZ:          [
                r"quiz me", r"test me", r"ask me a question",
                r"check my understanding",
            ],
            NavCommand.SUMMARY:       [
                r"summarize", r"summary", r"recap",
                r"what did we cover", r"what have we seen",
            ],
        },

        "fr": {
            NavCommand.NEXT_SECTION:  [
                r"section suivante", r"partie suivante", r"passe à la suite",
                r"on continue", r"au suivant", r"next",
            ],
            NavCommand.PREV_SECTION:  [
                r"section précédente", r"reviens? en arrière", r"recule",
            ],
            NavCommand.NEXT_CHAPTER:  [
                r"chapitre suivant", r"prochain chapitre",
                r"passe au chapitre",
            ],
            NavCommand.PREV_CHAPTER:  [
                r"chapitre précédent", r"retourne au chapitre",
            ],
            NavCommand.GOTO_CHAPTER:  [
                r"(?:aller au |va au |passe au )?chapitre (\d)",
                r"\bch(\d)\b",
                r"(?:aller à |va à )?(introduction)",
                r"(?:aller à |va à )?(entrepôt de données|data warehouse)",
                r"(?:aller à |va à )?(analyse exploratoire|eda)",
                r"(?:aller à |va à )?(nettoyage|prétraitement)",
                r"(?:aller à |va à )?(feature engineering|ingénierie)",
                r"(?:aller à |va à )?(apprentissage supervisé|supervisé)",
                r"(?:aller à |va à )?(apprentissage non supervisé|non supervisé)",
            ],
            NavCommand.REPEAT:        [
                r"répète[- ]?[ça]?", r"redis[- ]?le", r"encore une fois",
                r"tu peux répéter",
            ],
            NavCommand.SLOWER:        [
                r"plus lentement", r"moins vite", r"ralentis",
            ],
            NavCommand.FASTER:        [
                r"plus vite", r"accélère",
            ],
            NavCommand.EXPLAIN_AGAIN: [
                r"(je n'?ai pas compris|pas compris|je comprends? pas)",
                r"explique (encore|autrement|différemment)",
                r"c'est pas clair", r"je suis perdu",
            ],
            NavCommand.GIVE_EXAMPLE:  [
                r"donne[- ]?m?o?i? un exemple", r"illustre",
            ],
            NavCommand.PAUSE:         [
                r"^pause$", r"arrête[- ]?toi", r"stop", r"attends?",
            ],
            NavCommand.RESUME:        [
                r"continue[sz]?", r"reprends?", r"vas[- ]?y",
            ],
            NavCommand.GOTO_TOPIC:    [
                r"revien[st]? sur (.+)", r"parle[- ]?moi de (.+)",
                r"explique[- ]?moi (.+)", r"c'est quoi (.+)",
            ],
            NavCommand.QUIZ:          [
                r"interroge[- ]?moi", r"teste[- ]?moi", r"quiz",
            ],
            NavCommand.SUMMARY:       [
                r"résume[- ]?[ça]?", r"fais un résumé", r"récapitule",
            ],
        },

        "ar": {
            NavCommand.NEXT_SECTION:  [r"القسم التالي", r"انتقل للتالي", r"تابع"],
            NavCommand.PREV_SECTION:  [r"القسم السابق", r"ارجع للسابق"],
            NavCommand.NEXT_CHAPTER:  [r"الفصل التالي", r"انتقل للفصل"],
            NavCommand.GOTO_CHAPTER:  [r"اذهب إلى الفصل (\d)", r"الفصل (\d)"],
            NavCommand.REPEAT:        [r"أعد", r"كرر", r"مرة أخرى"],
            NavCommand.SLOWER:        [r"بشكل أبطأ", r"ببطء"],
            NavCommand.EXPLAIN_AGAIN: [r"لم أفهم", r"ما فهمت", r"اشرح مرة"],
            NavCommand.GIVE_EXAMPLE:  [r"أعطني مثال", r"مثال"],
            NavCommand.PAUSE:         [r"توقف", r"استراحة"],
            NavCommand.RESUME:        [r"تابع", r"استمر"],
            NavCommand.GOTO_TOPIC:    [r"تحدث عن (.+)", r"اشرح (.+)"],
            NavCommand.SUMMARY:       [r"لخص", r"ملخص"],
        },
    }

    # Mapping de nom de section → chapter_idx
    SECTION_NAMES = {
        "introduction": 1,
        "data warehouse": 2, "dataset": 2, "data,": 2,
        "exploratory": 3, "eda": 3,
        "cleaning": 4, "preprocessing": 4, "prétraitement": 4,
        "feature engineering": 5, "ingénierie": 5,
        "supervised": 6, "supervisé": 6,
        "unsupervised": 7, "non supervisé": 7, "clustering": 7,
    }

    def detect(self, text: str, language: str = "en") -> NavResult:
        """
        Analyse le texte et retourne la commande détectée.
        Priorité : GOTO_CHAPTER > commandes spécifiques > NONE.
        """
        text_lower = text.lower().strip()
        lang       = language[:2].lower()
        patterns   = self.PATTERNS.get(lang, self.PATTERNS["en"])

        # ── Vérification prioritaire GOTO_CHAPTER ─────────────────────
        # "chapter 3" / "ch3" / "chapter three"
        ch_direct = re.search(r'\bchapter\s+(\d)\b|\bch(\d)\b', text_lower, re.IGNORECASE)
        if ch_direct:
            idx = int(ch_direct.group(1) or ch_direct.group(2))
            if 1 <= idx <= 7:
                return NavResult(
                    command=NavCommand.GOTO_CHAPTER,
                    chapter_idx=idx,
                    raw_text=text,
                )

        # Noms textuels génériques
        for name, ch_idx in self.SECTION_NAMES.items():
            if name in text_lower:
                # Vérifier que c'est bien une commande de navigation
                nav_indicators = [
                    "go to", "jump", "chapter", "open", "aller", "chapitre",
                    "skip to", "passe", "انتقل", "اذهب"
                ]
                if any(ind in text_lower for ind in nav_indicators):
                    return NavResult(
                        command=NavCommand.GOTO_CHAPTER,
                        chapter_idx=ch_idx,
                        raw_text=text,
                    )

        # ── Patterns standards ─────────────────────────────────────────
        for command, regexes in patterns.items():
            for pattern in regexes:
                m = re.search(pattern, text_lower, re.IGNORECASE)
                if m:
                    # GOTO_CHAPTER : extraire le numéro
                    if command == NavCommand.GOTO_CHAPTER and m.lastindex:
                        try:
                            raw_idx = m.group(1)
                            idx = int(raw_idx) if raw_idx.isdigit() else \
                                  self._name_to_chapter(raw_idx)
                            if idx and 1 <= idx <= 7:
                                return NavResult(
                                    command=NavCommand.GOTO_CHAPTER,
                                    chapter_idx=idx,
                                    raw_text=text,
                                )
                        except (ValueError, TypeError):
                            pass

                    # GOTO_TOPIC : extraire le sujet
                    topic = None
                    if command == NavCommand.GOTO_TOPIC and m.lastindex:
                        topic = m.group(1).strip()

                    log.info(f"🎯 Commande : {command.value} | '{text[:50]}'")
                    return NavResult(command=command, topic=topic, raw_text=text)

        return NavResult(command=NavCommand.NONE, raw_text=text)

    def _name_to_chapter(self, name: str) -> int | None:
        """Convertit un nom de chapitre en index."""
        name_lower = name.lower()
        for kw, idx in self.SECTION_NAMES.items():
            if kw in name_lower:
                return idx
        return None

    def get_response(self, command: NavCommand, language: str = "en",
                     chapter_idx: int | None = None) -> str:
        """Retourne une réponse verbale confirmant la commande."""
        lang = language[:2].lower()

        # Réponse spéciale GOTO_CHAPTER avec nom de chapitre
        if command == NavCommand.GOTO_CHAPTER and chapter_idx:
            ch_title = CHAPTERS.get(chapter_idx, f"Chapter {chapter_idx}")
            responses = {
                "en": f"Sure, jumping to Chapter {chapter_idx}: {ch_title}.",
                "fr": f"D'accord, je passe au Chapitre {chapter_idx} : {ch_title}.",
                "ar": f"حسنًا، ننتقل إلى الفصل {chapter_idx}: {ch_title}.",
            }
            return responses.get(lang, responses["en"])

        responses = {
            "en": {
                NavCommand.NEXT_SECTION:  "Moving to the next section.",
                NavCommand.PREV_SECTION:  "Going back to the previous section.",
                NavCommand.NEXT_CHAPTER:  "Moving to the next chapter.",
                NavCommand.PREV_CHAPTER:  "Going back to the previous chapter.",
                NavCommand.REPEAT:        "Let me repeat that.",
                NavCommand.SLOWER:        "Sure, I'll slow down.",
                NavCommand.FASTER:        "Sure, speeding up.",
                NavCommand.EXPLAIN_AGAIN: "No problem, let me explain that differently.",
                NavCommand.GIVE_EXAMPLE:  "Here's a concrete example.",
                NavCommand.PAUSE:         "Paused. Say 'continue' when ready.",
                NavCommand.RESUME:        "Resuming the lesson.",
                NavCommand.QUIZ:          "Great! Let me test your understanding.",
                NavCommand.SUMMARY:       "Here's a summary of what we covered.",
                NavCommand.GOTO_TOPIC:    "Let me cover that topic.",
            },
            "fr": {
                NavCommand.NEXT_SECTION:  "Passons à la section suivante.",
                NavCommand.PREV_SECTION:  "Je reviens à la section précédente.",
                NavCommand.NEXT_CHAPTER:  "Passons au chapitre suivant.",
                NavCommand.PREV_CHAPTER:  "Je reviens au chapitre précédent.",
                NavCommand.REPEAT:        "Je répète.",
                NavCommand.SLOWER:        "D'accord, je parle plus lentement.",
                NavCommand.FASTER:        "D'accord, j'accélère.",
                NavCommand.EXPLAIN_AGAIN: "Pas de problème, je reformule.",
                NavCommand.GIVE_EXAMPLE:  "Voici un exemple concret.",
                NavCommand.PAUSE:         "Pause. Dites 'continue' quand vous êtes prêt.",
                NavCommand.RESUME:        "Je reprends le cours.",
                NavCommand.QUIZ:          "Parfait ! Je vous pose une question.",
                NavCommand.SUMMARY:       "Voici un résumé de ce que nous avons vu.",
            },
            "ar": {
                NavCommand.NEXT_SECTION:  "ننتقل للقسم التالي.",
                NavCommand.REPEAT:        "سأعيد.",
                NavCommand.EXPLAIN_AGAIN: "لا بأس، سأشرح بطريقة أخرى.",
                NavCommand.PAUSE:         "توقف. قل 'تابع' عندما تكون مستعدًا.",
                NavCommand.RESUME:        "نكمل الدرس.",
            },
        }
        lang_resp = responses.get(lang, responses["en"])
        return lang_resp.get(command, "")