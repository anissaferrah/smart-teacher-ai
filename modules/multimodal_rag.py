"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         SMART TEACHER — Multi-Modal RAG Module  (QDRANT VERSION)           ║
║                                                                              ║
║  AMÉLIORATIONS v2 :                                                          ║
║    ✅ ISOLATION PAR CHAPITRE : filtrage Qdrant strict ch1..ch7 séparés       ║
║    ✅ Data Mining keywords enrichis (50+ termes DM/ML/IA spécifiques)        ║
║    ✅ Boost de pertinence si chunk = même chapitre que position actuelle      ║
║    ✅ Prompt pédagogique adapté : domaine informatique / data mining          ║
║    ✅ Context window : injection du titre de chapitre courant dans le prompt  ║
║    ✅ RRF amélioré : pénalité cross-chapter pour rester cohérent             ║
║    ✅ Ingestion par dossier : courses/dm/ch1..ch7 auto-détectés               ║
║    ✅ Metadata enrichie : chapter_idx, chapter_title, slide_idx              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

# ─── Unstructured ─────────────────────────────────────────────────────────────
from unstructured.partition.auto import partition
from unstructured.chunking.title import chunk_by_title

# ─── LangChain ────────────────────────────────────────────────────────────────
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_community.retrievers import BM25Retriever

# ─── Qdrant ───────────────────────────────────────────────────────────────────
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance, VectorParams, Filter, FieldCondition, MatchValue
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("SmartTeacher.RAG")


# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTES
# ══════════════════════════════════════════════════════════════════════════════

COLLECTION_NAME  = "smart_teacher_multimodal"
EMBEDDING_DIM    = 1536
EMBEDDING_MODEL  = "text-embedding-3-small"
LLM_SUMMARY      = "gpt-4o-mini"
LLM_ANSWER       = "gpt-4o-mini"

# ── Mots-clés DATA MINING enrichis (domaine informatique) ─────────────────────
SUBJECT_KEYWORDS: dict[str, list[str]] = {
    "data_mining": [
        # Core DM
        "data mining", "fouille de données", "kdd", "knowledge discovery",
        "pattern", "association rules", "apriori", "fp-growth",
        "frequent itemset", "support", "confidence", "lift",
        # Clustering
        "clustering", "kmeans", "k-means", "dbscan", "hierarchical",
        "dendrogram", "silhouette", "inertia", "centroid",
        # Classification
        "classification", "decision tree", "random forest", "svm",
        "support vector machine", "naive bayes", "knn", "k-nearest",
        "logistic regression", "gradient boosting", "xgboost",
        # Regression
        "regression", "linear regression", "polynomial", "overfitting",
        "underfitting", "bias variance", "cross validation",
        # Data preprocessing
        "preprocessing", "normalisation", "standardisation", "imputation",
        "missing values", "outlier", "feature engineering", "feature selection",
        "dimensionality reduction", "pca", "t-sne", "umap",
        # Evaluation
        "accuracy", "precision", "recall", "f1 score", "roc", "auc",
        "confusion matrix", "mae", "mse", "rmse",
        # Deep Learning / NN
        "neural network", "deep learning", "cnn", "rnn", "lstm",
        "transformer", "attention", "backpropagation", "gradient descent",
        "epoch", "batch size", "learning rate", "dropout", "relu",
        # Data warehousing
        "data warehouse", "etl", "olap", "oltp", "star schema",
        "snowflake schema", "fact table", "dimension table",
        # Anomaly detection
        "anomaly detection", "isolation forest", "autoencoder",
        "one-class svm",
        # EDA
        "exploratory data analysis", "eda", "distribution", "histogram",
        "boxplot", "correlation", "heatmap", "univariate", "bivariate",
        "multivariate",
        # General CS
        "algorithm", "algorithme", "complexity", "big o", "dataset",
        "dataframe", "pandas", "numpy", "scikit-learn", "tensorflow",
        "pytorch", "machine learning", "artificial intelligence",
    ],
    "computer_science": [
        "algorithm", "data structure", "graph", "tree", "hash",
        "sorting", "searching", "recursion", "dynamic programming",
        "complexity", "big o", "programming", "python", "java",
        "database", "sql", "nosql", "api", "rest", "microservices",
    ],
    "math": [
        "matrix", "vector", "eigenvalue", "statistics", "probability",
        "bayes", "entropy", "information gain", "gradient",
    ],
}

# Chapitres DM attendus dans courses/dm/
DM_CHAPTER_MAP = {
    "ch1": ("Introduction", 1),
    "ch2": ("Data, Dataset, Data Warehouse", 2),
    "ch3": ("Exploratory Data Analysis", 3),
    "ch4": ("Data Cleaning & Preprocessing", 4),
    "ch5": ("Feature Engineering", 5),
    "ch6": ("Supervised Machine Learning", 6),
    "ch7": ("Unsupervised Machine Learning", 7),
}

LANG_KEYWORDS: dict[str, list[str]] = {
    "fr": ["fr_", "_fr", "french", "francais", "français"],
    "ar": ["ar_", "_ar", "arabic", "arabe"],
    "en": ["en_", "_en", "english", "chapter", "ch"],
}


# ══════════════════════════════════════════════════════════════════════════════
#  CLASSE PRINCIPALE
# ══════════════════════════════════════════════════════════════════════════════

class MultiModalRAG:
    """
    Pipeline RAG multimodal — optimisé Data Mining / Informatique.

    Ingestion depuis dossier courses/dm/ :
        rag = MultiModalRAG()
        rag.ingest_dm_course("C:/Users/Admin/.../courses/dm")

    Retrieval contextualisé au chapitre courant :
        chunks = rag.retrieve_chunks(
            query, k=5,
            current_chapter_idx=2,   # filtre sur ch2
        )
    """

    def __init__(self, db_dir: str = "data/qdrant_db"):
        self.db_dir      = Path(db_dir)
        self.docs_cache  = self.db_dir / "docs_cache.json"
        self.summary_cache_path = self.db_dir / "summary_cache.json"

        self.vectorstore:     QdrantVectorStore | None = None
        self.client:          QdrantClient | None      = None
        self.bm25_retriever:  BM25Retriever | None     = None
        self.vector_retriever = None
        self.all_docs:        list[Document]           = []
        self.summary_cache:   dict[str, str]           = {}
        self.is_ready = False

        log.info("Initializing Smart Teacher Multi-Modal RAG (Qdrant) v2…")

        try:
            self.embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
            log.info(f"✅ Embeddings ready ({EMBEDDING_MODEL})")
        except Exception as exc:
            log.error(f"❌ Embeddings failed: {exc}")
            return

        self.db_dir.mkdir(parents=True, exist_ok=True)
        self._load_summary_cache()

        try:
            self.client = QdrantClient(path=str(self.db_dir))
            log.info(f"✅ Qdrant client connected → {self.db_dir}")
            if self.client.collection_exists(COLLECTION_NAME):
                self._load_existing_db()
            else:
                log.warning(f"Collection '{COLLECTION_NAME}' not found — run ingestion first.")
        except Exception as exc:
            log.error(f"❌ Qdrant init error: {exc}")

    # ══════════════════════════════════════════════════════════════════════════
    #  INGESTION SPÉCIALE DATA MINING (courses/dm/ch1..ch7)
    # ══════════════════════════════════════════════════════════════════════════

    def ingest_dm_course(self, courses_dm_path: str, incremental: bool = False) -> bool:
        """
        Ingère le cours Data Mining depuis le dossier courses/dm/.
        Détecte automatiquement ch1..ch7 et attache les métadonnées chapitre.

        Structure attendue :
            courses/dm/
              ch1/  (ou ch1.pdf, Chapter_1.pdf, etc.)
              ch2/
              ...
              ch7/

        Args:
            courses_dm_path: Chemin vers le dossier courses/dm/
            incremental:     Ajouter sans écraser (défaut: False → réingestion)
        """
        dm_path = Path(courses_dm_path)
        if not dm_path.exists():
            log.error(f"❌ Dossier introuvable : {dm_path}")
            return False

        log.info(f"📚 Ingestion DM depuis : {dm_path}")

        # Collecter tous les fichiers avec métadonnées chapitre
        chapter_files: list[tuple[Path, int, str]] = []  # (path, chapter_idx, chapter_title)

        for ch_key, (ch_title, ch_idx) in DM_CHAPTER_MAP.items():
            # Chercher sous-dossier ou fichiers directs
            patterns = [
                dm_path / ch_key,                         # ch1/
                dm_path / ch_key.upper(),                 # CH1/
                dm_path / f"chapter_{ch_idx}",            # chapter_1/
                dm_path / f"Chapter_{ch_idx}",
            ]
            # Fichiers directs
            file_patterns = [
                dm_path / f"{ch_key}.pdf",
                dm_path / f"Chapter_{ch_idx}.pdf",
                dm_path / f"chapter_{ch_idx}.pdf",
                dm_path / f"ch{ch_idx}.pdf",
                dm_path / f"DM_ch{ch_idx}.pdf",
            ]

            found_files = []

            # Sous-dossier
            for p in patterns:
                if p.is_dir():
                    found_files.extend(p.rglob("*.pdf"))
                    found_files.extend(p.rglob("*.pptx"))
                    found_files.extend(p.rglob("*.docx"))
                    break

            # Fichiers directs
            for fp in file_patterns:
                if fp.exists():
                    found_files.append(fp)

            # Fallback : chercher par pattern dans le dossier
            if not found_files:
                for f in dm_path.iterdir():
                    name_lower = f.name.lower()
                    if (f"{ch_idx}" in f.name or ch_key in name_lower) and \
                       f.suffix.lower() in (".pdf", ".pptx", ".docx"):
                        found_files.append(f)

            for fp in found_files:
                chapter_files.append((fp, ch_idx, ch_title))
                log.info(f"  ✅ Ch{ch_idx} ({ch_title}): {fp.name}")

        if not chapter_files:
            log.error("❌ Aucun fichier trouvé dans le dossier DM")
            return False

        # Ingestion avec métadonnées chapitre
        return self._ingest_with_chapter_metadata(chapter_files, incremental)

    def _ingest_with_chapter_metadata(
        self,
        chapter_files: list[tuple[Path, int, str]],
        incremental: bool
    ) -> bool:
        """Ingestion enrichie avec métadonnées chapitre pour isolation."""
        t0 = time.time()
        all_documents: list[Document] = []

        for file_path, chapter_idx, chapter_title in chapter_files:
            log.info(f"  📄 Traitement : {file_path.name} (Ch{chapter_idx})")
            try:
                elements = partition(filename=str(file_path))
                chunks   = chunk_by_title(elements, max_characters=1500, new_after_n_chars=1200)

                for i, chunk in enumerate(chunks):
                    text = str(chunk).strip()
                    if len(text) < 30:
                        continue

                    # Résumé IA (avec cache)
                    summary = self._get_or_create_summary(text, chapter_title)

                    # Détection slide (si PPTX)
                    slide_idx = None
                    meta = getattr(chunk, "metadata", None)
                    if meta:
                        slide_idx = getattr(meta, "page_number", None)

                    doc = Document(
                        page_content=summary or text,
                        metadata={
                            # Métadonnées chapitre (clé pour isolation)
                            "chapter_idx":    chapter_idx,
                            "chapter_title":  chapter_title,
                            "source_file":    file_path.name,
                            "chunk_idx":      i,
                            "slide_idx":      slide_idx,
                            # Métadonnées RAG
                            "original_text":  text[:500],
                            "subject":        "data_mining",
                            "language":       self._detect_language(text),
                            "content_hash":   hashlib.md5(text.encode()).hexdigest()[:8],
                        }
                    )
                    all_documents.append(doc)

            except Exception as exc:
                log.error(f"❌ Erreur sur {file_path.name}: {exc}")

        if not all_documents:
            log.error("❌ Aucun document produit")
            return False

        log.info(f"📦 {len(all_documents)} chunks produits — stockage Qdrant…")
        ok = self._store_documents(all_documents, incremental=incremental)

        if ok:
            elapsed = time.time() - t0
            log.info(f"✅ Ingestion DM terminée en {elapsed:.1f}s ({len(all_documents)} chunks)")
            # Répartition par chapitre
            by_ch: dict[int, int] = {}
            for d in all_documents:
                idx = d.metadata.get("chapter_idx", 0)
                by_ch[idx] = by_ch.get(idx, 0) + 1
            for idx in sorted(by_ch):
                log.info(f"  Ch{idx}: {by_ch[idx]} chunks")

        return ok

    # ══════════════════════════════════════════════════════════════════════════
    #  INGESTION GÉNÉRIQUE (PDF / DOCX / PPTX)
    # ══════════════════════════════════════════════════════════════════════════

    def run_ingestion_pipeline_for_files(
        self,
        file_paths: list[str],
        incremental: bool = False,
    ) -> bool:
        t0 = time.time()
        log.info("=" * 60)
        log.info(f"🚀 Ingestion — {len(file_paths)} fichier(s) | incremental={incremental}")
        log.info("=" * 60)

        elements = self._partition_files(file_paths)
        if not elements:
            log.error("Partitioning produced no elements.")
            return False

        chunks = self._create_chunks_by_title(elements)
        if not chunks:
            log.error("Chunking produced no chunks.")
            return False

        documents = self._summarise_chunks(chunks)
        if not documents:
            log.error("Summarization produced no documents.")
            return False

        ok = self._store_documents(documents, incremental=incremental)
        if ok:
            self.is_ready = True
            elapsed = time.time() - t0
            log.info(f"✅ Ingestion terminée en {elapsed:.1f}s ({len(documents)} docs)")
        return ok

    # ══════════════════════════════════════════════════════════════════════════
    #  RETRIEVAL HYBRIDE AVEC ISOLATION PAR CHAPITRE
    # ══════════════════════════════════════════════════════════════════════════

    def retrieve_chunks(
        self,
        query: str,
        k: int = 5,
        current_chapter_idx: int | None = None,
        strict_chapter: bool = False,
    ) -> list[Document]:
        """
        Recherche hybride BM25 + Vectorielle + RRF.

        NOUVEAU : isolation par chapitre.
        - Si strict_chapter=True : retourne uniquement les chunks du chapitre courant
        - Sinon : boost +0.3 pour les chunks du chapitre courant (RRF amélioré)

        Args:
            query:               Question de l'étudiant
            k:                   Nombre de chunks à retourner
            current_chapter_idx: Index du chapitre en cours (1-7 pour DM)
            strict_chapter:      Forcer l'isolation au chapitre courant
        """
        if not self.is_ready:
            log.warning("RAG not ready — returning empty results")
            return []

        log.info(f"🔍 Retrieval | ch={current_chapter_idx} | strict={strict_chapter} | q='{query[:60]}'")

        # ── Recherche vectorielle (avec filtre Qdrant si strict) ──────────────
        vector_docs = self._vector_search(query, k * 3, current_chapter_idx if strict_chapter else None)

        # ── Recherche BM25 ─────────────────────────────────────────────────────
        bm25_docs = self._bm25_search(query, k * 3)

        # ── RRF avec boost chapitre ────────────────────────────────────────────
        fused = self._rrf_with_chapter_boost(
            vector_docs, bm25_docs,
            current_chapter_idx=current_chapter_idx,
            chapter_boost=0.35,
        )

        results = fused[:k]
        log.info(f"✅ {len(results)} chunks retenus (vector={len(vector_docs)}, bm25={len(bm25_docs)})")
        return results

    def _vector_search(
        self, query: str, k: int,
        chapter_filter: int | None = None
    ) -> list[Document]:
        """Recherche vectorielle Qdrant avec filtre optionnel sur chapter_idx."""
        if not self.vectorstore:
            return []
        try:
            if chapter_filter is not None:
                # Filtre Qdrant natif pour isolation chapitre
                qdrant_filter = Filter(
                    must=[FieldCondition(
                        key="metadata.chapter_idx",
                        match=MatchValue(value=chapter_filter)
                    )]
                )
                retriever = self.vectorstore.as_retriever(
                    search_kwargs={"k": k, "filter": qdrant_filter}
                )
            else:
                retriever = self.vectorstore.as_retriever(search_kwargs={"k": k})
            return retriever.invoke(query)
        except Exception as exc:
            log.warning(f"Vector search error: {exc}")
            return []

    def _bm25_search(self, query: str, k: int) -> list[Document]:
        if not self.bm25_retriever:
            return []
        try:
            self.bm25_retriever.k = k
            return self.bm25_retriever.invoke(query)
        except Exception as exc:
            log.warning(f"BM25 search error: {exc}")
            return []

    def _rrf_with_chapter_boost(
        self,
        vector_docs: list[Document],
        bm25_docs: list[Document],
        current_chapter_idx: int | None,
        chapter_boost: float = 0.3,
        rrf_k: int = 60,
    ) -> list[Document]:
        """
        Reciprocal Rank Fusion avec boost pour le chapitre courant.
        Chunks hors-chapitre reçoivent une pénalité si current_chapter_idx défini.
        """
        scores: dict[str, float] = {}
        docs_map: dict[str, Document] = {}

        def _doc_id(doc: Document) -> str:
            return doc.metadata.get("content_hash", "") or \
                   hashlib.md5(doc.page_content[:100].encode()).hexdigest()[:12]

        for rank, doc in enumerate(vector_docs):
            did = _doc_id(doc)
            scores[did] = scores.get(did, 0.0) + 1.0 / (rrf_k + rank + 1)
            docs_map[did] = doc

        for rank, doc in enumerate(bm25_docs):
            did = _doc_id(doc)
            scores[did] = scores.get(did, 0.0) + 1.0 / (rrf_k + rank + 1)
            docs_map[did] = doc

        # Boost / pénalité chapitre
        if current_chapter_idx is not None:
            for did, doc in docs_map.items():
                doc_ch = doc.metadata.get("chapter_idx")
                if doc_ch == current_chapter_idx:
                    scores[did] = scores[did] + chapter_boost
                elif doc_ch is not None:
                    # Pénalité légère pour les chunks d'autres chapitres
                    scores[did] = scores[did] * 0.7

        sorted_ids = sorted(scores, key=lambda x: -scores[x])
        return [docs_map[did] for did in sorted_ids if did in docs_map]

    # ══════════════════════════════════════════════════════════════════════════
    #  GÉNÉRATION DE RÉPONSE PÉDAGOGIQUE
    # ══════════════════════════════════════════════════════════════════════════

    def generate_final_answer(
        self,
        retrieved_chunks: list[Document],
        question: str,
        history: list[dict],
        language: str = "fr",
        student_level: str = "université",
        current_chapter_title: str = "",
        current_section_title: str = "",
    ) -> str:
        """
        Génère une réponse pédagogique optimisée pour le domaine Data Mining.

        AMÉLIORATIONS :
        - Contexte chapitre/section injecté → réponse cohérente avec le cours
        - Terminologie DM préservée (pas simplifiée à l'excès)
        - Exemples issus du cours DM (pas de la vie quotidienne générique)
        """
        if not retrieved_chunks:
            return self._no_answer_message(language)

        # Construire le contexte RAG
        context_parts = []
        for i, doc in enumerate(retrieved_chunks[:5]):
            ch_title  = doc.metadata.get("chapter_title", "")
            slide_idx = doc.metadata.get("slide_idx")
            slide_ref = f" (slide {slide_idx})" if slide_idx else ""
            prefix    = f"[Ch: {ch_title}{slide_ref}]\n" if ch_title else ""
            context_parts.append(f"{prefix}{doc.page_content}")

        context_str = "\n\n---\n\n".join(context_parts)

        # Construire le prompt système DM
        system_prompt = self._build_dm_system_prompt(
            language=language,
            student_level=student_level,
            current_chapter_title=current_chapter_title,
            current_section_title=current_section_title,
        )

        # Construire les messages
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for msg in history[-6:]:  # 3 derniers échanges
            messages.append({"role": msg["role"], "content": msg["content"]})

        user_content = f"EXTRAITS DU COURS :\n{context_str}\n\n---\n\nQUESTION : {question}"
        messages.append({"role": "user", "content": user_content})

        try:
            llm = ChatOpenAI(model=LLM_ANSWER, temperature=0.4, max_tokens=500)
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_content),
            ])
            answer = self._clean_for_speech(response.content.strip())
            log.info(f"✅ Réponse générée : {len(answer)} chars")
            return answer
        except Exception as exc:
            log.error(f"❌ LLM error: {exc}")
            return self._error_message(language)

    # ══════════════════════════════════════════════════════════════════════════
    #  PIPELINE D'INGESTION INTERNE
    # ══════════════════════════════════════════════════════════════════════════

    def _partition_files(self, file_paths: list[str]) -> list:
        elements = []
        for fp in file_paths:
            try:
                elems = partition(filename=fp)
                log.info(f"  📄 {Path(fp).name} → {len(elems)} éléments")
                elements.extend(elems)
            except Exception as exc:
                log.error(f"  ❌ {fp}: {exc}")
        log.info(f"📦 Total éléments : {len(elements)}")
        return elements

    def _create_chunks_by_title(self, elements: list) -> list:
        try:
            chunks = chunk_by_title(elements, max_characters=1500, new_after_n_chars=1200)
            log.info(f"✂️  Chunks créés : {len(chunks)}")
            return chunks
        except Exception as exc:
            log.error(f"❌ Chunking error: {exc}")
            return []

    def _summarise_chunks(self, chunks: list) -> list[Document]:
        documents: list[Document] = []
        for i, chunk in enumerate(chunks):
            text = str(chunk).strip()
            if len(text) < 30:
                continue
            summary = self._get_or_create_summary(text, "")
            source  = self._extract_source_file(chunk)
            subject = self._detect_subject(source)
            lang    = self._detect_language(text)

            doc = Document(
                page_content=summary or text,
                metadata={
                    "source_file":   source,
                    "chunk_idx":     i,
                    "subject":       subject,
                    "language":      lang,
                    "original_text": text[:500],
                    "content_hash":  hashlib.md5(text.encode()).hexdigest()[:8],
                    "chapter_idx":   self._guess_chapter_idx(source),
                    "chapter_title": self._guess_chapter_title(source),
                    "slide_idx":     self._extract_page_number(chunk),
                }
            )
            documents.append(doc)

        if self.summary_cache:
            self._save_summary_cache()
        log.info(f"📝 Documents produits : {len(documents)}")
        return documents

    def _get_or_create_summary(self, text: str, chapter_context: str) -> str:
        """Résumé IA avec cache. Adapté pour le contenu DM."""
        key = hashlib.md5(text.encode()).hexdigest()
        if key in self.summary_cache:
            return self.summary_cache[key]

        if len(text) < 120:
            self.summary_cache[key] = text
            return text

        try:
            llm = ChatOpenAI(model=LLM_SUMMARY, temperature=0.0, max_tokens=300)
            ctx = f" (contexte : {chapter_context})" if chapter_context else ""
            prompt = (
                f"Tu es expert en Data Mining et Machine Learning{ctx}.\n"
                f"Résume ce contenu de cours en 2-3 phrases claires et précises.\n"
                f"Conserve TOUS les termes techniques (algorithmes, métriques, formules).\n"
                f"Ne simplifie pas la terminologie technique.\n\n"
                f"CONTENU :\n{text[:1200]}"
            )
            response = llm.invoke([HumanMessage(content=prompt)])
            summary  = response.content.strip()
            self.summary_cache[key] = summary
            return summary
        except Exception as exc:
            log.warning(f"Summary error: {exc}")
            return text

    def _store_documents(self, documents: list[Document], incremental: bool) -> bool:
        try:
            if not incremental and self.client and self.client.collection_exists(COLLECTION_NAME):
                self.client.delete_collection(COLLECTION_NAME)
                log.info(f"🗑️  Collection '{COLLECTION_NAME}' supprimée pour réingestion.")

            if not self.client.collection_exists(COLLECTION_NAME):
                self.client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
                )

            self.vectorstore = QdrantVectorStore.from_documents(
                documents=documents,
                embedding=self.embeddings,
                url="http://localhost:6333",
                collection_name=COLLECTION_NAME,
            )
            self.all_docs = documents
            self._build_hybrid_retriever()
            self._save_docs_cache()
            self.is_ready = True
            log.info(f"✅ {len(documents)} documents stockés dans Qdrant.")
            return True
        except Exception as exc:
            log.error(f"❌ Store error: {exc}")
            return False

    def _build_hybrid_retriever(self) -> None:
        if not self.all_docs:
            return
        try:
            self.bm25_retriever = BM25Retriever.from_documents(self.all_docs)
            log.info(f"✅ BM25 retriever construit ({len(self.all_docs)} docs)")
        except Exception as exc:
            log.warning(f"BM25 build error: {exc}")

    # ══════════════════════════════════════════════════════════════════════════
    #  PROMPTS PÉDAGOGIQUES DM
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _build_dm_system_prompt(
        language: str,
        student_level: str,
        current_chapter_title: str = "",
        current_section_title: str = "",
    ) -> str:
        """
        Prompt système spécialisé Data Mining / Informatique.
        Contextualisé avec le chapitre et la section en cours.
        """
        ch_ctx = ""
        if current_chapter_title:
            ch_ctx = f"\nNous sommes actuellement dans le chapitre : '{current_chapter_title}'."
        if current_section_title:
            ch_ctx += f" Section : '{current_section_title}'."

        base = {
            "fr": (
                f"Tu es Smart Teacher, un professeur expert en Data Mining et Intelligence Artificielle "
                f"qui enseigne à des étudiants de niveau {student_level}.{ch_ctx}\n\n"
                f"RÈGLES ABSOLUES — tu PARLES, tu n'écris PAS :\n"
                f"- JAMAIS de markdown : pas de **, pas de #, pas de tirets -, pas de listes.\n"
                f"- JAMAIS de LaTeX : écris les formules en clair ('entropie égal moins somme...').\n"
                f"- Réponds comme tu PARLERAIS en cours : phrases naturelles, transitions fluides.\n"
                f"- Commence par : 'Bonne question !', 'Exactement !', 'Alors, pour ce concept...' etc.\n"
                f"- Utilise la terminologie technique DM (k-means, Gini, AUC...) sans simplifier.\n"
                f"- Si disponible, base-toi sur les extraits du cours fournis.\n"
                f"- Un exemple concret de Data Mining ou ML (pas de la vie quotidienne abstraite).\n"
                f"- 4 à 6 phrases naturelles. Termine par une question si concept difficile.\n"
                f"- Uniquement en français."
            ),
            "en": (
                f"You are Smart Teacher, an expert professor in Data Mining and AI "
                f"teaching {student_level} level students.{ch_ctx}\n\n"
                f"ABSOLUTE RULES — you are SPEAKING, not writing:\n"
                f"- NEVER use markdown: no **, #, bullet points, numbered lists.\n"
                f"- NEVER use LaTeX: write formulas in plain words.\n"
                f"- Reply as if TALKING in class: natural sentences, smooth transitions.\n"
                f"- Start with: 'Great question!', 'Exactly!', 'So, for this concept...' etc.\n"
                f"- Use technical DM terminology (k-means, Gini, AUC...) precisely.\n"
                f"- Use course extracts provided when available.\n"
                f"- Include a concrete DM/ML example.\n"
                f"- 4 to 6 natural sentences. End with a comprehension question if complex.\n"
                f"- Reply ONLY in English."
            ),
            "ar": (
                f"أنت Smart Teacher، أستاذ خبير في استخراج البيانات والذكاء الاصطناعي "
                f"تدرّس طلاباً من مستوى {student_level}.{ch_ctx}\n\n"
                f"قواعد مطلقة:\n"
                f"- لا markdown أبداً. لا LaTeX. جمل طبيعية كما في الفصل الدراسي.\n"
                f"- استخدم المصطلحات التقنية الدقيقة (k-means، Gini، AUC...).\n"
                f"- 4 إلى 6 جمل طبيعية. أجب فقط بالعربية."
            ),
        }
        return base.get(language[:2].lower(), base["fr"])

    # ══════════════════════════════════════════════════════════════════════════
    #  UTILITAIRES
    # ══════════════════════════════════════════════════════════════════════════

    def _detect_subject(self, source: str) -> str:
        source_lower = source.lower()
        dm_terms = SUBJECT_KEYWORDS["data_mining"]
        if any(t in source_lower for t in ["dm", "data_mining", "mining", "ch"]):
            return "data_mining"
        for subj, kws in SUBJECT_KEYWORDS.items():
            if any(kw in source_lower for kw in kws):
                return subj
        return "computer_science"

    def _detect_language(self, text: str) -> str:
        """Détecte la langue du texte."""
        if not text:
            return "en"
        ar_count = len(re.findall(r'[\u0600-\u06FF]', text))
        fr_count  = len(re.findall(r'\b(le|la|les|de|du|des|un|une|et|est|qui|que|dans|pour|avec|sur|par)\b', text.lower()))
        en_count  = len(re.findall(r'\b(the|of|and|is|are|in|for|with|on|by|this|that|which|from)\b', text.lower()))
        if ar_count > 10:
            return "ar"
        if fr_count > en_count:
            return "fr"
        return "en"

    def _guess_chapter_idx(self, source: str) -> int | None:
        """Infère l'index de chapitre depuis le nom de fichier."""
        source_lower = source.lower()
        for ch_key, (_, ch_idx) in DM_CHAPTER_MAP.items():
            if ch_key in source_lower or f"chapter_{ch_idx}" in source_lower \
               or f"ch{ch_idx}" in source_lower:
                return ch_idx
        return None

    def _guess_chapter_title(self, source: str) -> str:
        idx = self._guess_chapter_idx(source)
        if idx:
            for ch_key, (ch_title, ch_idx) in DM_CHAPTER_MAP.items():
                if ch_idx == idx:
                    return ch_title
        return ""

    def _extract_source_file(self, chunk) -> str:
        meta = getattr(chunk, "metadata", None)
        if meta is None:
            return "unknown"
        return (
            getattr(meta, "filename", None)
            or getattr(meta, "file_path", None)
            or "unknown"
        )

    def _extract_page_number(self, chunk) -> int | None:
        meta = getattr(chunk, "metadata", None)
        page = getattr(meta, "page_number", None) if meta else None
        return int(page) if page is not None else None

    def _load_existing_db(self) -> None:
        try:
            self.vectorstore = QdrantVectorStore(
                client=self.client,
                collection_name=COLLECTION_NAME,
                embedding=self.embeddings,
            )
            self.is_ready = True
            log.info(f"✅ Collection '{COLLECTION_NAME}' chargée.")
            if self.docs_cache.exists():
                self._load_docs_cache()
            else:
                log.info("🔄 Pas de cache — chargement depuis Qdrant…")
                retriever  = self.vectorstore.as_retriever(search_kwargs={"k": 1000})
                self.all_docs = retriever.invoke(" ")
            self._build_hybrid_retriever()
        except Exception as exc:
            log.error(f"❌ Load DB error: {exc}")
            self.is_ready = False

    def _save_docs_cache(self) -> None:
        try:
            data = [{"page_content": d.page_content, "metadata": d.metadata}
                    for d in self.all_docs]
            with open(self.docs_cache, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            log.info(f"💾 Cache sauvegardé ({len(data)} docs → {self.docs_cache})")
        except Exception as exc:
            log.warning(f"Cache save error: {exc}")

    def _load_docs_cache(self) -> None:
        try:
            with open(self.docs_cache, encoding="utf-8") as f:
                data = json.load(f)
            self.all_docs = [Document(page_content=d["page_content"], metadata=d["metadata"])
                             for d in data]
            log.info(f"✅ Cache chargé ({len(self.all_docs)} docs)")
        except Exception as exc:
            log.warning(f"Cache load error: {exc}")

    def _save_summary_cache(self) -> None:
        try:
            with open(self.summary_cache_path, "w", encoding="utf-8") as f:
                json.dump(self.summary_cache, f, ensure_ascii=False)
        except Exception as exc:
            log.warning(f"Summary cache save error: {exc}")

    def _load_summary_cache(self) -> None:
        if self.summary_cache_path.exists():
            try:
                with open(self.summary_cache_path, encoding="utf-8") as f:
                    self.summary_cache = json.load(f)
                log.info(f"✅ Summary cache chargé ({len(self.summary_cache)} entrées)")
            except Exception:
                self.summary_cache = {}

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Supprime markdown et LaTeX pour la synthèse vocale."""
        import re
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
        return text.strip()

    @staticmethod
    def _no_answer_message(language: str) -> str:
        return {
            "fr": "Je n'ai pas trouvé d'information pertinente dans le cours. Pouvez-vous reformuler votre question ?",
            "ar": "لم أجد معلومات ذات صلة في المادة الدراسية. هل يمكنك إعادة صياغة سؤالك؟",
            "en": "I couldn't find relevant information in the course material. Could you rephrase your question?",
        }.get(language, "Je n'ai pas trouvé de réponse dans le cours.")

    @staticmethod
    def _error_message(language: str) -> str:
        return {
            "fr": "Une erreur s'est produite. Veuillez réessayer.",
            "ar": "حدث خطأ. يرجى المحاولة مرة أخرى.",
            "en": "An error occurred. Please try again.",
        }.get(language, "Une erreur s'est produite.")

    def get_stats(self) -> dict:
        by_ch: dict[int, int] = {}
        for doc in self.all_docs:
            ch = doc.metadata.get("chapter_idx", 0)
            by_ch[ch] = by_ch.get(ch, 0) + 1
        return {
            "is_ready":      self.is_ready,
            "total_docs":    len(self.all_docs),
            "collection":    COLLECTION_NAME,
            "by_chapter":    by_ch,
            "cache_entries": len(self.summary_cache),
            "bm25_ready":    self.bm25_retriever is not None,
        }

    def delete_collection(self) -> None:
        if self.client and self.client.collection_exists(COLLECTION_NAME):
            self.client.delete_collection(COLLECTION_NAME)
            log.info(f"🗑️  Collection '{COLLECTION_NAME}' supprimée.")
        self.vectorstore = None
        self.bm25_retriever = None
        self.all_docs = []
        self.is_ready = False


# ══════════════════════════════════════════════════════════════════════════════
#  SCRIPT DE TEST RAPIDE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    print("\n" + "=" * 60)
    print("  Smart Teacher — Multi-Modal RAG v2 — Quick Test")
    print("=" * 60)

    rag = MultiModalRAG(db_dir="data/qdrant_test")

    if len(sys.argv) > 1:
        if sys.argv[1] == "--dm":
            # Ingestion DM : python multimodal_rag.py --dm "C:/path/to/courses/dm"
            dm_path = sys.argv[2] if len(sys.argv) > 2 else "./courses/dm"
            print(f"\n📚 Ingestion DM : {dm_path}")
            rag.ingest_dm_course(dm_path)
        else:
            files = sys.argv[1:]
            print(f"\n📂 Ingestion {len(files)} fichier(s)…")
            rag.run_ingestion_pipeline_for_files(files)

    stats = rag.get_stats()
    print(f"\n📊 RAG Stats:")
    for k, v in stats.items():
        print(f"   {k:20s}: {v}")

    if rag.is_ready:
        print("\n" + "-" * 40)
        print("💬 Interactive Q&A (type 'quit' to exit)")
        print("   Commandes spéciales: 'ch1'..'ch7' pour filtrer le chapitre")
        print("-" * 40)
        history: list[dict] = []
        current_ch = None
        while True:
            raw = input("\n❓ Question: ").strip()
            if raw.lower() in ("quit", "exit", "q"):
                break
            if re.match(r'^ch[1-7]$', raw.lower()):
                current_ch = int(raw[2])
                print(f"   🎯 Chapitre {current_ch} sélectionné")
                continue
            if not raw:
                continue

            chunks = rag.retrieve_chunks(raw, k=4, current_chapter_idx=current_ch)
            print(f"   🔍 {len(chunks)} chunks récupérés")

            ch_title = DM_CHAPTER_MAP.get(f"ch{current_ch}", ("", 0))[0] if current_ch else ""
            answer = rag.generate_final_answer(
                chunks, raw,
                history=history,
                language="en",
                student_level="université",
                current_chapter_title=ch_title,
            )
            print(f"\n🤖 Réponse:\n{answer}")
            history.append({"role": "user",      "content": raw})
            history.append({"role": "assistant",  "content": answer})
    else:
        print("\n⚠️  RAG non prêt.")
        print("   Usage: python multimodal_rag.py --dm 'C:/path/to/courses/dm'")
        print("   Ou:    python multimodal_rag.py cours.pdf chapitre2.pptx")