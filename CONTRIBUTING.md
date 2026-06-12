# Contributing

Thanks for considering contributing to AskYourWiki!

## Getting started

1. Fork the repository and clone your fork.
2. Read [ARCHITECTURE.md](ARCHITECTURE.md) for an overview of how the project is structured
   and how data flows between the components.
3. Set up a local environment (see "Running locally" in the [README](README.md)), or use
   `docker compose up --build`.

## Making changes

- Keep pull requests focused: one feature or fix per PR makes review much easier.
- Match the existing code style (the codebase favors small, explicit modules over
  abstractions).
- Update `README.md` and/or `ARCHITECTURE.md` if your change affects configuration,
  behavior, or the project structure.
- Make sure the application still starts (`uvicorn main:app --reload` or
  `docker compose up --build`) before opening a PR.

## Reporting issues

When reporting a bug, please include:

- Steps to reproduce
- Expected vs. actual behavior
- Relevant logs (with any tokens/secrets redacted)
- Your `LLM_PROVIDER` and how the app is run (local / Docker)

## Code of conduct

Be respectful and constructive. Treat other contributors the way you'd like to be treated.
