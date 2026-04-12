"""
PDF to Slides Converter

Convertit les fichiers PDF en images PNG/JPG individuelles (une par page).
Facilite l'affichage de slides avec synchronisation audio.

Classes:
    PDFToSlidesConverter: Gestionnaire de conversion PDF → Images

Exemple:
    >>> converter = PDFToSlidesConverter()
    >>> result = converter.convert_pdf(
    ...     pdf_path="courses/dm/Chapter 1.pdf",
    ...     course="dm",
    ...     chapter="chapter_1"
    ... )
    >>> image_path = converter.get_slide_path("dm", "chapter_1", 1)
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
    print("✅ pdf2image disponible")
except ImportError as e:
    PDF2IMAGE_AVAILABLE = False
    print(f"⚠️  pdf2image manquant: {e}")
    print("   Installer avec: pip install pdf2image pillow")

# Essayer de détecter poppler
try:
    import shutil
    POPPLER_PATH = None
    if shutil.which("pdftoppm"):
        POPPLER_PATH = "pdftoppm found in PATH"
        print(f"✅ Poppler trouvé: {POPPLER_PATH}")
    else:
        print("⚠️  Poppler non trouvé dans PATH")
        print("   Windows: télécharger depuis https://github.com/oschwartz10612/poppler-windows/releases/")
        print("   Linux: sudo apt-get install poppler-utils")
        print("   macOS: brew install poppler")
except Exception as e:
    print(f"⚠️  Erreur détection poppler: {e}")

# ════════════════════════════════════════════════════════════════════════
# LOGGING
# ════════════════════════════════════════════════════════════════════════

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════
# CLASSE CONVERTISSEUR
# ════════════════════════════════════════════════════════════════════════


class PDFToSlidesConverter:
    """
    Convertisseur PDF → Images.
    
    Transforme chaque page PDF en image PNG ou JPG
    et les organise par cours/chapitre.
    """

    def __init__(self, slides_dir: Optional[Path] = None) -> None:
        """
        Initialise le convertisseur.
        
        Args:
            slides_dir: Répertoire racine pour les slides.
                       Défaut: media/slides
        """
        if slides_dir is None:
            slides_dir = Path(__file__).parent.parent / "media" / "slides"
        
        self.slides_dir = Path(slides_dir)
        self.slides_dir.mkdir(parents=True, exist_ok=True)
        
        if not PDF2IMAGE_AVAILABLE:
            logger.warning("pdf2image not available. PDF conversion will fail.")

    def convert_pdf(
        self,
        pdf_path: str,
        course: str = "dm",
        chapter: str = "chapter_1",
        dpi: int = 150,
        fmt: str = "png"
    ) -> dict:
        """
        Convertit un PDF en images slides.
        
        Args:
            pdf_path: Chemin vers le PDF
            course: Code du cours (e.g., "dm")
            chapter: Code du chapitre (e.g., "chapter_1")
            dpi: Résolution (default: 150)
            fmt: Format de sortie ("png" ou "jpg")
        
        Returns:
            {
                "status": "success|error",
                "message": "...",
                "total_pages": 5,
                "output_dir": "media/slides/dm/chapter_1/",
                "images": ["page_1.png", "page_2.png", ...]
            }
        """
        logger.info(f"🎬 convert_pdf() appelée avec:")
        logger.info(f"   pdf_path={pdf_path}")
        logger.info(f"   course={course}")
        logger.info(f"   chapter={chapter}")
        logger.info(f"   dpi={dpi}, fmt={fmt}")
        
        if not PDF2IMAGE_AVAILABLE:
            msg = "pdf2image not installed. Run: pip install pdf2image pillow"
            logger.error(f"❌ {msg}")
            return {
                "status": "error",
                "message": msg,
                "total_pages": 0,
                "output_dir": None,
                "images": []
            }
        
        try:
            pdf_path = Path(pdf_path)
            logger.info(f"📄 Fichier PDF réel: {pdf_path.absolute()}")
            
            if not pdf_path.exists():
                msg = f"PDF not found: {pdf_path.absolute()}"
                logger.error(f"❌ {msg}")
                return {
                    "status": "error",
                    "message": msg,
                    "total_pages": 0,
                    "output_dir": None,
                    "images": []
                }
            
            logger.info(f"✅ Fichier déjà existe: {pdf_path.stat().st_size} bytes")
            
            # Créer le répertoire de sortie
            output_dir = self.slides_dir / course / chapter
            logger.info(f"📂 Répertoire sortie: {output_dir.absolute()}")
            output_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"✅ Répertoire créé")
            
            logger.info(f"🔄 Conversion PDF → Images (DPI: {dpi})...")
            
            # Convertir le PDF en images
            images = convert_from_path(str(pdf_path), dpi=dpi)
            logger.info(f"✅ convert_from_path() réussi: {len(images)} images trouvées")
            
            # Sauvegarder chaque page
            saved_images = []
            for i, image in enumerate(images, start=1):
                filename = f"page_{i}.{fmt}"
                filepath = output_dir / filename
                
                logger.info(f"   💾 Sauvegarde page {i}/{len(images)}: {filepath}")
                
                if fmt.lower() == "png":
                    image.save(filepath, "PNG")
                elif fmt.lower() in ["jpg", "jpeg"]:
                    # Convertir RGBA → RGB pour JPEG
                    if image.mode == "RGBA":
                        rgb_image = image.convert("RGB")
                        rgb_image.save(filepath, "JPEG", quality=95)
                    else:
                        image.save(filepath, "JPEG", quality=95)
                else:
                    msg = f"Unsupported format: {fmt}"
                    logger.error(f"❌ {msg}")
                    return {
                        "status": "error",
                        "message": msg,
                        "total_pages": 0,
                        "output_dir": None,
                        "images": []
                    }
                
                saved_images.append(filename)
                logger.info(f"   ✅ Sauvegardé: {filepath}")
            
            logger.info(f"✅ Conversion terminée: {len(saved_images)} pages sauvegardées")
            
            # Retourner le chemin relatif de manière robuste
            try:
                output_rel = output_dir.relative_to(Path.cwd())
            except ValueError:
                # Si .relative_to() échoue, utiliser os.path.relpath
                import os
                output_rel = Path(os.path.relpath(str(output_dir), str(Path.cwd())))
            
            logger.info(f"📂 Chemin relatif: {output_rel}")
            
            return {
                "status": "success",
                "message": f"Converted {len(saved_images)} pages",
                "total_pages": len(saved_images),
                "output_dir": str(output_rel),
                "images": saved_images
            }
        
        except Exception as e:
            logger.error(f"❌ Conversion échouée: {e}", exc_info=True)
            return {
                "status": "error",
                "message": str(e),
                "total_pages": 0,
                "output_dir": None,
                "images": []
            }

    def get_slide_path(
        self,
        course: str,
        chapter: str,
        page_num: int
    ) -> Optional[Path]:
        """
        Récupère le chemin d'une slide.
        
        Args:
            course: Code du cours
            chapter: Code du chapitre
            page_num: Numéro de la page (1-indexed)
        
        Returns:
            Path si existe, None sinon
        """
        image_path = self.slides_dir / course / chapter / f"page_{page_num}.png"
        
        if image_path.exists():
            return image_path
        
        # Essayer JPEG
        image_path = self.slides_dir / course / chapter / f"page_{page_num}.jpg"
        if image_path.exists():
            return image_path
        
        return None

    def get_chapter_slides(
        self,
        course: str,
        chapter: str
    ) -> List[Path]:
        """
        Récupère toutes les slides d'un chapitre.
        
        Args:
            course: Code du cours
            chapter: Code du chapitre
        
        Returns:
            Liste des chemins des images (triées par numéro)
        """
        chapter_dir = self.slides_dir / course / chapter
        
        if not chapter_dir.exists():
            return []
        
        # Récupérer tous les PNG et JPG
        images = list(chapter_dir.glob("page_*.png")) + list(chapter_dir.glob("page_*.jpg"))
        
        # Trier par numéro
        images.sort(key=lambda x: int(x.stem.split("_")[1]))
        
        return images

    def list_courses(self) -> dict:
        """
        Liste tous les cours avec leurs chapitres et slides.
        
        Returns:
            {
                "dm": {
                    "chapter_1": {"total_pages": 5, "slides": ["page_1.png", ...]},
                    "chapter_2": {"total_pages": 3, ...}
                }
            }
        """
        result = {}
        
        if not self.slides_dir.exists():
            return result
        
        for course_dir in self.slides_dir.iterdir():
            if not course_dir.is_dir():
                continue
            
            course_name = course_dir.name
            result[course_name] = {}
            
            for chapter_dir in course_dir.iterdir():
                if not chapter_dir.is_dir():
                    continue
                
                chapter_name = chapter_dir.name
                slides = self.get_chapter_slides(course_name, chapter_name)
                
                result[course_name][chapter_name] = {
                    "total_pages": len(slides),
                    "slides": [s.name for s in slides]
                }
        
        return result

    def slides_exist(self, course: str, chapter: str) -> bool:
        """
        Vérifie si les slides existent pour un chapitre.
        
        Args:
            course: Code du cours
            chapter: Code du chapitre
        
        Returns:
            True si au moins page_1.png existe, False sinon
        """
        chapter_dir = self.slides_dir / course / chapter
        return (chapter_dir / "page_1.png").exists() or (chapter_dir / "page_1.jpg").exists()

    def get_chapter_pdf_path(self, domain: str, course: str, chapter_num: int = 1) -> Optional[Path]:
        """
        Trouve le fichier PDF correspondant à un chapitre.
        
        Cherche dans: courses/{domain}/{course}/Chapter {N}.pdf
        ou Chapitre {N}.pdf, Chapter {N}.pdf, Ch {N}.pdf, {N}.pdf
        
        Args:
            domain: Domaine (e.g., "informatique")
            course: Code du cours (e.g., "mon_cours")
            chapter_num: Numéro du chapitre (défaut: 1)
        
        Returns:
            Path du PDF si trouvé, None sinon
        """
        courses_base = Path("courses") / domain / course
        
        if not courses_base.exists():
            logger.warning(f"Dossier cours introuvable: {courses_base}")
            return None
        
        # Patterns à chercher (par ordre de priorité)
        patterns = [
            f"Chapter {chapter_num}.pdf",
            f"Chapitre {chapter_num}.pdf",
            f"Ch {chapter_num}.pdf",
            f"{chapter_num}.pdf",
        ]
        
        for pattern in patterns:
            pdf_path = courses_base / pattern
            if pdf_path.exists():
                logger.info(f"✅ PDF trouvé: {pdf_path}")
                return pdf_path
        
        # Fallback: chercher n'importe quel PDF
        pdfs = list(courses_base.glob("*.pdf"))
        if pdfs:
            logger.info(f"⚠️  Pattern non trouvé, utilisant: {pdfs[0]}")
            return pdfs[0]
        
        logger.warning(f"❌ Aucun PDF trouvé dans {courses_base}")
        return None

    def ensure_slides_exist(self, domain: str, course: str, chapter: str, chapter_num: int = 1, dpi: int = 150) -> dict:
        """
        Vérifie que les slides existent, et les régénère si manquantes.
        
        Cas d'usage: 
        - Slides supprimées manuellement
        - Upload récent non convertis
        - Cache cleared
        
        Args:
            domain: Domaine (e.g., "informatique")
            course: Code du cours (e.g., "mon_cours")
            chapter: Code du chapitre interne (e.g., "chapter_1")
            chapter_num: Numéro du chapitre (pour trouver le PDF)
            dpi: Résolution de conversion
        
        Returns:
            {
                "status": "exists|regenerated|error",
                "slides_count": N,
                "message": "...",
                "output_dir": "..."
            }
        """
        # Vérifier si slides existent
        if self.slides_exist(course, chapter):
            slides = self.get_chapter_slides(course, chapter)
            return {
                "status": "exists",
                "slides_count": len(slides),
                "message": f"✅ {len(slides)} slides existent déjà"
            }
        
        logger.info(f"⚠️  Slides manquantes pour {domain}/{course}/{chapter} — régénération...")
        
        # Trouver le PDF
        pdf_path = self.get_chapter_pdf_path(domain, course, chapter_num)
        
        if not pdf_path:
            return {
                "status": "error",
                "slides_count": 0,
                "message": f"❌ PDF introuvable pour {domain}/{course}"
            }
        
        # Régénérer les slides
        result = self.convert_pdf(
            pdf_path=str(pdf_path),
            course=course,
            chapter=chapter,
            dpi=dpi,
            fmt="png"
        )
        
        if result["status"] == "success":
            logger.info(f"✅ {result['total_pages']} slides régénérées pour {domain}/{course}/{chapter}")
            return {
                "status": "regenerated",
                "slides_count": result["total_pages"],
                "message": f"✅ {result['total_pages']} slides régénérées automatiquement"
            }
        else:
            logger.error(f"❌ Régénération échouée: {result['message']}")
            return {
                "status": "error",
                "slides_count": 0,
                "message": f"❌ Erreur: {result['message']}"
            }


# Initialiser le converter global
converter = PDFToSlidesConverter()


if __name__ == "__main__":
    # Test
    converter = PDFToSlidesConverter()
    
    # Convertir Chapter 1
    result = converter.convert_pdf(
        pdf_path="courses/dm/Chapter 1.pdf",
        course="dm",
        chapter="chapter_1",
        dpi=150
    )
    print(result)
    
    # Lister les slides
    inventory = converter.list_courses()
    print(inventory)
