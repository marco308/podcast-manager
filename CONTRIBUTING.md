# Contributing

Thanks for your interest in improving Podcast Manager. This is a small self-hosted project — issues and pull requests are welcome. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

See the [README](README.md#local-development) for full local setup (Spotify app registration, HTTPS certs, env vars). In short:

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head

# Frontend
cd frontend
npm install
npm run dev
```

For the iOS app, see [ios/README.md](ios/README.md) for the XcodeGen workflow and the `Local.yml` signing overrides, and [ios/CLAUDE.md](ios/CLAUDE.md) for implementation notes.

## Before opening a PR

Run the same checks CI runs:

```bash
# Backend (from backend/)
ruff check app
ruff format --check app
pytest tests

# Frontend (from frontend/)
npm run lint
npm run format:check
npm run build
```

Keep PRs small and focused, and describe the behavior change (not just the diff). If you're adding a feature, an issue first is appreciated so we can agree on the approach.

## License of contributions

Podcast Manager is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). By submitting a contribution, you agree that it is your own work (or you have the right to submit it), that it is licensed under PolyForm Noncommercial 1.0.0 like the rest of the project, and that the project owner may also license your contribution under other terms (including commercial licences).
