"""
╔══════════════════════════════════════════════════════════════════════╗
║     SMART TEACHER — Configuration Domaines & Cours v5              ║
║                                                                      ║
║  Structure 100% DYNAMIQUE : Découverte depuis les dossiers         ║
║  - Domaines & Cours : découverts depuis courses/{domain}/          ║
║  - Chapitre : découverts dynamiquement depuis les fichiers         ║
║  - Métadonnées : générées automatiquement depuis les noms          ║
║                                                                      ║
║  Aucun hardcodage des cours ! Tout est automatique.                ║
║                                                                      ║
║  Exemple :                                                           ║
║    courses/informatique/                                            ║
║    ├── calcul/                                                     ║
║    │   ├── Chapter 1.pdf                                           ║
║    │   └── Chapter 2.pdf                                           ║
║    └── linguistique/                                               ║
║        ├── Chapter 1.pdf                                           ║
║        └── Chapter 2.pdf                                           ║
║                                                                      ║
║  Pour AJOUTER UN COURS : Créez simplement le dossier !            ║
║    mkdir -p courses/informatique/"MonNouveauCours"                 ║
║    cp mon_pdf.pdf "courses/informatique/MonNouveauCours/"          ║
║  C'est tout ! Le cours sera automatiquement détecté.               ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from typing import Dict
import sys

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

# ═══════════════════════════════════════════════════════════════════════
#  CONFIGURATION DOMAINES & COURS (ACTUELS)
# ═══════════════════════════════════════════════════════════════════════
#  - INFORMATIQUE : 4 cours principaux
#  - Autres domaines : à ajouter progressivement
# ═══════════════════════════════════════════════════════════════════════

DOMAINS: Dict[str, list] = {
    "informatique": [],  # Découvert dynamiquement depuis courses/informatique/
}

# ═══════════════════════════════════════════════════════════════════════
#  MÉTADONNÉES OPTIONNELLES (SPÉCIALISÉES)
# ═══════════════════════════════════════════════════════════════════════
#  Utilisé seulement si vous voulez personnaliser les métadonnées
#  Sinon, les métadonnées sont auto-générées depuis le nom du cours

COURSE_METADATA: Dict[str, Dict[str, dict]] = {}
# Exemple si vous voulez personnaliser un cours:
# {
#     "informatique": {
#         "mon_cours": {
#             "title": "Mon cours",
#             "description": "Contenu du cours",
#             "level": "licence",
#             "language": "fr",
#         },
#     },
# }

# ═══════════════════════════════════════════════════════════════════════
#  FONCTIONS UTILITAIRES
# ═══════════════════════════════════════════════════════════════════════

def get_domains() -> list[str]:
    """Retourne la liste des domaines disponibles."""
    from pathlib import Path

    domains = set(DOMAINS.keys())
    courses_dir = Path("courses")
    if courses_dir.exists():
        for domain_folder in courses_dir.iterdir():
            if domain_folder.is_dir():
                domains.add(domain_folder.name)

    return sorted(domains)


def get_courses(domain: str) -> list[str]:
    """
    Retourne les cours d'un domaine.
    Les cours sont découverts DYNAMIQUEMENT depuis les dossiers dans courses/{domain}/
    """
    from pathlib import Path
    
    # Lire dynamiquement les dossiers dans courses/{domain}/
    domain_dir = Path("courses") / domain
    
    if not domain_dir.exists():
        return []
    
    # Récupérer tous les sous-dossiers (qui représentent les cours)
    courses = []
    for course_folder in sorted(domain_dir.iterdir()):
        if course_folder.is_dir():
            courses.append(course_folder.name)
    
    return courses


def get_courses_list(domain: str) -> list[str]:
    """Alias pour get_courses()."""
    return get_courses(domain)


def get_course_metadata(domain: str, course: str) -> dict:
    """
    Retourne les métadonnées d'un cours (titre, description, etc.).
    
    Les métadonnées sont découvertes DYNAMIQUEMENT:
    1. D'abord, cherche dans COURSE_METADATA (pour les cours spécialisés)
    2. Sinon, génère automatiquement à partir du nom du dossier
    """
    # Si dans COURSE_METADATA, retourner ça
    if domain in COURSE_METADATA and course in COURSE_METADATA[domain]:
        return COURSE_METADATA[domain][course]
    
    # Sinon, générer automatiquement depuis le nom du dossier
    # "mon_cours" → "Mon Cours"
    # "Traitement Automatique du Langage Naturel" → "Traitement Automatique du Langage Naturel"
    title = course.replace("_", " ").title() if "_" in course else course
    
    return {
        "title": title,
        "description": f"Cours : {title}",
        "level": "licence",
        "language": "fr",
    }


def get_course_title(domain: str, course: str) -> str:
    """Retourne le titre d'un cours."""
    return get_course_metadata(domain, course).get("title", course)


# ═══════════════════════════════════════════════════════════════════════
#  FONCTIONS DE DÉCOUVERTE DE CHAPITRES (DYNAMIQUE)
# ═══════════════════════════════════════════════════════════════════════

from pathlib import Path
import re

def discover_chapters(domain: str, course: str) -> Dict[int, str]:
    """
    Découvre automatiquement les chapitres depuis le dossier cours.
    
    Structure attendue :
        courses/{domain}/{course}/
        ├── Chapter 1.pdf
        ├── Chapter 2.pdf
        ├── Chapter 3.pdf
        └── ...
    
    Retourne un dict {1: "Nom du chapitre", 2: "...", ...}
    Les noms peuvent être :
    1. Extraits du contenu PDF (futur)
    2. Extraits du titre du fichier (actuellement)
    3. Auto-générés si absent
    
    Returns:
        Dict[int, str] : {chapter_number: chapter_title}
    """
    course_path = Path("courses") / domain / course
    
    if not course_path.exists():
        return {}

    def _extract_chapter_num(name: str) -> int | None:
        patterns = [
            r"[Cc]hapter\s+(\d+)",
            r"[Cc]hapitre\s+(\d+)",
            r"[Cc]h(\d+)",
            r"(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, name)
            if match:
                for group in match.groups():
                    if group:
                        return int(group)
        return None
    
    # Patterns de fichiers acceptés
    chapters = {}

    # Chapitres au niveau racine
    for pdf_file in sorted(course_path.glob("*.pdf")):
        chapter_num = _extract_chapter_num(pdf_file.stem) or _extract_chapter_num(pdf_file.name)
        if chapter_num is None:
            continue
        chapters[chapter_num] = f"Chapter {chapter_num}"

    # Chapitres dans des sous-dossiers chapter_*/
    for subdir in sorted(course_path.iterdir()):
        if not subdir.is_dir():
            continue
        chapter_num = _extract_chapter_num(subdir.name)
        pdfs = sorted(list(subdir.glob("*.pdf")))
        if chapter_num is None and pdfs:
            chapter_num = _extract_chapter_num(pdfs[0].stem) or _extract_chapter_num(pdfs[0].name)
        if chapter_num is None:
            continue
        chapters[chapter_num] = f"Chapter {chapter_num}"
    
    return chapters


def get_chapters(domain: str, course: str) -> Dict[int, str]:
    """
    Retourne les chapitres d'un cours.
    Chapitres découverts dynamiquement depuis les fichiers.
    
    Returns:
        Dict[int, str] : {1: "Chapter 1", 2: "Chapter 2", ...}
    """
    courses_list = get_courses(domain)
    if course not in courses_list:
        raise ValueError(
            f"Cours '{course}' introuvable dans '{domain}'. "
            f"Disponibles : {courses_list}"
        )
    
    return discover_chapters(domain, course)


def get_chapter_title(domain: str, course: str, chapter_idx: int) -> str:
    """Retourne le titre d'un chapitre spécifique."""
    chapters = get_chapters(domain, course)
    if chapter_idx not in chapters:
        raise ValueError(
            f"Chapitre {chapter_idx} introuvable dans {course}. "
            f"Disponibles : {list(chapters.keys())}"
        )
    return chapters[chapter_idx]


# ═══════════════════════════════════════════════════════════════════════
#  VALEURS PAR DÉFAUT (Génériques)
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_DOMAIN = "general"  # Domaine générique par défaut
DEFAULT_COURSE = "generic"  # Cours générique par défaut

print(f"✅ Config Domaines & Cours chargée : {len(DOMAINS)} domaine(s)")
print(f"   Domaines actuels : {list(DOMAINS.keys())}")
print(f"   📝 Chapitres découverts DYNAMIQUEMENT depuis courses/{{domain}}/{{course}}/")
print(f"   💡 Ajouter un nouveau domaine : modifier ce fichier + créer le dossier courses/{{new_domain}}/")
print(f"   Defaults: domain='{DEFAULT_DOMAIN}', course='{DEFAULT_COURSE}' (Génériques)")

# ═══════════════════════════════════════════════════════════════════════
#  DÉTECTION AUTOMATIQUE DU DOMAINE & COURS
# ═══════════════════════════════════════════════════════════════════════
#  
#  La détection fonctionne 100% dynamiquement:
#  1. Cherche dans les dossiers existants de courses/
#  2. Compare le nom du fichier et le contenu avec les noms des cours
#  3. Aucun mot-clé hardcodé, tout est automatique!
#

def auto_detect_course(file_path: str) -> tuple[str, str]:
    """
    Détecte le domaine et course depuis un fichier PDF.
    
    Stratégie (par ordre de priorité):
    1. Cherche si le fichier est DÉJÀ dans courses/{domain}/{course}/
    2. Compare le nom du fichier avec les noms des cours existants
    3. Compare le contenu PDF avec les noms des cours
    4. Fallback: retourne le domaine/cours par défaut
    
    Args:
        file_path: Chemin vers le fichier PDF
    
    Returns:
        tuple[str, str] : (domain, course) - découvert AUTOMATIQUEMENT
    """
    from pathlib import Path
    import unicodedata
    
    file_path_obj = Path(file_path)
    
    def normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        normalized = normalized.lower().replace("_", " ").replace("-", " ")
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        return " ".join(normalized.split())

    filename_key = normalize_text(file_path_obj.stem)
    parts = [part for part in file_path_obj.parts if part not in ("", ".", "..")]
    normalized_parts = [normalize_text(part) for part in parts]
    text_key = ""

    try:
        from unstructured.partition.auto import partition
        elements = partition(file_path)
        text = " ".join((getattr(el, "text", None) or str(el) or "") for el in elements)
        text_key = normalize_text(text)
    except Exception:
        text_key = ""

    # STRATÉGIE 0: si le chemin contient déjà courses/{domain}/{course}/, on le réutilise
    if "courses" in normalized_parts:
        courses_index = normalized_parts.index("courses")
        if courses_index + 2 < len(parts):
            hinted_domain = parts[courses_index + 1]
            hinted_course = parts[courses_index + 2]
            hinted_domain_key = normalize_text(hinted_domain)
            hinted_course_key = normalize_text(hinted_course)
            if hinted_domain_key not in {"", "general"} and hinted_course_key not in {"", "generic"}:
                return (hinted_domain, hinted_course)
    
    # STRATÉGIE 1: Vérifier si le fichier est déjà dans courses/
    courses_dir = Path("courses")
    if courses_dir.exists():
        best_match: tuple[str, str] | None = None
        best_match_score = -1

        # Chercher dans tous les domaines/cours
        for domain_folder in courses_dir.iterdir():
            if not domain_folder.is_dir():
                continue
            
            domain_name = domain_folder.name
            domain_key = normalize_text(domain_name)
            
            for course_folder in domain_folder.iterdir():
                if not course_folder.is_dir():
                    continue
                
                course_name = course_folder.name
                course_key = normalize_text(course_name)

                if not course_key or course_key in {"general", "generic"}:
                    continue

                score = 0
                if course_key == filename_key:
                    score += 10
                if course_key in filename_key:
                    score += 5
                if filename_key in course_key:
                    score += 3

                if course_key in text_key:
                    score += 8

                course_tokens = [token for token in course_key.split() if token]
                if course_tokens:
                    overlap = sum(1 for token in course_tokens if token in text_key or token in filename_key)
                    score += overlap * 2

                if domain_key and domain_key in text_key:
                    score += 1

                if score > best_match_score:
                    best_match = (domain_name, course_name)
                    best_match_score = score

                # Vérifier si le fichier est déjà dans ce dossier
                for existing_file in course_folder.glob(f"*{file_path_obj.suffix}"):
                    if existing_file.name.lower() == file_path_obj.name.lower():
                        return (domain_name, course_name)

        if best_match and best_match_score > 0:
            return best_match

        # Dernier recours: renvoyer un cours non générique si la structure existe déjà.
        for domain_folder in courses_dir.iterdir():
            if not domain_folder.is_dir():
                continue
            for course_folder in domain_folder.iterdir():
                if course_folder.is_dir():
                    course_name_key = normalize_text(course_folder.name)
                    if course_name_key not in {"general", "generic"}:
                        return (domain_folder.name, course_folder.name)
    
    # STRATÉGIE 2: Comparer avec les noms des cours existants
    if courses_dir.exists():
        for domain_folder in courses_dir.iterdir():
            if not domain_folder.is_dir():
                continue
            
            domain_name = domain_folder.name
            
            for course_folder in domain_folder.iterdir():
                if not course_folder.is_dir():
                    continue
                
                course_name = course_folder.name
                course_name_key = normalize_text(course_name)
                
                # Comparer avec le NOM DU FICHIER
                if course_name_key and (course_name_key in filename_key or filename_key in course_name_key):
                    return (domain_name, course_name)
    
    # STRATÉGIE 3: Comparer avec le CONTENU DU PDF
    if courses_dir.exists():
        try:
            from unstructured.partition.auto import partition
            elements = partition(file_path)
            text = normalize_text(" ".join([(getattr(el, "text", None) or str(el) or "") for el in elements]))
            
            for domain_folder in courses_dir.iterdir():
                if not domain_folder.is_dir():
                    continue
                
                domain_name = domain_folder.name
                
                for course_folder in domain_folder.iterdir():
                    if not course_folder.is_dir():
                        continue
                    
                    course_name = course_folder.name
                    course_name_key = normalize_text(course_name)
                    if not course_name_key or course_name_key in {"general", "generic"}:
                        continue
                    
                    # Si le contenu mentionne le cours, c'est probablement ce cours
                    if course_name_key in text:
                        return (domain_name, course_name)
        except:
            pass
    
    # FALLBACK : retourner le domaine/cours par défaut
    return (DEFAULT_DOMAIN, DEFAULT_COURSE)

#
#  ✅ POUR AJOUTER UN COURS DYNAMIQUEMENT:
#
#  C'est très simple maintenant! Aucune modification de code n'est nécessaire.
#  
#  MÉTHODE 1: Ajouter un nouveau cours dans un domaine existant
#  ─────────────────────────────────────────────────────────────
#    mkdir -p "courses/informatique/Mon Nouveau Cours"
#    cp mon_pdf.pdf "courses/informatique/Mon Nouveau Cours/"
#
#    ✅ Le cours sera AUTOMATIQUEMENT découvert!
#    ✅ Les métadonnées seront AUTO-GÉNÉRÉES!
#    ✅ Les chapitres seront AUTOMATIQUEMENT listés!
#
#
#  MÉTHODE 2: Ajouter un nouveau domaine
#  ──────────────────────────────────────
#    mkdir -p courses/data_science/machine_learning
#    mkdir -p courses/data_science/statistics
#    cp mon_pdf.pdf courses/data_science/machine_learning/
#    
#  Puis modifier seulement la ligne DOMAINS:
#    DOMAINS = {
#        "informatique": [],
#        "data_science": [],  # ← Ajouter cette ligne
#    }
#
#    ✅ Tout le reste est automatique!
#
#
#  🎯 RÉSUMÉ:
#  ──────────
#  - Domaines & Cours: découverts depuis courses/
#  - Métadonnées: générées automatiquement
#  - Chapitres: détectés depuis les fichiers PDF
#  - AUCUNE configuration supplémentaire nécessaire!
#
# ═══════════════════════════════════════════════════════════════════════


