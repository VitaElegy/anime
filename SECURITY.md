# Security Policy

## Supported Versions

The project is in active development. Only the latest commit on `master` is
supported with security fixes.

## Reporting a Vulnerability

Please **do not open a public issue** for security vulnerabilities. Instead,
report privately via one of:

- GitHub Security Advisory: https://github.com/VitaElegy/anime/security/advisories/new

Please include:

- Affected version / commit hash
- Steps to reproduce (as minimal as possible)
- Impact description
- Any suggested fix (optional)

You should receive an acknowledgement within 72 hours.

## Security Notes for Self-Hosting

- Never run in `ANIME_ENV=production` with the default qBittorrent password —
  the backend refuses to start in this state on purpose.
- Keep `ANIME_QB_PASSWORD` and any proxy credentials in `.env` (git-ignored).
- Put the app behind a reverse proxy with TLS before exposing it publicly.
