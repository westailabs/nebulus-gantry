# Contributing

## Git workflow

- Branch off `develop`.
- Use conventional commits (`feat:`, `fix:`, `docs:`, `chore:`).
- Merge with `--no-ff`. Never commit straight to `main` or `develop`.
- Keep feature branches local until the maintainer approves a push or pull request.

## Checks

From the repository root:

```bash
python3 -m pytest backend/tests -v
cd frontend && npm test && npm run lint
# if pre-commit is installed:
bin/gantry validate
```

More context for coding agents is in `AGENTS.md`.
