# 🤖 Smart Teacher — Professeur IA Vocal Interactif

Système d'enseignement intelligent combinant **STT + RAG + LLM + TTS** pour créer un professeur virtuel vocal capable d'interagir en temps réel avec les étudiants en **Français, Arabe, Anglais et Turc**.

---

## 📁 Structure du projet

```
smart_teacher/
├── main.py                  ← Point d'entrée PRINCIPAL (WebSocket + REST)
├── server.py                ← Serveur REST simplifié (sans WebSocket)
├── config.py                ← Configuration centralisée
├── ingest.py                ← Script d'indexation des cours
├── rag.py                   ← RAG Chroma simple (local, sans API)
├── analyze_metrics.py       ← Analyse des performances (graphiques)
├── requirements.txt         ← Dépendances Python
├── .env.example             ← Template variables d'environnement
├── Dockerfile               ← Image Docker
├── docker-compose.yml       ← Infrastructure complète
│
├── modules/
│   ├── transcriber.py       ← STT : Whisper (faster-whisper)
│   ├── llm.py               ← LLM : OpenAI GPT avec mémoire
│   ├── tts.py               ← TTS : Edge-TTS + ElevenLabs
│   ├── tts_edge.py          ← TTS : Edge-TTS standalone
│   ├── audio_input.py       ← Microphone + VAD Silero
│   ├── multimodal_rag.py    ← RAG : Qdrant + BM25 + RRF
│   ├── dialogue.py          ← Machine d'état (Redis)
│   ├── logger.py            ← Logger CSV métriques globales
│   └── stt_logger.py        ← Logger CSV métriques STT
│
├── database/
│   ├── models.py            ← Modèles SQLAlchemy
│   ├── init_db.py           ← Création tables + données démo
│   ├── crud.py              ← Fonctions CRUD PostgreSQL
│   └── init.sql             ← Extensions SQL
│
└── static/
    └── index.html           ← Interface étudiant (WebSocket)
```

---

## 🚀 Démarrage rapide

### 1. Prérequis

```bash
# Python 3.11+
python --version

# Docker + Docker Compose
docker --version
docker-compose --version
```

### 2. Configuration

```bash
# Copier le fichier de configuration
cp .env.example .env

# Éditer .env et ajouter votre clé OpenAI
nano .env
# OPENAI_API_KEY=sk-...votre-clé...


envProject\Scripts\activate
```

### 3. Lancer l'infrastructure

```bash
# Démarrer PostgreSQL + Redis + Qdrant
docker-compose up -d

# Vérifier que tout est démarré
docker-compose ps
```

### 4. Installer les dépendances Python

```bash
pip install -r requirements.txt
```

### 5. Indexer vos cours

```bash
# Placer vos PDF dans le dossier courses/
mkdir courses
cp mon_cours.pdf courses/

# Lancer l'indexation
python ingest.py

# Vérifier les stats
python ingest.py --stats
```

### 6. Lancer le serveur

```bash
# Avec WebSocket (recommandé pour production)
python main.py

# Ou version REST simple (développement)
python server.py
```

### 7. Accéder à l'interface

```
http://localhost:8000/static/index.html
```

---

## 🏗️ Architecture

```
Étudiant
   │
   │ Parole / Texte
   ▼
[VAD Silero]          ← Détecte la parole en temps réel
   │
   ▼
[STT — Whisper]       ← Transcrit l'audio en texte (FR/AR/EN)
   │
   ▼
[RAG — Qdrant]        ← Recherche les passages pertinents du cours
   │                     (BM25 + Vector + RRF)
   ▼
[LLM — GPT]           ← Génère la réponse pédagogique
   │
   ▼
[TTS — Edge-TTS]      ← Synthétise la réponse en audio
   │
   ▼
Étudiant (réponse vocale)
```

### Machine d'état

```
IDLE → PRESENTING → LISTENING → PROCESSING → RESPONDING → PRESENTING
                       ↑                                        │
                       └────────────────────────────────────────┘
```

---

## 🌐 API WebSocket

### Connexion
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/{session_id}');
```

### Messages client → serveur

| Type | Description | Paramètres |
|------|-------------|------------|
| `start_session` | Démarre une session | `language`, `level` |
| `audio_chunk` | Envoie un chunk audio | `data` (base64) |
| `audio_end` | Fin de l'enregistrement | — |
| `interrupt` | Coupe l'IA | — |
| `text` | Question texte | `content` |
| `next_section` | Section suivante | — |

### Messages serveur → client

| Type | Description |
|------|-------------|
| `session_ready` | Session créée |
| `state_change` | Nouveau state (IDLE/PRESENTING/…) |
| `transcription` | Texte transcrit par Whisper |
| `answer_text` | Réponse texte du LLM |
| `audio_chunk` | Chunk audio TTS (base64) |
| `performance` | Métriques STT/LLM/TTS |
| `error` | Erreur |

---

## 📡 API REST

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/` | État du serveur |
| `GET` | `/health` | Healthcheck complet |
| `POST` | `/process-audio` | Audio → STT → RAG → LLM → TTS |
| `POST` | `/ask` | Texte → RAG → LLM → TTS |
| `POST` | `/ingest` | Upload + indexation fichiers |
| `GET` | `/rag/stats` | Statistiques RAG |
| `GET` | `/session/{id}` | État d'une session |
| `POST` | `/session/clear` | Reset session |

### Exemple `/ask`

```bash
curl -X POST http://localhost:8000/ask \
  -H "X-Session-ID: mon-id" \
  -F "question=Qu'est-ce qu'une dérivée ?"
```

### Exemple `/process-audio`

```bash
curl -X POST http://localhost:8000/process-audio \
  -H "X-Session-ID: mon-id" \
  -F "audio=@enregistrement.webm"
```

---

## 🎯 KPIs cibles

| Indicateur | Objectif |
|------------|----------|
| Temps de réponse total | < 5 secondes |
| Latence d'interruption | < 500 ms |
| WER français | < 10% |
| WER arabe | < 20% |
| RTF (Real-Time Factor) | < 0.5x |

---

## 📊 Analyse des performances

```bash
# Dashboard graphiques complet
python analyze_metrics.py

# Avec analyse STT détaillée (WER, RTF)
python analyze_metrics.py --stt
```

---

## ⚙️ Configuration

Fichier `config.py` — principales variables :

| Variable | Défaut | Description |
|----------|--------|-------------|
| `WHISPER_MODEL_SIZE` | `tiny` | `tiny` / `base` / `small` / `medium` |
| `GPT_MODEL` | `gpt-4o-mini` | Modèle OpenAI |
| `TTS_PROVIDER` | `edge` | `edge` / `elevenlabs` |
| `RAG_NUM_RESULTS` | `5` | Chunks RAG retournés |
| `MAX_RESPONSE_TIME` | `5.0` | KPI temps réponse (s) |
| `MAX_HISTORY_TURNS` | `10` | Paires de messages gardés |

---

## 🐳 Docker

```bash
# Tout démarrer (infra + API)
docker-compose up -d

# Voir les logs
docker-compose logs -f api

# Arrêter
docker-compose down

# Tout supprimer (volumes inclus)
docker-compose down -v
```

---

## 🔧 Commandes utiles

```bash
# Réindexer tous les cours
python ingest.py --reset

# Ajouter un fichier sans effacer
python ingest.py --file nouveau_cours.pdf --incremental

# Statistiques RAG
python ingest.py --stats

# Tester le TTS
python modules/tts_edge.py

# Initialiser la base de données manuellement
python -m database.init_db
```

---

## 📦 Dépendances principales

| Package | Usage |
|---------|-------|
| `fastapi` + `uvicorn` | Serveur web + WebSocket |
| `faster-whisper` | STT optimisé CPU |
| `edge-tts` | TTS gratuit (Microsoft Neural) |
| `openai` | LLM GPT |
| `qdrant-client` | Base vectorielle RAG |
| `langchain` | Pipeline RAG |
| `sqlalchemy` + `asyncpg` | ORM PostgreSQL async |
| `redis` | Sessions temps réel |
| `torch` | VAD Silero |
| `langdetect` | Détection de langue |

---

*Smart Teacher — Projet de Master en Intelligence Artificielle*
