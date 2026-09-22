## What changes and why

<!-- Describe the behaviour change, not just the diff. Link the issue with "Closes #123" if there is one. -->

## How it was tested

<!-- e.g. pytest tests, npm run build, ran the playlist update job locally, TestFlight build on device -->

## Checklist

- [ ] `ruff check app && ruff format --check app && pytest tests` pass (backend)
- [ ] `npm run lint && npm run format:check && npm run build` pass (frontend)
- [ ] New settings or env vars are documented in the README and `.env.example`
- [ ] Schema changes come with an Alembic migration
- [ ] I agree my contribution is licensed under AGPL-3.0 (see [CONTRIBUTING.md](../blob/main/CONTRIBUTING.md))
