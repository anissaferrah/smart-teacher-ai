"""
╔══════════════════════════════════════════════════════════════════════╗
║        SMART TEACHER — Script d'Ingestion des Cours                ║
║                                                                      ║
║  Indexe les fichiers PDF/DOCX/PPTX dans Qdrant (RAG multimodal)    ║
║                                                                      ║
║  Usage :                                                             ║
║    python ingest.py                        # indexe courses/        ║
║    python ingest.py --file cours.pdf       # un seul fichier        ║
║    python ingest.py --dir mes_cours/       # un dossier             ║
║    python ingest.py --incremental          # ajoute sans supprimer  ║
║    python ingest.py --reset                # efface puis réindexe   ║
║    python ingest.py --stats                # affiche les stats RAG  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import argparse
import os
import sys
import time
from pathlib import Path

# ── Charger .env avant tout ───────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

from config import Config
from modules.multimodal_rag import MultiModalRAG

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".html", ".md"}


def collect_files(path: str) -> list[str]:
    """Collecte tous les fichiers supportés dans un chemin (fichier ou dossier)."""
    p = Path(path)
    if not p.exists():
        print(f"❌ Chemin introuvable : {path}")
        return []

    if p.is_file():
        if p.suffix.lower() in SUPPORTED_EXTENSIONS:
            return [str(p)]
        else:
            print(f"⚠️  Extension non supportée : {p.suffix}")
            return []

    # Dossier → recherche récursive
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(p.glob(f"**/*{ext}"))
    return [str(f) for f in sorted(files)]


def print_stats(rag: MultiModalRAG) -> None:
    stats = rag.get_stats()
    print("\n" + "=" * 50)
    print("📊 STATISTIQUES RAG")
    print("=" * 50)
    print(f"  Prêt         : {'✅ Oui' if stats['is_ready'] else '❌ Non'}")
    print(f"  Total chunks : {stats.get('total_docs', 0)}")
    print(f"  Cache AI     : {stats.get('cache_entries', 0)} résumés")
    print(f"  BM25 prêt    : {'✅' if stats.get('bm25_ready') else '❌'}")

    subjects = stats.get("subjects", {})
    if subjects:
        print(f"\n  📚 Matières indexées :")
        for subj, count in sorted(subjects.items(), key=lambda x: -x[1]):
            print(f"     {subj:20s} → {count} chunks")

    languages = stats.get("languages", {})
    if languages:
        print(f"\n  🌍 Langues détectées :")
        for lang, count in sorted(languages.items(), key=lambda x: -x[1]):
            print(f"     {lang:10s} → {count} chunks")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="Smart Teacher — Ingestion des cours dans le RAG Qdrant"
    )
    parser.add_argument("--file",        type=str,  help="Fichier unique à indexer")
    parser.add_argument("--dir",         type=str,  help="Dossier à indexer (récursif)")
    parser.add_argument("--incremental", action="store_true",
                        help="Ajoute sans effacer la collection existante")
    parser.add_argument("--reset",       action="store_true",
                        help="Efface la collection puis réindexe tout")
    parser.add_argument("--stats",       action="store_true",
                        help="Affiche les statistiques sans indexer")
    args = parser.parse_args()

    print("=" * 60)
    print("📚 SMART TEACHER — INGESTION DES COURS")
    print("=" * 60)

    # Initialiser le RAG
    print(f"\n🔧 Initialisation RAG ({Config.RAG_DB_DIR})…")
    rag = MultiModalRAG(db_dir=Config.RAG_DB_DIR)

    # Mode stats uniquement
    if args.stats:
        print_stats(rag)
        return

    # Mode reset
    if args.reset:
        print("🗑️  Suppression de la collection existante…")
        rag.delete_collection()
        print("✅ Collection supprimée")

    # Déterminer les fichiers à indexer
    if args.file:
        files = collect_files(args.file)
    elif args.dir:
        files = collect_files(args.dir)
    else:
        # Défaut : dossier courses/
        courses_dir = Config.COURSES_DIR
        os.makedirs(courses_dir, exist_ok=True)
        files = collect_files(courses_dir)

    if not files:
        print(f"\n❌ Aucun fichier trouvé.")
        print(f"   Placez vos PDF dans le dossier : {Config.COURSES_DIR}/")
        print(f"   Extensions supportées : {', '.join(SUPPORTED_EXTENSIONS)}")
        sys.exit(1)

    # Afficher les fichiers trouvés
    print(f"\n📄 {len(files)} fichier(s) trouvé(s) :")
    for f in files:
        size_kb = os.path.getsize(f) / 1024
        print(f"   📕 {Path(f).name} ({size_kb:.0f} KB)")

    # Lancer l'ingestion
    print(f"\n⏳ Ingestion en cours (incremental={args.incremental})…")
    start = time.time()

    ok = rag.run_ingestion_pipeline_for_files(files, incremental=args.incremental)

    duration = time.time() - start

    if ok:
        print(f"\n✅ Ingestion terminée en {duration:.1f}s")
        print_stats(rag)
        print("\n🚀 Vous pouvez maintenant lancer le serveur :")
        print("   python main.py")
    else:
        print(f"\n❌ Ingestion échouée — vérifiez les logs ci-dessus")
        sys.exit(1)


if __name__ == "__main__":
    main()