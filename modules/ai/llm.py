"""Smart Teacher — LLM Module (OpenAI GPT + Local LLM Fallback)"""

from __future__ import annotations

import json
import logging
import re
import time
from difflib import SequenceMatcher

import requests
from openai import OpenAI

from config import Config
from modules.ai.local_llm import LocalLLMFallback

log = logging.getLogger("SmartTeacher.LLM")


_FALLBACK_PROMPTS = {
    "en": (
        "You are Smart Teacher, a highly experienced professor. "
        "You are teaching a Master's level course (M2) at a university. "
        "You ALWAYS answer as if you are SPEAKING in class - never writing. "
        "Be concise (max 4 natural sentences) unless more detail is requested. "
        "Use precise technical terminology without dumbing it down. "
        "NEVER use markdown, bullet points, or LaTeX. "
        "If an idea has already been stated, do not repeat it with slightly different wording."
    ),
    "fr": (
        "Tu es Smart Teacher, un professeur expert. "
        "Tu enseignes un cours de niveau Master 2 à l'université. "
        "Tu réponds TOUJOURS comme si tu PARLAIS en cours - jamais comme un texte écrit. "
        "Sois concis (max 4 phrases naturelles) sauf si plus de détails sont demandés. "
        "Utilise la terminologie technique précise. "
        "JAMAIS de markdown, listes, ni LaTeX. "
        "Si une idée a déjà été dite, ne la répète pas avec des mots proches."
    ),
}


_FALLBACK_PRESENTATION_PROMPTS = {
    "en": (
        "You are an experienced professor presenting a lecture to M2 students. "
        "Present only the current slide content out loud naturally. "
        "Focus only on this slide/page, not future slides. "
        "- NEVER read word for word. Rephrase in your own words.\n"
        "- ZERO markdown and LaTeX.\n"
        "- 3 to 5 natural sentences. Only in English."
    ),
    "fr": (
        "Tu es un professeur expérimenté qui présente un cours à des étudiants M2. "
        "Présente seulement le contenu de la slide courante à voix haute naturellement. "
        "Concentre-toi sur cette slide/page, pas sur les suivantes. "
        "- NE LIS JAMAIS le texte mot pour mot. Reformule.\n"
        "- ZÉRO markdown et LaTeX.\n"
        "- 3 à 5 phrases naturelles. Uniquement en français."
    ),
}


def _resolve_domain_prompt_parts(domain: str | None) -> tuple[str, str]:
    """Return human-readable domain description and label for prompts."""
    fallback_desc = "specialty subjects"
    fallback_name = "diverse topics"

    if not domain:
        return fallback_desc, fallback_name

    try:
        from domains_config import DOMAINS
    except ImportError:
        human = domain.replace("_", " ")
        return human, human

    domain_entry = DOMAINS.get(domain)
    human_domain = domain.replace("_", " ")

    if isinstance(domain_entry, dict):
        return (
            domain_entry.get("description", human_domain),
            domain_entry.get("name", human_domain),
        )

    if isinstance(domain_entry, list):
        return human_domain, human_domain

    if domain_entry is not None:
        return human_domain, human_domain

    return human_domain, human_domain


# ══════════════════════════════════════════════════════════════════════
#  DÉTECTION AUTOMATIQUE DE CONFUSION (S29-32)
# ══════════════════════════════════════════════════════════════════════

def detect_confusion(
    transcript: str,
    previous_message: str = "",
    language: str = "fr"
) -> tuple[bool, str]:
    """
    ✅ Détecte si l'étudiant est confus ou demande une clarification.
    
    Critères :
    1. Mots clés de confusion dans le transcript
    2. Même question posée 2x (similarité > 0.8)
    
    Returns: (is_confused, reason)
    """
    if not transcript:
        return False, ""
    
    transcript_lower = transcript.lower().strip()
    
    # Mots clés par langue
    confusion_keywords = {
        "fr": ["comprends pas", "je comprends pas", "c'est pas clair", "quoi", "hein", 
               "peux tu répéter", "reexplique", "explique mieux", "c'est confus", "comprend rien"],
        "en": ["don't understand", "i don't get it", "what", "huh", "can you repeat", 
               "explain again", "that's confusing", "not clear"],
    }
    
    lang_keywords = confusion_keywords.get(language.lower()[:2], confusion_keywords["fr"])
    
    # 1️⃣ Détection par mot clé
    for keyword in lang_keywords:
        if keyword in transcript_lower:
            return True, f"Confusion keyword detected: '{keyword}'"
    
    # 2️⃣ Détection de question répétée (similarité)
    if previous_message:
        from difflib import SequenceMatcher
        similarity = SequenceMatcher(None, transcript_lower, previous_message.lower()).ratio()
        if similarity > 0.75:  # 75% similaire = même question
            return True, f"Question répétée (similarité: {similarity:.0%})"
    
    return False, ""


def get_clarification_prompt(language: str = "fr", domain: str = None) -> str:
    """
    ✅ Prompt spécial quand l'étudiant demande une clarification.
    Demande une explication PLUS SIMPLE et PLUS DIRECTE.
    """
    clarification_prompts = {
        "en": (
            "The student is confused. Your task is to CLARIFY and SIMPLIFY your explanation.\n"
            "- Use ONLY simple words (no advanced terminology).\n"
            "- Give a CONCRETE EXAMPLE first.\n"
            "- Explain the core idea in 2-3 sentences maximum.\n"
            "- Then explain the more technical part.\n"
            "- Ask: 'Does that make sense?'"
        ),
        "fr": (
            "L'étudiant est confus. Tu dois CLARIFIER et SIMPLIFIER ta réponse.\n"
            "- Utilise des mots FACILES (pas de jargon).\n"
            "- Donne d'ABORD un EXEMPLE CONCRET.\n"
            "- Explique l'idée centrale en 2-3 phrases max.\n"
            "- Puis explique la partie plus technique.\n"
            "- Demande : 'C'est plus clair?'"
        ),
    }
    
    lang = language.lower()[:2]
    return clarification_prompts.get(lang, clarification_prompts["en"])


def get_system_prompt(domain: str = None, language: str = "en") -> str:
    """Génère un prompt système dynamique basé sur le domaine."""
    lang = language.lower()[:2] if language else "en"

    try:
        domain_desc, domain_name = _resolve_domain_prompt_parts(domain)
    except Exception:
        log.warning("⚠️  domains_config not available, using fallback prompts")
        return _FALLBACK_PROMPTS.get(language, _FALLBACK_PROMPTS["en"])

    prompts_map = {
        "en": (
            f"You are Smart Teacher, a highly experienced professor specializing in {domain_desc}. "
            f"You are teaching a Master's level course (M2) at a university. "
            f"You ALWAYS answer as if you are SPEAKING in class - never writing. "
            f"Be concise (max 4 natural sentences) unless more detail is requested. "
            f"Use precise technical terminology appropriate to {domain_name} without dumbing it down. "
            f"If a course context is provided, base your answer on it. "
            f"NEVER use markdown, bullet points, or LaTeX. "
            f"If the same idea appears more than once, merge it into one explanation. "
            f"Write formulas in plain words."
        ),
        "fr": (
            f"Tu es Smart Teacher, un professeur expert en {domain_desc}. "
            f"Tu enseignes un cours de niveau Master 2 à l'université. "
            f"Tu réponds TOUJOURS comme si tu PARLAIS en cours - jamais comme un texte écrit. "
            f"Sois concis (max 4 phrases naturelles) sauf si plus de détails sont demandés. "
            f"Utilise la terminologie technique précise en {domain_name}. "
            f"Si un contexte de cours est fourni, base ta réponse dessus. "
            f"JAMAIS de markdown, listes, ni LaTeX. "
            f"Si une même idée apparaît plusieurs fois, fusionne-la en une seule explication. "
            f"Les formules en clair."
        ),
    }

    return prompts_map.get(lang, prompts_map["en"])


def get_presentation_prompt(domain: str = None, language: str = "en", chapter_title: str = "") -> str:
    """Génère un prompt de présentation centré sur la slide courante."""
    lang = language.lower()[:2] if language else "en"

    try:
        domain_desc, domain_name = _resolve_domain_prompt_parts(domain)
    except Exception:
        log.warning("⚠️  domains_config not available, using fallback presentation prompts")
        return _FALLBACK_PRESENTATION_PROMPTS.get(language, _FALLBACK_PRESENTATION_PROMPTS["en"])

    if domain_name == domain_desc:
        domain_name = domain_name or "this field"

    chapter_ctx = f"\nThis content is from the chapter: '{chapter_title}'." if chapter_title else ""

    prompts_map = {
        "en": (
            f"You are an experienced {domain_name} professor presenting a lecture to M2 students. "
            f"You receive the current slide content and must PRESENT only this slide out loud.{chapter_ctx}\n\n"
            "ABSOLUTE RULES:\n"
            "- Focus only on the current slide/page, never on future slides.\n"
            "- Start naturally: 'In this section, we will look at...'.\n"
            "- NEVER read the text word for word. Rephrase in your own words.\n"
            "- ZERO markdown: no **, no #, no bullet points, no lists.\n"
            "- ZERO LaTeX: write math in plain words.\n"
            "- Keep ALL technical terminology from this domain.\n"
            "- If the slide repeats the same idea in several bullets, synthesize it once.\n"
            "- Do not restate the same point with small wording changes.\n"
            "- Natural academic transitions.\n"
            "- A concrete domain-specific example.\n"
            "- 3 to 5 natural sentences. Only in English."
        ),
        "fr": (
            f"Tu es un professeur de {domain_name} expérimenté qui présente un cours à des étudiants M2. "
            f"Tu reçois le contenu de la slide courante et dois PRÉSENTER uniquement cette slide à voix haute.{chapter_ctx}\n\n"
            "RÈGLES ABSOLUES :\n"
            "- Concentre-toi uniquement sur la slide/page courante, jamais sur les suivantes.\n"
            "- Commence naturellement : 'Dans cette partie, nous allons voir...'.\n"
            "- NE LIS JAMAIS le texte mot pour mot. Reformule avec tes propres mots.\n"
            "- ZÉRO markdown : pas de **, pas de #, pas de tirets, pas de listes.\n"
            "- ZÉRO LaTeX : formules en clair.\n"
            "- Conserve TOUS les termes techniques du domaine.\n"
            "- Si la slide répète la même idée plusieurs fois, synthétise une seule fois.\n"
            "- Ne redis pas le même point avec de petites variations.\n"
            "- Transitions académiques naturelles.\n"
            "- Un exemple concret spécifique au domaine.\n"
            "- 3 à 5 phrases naturelles. Uniquement en français."
        ),
    }

    return prompts_map.get(lang, prompts_map["en"])


def _extract_json_payload(raw_text: str) -> dict[str, object] | None:
    if not raw_text:
        return None

    cleaned = raw_text.strip().replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None

    return payload if isinstance(payload, dict) else None


class Brain:
    def __init__(self):
        self.client: OpenAI | None = None
        self.fallback: LocalLLMFallback | None = None
        self.history: list[dict] = []
        self.max_history_len = Config.MAX_HISTORY_TURNS * 2
        
        # ✅ Rate limiting: per-session throttler (session_id -> {last_call_time, call_count, minute_reset_time})
        self.session_throttlers: dict[str, dict] = {}
        self.min_call_interval = 1.0  # Minimum 1 second between calls per session
        self.max_calls_per_minute = 10  # Maximum 10 calls per minute per session

        if Config.OPENAI_API_KEY:
            try:
                self.client = OpenAI(api_key=Config.OPENAI_API_KEY, max_retries=0)
                log.info("✅ OpenAI API clé valide")
            except Exception as exc:
                log.error(f"❌ OpenAI erreur: {exc}")
        else:
            log.info("ℹ️ OpenAI non configuré (fallback Ollama utilisé)")

        self.fallback = LocalLLMFallback(model="mistral")

    @staticmethod
    def _should_disable_openai(exc: Exception) -> bool:
        message = f"{exc.__class__.__module__}:{exc.__class__.__name__}:{exc}".lower()
        return any(
            token in message
            for token in (
                "insufficient_quota",
                "quota",
                "429",
                "rate limit",
                "ratelimit",
                "authentication",
                "unauthorized",
                "invalid_api_key",
            )
        )

    def _disable_openai(self, reason: str) -> None:
        if self.client is not None:
            self.client = None
            log.info("ℹ️ OpenAI désactivé pour cette session (%s) → Ollama prioritaire", reason)

    def clear_memory(self):
        self.history = []
        log.info("🧠 Mémoire effacée")
    
    def _check_rate_limit(self, session_id: str | None = None) -> tuple[bool, str]:
        """
        ✅ Check if LLM call is allowed for this session.
        
        Returns:
            (allowed: bool, reason: str)
            - If allowed, reason is empty string
            - If not allowed, reason explains why
        """
        if not session_id:
            # No session_id provided, always allow (for backward compatibility)
            return True, ""
        
        now = time.time()
        
        if session_id not in self.session_throttlers:
            # First call for this session
            self.session_throttlers[session_id] = {
                "last_call_time": now,
                "call_count": 0,
                "minute_reset_time": now,
            }
            return True, ""
        
        throttler = self.session_throttlers[session_id]
        
        # 1. Check minimum interval between calls (1 second)
        time_since_last_call = now - throttler["last_call_time"]
        if time_since_last_call < self.min_call_interval:
            wait_time = self.min_call_interval - time_since_last_call
            reason = f"Rate limited: wait {wait_time:.1f}s (min interval: {self.min_call_interval}s)"
            return False, reason
        
        # 2. Check per-minute call limit
        time_since_minute_reset = now - throttler["minute_reset_time"]
        if time_since_minute_reset > 60:
            # Reset minute counter
            throttler["call_count"] = 0
            throttler["minute_reset_time"] = now
        
        if throttler["call_count"] >= self.max_calls_per_minute:
            reason = f"Per-minute limit reached ({self.max_calls_per_minute} calls/min)"
            return False, reason
        
        # All checks passed - update throttler
        throttler["last_call_time"] = now
        throttler["call_count"] += 1
        return True, ""

    def _call_ollama_sync(self, prompt: str, temperature: float = 0.7, max_tokens: int = 400) -> str | None:
        """Appel synchrone à Ollama via HTTP."""
        if not self.fallback or not self.fallback.available:
            return None

        try:
            log.info("🖥️ Appel Ollama synchrone...")
            payload = {
                "model": self.fallback.model,
                "prompt": prompt,
                "temperature": temperature,
                "num_predict": max_tokens,
                "stream": False,
            }
            response = requests.post(
                f"{self.fallback.base_url}/api/generate",
                json=payload,
                timeout=None,
            )

            if response.status_code == 200:
                result = response.json()
                answer = result.get("response", "").strip()
                if answer:
                    log.info(f"✅ Ollama réponse : {len(answer)} chars")
                    return answer
                log.warning("⚠️  Ollama réponse vide")
                return None

            log.error(f"❌ Ollama HTTP {response.status_code}")
            return None
        except requests.exceptions.Timeout:
            log.error("❌ Ollama request failed or was interrupted")
            return None
        except requests.exceptions.ConnectionError:
            log.error("❌ Ollama connexion échouée — Lancez: docker-compose up -d ollama")
            return None
        except Exception as exc:
            log.error(f"❌ Ollama erreur : {exc}")
            return None

    def ask(
        self,
        question: str,
        course_context: str = "",
        reply_language: str | None = None,
        chapter_idx: int | None = None,
        chapter_title: str = "",
        section_title: str = "",
        domain: str | None = None,
        session_id: str | None = None,  # ✅ For rate limiting
    ) -> tuple[str, float]:
        """Répond à une question de l'étudiant."""
        # ✅ Check rate limit before proceeding
        allowed, reason = self._check_rate_limit(session_id)
        if not allowed:
            log.warning(f"[{session_id[:8] if session_id else 'NA'}] ⚠️  {reason}")
            return f"Trop rapide! Attendez une seconde antes de poser une autre question.", 0.0
        
        start = time.time()
        lang = (reply_language or "en").lower()[:2]

        system_content = get_system_prompt(domain, lang)

        ch_ctx = ""
        if chapter_title:
            if lang == "en":
                ch_ctx = f"\nWe are currently in: '{chapter_title}'."
            elif lang == "fr":
                ch_ctx = f"\nNous sommes actuellement dans : '{chapter_title}'."
            else:
                ch_ctx = f"\nنحن الآن في : '{chapter_title}'."
            if section_title:
                ch_ctx += f" Section: '{section_title}'." if lang == "en" else f" Section : '{section_title}'."

        system_content += ch_ctx

        if course_context:
            sep = "─" * 40
            system_content += f"\n\n{sep}\nCOURSE CONTEXT:\n{course_context}\n{sep}"

        messages = [
            {"role": "system", "content": system_content},
            *self.history,
            {"role": "user", "content": question},
        ]

        if self.client:
            try:
                log.info("🤖 Tentative OpenAI...")
                response = self.client.chat.completions.create(
                    model=Config.GPT_MODEL,
                    messages=messages,
                    temperature=Config.GPT_TEMPERATURE,
                    max_tokens=Config.GPT_MAX_TOKENS,
                )
                answer = self._clean_for_speech(response.choices[0].message.content)
                answer = self._dedupe_answer_text(answer)
                self.history.append({"role": "user", "content": question})
                self.history.append({"role": "assistant", "content": answer})
                if len(self.history) > self.max_history_len:
                    self.history = self.history[2:]
                duration = time.time() - start
                log.info(f"✅ OpenAI OK | {duration:.2f}s | lang={lang} | {len(answer)} chars")
                return answer, duration
            except Exception as openai_err:
                if self._should_disable_openai(openai_err):
                    self._disable_openai(str(openai_err))
                log.warning(f"⚠️  OpenAI échoué: {openai_err} → Fallback Ollama...")

        if self.fallback and self.fallback.available:
            log.info("🖥️ Ollama fallback activé (sans timeout)...")
            lang_instruction = {
                "en": "\n\n[!!!CRITICAL!!!] You MUST respond ONLY in English. Any response in French or other languages is forbidden. ONLY English.",
                "fr": "\n\n[!!!CRITIQUE!!!] Tu DOIS répondre UNIQUEMENT en français. Aucune réponse en anglais ou autre langue. SEULEMENT du français.",
            }
            fallback_prompt = f"{system_content}{lang_instruction.get(lang, lang_instruction['en'])}\n\nQuestion/Prompt: {question}"
            answer = self._call_ollama_sync(
                prompt=fallback_prompt,
                temperature=Config.GPT_TEMPERATURE,
                max_tokens=250,
            )

            if answer:
                answer = self._clean_for_speech(answer)
                answer = self._dedupe_answer_text(answer)
                self.history.append({"role": "user", "content": question})
                self.history.append({"role": "assistant", "content": answer})
                if len(self.history) > self.max_history_len:
                    self.history = self.history[2:]
                duration = time.time() - start
                log.info(f"✅ Ollama OK | {duration:.2f}s | {len(answer)} chars")
                return answer, duration

        log.error("❌ LLM indisponible (OpenAI + Ollama échoué) — Vérifiez: docker-compose up -d")
        return "Je n'ai pas pu générer de réponse pour le moment. Réessayez dans un instant.", time.time() - start

    def label_confusion(
        self,
        text: str,
        domain: str = "",
        module: str = "",
        language: str = "en",
    ) -> tuple[str, float, str]:
        """Label a student text as confused or not_confused using the LLM."""
        text = (text or "").strip()
        if not text:
            return "not_confused", 0.0, "empty input"

        lang = (language or "en").lower()[:2]
        system_prompts = {
            "en": (
                "You are a strict annotation assistant for the Smart Teacher dataset. "
                "Decide whether the text expresses confusion. "
                "confused = explicit lack of understanding, request to re-explain, says lost/confused/stuck, or cannot follow the explanation. "
                "not_confused = normal question, factual question, statement of understanding, neutral remark, or administrative text. "
                "A question mark alone does NOT mean confused. "
                "Return only JSON with keys label, confidence, and reason. "
                "label must be confused or not_confused. confidence must be a number between 0 and 1."
            ),
            "fr": (
                "Tu es un annotateur strict pour le dataset Smart Teacher. "
                "Decide si le texte exprime une confusion. "
                "confused = manque de comprehension explicite, demande de reexplication, texte perdu, confus, bloque, ou incapacite a suivre l'explication. "
                "not_confused = question normale, question factuelle, phrase de comprehension, remarque neutre, ou texte administratif. "
                "Un point d'interrogation seul ne veut pas dire confused. "
                "Retourne uniquement du JSON avec les cles label, confidence et reason. "
                "label doit etre confused ou not_confused. confidence doit etre un nombre entre 0 et 1."
            ),
        }
        system_prompt = system_prompts.get(lang, system_prompts["en"])

        user_prompt = (
            f"Text: {text}\n"
            f"Language: {lang}\n"
            f"Domain: {domain or 'general'}\n"
            f"Module: {module or 'general'}\n\n"
            "Return one JSON object only."
        )

        raw_response = None

        if self.client:
            try:
                response = self.client.chat.completions.create(
                    model=Config.GPT_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.0,
                    max_tokens=120,
                )
                raw_response = (response.choices[0].message.content or "").strip()
            except Exception as openai_err:
                if self._should_disable_openai(openai_err):
                    self._disable_openai(str(openai_err))
                log.warning(f"⚠️  LLM labeling OpenAI failed: {openai_err} → fallback Ollama...")

        if not raw_response and self.fallback and self.fallback.available:
            raw_response = self._call_ollama_sync(
                prompt=f"{system_prompt}\n\n{user_prompt}",
                temperature=0.0,
                max_tokens=120,
            )

        if raw_response:
            payload = _extract_json_payload(raw_response)
            if payload:
                label = str(payload.get("label", "")).strip().lower().replace(" ", "_").replace("-", "_")
                if label in {"confused", "not_confused"}:
                    try:
                        confidence = float(payload.get("confidence", 0.0))
                    except Exception:
                        confidence = 0.0
                    confidence = max(0.0, min(1.0, confidence))
                    reason = str(payload.get("reason", "")).strip() or "LLM label"
                    return label, confidence, reason

            normalized = raw_response.lower()
            if "not_confused" in normalized or "not confused" in normalized:
                return "not_confused", 0.55, "parsed from raw LLM response"
            if "confused" in normalized:
                return "confused", 0.55, "parsed from raw LLM response"

        is_confused, reason = detect_confusion(text, language=lang)
        return ("confused" if is_confused else "not_confused"), 0.5, reason or "rule-based fallback"

    def present(
        self,
        section_content: str,
        language: str = "en",
        student_level: str = "université",
        chapter_idx: int | None = None,
        chapter_title: str = "",
        section_title: str = "",
        domain: str | None = None,
        session_id: str | None = None,  # ✅ For rate limiting
    ) -> tuple[str, float]:
        """Présente une slide ou section de cours oralement."""
        # ✅ Check rate limit before proceeding
        allowed, reason = self._check_rate_limit(session_id)
        if not allowed:
            log.warning(f"[{session_id[:8] if session_id else 'NA'}] ⚠️  {reason}")
            return "", 0.0
        
        if not section_content or not section_content.strip():
            log.warning("⚠️  Slide content vide — rien à expliquer")
            return "", 0.0

        if not self.client and not (self.fallback and self.fallback.available):
            log.error("❌ No LLM available — returning raw content")
            return self._clean_for_speech(section_content), 0.0

        start = time.time()
        lang = (language or "en").lower()[:2]
        system_content = get_presentation_prompt(domain, lang, chapter_title)

        level_hint = ""
        if student_level == "université" and lang == "en":
            level_hint = " Use precise technical terminology appropriate for Master's level students."
        elif student_level == "lycée" and lang == "en":
            level_hint = " Simplify slightly without losing technical accuracy."
        system_content += level_hint

        if self.client:
            try:
                log.info("🤖 Presentation: OpenAI...")
                response = self.client.chat.completions.create(
                    model=Config.GPT_MODEL,
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": f"Content to present:\n\n{section_content}"},
                    ],
                    temperature=0.7,
                    max_tokens=400,
                )
                answer = self._clean_for_speech(response.choices[0].message.content.strip())
                answer = self._dedupe_answer_text(answer)
                duration = time.time() - start
                log.info(f"✅ OpenAI present OK | {duration:.2f}s | ch={chapter_idx} | {len(answer)} chars")
                return answer, duration
            except Exception as openai_err:
                if self._should_disable_openai(openai_err):
                    self._disable_openai(str(openai_err))
                log.warning(f"⚠️  OpenAI presentation failed: {openai_err} → Trying Ollama...")

        if self.fallback and self.fallback.available:
            log.info("🖥️ Presentation: Ollama fallback (sans timeout)...")
            lang_instruction = {
                "en": "\n\n*** IMPORTANT: You MUST respond ONLY in English. Do NOT respond in French. ***",
                "fr": "\n\n*** IMPORTANT: Tu DOIS répondre UNIQUEMENT en français. Ne réponds pas en anglais. ***",
            }
            fallback_prompt = f"{system_content}{lang_instruction.get(lang, lang_instruction['en'])}\n\nContent to present:\n\n{section_content}"
            answer = self._call_ollama_sync(
                prompt=fallback_prompt,
                temperature=0.7,
                max_tokens=300,
            )

            if answer:
                answer = self._clean_for_speech(answer)
                answer = self._dedupe_answer_text(answer)
                duration = time.time() - start
                log.info(f"✅ Ollama present OK | {duration:.2f}s | {len(answer)} chars")
                return answer, duration

        log.warning("⚠️  All LLMs failed → returning raw content")
        return self._clean_for_speech(section_content), time.time() - start

    def chat(self, content: str, language: str = "en") -> str:
        """Alias rétrocompatible."""
        text, _ = self.present(section_content=content, language=language)
        return text

    def _dedupe_answer_text(self, text: str) -> str:
        clean_text = text.strip()
        if not clean_text:
            return clean_text

        sentences = re.split(r"(?<=[.!?])\s+", clean_text)
        kept_sentences: list[str] = []
        seen_signatures: list[str] = []

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            signature = re.sub(r"[^\w\sÀ-ÿ]+", " ", sentence.lower())
            signature = re.sub(r"\s+", " ", signature).strip()
            if not signature:
                continue

            if any(SequenceMatcher(None, signature, seen).ratio() >= 0.9 for seen in seen_signatures[-4:]):
                continue

            kept_sentences.append(sentence)
            seen_signatures.append(signature)

        deduped = " ".join(kept_sentences).strip()
        return deduped or clean_text

    def _clean_for_speech(self, text: str) -> str:
        """Supprime markdown et LaTeX pour la synthèse vocale."""
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

        for ph, term in protected_map.items():
            text = text.replace(ph, term)

        return text.strip()
