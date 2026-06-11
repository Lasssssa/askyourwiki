# GitLab Wiki Chat

Application de chat permettant d'interroger en langage naturel les wikis (projets et/ou groupes)
d'une instance GitLab auto-hébergée, en utilisant l'API Claude (Anthropic) comme moteur de réponse.

## Fonctionnalités

- Synchronisation des pages de wiki de projets et de groupes GitLab vers un stockage local markdown
- Synchronisation automatique périodique + endpoint de synchronisation manuelle
- Chat en langage naturel basé sur le contenu des wikis, avec réponses en streaming (SSE)
- Interface web sobre en dark mode, avec rendu markdown des réponses
- Conteneurisation Docker prête à l'emploi

## Prérequis

- Python 3.11+
- Un Personal Access Token GitLab avec le scope `read_api` (ou `api`)
- Une clé API Anthropic (https://console.anthropic.com/)
- (Optionnel) Docker et Docker Compose

## Configuration (.env)

1. Copiez le fichier d'exemple :

   ```bash
   cp .env.example .env
   ```

2. Remplissez les variables :

   | Variable | Description |
   |---|---|
   | `GITLAB_URL` | URL de base de votre instance GitLab (ex: `https://gitlab.monentreprise.com`) |
   | `GITLAB_TOKEN` | Personal Access Token GitLab (scope `read_api`) |
   | `GITLAB_PROJECT_IDS` | IDs des projets dont les wikis doivent être indexés, séparés par des virgules |
   | `GITLAB_GROUP_IDS` | IDs des groupes dont les wikis doivent être indexés (optionnel) |
   | `ANTHROPIC_API_KEY` | Clé API Anthropic |
   | `SYNC_INTERVAL_MINUTES` | Fréquence de la synchronisation automatique (en minutes) |
   | `APP_PORT` | Port d'écoute de l'application |

### Trouver les IDs de projets/groupes GitLab

- **Projet** : ouvrez le projet sur GitLab, l'ID est affiché sous le nom du projet sur la page
  d'accueil du projet (ou via `Settings > General`). Il est aussi visible dans la réponse de
  `GET /api/v4/projects/<namespace>%2F<projet>` (encodez le `/` en `%2F`).
- **Groupe** : ouvrez le groupe sur GitLab, l'ID est affiché sous le nom du groupe sur la page
  d'accueil du groupe (ou via `Settings > General`).

> Le wiki doit être activé pour le projet ou le groupe concerné, et le token doit avoir accès
> en lecture à ce projet/groupe.

## Lancer en local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn main:app --reload --port 8000
```

L'application sera accessible sur http://localhost:8000.

Au démarrage, une synchronisation initiale des wikis est lancée automatiquement (si des
projets/groupes sont configurés), puis une synchronisation périodique est planifiée toutes les
`SYNC_INTERVAL_MINUTES` minutes.

## Lancer avec Docker

```bash
docker compose up --build
```

Les pages de wiki synchronisées sont persistées dans `./data/wikis` (monté en volume).

## Utiliser un modèle auto-hébergé (vLLM) au lieu de Claude

Par défaut, le chat utilise l'API Anthropic (`LLM_PROVIDER=anthropic`). Pour utiliser un modèle
servi par votre propre instance **vLLM** (qui expose une API compatible OpenAI), modifiez votre
`.env` :

```bash
LLM_PROVIDER=vllm
VLLM_BASE_URL=http://<host-vllm>:8000/v1
VLLM_MODEL=<nom-du-modele-servi>
VLLM_API_KEY=EMPTY
```

- `VLLM_BASE_URL` doit pointer vers l'endpoint `/v1` du serveur vLLM (lancé par exemple avec
  `vllm serve <model> --port 8000`).
- `VLLM_MODEL` doit correspondre exactement au nom renvoyé par `GET /v1/models` sur votre
  serveur vLLM (par défaut le chemin/nom HuggingFace du modèle, ou la valeur passée à
  `--served-model-name`).
- `VLLM_API_KEY` : laissez `EMPTY` si vLLM est lancé sans `--api-key`. Sinon, renseignez la
  clé attendue.
- `ANTHROPIC_API_KEY` n'est plus nécessaire dans ce mode.

Le reste de l'application (synchronisation des wikis, contexte, interface, streaming) fonctionne
à l'identique : seul le moteur de génération change (`chat/vllm.py` au lieu de `chat/claude.py`),
via l'API "chat completions" compatible OpenAI exposée par vLLM.

> Le modèle choisi doit avoir une fenêtre de contexte suffisante pour accueillir le contenu des
> wikis + l'historique. Si votre modèle a une fenêtre plus petite que 150k tokens, réduisez
> `MAX_CONTEXT_TOKENS` dans `.env` en conséquence.

## Utilisation

- Posez vos questions dans la zone de chat : les réponses sont générées par Claude en se basant
  sur le contenu des wikis indexés, et streamées en temps réel.
- Le bouton **"Synchroniser les wikis"** déclenche une resynchronisation manuelle complète.
- La barre de statut affiche le nombre de pages indexées et la date de la dernière synchronisation.

## API

| Méthode | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Sert l'interface de chat |
| `POST` | `/api/chat` | `{message, history}` → réponse en streaming SSE |
| `POST` | `/api/sync` | Déclenche une synchronisation manuelle des wikis |
| `GET` | `/api/status` | Nombre de pages indexées, date de dernière sync, erreurs éventuelles |

## Limitations connues

- L'API REST GitLab pour les wikis (`/wikis`) ne fournit pas de date de dernière modification par
  page. La synchronisation est donc une **resynchronisation complète** de chaque projet/groupe
  configuré (et non un diff incrémental page par page).
- L'estimation du nombre de tokens pour la troncature du contexte est une heuristique simple
  (~4 caractères par token), pas un comptage exact via le tokenizer Claude.
- Les pages de wiki au format autre que Markdown (ex: AsciiDoc, RDoc) sont stockées telles
  quelles ; leur rendu dans le contexte envoyé à Claude n'est pas converti en markdown.
- Aucune authentification n'est mise en place sur l'interface web : à déployer derrière un
  reverse proxy / VPN si l'instance n'est pas destinée à un accès public.
