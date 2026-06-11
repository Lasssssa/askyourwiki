# AskYourWiki

Application de chat permettant d'interroger en langage naturel les wikis (projets et/ou groupes)
d'une instance GitLab auto-hébergée, en s'appuyant sur un grand modèle de langage (LLM) comme
moteur de réponse.

Le moteur de génération est **pluggable** : par défaut l'application utilise un modèle
auto-hébergé via une API compatible **OpenAI** (par exemple servi par **vLLM**, mais aussi
Ollama, llama.cpp, TGI, ...). Une API hébergée (Anthropic) peut être utilisée en alternative.

## Fonctionnalités

- Synchronisation des pages de wiki de projets et de groupes GitLab vers un stockage local markdown
- Synchronisation automatique périodique + endpoint de synchronisation manuelle
- Chat en langage naturel basé sur le contenu des wikis, avec réponses en streaming (SSE)
- Moteur LLM configurable : modèle auto-hébergé compatible OpenAI (vLLM, ...) par défaut, ou API hébergée
- Interface web sobre en dark mode, avec rendu markdown et coloration syntaxique des réponses
- Conteneurisation Docker prête à l'emploi

## Prérequis

- Python 3.11+
- Un Personal Access Token GitLab avec le scope `read_api` (ou `api`)
- Un moteur LLM :
  - soit un serveur exposant une API compatible OpenAI (ex: [vLLM](https://github.com/vllm-project/vllm), Ollama, TGI, llama.cpp) — par défaut
  - soit une clé API d'un fournisseur compatible Anthropic, en alternative
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
   | `LLM_PROVIDER` | `vllm` (par défaut) ou `anthropic` |
   | `VLLM_BASE_URL` / `VLLM_MODEL` / `VLLM_API_KEY` | Configuration du modèle auto-hébergé (si `LLM_PROVIDER=vllm`) |
   | `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | Configuration de l'API hébergée (si `LLM_PROVIDER=anthropic`) |
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

## Modèle auto-hébergé compatible OpenAI (vLLM, etc.)

Par défaut (`LLM_PROVIDER=vllm`), l'application appelle un serveur exposant une API
"chat completions" compatible OpenAI. Configurez votre `.env` :

```bash
LLM_PROVIDER=vllm
VLLM_BASE_URL=http://<host>:8000/v1
VLLM_MODEL=<nom-du-modele-servi>
VLLM_API_KEY=EMPTY
```

- `VLLM_BASE_URL` doit pointer vers l'endpoint `/v1` du serveur (lancé par exemple avec
  `vllm serve <model> --port 8000`).
- `VLLM_MODEL` doit correspondre exactement au nom renvoyé par `GET /v1/models` sur votre
  serveur (par défaut le chemin/nom HuggingFace du modèle, ou la valeur passée à
  `--served-model-name`).
- `VLLM_API_KEY` : laissez `EMPTY` si le serveur est lancé sans authentification. Sinon,
  renseignez la clé attendue.

> Le modèle choisi doit avoir une fenêtre de contexte suffisante pour accueillir le contenu des
> wikis + l'historique. Si votre modèle a une fenêtre plus petite que 150k tokens, réduisez
> `MAX_CONTEXT_TOKENS` dans `.env` en conséquence.

## API hébergée (Anthropic) en alternative

Pour utiliser une API hébergée plutôt qu'un modèle auto-hébergé, configurez :

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=<votre-clé>
ANTHROPIC_MODEL=<identifiant-du-modèle>
```

Le reste de l'application (synchronisation des wikis, contexte, interface, streaming) fonctionne
à l'identique quel que soit le moteur choisi : seul le module `chat/` change en interne
(`chat/vllm.py` ou `chat/anthropic_chat.py`).

## Utilisation

- Posez vos questions dans la zone de chat : les réponses sont générées à partir du contenu des
  wikis indexés et streamées en temps réel.
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
  (~4 caractères par token), pas un comptage exact via le tokenizer du modèle utilisé.
- Les pages de wiki au format autre que Markdown (ex: AsciiDoc, RDoc) sont stockées telles
  quelles ; leur rendu dans le contexte envoyé au modèle n'est pas converti en markdown.
- Aucune authentification n'est mise en place sur l'interface web : à déployer derrière un
  reverse proxy / VPN si l'instance n'est pas destinée à un accès public.
