"""
╔══════════════════════════════════════════════════════════════════════╗
║  AGENT PERCEPTION — User Understanding Module                       ║
║                                                                      ║
║  Ce module COMPREND ce que l'étudiant demande/dit:                  ║
║  • Intent: ask_help, ask_quiz, comment, feedback, interrupt        ║
║  • Confusion score: basé sur mots-clés confusion                    ║
║  • Keywords: extraction des concepts clés                           ║
║  • Confidence: certitude de l'analyse                               ║
║                                                                      ║
║  INPUT: transcript (texte STT) + metadata                           ║
║  OUTPUT: PerceptionResult (structured)                              ║
║                                                                      ║
║  Utilisé par: agent/brain.py → décision action                      ║
║  Fournit:    audio_features (Phase 4 confusion detector)           ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict
from enum import Enum

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  ENUMS & TYPES
# ══════════════════════════════════════════════════════════════════════

class Intent(str, Enum):
    """Types d'intentions utilisateur détectées."""
    ASK_HELP = "ask_help"          # "Je ne comprends pas"
    ASK_CLARIFICATION = "ask_clarification"  # "Peux-tu expliquer?"
    ASK_EXAMPLE = "ask_example"    # "Donne un exemple"
    ASK_QUIZ = "ask_quiz"          # "Teste-moi"
    COMMENT = "comment"            # Engagement ("C'est intéressant")
    FEEDBACK = "feedback"          # Critique ("pas compris")
    INTERRUPT = "interrupt"        # Coupe la parole
    GREETING = "greeting"          # Salutation
    QUESTION_CLARIFY = "question_clarify"  # Questions sur ce qui a été dit
    OTHER = "other"                # Non catégorisé


@dataclass
class PerceptionResult:
    """
    Résultat de l'analyse Perception.

    Contient tout ce qu'on a compris de l'étudiant.
    """

    # Intent principal
    intent: Intent

    # Score de confusion (0-1, où 1 = très confus)
    confusion_score: float

    # Confidence de l'analyse (0-1)
    confidence: float

    # Texte transcrit
    transcript: str

    # Mots-clés extraits (concepts)
    keywords: List[str]

    # Marqueurs de confusion détectés
    confusion_markers: List[str]

    # Metadata
    language: str                  # 'fr', 'ar', 'en'
    duration_seconds: Optional[float] = None  # Durée du segment audio


# ══════════════════════════════════════════════════════════════════════
#  DICTIONNAIRES CONFESSION PROCESSING
# ══════════════════════════════════════════════════════════════════════

# FRANÇAIS
CONFUSION_WORDS_FR = {
    "comprends pas": 0.9,
    "ne comprends": 0.9,
    "confus": 0.8,
    "perdu": 0.8,
    "compliqué": 0.7,
    "c'est quoi": 0.7,
    "comment ca": 0.6,
    "pourquoi ca": 0.6,
    "pas clair": 0.8,
    "trouble": 0.7,
    "dérouté": 0.8,
    "hésitant": 0.6,
    "incertain": 0.6,
    "je sais pas": 0.7,
    "pas sûr": 0.7,
    "flou": 0.8,
    "embrouillé": 0.8,
}

HELP_WORDS_FR = {
    "aide": 1.0,
    "explique": 1.0,
    "montre": 0.9,
    "aide-moi": 1.0,
    "peux-tu": 0.8,
    "peut-tu": 0.8,
    "je veux": 0.7,
    "besoin": 0.7,
    "aide moi": 1.0,
}

QUIZ_WORDS_FR = {
    "teste": 0.9,
    "test": 0.9,
    "quiz": 1.0,
    "question": 0.7,
    "évalue": 0.9,
    "vérifie": 0.8,
    "contrôle": 0.8,
}

EXAMPLE_WORDS_FR = {
    "exemple": 1.0,
    "exemple concret": 1.0,
    "cas": 0.8,
    "situation": 0.7,
    "contexte": 0.7,
    "illustration": 0.9,
}

INTERRUPT_WORDS_FR = {
    "attends": 0.9,
    "arrête": 0.9,
    "stop": 0.9,
    "c'est bon": 0.8,
    "ça suffit": 0.8,
    "je sais": 0.7,
    "j'ai compris": 0.8,
}

# ARABE (translit standard + darija basic)
CONFUSION_WORDS_AR = {
    "فهمت ما": 0.9,          # fahemt ma (didn't understand)
    "فهمتش": 0.9,            # fahemtesh
    "مشروح": 0.8,            # macherou7 (not explained)
    "غريب": 0.7,             # gharib (strange)
    "معقد": 0.8,             # mo3akad (complicated)
    "متاه": 0.8,             # motah (lost)
    "حايرة": 0.8,            # hayra (confused - fem)
    "حاير": 0.8,             # hayir (confused - masc)
    "مشوشة": 0.8,            # mchawcha (confused - fem)
    "مشوش": 0.8,             # mchawsh (confused - masc)
}

HELP_WORDS_AR = {
    "ساعدني": 1.0,           # sa3adni (help me)
    "شرح لي": 1.0,           # shrah li (explain to me)
    "قول لي": 0.9,           # qul li (tell me)
    "شنية": 0.7,             # shniya (what is it)
    "الحاجة": 0.6,           # lhaja (the thing)
}

# ══════════════════════════════════════════════════════════════════════
#  PERCEPTION ANALYZER
# ══════════════════════════════════════════════════════════════════════

class Perception:
    """
    Analyse et comprend l'input utilisateur.

    Pipeline:
    1. Normalize transcript
    2. Detect intent
    3. Compute confusion score
    4. Extract keywords
    5. Return PerceptionResult
    """

    def __init__(self, language: str = "fr"):
        """
        Args:
            language: 'fr', 'ar', 'en'
        """
        self.language = language
        self._load_dicts()

    def _load_dicts(self):
        """Charger dictionnaires selon langue."""
        if self.language == "fr":
            self.confusion_words = CONFUSION_WORDS_FR
            self.help_words = HELP_WORDS_FR
            self.quiz_words = QUIZ_WORDS_FR
            self.example_words = EXAMPLE_WORDS_FR
            self.interrupt_words = INTERRUPT_WORDS_FR
        elif self.language == "ar":
            self.confusion_words = CONFUSION_WORDS_AR
            self.help_words = HELP_WORDS_AR
            # other dicts for AR...
        else:
            # Default English (passthrough)
            self.confusion_words = {}
            self.help_words = {}
            self.quiz_words = {}
            self.example_words = {}
            self.interrupt_words = {}

    # ─────────────────────────────────────────────────────────────────
    #  TEXT NORMALIZATION
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize: lowercase, remove punctuation, extra spaces."""
        text = text.lower()
        text = re.sub(r'[.,!?;:\'-]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    # ─────────────────────────────────────────────────────────────────
    #  INTENT DETECTION
    # ─────────────────────────────────────────────────────────────────

    def _detect_intent(self, text_norm: str) -> tuple[Intent, float]:
        """
        Détecte l'intention principale.

        Returns: (intent, confidence)
        """

        scores = {intent: 0.0 for intent in Intent}

        # 1. HELP & CLARIFICATION
        for word, weight in self.help_words.items():
            if word in text_norm:
                scores[Intent.ASK_HELP] += weight
                scores[Intent.ASK_CLARIFICATION] += weight * 0.5

        # 2. CONFUSION (texte explicite)
        for word, weight in self.confusion_words.items():
            if word in text_norm:
                scores[Intent.ASK_HELP] += weight * 0.7
                scores[Intent.FEEDBACK] += weight * 0.5

        # 3. QUIZ
        for word, weight in self.quiz_words.items():
            if word in text_norm:
                scores[Intent.ASK_QUIZ] += weight

        # 4. EXAMPLES
        for word, weight in self.example_words.items():
            if word in text_norm:
                scores[Intent.ASK_EXAMPLE] += weight
                scores[Intent.ASK_CLARIFICATION] += weight * 0.5

        # 5. INTERRUPTION
        for word, weight in self.interrupt_words.items():
            if word in text_norm:
                scores[Intent.INTERRUPT] += weight

        # 6. GREETING
        if any(w in text_norm for w in ["bonjour", "salut", "hello", "hi"]):
            scores[Intent.GREETING] += 1.0

        # 7. QUESTION PATTERNS
        if "?" in text_norm or text_norm.endswith("?"):
            scores[Intent.QUESTION_CLARIFY] += 0.7

        # 8. POSITIVE COMMENT
        if any(w in text_norm for w in ["intéressant", "cool", "bien", "super", "bien", "génial"]):
            scores[Intent.COMMENT] += 0.8

        # Find max
        best_intent = max(scores, key=scores.get)
        best_score = scores[best_intent]
        confidence = min(best_score / 2.0, 1.0)  # Normalize confidence

        # Si score très bas → OTHER
        if best_score < 0.3:
            best_intent = Intent.OTHER
            confidence = 0.3

        return best_intent, confidence

    # ─────────────────────────────────────────────────────────────────
    #  CONFUSION SCORING (TEXT ONLY)
    # ─────────────────────────────────────────────────────────────────

    def _compute_confusion_score_text(self, text_norm: str) -> tuple[float, List[str]]:
        """
        Compute confusion score du texte (0-1).

        Returns: (score, markers_list)
        """

        markers = []
        total_weight = 0.0

        for word, weight in self.confusion_words.items():
            if word in text_norm:
                markers.append(word)
                total_weight += weight

        # Normalize to 0-1
        confusion_score = min(total_weight / 3.0, 1.0)

        return confusion_score, markers

    # ─────────────────────────────────────────────────────────────────
    #  KEYWORD EXTRACTION
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        """
        Extrait mots-clés (NLP simple).

        Stratégie:
        • Remove stopwords
        • Extract nouns/verbs
        • Return most frequent words
        """

        stopwords_fr = {
            "le", "la", "les", "un", "une", "des", "et", "ou", "mais",
            "de", "du", "à", "au", "par", "pour", "dans", "sur", "avec",
            "est", "sont", "a", "c", "ca", "je", "tu", "il", "elle",
            "nous", "vous", "on", "me", "te", "se", "moi", "toi",
            "ce", "ces", "cet", "cette", "qui", "que", "quel", "quoi"
        }

        # Split & filter stopwords
        words = text.lower().split()
        keywords = [w for w in words if w not in stopwords_fr and len(w) > 2]

        # Count & sort by frequency
        from collections import Counter
        freq = Counter(keywords)

        # Return top 5
        return [word for word, _ in freq.most_common(5)]

    # ─────────────────────────────────────────────────────────────────
    #  MAIN PERCEPTION PIPELINE
    # ─────────────────────────────────────────────────────────────────

    def analyze(
        self,
        transcript: str,
        language: Optional[str] = None,
        duration_seconds: Optional[float] = None,
    ) -> PerceptionResult:
        """
        Analyse complète du transcript.

        Args:
            transcript: Texte STT
            language: Overrides self.language if provided
            duration_seconds: Durée audio

        Returns:
            PerceptionResult
        """

        if language:
            self.language = language
            self._load_dicts()

        if not transcript or len(transcript) < 2:
            log.warning("⚠️ Empty or very short transcript")
            return PerceptionResult(
                intent=Intent.OTHER,
                confusion_score=0.0,
                confidence=0.0,
                transcript=transcript,
                keywords=[],
                confusion_markers=[],
                language=self.language,
                duration_seconds=duration_seconds,
            )

        # 1. NORMALIZE
        text_norm = self._normalize_text(transcript)

        # 2. DETECT INTENT
        intent, intent_confidence = self._detect_intent(text_norm)

        # 3. COMPUTE CONFUSION SCORE (TEXT ONLY)
        confusion_score, confusion_markers = self._compute_confusion_score_text(
            text_norm
        )

        # 4. EXTRACT KEYWORDS
        keywords = self._extract_keywords(transcript)

        # 5. BUILD RESULT
        result = PerceptionResult(
            intent=intent,
            confusion_score=confusion_score,
            confidence=intent_confidence,
            transcript=transcript,
            keywords=keywords,
            confusion_markers=confusion_markers,
            language=self.language,
            duration_seconds=duration_seconds,
        )

        log.info(
            f"✅ Perception: intent={intent.value} "
            f"(confidence={intent_confidence:.0%}) | "
            f"confusion={confusion_score:.0%} | "
            f"keywords={keywords}"
        )

        return result


# ══════════════════════════════════════════════════════════════════════
#  SINGLETON HELPER
# ══════════════════════════════════════════════════════════════════════

_perception_instances: Dict[str, Perception] = {}


def get_perception(language: str = "fr") -> Perception:
    """Get or create Perception instance for language."""
    if language not in _perception_instances:
        _perception_instances[language] = Perception(language=language)
    return _perception_instances[language]


# ══════════════════════════════════════════════════════════════════════
#  EXAMPLES & TESTS
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("🧠 AGENT PERCEPTION — Examples")
    print("=" * 70)

    # Initialize
    perception_fr = get_perception("fr")

    # Test cases
    test_cases = [
        (
            "Je ne comprends pas comment la relativité affecte le temps",
            "ask_help"
        ),
        (
            "Peux-tu donner un exemple concret?",
            "ask_example"
        ),
        (
            "C'est vraiment compliqué, je suis perdu",
            "feedback"
        ),
        (
            "Teste-moi sur ce chapitre",
            "ask_quiz"
        ),
        (
            "Salut, ça va?",
            "greeting"
        ),
        (
            "Arrête, j'ai compris",
            "interrupt"
        ),
    ]

    print("\n📊 TEST RESULTS:\n")

    for transcript, expected_intent in test_cases:
        result = perception_fr.analyze(transcript)

        match = "✅" if result.intent.value == expected_intent else "❌"
        print(f"{match} Input: \"{transcript}\"")
        print(f"   Intent: {result.intent.value} (conf: {result.confidence:.0%})")
        print(f"   Confusion: {result.confusion_score:.0%}")
        print(f"   Keywords: {result.keywords}")
        if result.confusion_markers:
            print(f"   Markers: {result.confusion_markers}")
        print()

    print("=" * 70)
    print("✅ PERCEPTION MODULE READY")
    print("=" * 70)

    print("\n💡 USAGE IN AGENT:")
    print("""
from agent.perception import get_perception

perception = get_perception("fr")
result = perception.analyze(transcript="Je ne comprends pas la relativité")

# Now use result in brain.py:
decided_action = brain.decide(
    perception_result=result,
    audio_features=audio_feats,  # From audio_features_v3
    session_history=history
)
""")
