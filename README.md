# Smart Teacher

Assistant pédagogique vocal interactif basé sur **STT + RAG + LLM + TTS**.

Smart Teacher charge un cours depuis les fichiers du dossier `courses/`, extrait sa structure en chapitres et sections, puis le présente à voix haute avec interaction en temps réel par micro ou texte.

Le flux principal est volontairement direct : import des fichiers de cours -> construction de la structure -> présentation -> questions/réponses -> reprise depuis le point d’arrêt quand c’est possible.

---

## Vue d’ensemble

### Ce que fait l’application

1. L’utilisateur sélectionne un cours importé ou en cours de préparation.
2. L’application affiche la structure du cours et la slide courante.
3. Le professeur IA lit le contenu à voix haute.
4. L’étudiant peut poser une question, interrompre la présentation, puis reprendre.
5. Le système combine transcription, recherche documentaire, génération de réponse et synthèse vocale.

### Chaîne technique

```text
Micro / texte
   -> VAD Silero
   -> STT Whisper
   -> RAG Qdrant + BM25
   -> LLM OpenAI ou Ollama
   -> TTS Edge-TTS
   -> Réponse audio + chat
```

### Machine d’état

```text
IDLE -> PRESENTING -> LISTENING -> PROCESSING -> RESPONDING
```

---

## Fonctionnalités principales

- Présentation de cours par chapitres et sections.
- Interaction vocale en temps réel via WebSocket.
- Réponses textuelles et audio.
- Transcription affichée dès la détection STT.
- Interruption immédiate quand l’étudiant pose une question.
- Reprise du cours depuis le point sauvegardé quand c’est possible.
- Métriques de performance pour STT, LLM, TTS et temps total.
- Fallback local via Ollama si OpenAI est indisponible ou en quota insuffisant.

---

## Prérequis

- Python 3.13+
- Docker et Docker Compose
- Une clé `OPENAI_API_KEY` dans un fichier `.env`
- Optionnel : `ELEVENLABS_API_KEY` si vous utilisez ElevenLabs pour le TTS

### Services Docker

#### Minimum

- PostgreSQL 15
- Redis 7
- Qdrant

#### Profile complet (`--profile full`)

- MinIO
- Elasticsearch
- ClickHouse
- Ollama

---

## Installation rapide

### 1. Créer et activer l’environnement Python

```powershell
envProject\Scripts\Activate.ps1
```

### 2. Installer les dépendances

Le dépôt ne fournit pas de fichier `requirements.txt`.

Utilisez l’environnement Python déjà préparé (`envProject`) ou installez les paquets du projet dans votre propre environnement de travail.

### 3. Préparer le fichier `.env`

```bash
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=
TTS_PROVIDER=edge
GPT_MODEL=gpt-4o-mini
```

### 4. Démarrer l’infrastructure

```bash
docker-compose up -d
```

Si vous voulez les services optionnels :

```bash
docker-compose --profile full up -d
```

### 5. Lancer l’application

```bash
python main.py
```

### 6. Ouvrir l’interface

```text
http://localhost:8000/static/index.html
```

---

## Configuration utile

Les principales variables sont définies dans `config.py`.

| Variable | Rôle |
|----------|------|
| `OPENAI_API_KEY` | Clé OpenAI utilisée pour le LLM et les embeddings |
| `ELEVENLABS_API_KEY` | Clé optionnelle si `TTS_PROVIDER=elevenlabs` |
| `POSTGRES_HOST` / `POSTGRES_PORT` | Connexion PostgreSQL |
| `REDIS_HOST` / `REDIS_PORT` | Connexion Redis |
| `QDRANT_HOST` / `QDRANT_PORT` | Connexion Qdrant |
| `GPT_MODEL` | Modèle OpenAI utilisé par défaut |
| `WHISPER_MODEL_SIZE` | Taille du modèle STT |
| `TTS_PROVIDER` | Moteur TTS (`edge` ou `elevenlabs`) |
| `COURSES_DIR` | Dossier racine des cours |
| `SERVER_PORT` | Port HTTP du serveur |

---

## API exposée

### WebSocket

| Route | Rôle |
|-------|------|
| `WS /ws/{session_id}` | Pipeline vocal temps réel |

### REST

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/` | État général du serveur |
| `GET` | `/health` | Vérification de santé |
| `POST` | `/session` | Création / initialisation d’une session |
| `GET` | `/session/{session_id}` | Lecture d’une session |
| `POST` | `/session/clear` | Réinitialisation d’une session |
| `POST` | `/ask` | Question texte -> réponse audio |
| `POST` | `/course/build` | Construction d’un cours depuis des fichiers |
| `POST` | `/ingest` | Ingestion manuelle / indexation |
| `GET` | `/course/list` | Liste des cours disponibles |
| `GET` | `/course/{course_id}/structure` | Structure complète d’un cours |
| `GET` | `/rag/stats` | Statistiques RAG |
| `GET` | `/cache/stats` | Statistiques cache |
| `GET` | `/ingestion/status` | Avancement de l’ingestion |
| `GET` | `/debug/rag_test` | Test RAG avec requête personnalisée |

---

## Structure du projet

```text
smart_teacher/
├── main.py              # Serveur FastAPI principal
├── config.py            # Configuration centralisée
├── analyze_metrics.py   # Analyse des métriques
├── handlers/            # Pipeline audio et gestion de session
├── modules/             # STT, LLM, TTS, RAG, analytics, etc.
├── database/            # Modèles, CRUD, init DB, SQL
├── courses/             # Cours importés
├── static/              # Interface web
├── media/               # Audio, PDFs, slides
├── data/                # Caches et données locales
├── logs/                # Métriques et logs CSV
├── analytics/           # Exports d’événements
├── docker-compose.yml   # Infrastructure locale
├── Dockerfile           # Image applicative
└── init_ollama.sh       # Initialisation Ollama locale
```

---

## Commandes utiles

### Démarrage / arrêt

```bash
docker-compose down
docker-compose down -v
```

### Base de données

```bash
python -m database.init_db
```

### Analyse des métriques

```bash
python analyze_metrics.py
python analyze_metrics.py --stt
```

### Ingestion / indexation

Le dépôt actuel n’inclut pas de script `ingest.py`.

Le flux d’import passe par l’API :

- `POST /course/build` pour construire un cours à partir de fichiers importés.
- `POST /ingest` pour une ingestion / indexation manuelle si besoin.

Si vous automatisez l’import, appelez directement ces endpoints depuis un script ou un client HTTP.

---

## Notes d’exploitation

- Le système privilégie l’upload direct et la présentation du cours à partir des fichiers importés.
- Si OpenAI retourne `insufficient_quota`, l’application peut basculer sur Ollama quand il est disponible.
- Les métriques sont écrites dans `logs/` et `analytics/`.
- L’interface principale est `static/index.html`.
- Les services optionnels du profile complet servent au stockage média, à la recherche et à l’analytics.

---

## Dépannage rapide

- Vérifier que PostgreSQL, Redis et Qdrant sont bien démarrés.
- Vérifier la présence de `OPENAI_API_KEY` dans `.env`.
- Si le serveur refuse de démarrer, libérer le port 8000 puis relancer `python main.py`.
- Si le fallback local est attendu, vérifier que Ollama est actif.
