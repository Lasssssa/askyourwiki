# Architecture - GitLab Wiki Chat

Ce document décrit le fonctionnement interne de l'application : comment les composants
s'articulent, comment les données circulent, et les choix de conception importants.

## Vue d'ensemble

```
┌─────────────┐      ┌──────────────────────────────────────────────┐      ┌─────────────┐
│   GitLab     │◄────►│              FastAPI (main.py)                │◄────►│   Claude     │
│ (projets &   │ REST │                                                │ API  │ (Anthropic)  │
│  groupes,    │      │  ┌────────────┐  ┌────────────┐  ┌──────────┐ │      └─────────────┘
│  wikis)      │      │  │ SyncManager│  │ WikiStore  │  │ context/ │ │
└─────────────┘      │  │(gitlab/sync│  │(storage/   │  │ claude   │ │
                      │  │   .py)     │  │wiki_store) │  │ (chat/)  │ │
                      │  └────────────┘  └────────────┘  └──────────┘ │
                      │         │               │                      │
                      │         └──────►  data/wikis/*.md ◄────────────┘
                      └────────────────────┬───────────────────────────┘
                                            │ HTTP (SSE)
                                            ▼
                                  ┌────────────────────┐
                                  │  static/ (UI web)   │
                                  │ index.html / app.js │
                                  └────────────────────┘
```

L'application a deux flux principaux :

1. **Flux de synchronisation** : GitLab → `gitlab/client.py` → `gitlab/sync.py` →
   `storage/wiki_store.py` → fichiers markdown dans `data/wikis/`.
2. **Flux de chat** : navigateur → `POST /api/chat` → `chat/context.py` (lit
   `data/wikis/`) → `chat/claude.py` (appel API Anthropic en streaming) → SSE → navigateur.

## Configuration (`config.py`)

Point d'entrée unique pour toutes les variables d'environnement (chargées via `python-dotenv`
depuis `.env`). Expose un objet singleton `config` utilisé par tous les modules :

- `GITLAB_URL`, `GITLAB_TOKEN` : accès à l'instance GitLab
- `GITLAB_PROJECT_IDS`, `GITLAB_GROUP_IDS` : listes d'IDs (parsées depuis des chaînes
  `"123,456"`), scopes à synchroniser
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` : accès à l'API Claude
- `SYNC_INTERVAL_MINUTES` : fréquence du job de sync planifié
- `MAX_CONTEXT_TOKENS` (150 000 par défaut) : budget de tokens pour le contexte envoyé à Claude
- `MAX_HISTORY_MESSAGES` (5 par défaut) : nombre d'échanges d'historique conservés
- `DATA_DIR` : `data/wikis/`, racine du stockage local

`Config.validate()` retourne une liste d'avertissements (config manquante) loggés au démarrage,
sans bloquer le lancement de l'application (permet de démarrer même sans config GitLab pour
tester l'UI, par ex.).

## Synchronisation des wikis

### `gitlab/client.py` — `GitLabClient`

Client HTTP asynchrone (httpx) autour de l'API REST GitLab v4.

- Toutes les requêtes passent par `_get()`, qui traduit les codes HTTP en exceptions
  métier : `GitLabAuthError` (401), `GitLabNotFoundError` (404 — projet/groupe/wiki
  inaccessible ou désactivé), `GitLabAPIError` (autres erreurs / erreurs réseau).
- `_get_paginated()` suit l'en-tête `X-Next-Page` pour récupérer toutes les pages d'une
  ressource paginée (100 éléments par page).
- `get_project_wiki_pages(project_id)` / `get_group_wiki_pages(group_id)` appellent
  respectivement `GET /projects/:id/wikis` et `GET /groups/:id/wikis` avec
  `with_content=1` (le contenu markdown est donc récupéré en une seule passe). Si le wiki
  est désactivé ou absent (404), la méthode retourne une liste vide plutôt que de planter.

### `gitlab/sync.py` — `SyncManager`

Orchestre la synchronisation et conserve l'état (`last_sync_at`, `last_sync_errors`,
`is_syncing`) consulté par `/api/status`.

- `sync_all()` : pour chaque projet (`GITLAB_PROJECT_IDS`) puis chaque groupe
  (`GITLAB_GROUP_IDS`), appelle `_sync_scope()`. Un verrou (`is_syncing`) empêche les
  exécutions concurrentes (si une sync planifiée et une sync manuelle se chevauchent, la
  seconde est ignorée et renvoie le statut courant).
- `_sync_scope(client, scope_type, scope_id)` : récupère les pages via le client, puis
  **remplace intégralement** le contenu local du scope (`store.reset_scope()` supprime le
  dossier puis chaque page est réécrite via `store.save_page()`). Les erreurs par scope
  sont catchées et accumulées dans `last_sync_errors` sans interrompre la synchronisation
  des autres scopes.

> **Pourquoi une resync complète et pas incrémentale ?** L'API GitLab `/wikis` ne renvoie
> aucune date de dernière modification par page. Il n'y a donc aucun moyen fiable de savoir
> quelles pages ont changé sans tout retélécharger. Une resync complète par scope reste peu
> coûteuse (les wikis sont rarement volumineux) et garantit que les pages supprimées côté
> GitLab disparaissent aussi du stockage local.

### `storage/wiki_store.py` — `WikiStore`

Couche de persistance fichier, sans base de données.

- Arborescence : `data/wikis/{scope_type}_{scope_id}/{slug}.md` (les `/` dans les slugs
  imbriqués sont remplacés par `__`).
- Chaque fichier contient un frontmatter simple (`---` ... `---`) avec `title`, `slug`,
  `scope_type`, `scope_id`, `format`, `synced_at`, suivi du contenu markdown brut de la page.
- `load_all_pages()` relit tout le dossier, parse le frontmatter, et retourne une liste de
  `WikiPage` **triée par `synced_at` décroissant** (pages les plus récemment synchronisées
  en premier) — cet ordre est ensuite exploité pour la troncature du contexte.
- `count_pages()` / `reset_scope()` sont des utilitaires pour le statut et la resync.

## Chat avec Claude

### `chat/context.py` — `build_context()`

Construit le texte qui sera injecté dans le system prompt de Claude.

- Charge toutes les pages via `WikiStore.load_all_pages()` (déjà triées, plus récentes
  d'abord).
- Formate chaque page en section markdown : `### {title} (scope: ..., slug: ...)` suivi du
  contenu.
- Additionne les sections tant que la taille cumulée (en caractères) reste sous
  `MAX_CONTEXT_TOKENS * 4` (heuristique ~4 caractères/token). Dès que l'ajout d'une page
  dépasserait le budget, on s'arrête : les pages les plus anciennes sont donc celles
  exclues en premier (priorité aux pages récentes, comme demandé dans le cahier des
  charges).
- Cas limite : si même la première page dépasse le budget à elle seule, elle est tronquée
  brutalement à `max_chars` caractères.
- Retourne un objet `WikiContext` (`text`, `pages_included`, `pages_total`, `truncated`)
  pour le logging/diagnostic.

### `chat/base.py` — `BaseChat` et backends interchangeables

Le moteur de génération est **pluggable** via `LLM_PROVIDER` (`anthropic` ou `vllm`).
`BaseChat` factorise ce qui est commun aux deux backends :

- `SYSTEM_PROMPT_TEMPLATE` : instruit le modèle de répondre **uniquement** à partir du
  contexte wiki fourni, de dire explicitement quand l'information est absente, et de
  répondre dans la langue de la question. Le contexte produit par `build_context()` est
  injecté directement dans ce template.
- `_build_messages()` : tronque l'historique reçu du frontend aux `MAX_HISTORY_MESSAGES`
  derniers échanges (× 2 messages par échange = user + assistant), puis ajoute le nouveau
  message utilisateur.
- `stream_response(message, history, context_text)` : générateur asynchrone qui `yield`
  chaque fragment de texte de la réponse — c'est l'interface implémentée par chaque backend
  et consommée directement par l'endpoint FastAPI.

#### `chat/claude.py` — `ClaudeChat` (backend par défaut)

Utilise le SDK officiel `anthropic` (`AsyncAnthropic`). `stream_response()` appelle
`client.messages.stream(...)` avec le modèle `claude-sonnet-4-20250514` (system prompt +
messages), et relaie `stream.text_stream`. En cas d'erreur API (`APIError`), un message
d'erreur est yield comme texte plutôt que de lever une exception, pour que le flux SSE se
termine proprement côté client.

#### `chat/vllm.py` — `VLLMChat` (modèle auto-hébergé)

Utilise le SDK `openai` (`AsyncOpenAI`) pointé vers `VLLM_BASE_URL` (l'endpoint
`/v1/chat/completions` compatible OpenAI exposé par vLLM). Le system prompt est passé comme
premier message `role: "system"` dans la liste `messages` (contrairement à l'API Anthropic
qui a un paramètre `system` séparé). `stream_response()` consomme le flux
`chat.completions.create(..., stream=True)` et yield `chunk.choices[0].delta.content` à
chaque itération. Mêmes garanties d'erreur que `ClaudeChat` (message d'erreur yield plutôt
qu'exception).

#### Sélection du backend (`main.py`)

`_build_chat_client()` lit `config.LLM_PROVIDER` et instancie `ClaudeChat` ou `VLLMChat` en
conséquence (ou retourne `None` si la configuration requise est manquante, auquel cas
`/api/chat` répond 503). Le reste de l'application (sync, contexte, UI, streaming SSE) est
strictement identique quel que soit le backend choisi.

## API FastAPI (`main.py`)

Au chargement du module :
- Instancie `WikiStore`, `SyncManager`, `AsyncIOScheduler`, et `ClaudeChat` (si
  `ANTHROPIC_API_KEY` est configuré — sinon `/api/chat` répondra 503).

`lifespan` (cycle de vie de l'app) :
1. Log les avertissements de config manquante.
2. Si des projets/groupes sont configurés : lance une **synchronisation initiale
   bloquante** (`await sync_manager.sync_all()`) avant que le serveur n'accepte du trafic,
   puis programme `sync_manager.sync_all` en job récurrent (`SYNC_INTERVAL_MINUTES`) via
   APScheduler.
3. Sinon : log un avertissement, aucune sync n'est programmée.
4. À l'arrêt : arrête proprement le scheduler.

Routes :

| Route | Comportement |
|---|---|
| `GET /` | Sert `static/index.html` |
| `GET /static/*` | Fichiers statiques (CSS/JS) via `StaticFiles` |
| `POST /api/sync` | Déclenche `sync_manager.sync_all()` (400 si aucun scope configuré) et retourne le statut résultant |
| `GET /api/status` | Retourne `sync_manager.status()` : nb de pages indexées, dernière sync, erreurs, scopes configurés |
| `POST /api/chat` | Voir ci-dessous |

### `POST /api/chat` en détail

1. Lit `{message, history}` du body JSON. 503 si Claude non configuré, 400 si message vide.
2. Construit le contexte wiki via `build_context(store, config.MAX_CONTEXT_TOKENS)` —
   **rechargé à chaque requête** (donc reflète immédiatement la dernière synchronisation).
3. Retourne une `StreamingResponse` (`text/event-stream`) qui :
   - itère sur `claude_chat.stream_response(message, history, context.text)`,
   - émet chaque fragment sous la forme `data: {"delta": "..."}\n\n`,
   - émet `data: {"error": "..."}\n\n` en cas d'exception,
   - termine toujours par `data: [DONE]\n\n`.

## Interface web (`static/`)

- **`index.html`** : structure (barre de statut + bouton sync, zone de messages,
  textarea + bouton envoyer). Charge `marked.js` via CDN pour le rendu markdown.
- **`style.css`** : thème dark mode (variables CSS `--bg`, `--accent`, etc.), bulles de
  chat différenciées user/assistant/erreur, indicateur de saisie animé.
- **`app.js`** :
  - `sendMessage()` : ajoute le message utilisateur à l'historique local (`history`),
    envoie `POST /api/chat`, lit la réponse via `response.body.getReader()` (le SSE est
    parsé manuellement car `EventSource` ne supporte pas POST), accumule les `delta` et
    re-render le markdown progressivement dans la bulle assistant.
  - `refreshStatus()` : interroge `/api/status` toutes les 30 s et affiche
    "X pages indexées · dernière sync il y a N minutes".
  - `triggerSync()` : appelle `POST /api/sync`, désactive le bouton pendant l'opération et
    affiche le résultat (nombre de pages) avant de revenir à l'état initial.

## Synchronisation des données : ordre des opérations

```
Démarrage de l'app
   │
   ├─► sync_all() (bloquant)
   │      ├─► pour chaque projet : reset_scope + save_page(s)
   │      └─► pour chaque groupe : reset_scope + save_page(s)
   │
   ├─► scheduler.start()  (rejoue sync_all() toutes les SYNC_INTERVAL_MINUTES)
   │
   └─► serveur accepte les requêtes

Requête /api/chat
   │
   ├─► build_context()  ← lit data/wikis/**/*.md (état courant, post-dernière sync)
   ├─► ClaudeChat.stream_response(message, history, context)
   └─► SSE → navigateur (rendu progressif)

Requête /api/sync (manuel, ou bouton UI)
   └─► sync_all() (même logique que le démarrage)
```

## Choix de conception notables

- **Pas de base de données** : le stockage fichier markdown est suffisant pour le volume
  attendu (wikis de quelques projets/groupes) et a l'avantage d'être directement
  inspectable/versionnable.
- **Resync complète par scope** plutôt qu'incrémentale (cf. limitation de l'API GitLab,
  voir README).
- **Contexte rechargé à chaque message** plutôt que mis en cache : garantit la fraîcheur
  des réponses après une sync, au prix d'une lecture disque par requête (négligeable vu le
  volume de données).
- **Heuristique de tokens (4 car./token)** plutôt qu'un tokenizer exact : suffisant pour
  rester sous la limite de contexte avec une marge de sécurité, sans dépendance
  supplémentaire.
- **Streaming de bout en bout** (Claude → SSE → fetch reader → DOM) pour un retour visuel
  immédiat, conformément au cahier des charges.
