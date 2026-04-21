# Smart Teacher - Organisation du code et regles de maintenance

Ce document sert a separer deux choses:

1. **Le vrai code du projet**: la logique qui fait fonctionner Smart Teacher en production.
2. **Le contenu genere ou documentaire**: diagrammes, rapports, exemples, exports et assets derives.

L'objectif est simple: garder une base de code lisible, maintenable, et eviter de confondre la logique metier avec du contenu genere automatiquement.

## 1. Structure logique du projet

### 1.1 Point d'entree et orchestration

- `main.py`: point d'entree principal FastAPI.
- `handlers/`: gestion des flux temps reel, session, et pipeline audio.
- `config.py`: configuration de l'environnement et des services.
- `domains_config.py`: lecture et organisation des domaines / cours / chapitres.

### 1.2 Logique metier

- `modules/multimodal_rag.py`: recuperation RAG, generation de reponses et quiz.
- `modules/dialogue.py`: machine d'etat, pause / reprise, confusion, gestion de session.
- `modules/transcriber.py`: transcription STT.
- `modules/tts.py`: synthese vocale.
- `modules/llm.py` et `modules/local_llm.py`: appels modele distant et fallback local.
- `modules/course_builder.py`: ingestion et structuration des cours.
- `modules/student_profile.py`: profil adaptatif de l'etudiant.
- `modules/analytics.py`: indicateurs et rapports.

### 1.3 Donnees et persistance

- `database/models.py`: schema SQLAlchemy.
- `database/crud.py`: operations CRUD.
- `database/init_db.py`: initialisation de la base.
- `database/init.sql`: schema SQL brut.
- `database/reset_db_fresh.py`: remise a zero en environnement de dev.

### 1.4 Interface utilisateur

- `static/index.html`: interface cours / presentation.
- `static/quiz.html`: interface quiz dediee.
- `static/sdk.js`: helper JavaScript cote client.

### 1.5 Ressources et artefacts runtime

- `courses/`: cours importes et structure logique.
- `media/`: fichiers media generes ou sauvegardes.
- `data/`: caches et index locaux.
- `logs/`: journaux d'execution et metriques.
- `chapter3-diagrams/`: pack de diagrammes generes en SVG + fichiers `.mmd`.
- `docs/chapter3/`: livrables documentaires du chapitre 3.

## 2. Ce qui doit rester du vrai code

Ces parties doivent etre ecrites, relues et teste es comme du code de production:

- Routage API et WebSocket dans `main.py`.
- Gestion de session, pause, reprise, et etat conversationnel.
- Ingestion de documents et structuration des cours.
- Recherche RAG, filtrage `course_id`, et assemblage du contexte.
- Transcription, TTS, fallback LLM, et logique audio temps reel.
- CRUD et modele de donnees.
- Code d'interface qui pilote les actions utilisateur.
- Tout ce qui gere la securite, l'authentification, la persistance et les erreurs.

## 3. Ce qui peut etre genere automatiquement

Le contenu suivant peut etre assiste par l'IA, puis valide par un humain:

- Diagrammes Mermaid, SVG, PNG et export visuel.
- Documentation technique, README, rapports de chapitre.
- Exemples de configuration.
- Textes d'explication, notes de conception, fiches d'architecture.
- Squelettes de tests ou de scripts repetitifs.

## 4. Ce qui ne doit pas etre genere aveuglement par l'IA

Ces zones doivent rester sous controle humain, car elles impactent directement le comportement du produit:

- Logique WebSocket et machine d'etat.
- Gestion de session et reprise apres interruption.
- Lien entre STT, RAG, LLM et TTS.
- Sauvegarde des donnees et schemas de base.
- Gestion des erreurs, des timeouts et des fallback.
- Toute logique de securite, d'acces, ou de routage sensible.

## 5. Regle pratique simple

Si le code:

- modifie l'etat utilisateur,
- enregistre des donnees,
- controle un flux temps reel,
- touche a la securite,
- ou decide quoi repondre a l'etudiant,

alors il doit etre considere comme **vrai code** et pas comme simple texte genere.

L'IA peut aider a le proposer, mais il faut le relire, le tester et le conserver comme code maintenu.

## 6. Repartition recommandee par dossier

| Dossier | Role | Statut |
|---|---|---|
| `main.py` | Orchestration principale | Vrai code |
| `handlers/` | Pipeline temps reel et sessions | Vrai code |
| `modules/` | Logique metier et IA | Vrai code |
| `database/` | Donnees et persistance | Vrai code |
| `static/` | Interface utilisateur | Vrai code |
| `courses/` | Contenu pedagogique source | Donnees |
| `media/` | Medias generes / sauvegardes | Artefacts runtime |
| `data/` | Caches / indexes | Artefacts runtime |
| `logs/` | Logs | Artefacts runtime |
| `docs/` | Documentation | Contenu documentaire |
| `chapter3-diagrams/` | Diagrammes generes | Contenu genere |

## 7. Recommandation de nettoyage

Pour garder le projet propre:

1. Garder le code metier dans `main.py`, `handlers/`, `modules/` et `database/`.
2. Mettre les livrables de memoire et les images dans `docs/`.
3. Garder les diagrammes generates hors du code source principal.
4. Eviter de melanger les preuves documentaires avec la logique de production.

## 8. Conclusion

La bonne separation est la suivante:

- **code reel** = ce qui fait fonctionner Smart Teacher;
- **code genere** = aides, schemas, exports, documentation;
- **donnees runtime** = logs, medias, caches, index.

Si vous voulez, je peux maintenant faire une version encore plus pratique avec:

- une arborescence propre du projet,
- un classement fichier par fichier,
- et une liste "a garder / a regenerer / a documenter".

## 9. Plan de refactor par fonctionnalite

Cette section donne une cible claire pour organiser le code dans des fichiers plus petits et plus simples a comprendre.

### 9.1 Regle principale

Le principe doit etre le suivant:

- `main.py` ne doit garder que le demarrage de l'application FastAPI, le montage des routers et la configuration globale.
- Chaque fonctionnalite metier doit vivre dans un fichier specialise.
- Les helpers partages doivent etre places dans des modules utilitaires courts et nommes clairement.

### 9.2 Arborescence cible recommandee

```text
smart_teacher/
├── main.py
├── config.py
├── domains_config.py
├── handlers/
│   ├── session_manager.py
│   ├── audio_pipeline.py
│   └── rest_routes.py
├── api/
│   ├── websocket.py
│   ├── sessions.py
│   ├── course.py
│   ├── search.py
│   ├── analytics.py
│   ├── media.py
│   ├── profile.py
│   └── health.py
├── services/
│   ├── bootstrap.py
│   ├── presentation.py
│   ├── quiz.py
│   ├── media_service.py
│   └── tts_cache.py
├── modules/
├── database/
├── static/
├── courses/
└── docs/
```

### 9.3 Fonctionnalite -> fichier cible

| Fonctionnalite | Fichier cible conseille | Pourquoi |
|---|---|---|
| Demarrage FastAPI, middleware, static mount | `main.py` | Point d'entree unique, facile a lire |
| Diagnostic des services au lancement | `services/bootstrap.py` | Code d'initialisation isole |
| Session WebSocket principale | `api/websocket.py` | Tout le flux temps reel au meme endroit |
| Envoi d'etat, cancel, stream audio | `api/websocket.py` | Fonctions liees au cycle conversationnel |
| Creation / lecture / nettoyage de session | `api/sessions.py` | Regroupe la logique session REST |
| Construction de cours et ingestion | `api/course.py` | Separer le traitement des cours du reste |
| Recherche transcripts / stats RAG | `api/search.py` | Regrouper les outils de recherche |
| Analytics et KPI | `api/analytics.py` | Rendre les metriques isolées et lisibles |
| Media serve + listing | `api/media.py` | Tout ce qui touche aux fichiers media |
| Profil et adaptation etudiant | `api/profile.py` | API dediee au profil adaptatif |
| Health check, favicon, root | `api/health.py` | Endpoints systeme simples |
| Gestion du cours presentation/lecture | `services/presentation.py` | Logique de narration et reprise |
| Quiz generation et affichage | `services/quiz.py` | Code de quiz separe du reste |
| Cache TTS et prefetch slide | `services/tts_cache.py` | Optimisation vocale isolee |
| Sauvegarde media et JSON | `services/media_service.py` | Helpers de stockage courts |

### 9.4 Decomposition de `main.py`

Aujourd'hui, `main.py` contient encore plusieurs blocs differents. Pour un code plus propre, il devrait garder seulement:

1. L'initialisation des dependances globales.
2. La creation de l'application FastAPI.
3. L'enregistrement des routers.
4. Le montage de `static/` et `media/`.
5. Le lifespan et les verifications minimales.

Tout le reste devrait etre appele depuis des fichiers dedies.

### 9.5 Repartition detaillee des fonctions existantes

#### A. Bootstrap et configuration

- `log_backend_diagnostics()` -> `services/bootstrap.py`
- `lifespan()` -> `services/bootstrap.py`
- `disable_html_cache()` -> `api/health.py` ou `services/bootstrap.py`
- `save_media_bytes()` -> `services/media_service.py`
- `save_media_json()` -> `services/media_service.py`

#### B. Session et WebSocket

- `websocket_endpoint()` -> `api/websocket.py`
- `send_state()` -> `api/websocket.py`
- `handle_post_response()` -> `api/websocket.py`
- `cancel_text_question_task()` -> `api/websocket.py`
- `process_text_question_turn()` -> `api/websocket.py`
- `process_quiz_request()` -> `api/websocket.py`
- `set_listening_state()` -> `api/websocket.py`
- `persist_learning_turn()` -> `api/websocket.py`
- `record_pause_point()` -> `services/presentation.py`
- `cancel_next_slide_prefetch()` -> `services/presentation.py`
- `warm_presentation_audio_cache()` -> `services/tts_cache.py`
- `prefetch_next_slide()` -> `services/presentation.py`
- `schedule_next_slide_prefetch()` -> `services/presentation.py`
- `synthesize_cached_tts()` -> `services/tts_cache.py`
- `_stream_audio()` -> `services/media_service.py` ou `api/websocket.py`
- `cancel_audio_stream()` -> `api/websocket.py`
- `start_audio_stream()` -> `api/websocket.py`
- `split_sentences_with_spans()` -> `services/presentation.py`
- `cancel_presentation_task()` -> `services/presentation.py`
- `explain_slide_focused()` -> `services/presentation.py`
- `run_presentation()` -> `services/presentation.py`
- `is_quiz_intent()` -> `services/quiz.py`
- `emit_confusion_micro_state()` -> `services/presentation.py` ou `api/websocket.py`

#### C. REST API

- `create_session()` -> `api/sessions.py`
- `root()` -> `api/health.py`
- `health()` -> `api/health.py`
- `dashboard_services()` -> `api/health.py` ou `modules/dashboard.py`
- `_probe_ollama()` -> `services/bootstrap.py` ou `api/health.py`
- `ask_question()` -> `api/search.py` ou `services/quiz.py` selon le flux texte
- `ingest_files()` -> `api/course.py`
- `_run_ingestion_background()` -> `api/course.py`
- `rag_stats()` -> `api/search.py`
- `get_ingestion_status()` -> `api/course.py`
- `debug_rag_test()` -> `api/search.py`
- `cache_stats()` -> `api/health.py` ou `services/bootstrap.py`
- `get_session_info()` -> `api/sessions.py`
- `clear_session()` -> `api/sessions.py`
- `search_transcripts()` -> `api/search.py`
- `get_session_transcript()` -> `api/search.py`
- `search_stats()` -> `api/search.py`
- `analytics_report()` -> `api/analytics.py`
- `analytics_kpi()` -> `api/analytics.py`
- `analytics_progression()` -> `api/analytics.py`
- `analytics_latency()` -> `api/analytics.py`
- `serve_media()` -> `api/media.py`
- `list_media()` -> `api/media.py`
- `get_student_profile()` -> `api/profile.py`
- `reset_student_profile()` -> `api/profile.py`
- `build_course()` -> `api/course.py`
- `list_courses()` -> `api/course.py`
- `get_course_structure()` -> `api/course.py`

### 9.6 Regle de lisibilite recommandee

Chaque fichier doit rester centre sur une seule responsabilite:

- un fichier pour le transport WebSocket,
- un fichier pour les routes REST,
- un fichier pour la presentation,
- un fichier pour le quiz,
- un fichier pour le stockage media,
- un fichier pour le bootstrap,
- un fichier pour le cache TTS.

Si une fonction commence a faire trois choses differentes, il faut la casser en plusieurs pieces.

### 9.7 Ce qui doit absolument rester du vrai code

Pour eviter de transformer le projet en documentation abstraite, ces parties doivent rester du code reel, versionne et teste:

- WebSocket temps reel.
- STT, RAG, LLM, TTS.
- Ingestion de cours.
- Sauvegarde et reprise de session.
- Profil adaptatif.
- Database CRUD.
- Metrics et dashboard backend.

### 9.8 Ce qui peut etre genere

- Diagrammes.
- Fichiers d'aide.
- README et notes de conception.
- Exemples de documentation.

### 9.9 Recommendation pratique pour la suite

Si vous voulez, le prochain pas utile est que je fasse un **plan de refactor fichier par fichier** en listant:

- le fichier actuel,
- les fonctions a deplacer,
- le nouveau fichier cible,
- et l'ordre de migration sans casser le projet.

## 10. Organisation recommandee du dossier `modules/`

Le dossier `modules/` contient aujourd'hui plusieurs responsabilites melangees. Pour rendre le code plus simple a lire, il faut le transformer en sous-domaines clairs.

### 10.1 Règle de base

Le dossier `modules/` doit contenir uniquement la logique metier et les services techniques reutilisables.

Il ne doit pas contenir:

- des routes FastAPI,
- des decorators `@app.get` ou `@router.get`,
- du HTML,
- du code de demarrage applicatif,
- ni des artefacts runtime.

### 10.2 Structure cible recommandee

```text
modules/
├── ai/
│   ├── llm.py
│   ├── local_llm.py
│   ├── multimodal_rag.py
│   ├── transcriber.py
│   ├── tts.py
│   └── confusion_detector.py
├── pedagogy/
│   ├── dialogue.py
│   ├── course_builder.py
│   ├── course_analyzer.py
│   ├── student_profile.py
│   ├── slide_sync.py
│   └── ingestion_manager.py
├── data/
│   ├── media_storage.py
│   ├── transcript_search.py
│   └── embedding_cache.py
├── monitoring/
│   ├── analytics.py
│   ├── logger.py
│   └── stt_logger.py
├── input/
│   └── audio_input.py
└── archived/
```

### 10.3 Repartition fichier par fichier

Cette table documente les anciens emplacements et leur destination dans la nouvelle arborescence.

| Ancien emplacement | Groupe cible | Role |
|---|---|---|
| `modules/llm.py` | `modules/ai/` | Generation de reponses et prompts |
| `modules/local_llm.py` | `modules/ai/` | Fallback Ollama local |
| `modules/multimodal_rag.py` | `modules/ai/` | Retrieval + generation |
| `modules/transcriber.py` | `modules/ai/` | STT |
| `modules/tts.py` | `modules/ai/` | TTS |
| `modules/confusion_detector.py` | `modules/ai/` | Chargement du modele confusion |
| `modules/dialogue.py` | `modules/pedagogy/` | Machine d'etat session / cours |
| `modules/course_builder.py` | `modules/pedagogy/` | Ingestion et structuration cours |
| `modules/course_analyzer.py` | `modules/pedagogy/` | Analyse du cours |
| `modules/student_profile.py` | `modules/pedagogy/` | Profil adaptatif |
| `modules/slide_sync.py` | `modules/pedagogy/` | Synchronisation slide / narration |
| `modules/ingestion_manager.py` | `modules/pedagogy/` | Orchestration ingestion |
| `modules/media_storage.py` | `modules/data/` | Stockage objet / local |
| `modules/transcript_search.py` | `modules/data/` | Recherche historique des transcriptions |
| `modules/embedding_cache.py` | `modules/data/` | Cache embeddings |
| `modules/analytics.py` | `modules/monitoring/` | KPI et reporting |
| `modules/logger.py` | `modules/monitoring/` | Journalisation CSV |
| `modules/stt_logger.py` | `modules/monitoring/` | Logs STT |
| `modules/audio_input.py` | `modules/input/` | Capture audio et VAD |
| `modules/dashboard.py` | `modules/monitoring/` ou `api/dashboard.py` | Dashboard professeur |

### 10.4 Sous-domaines conseilles

#### A. `modules/ai/`

Ce sous-dossier doit contenir tout ce qui concerne l'IA:

- reponse LLM,
- fallback local,
- RAG,
- STT,
- TTS,
- detection de confusion.

#### B. `modules/pedagogy/`

Ce sous-dossier doit contenir la logique d'apprentissage:

- etat de session,
- profil etudiant,
- construction des cours,
- synchronisation cours / slides,
- ingestion.

#### C. `modules/data/`

Ce sous-dossier doit contenir les briques de stockage et de recherche:

- MinIO ou stockage local,
- recherche des transcriptions,
- cache embeddings.

#### D. `modules/monitoring/`

Ce sous-dossier doit contenir les fonctions de supervision:

- analytics,
- logs,
- metriques STT,
- dashboard enseignant.

#### E. `modules/input/`

Ce sous-dossier doit contenir les entrees physiques:

- capture micro,
- VAD,
- conversion audio.

### 10.5 Regles de dependances entre modules

Pour garder le code propre:

- `modules/ai/` peut utiliser `modules/data/` et `modules/pedagogy/`, mais pas `main.py`.
- `modules/pedagogy/` peut utiliser `modules/ai/` et `modules/data/`.
- `modules/monitoring/` doit observer les autres modules, pas les piloter directement.
- `modules/input/` doit rester bas niveau et ne pas connaitre FastAPI.

### 10.6 Ce qu'il faut eviter

- Un fichier `modules.py` unique qui contient tout.
- Une logique de route HTTP dans les modules metier.
- Des imports circulaires entre `main.py`, `api/` et `modules/`.
- Des fonctions trop longues qui melangent I/O, IA et rendu.

### 10.7 Recommandation pratique

La migration la plus saine est:

1. Créer les sous-dossiers `modules/ai/`, `modules/pedagogy/`, `modules/data/`, `modules/monitoring/`, `modules/input/`.
2. Déplacer les fichiers sans changer leur logique interne au début.
3. Supprimer les anciens fichiers plats une fois le nouvel emplacement validé.
4. Ensuite, simplifier `main.py` pour qu'il n'importe que les orchestrateurs.
5. Enfin, extraire les fonctions trop longues en helpers plus petits.

Note: la migration `modules/` est maintenant physique. Le code vit dans `modules/ai/`, `modules/pedagogy/`, `modules/data/`, `modules/monitoring/` et `modules/input/`, et les anciens fichiers plats ont été supprimés.

### 10.8 Resultat attendu

Avec cette organisation, on obtient un code plus facile a comprendre parce que:

- l'IA est dans un seul endroit,
- la pedagogie est dans un seul endroit,
- la data est dans un seul endroit,
- la supervision est dans un seul endroit,
- et l'entree audio est dans un seul endroit.

Si vous voulez, je peux maintenant faire la version suivante: **un vrai plan de deplacement des fichiers existants vers cette nouvelle arborescence**.

## 11. Organisation recommandee du dossier `database/`

Le dossier `database/` doit aussi etre decoupe proprement, parce qu'il contient a la fois les modeles, les operations CRUD, l'initialisation et potentiellement les migrations.

### 11.1 Regle de base

Le dossier `database/` doit rester centre sur la persistence.

Il ne doit pas contenir:

- de logique metier de presentation,
- de WebSocket,
- de traitement audio,
- de generation RAG,
- ni de logique d'interface.

### 11.2 Structure cible recommandee

```text
database/
├── __init__.py
├── core/
│   ├── __init__.py
│   └── init_db.py
├── models/
│   └── __init__.py
├── repositories/
│   ├── __init__.py
│   └── crud.py
├── init.sql
└── reset_db_fresh.py
```

Note: le code reel a ete deplace dans `database/core/init_db.py`, `database/models/__init__.py` et `database/repositories/crud.py`. Les anciens fichiers plats ont ete supprimes; le tableau ci-dessous conserve le mapping historique vers la nouvelle structure.

### 11.3 Repartition fichier par fichier

| Ancien emplacement | Groupe cible | Role |
|---|---|---|
| `database/models.py` | `database/models/` | Definition des tables et relations |
| `database/crud.py` | `database/repositories/` | Operations d'acces aux donnees |
| `database/init_db.py` | `database/core/` | Engine, session factory, initialisation |
| `database/init.sql` | `database/` | Schema SQL brut ou migration initiale |
| `database/reset_db_fresh.py` | `database/` ou `scripts/` | Reset complet pour dev |

### 11.4 Decoupage des modeles

Pour rendre le schema plus facile a comprendre, les modeles peuvent etre repartis par domaine:

#### A. `database/models/auth.py`

- `Student`

#### B. `database/models/course.py`

- `Course`
- `Chapter`
- `Section`
- `Concept`

#### C. `database/models/learning.py`

- `LearningSession`
- `Interaction`
- `LearningEvent`
- `StudentProfile`
- `StudentMistake`
- `RAGChunk`

#### D. `database/models/analytics.py`

- `PerformanceMetric`

#### E. `database/models/system.py`

- `SystemLog`
- `LLMCache`

### 11.5 Decoupage des repositories

Le module `database/repositories/crud.py` centralise encore les operations de persistence, mais pour un code plus propre il faut le remplacer par des repositories specialises:

- `student_repository.py` -> comptes, profils, authentification.
- `course_repository.py` -> cours, chapitres, sections, concepts.
- `session_repository.py` -> sessions, interactions, etats conversationnels.
- `analytics_repository.py` -> KPI, statistiques, tendances.

### 11.6 Regle de lisibilite

Chaque repository doit faire une seule famille d'operations.

Exemple:

- un repository pour les cours,
- un repository pour les sessions,
- un repository pour les analytics,
- un repository pour les utilisateurs.

Il faut eviter un gros fichier CRUD qui contient absolument tout.

### 11.7 Dossier `core/`

Le sous-dossier `database/core/` doit contenir les objets techniques de base:

- moteur SQLAlchemy,
- session async,
- base declarative,
- configuration de connexion.

Cela permet de garder les modeles et les acces aux donnees separates des details techniques de connexion.

### 11.8 Recommendation pratique de migration

La migration la plus simple est:

1. Extraire d'abord `database/core/`.
2. Puis couper `models.py` en plusieurs fichiers de modeles.
3. Ensuite, decouper `crud.py` en repositories specialises.
4. Enfin, garder `init_db.py` comme point d'initialisation minimal.

### 11.9 Resultat attendu

Avec cette organisation, la couche base de donnees devient plus facile a maintenir parce que:

- le schema est decoupe par domaine,
- le CRUD est decoupe par responsabilite,
- l'initialisation est isolee,
- et la logique de persistence reste lisible.

Si vous voulez, je peux maintenant faire le **plan final complet: main.py + handlers + modules + database**, sous forme d'une arborescence cible unique et tres claire.