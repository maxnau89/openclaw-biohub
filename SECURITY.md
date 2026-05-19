# Security

## Reporting vulnerabilities

If you find a security issue in `openclaw-biohub`, please **do not**
open a public GitHub issue. Instead, use GitHub's private vulnerability
reporting (Security tab → "Report a vulnerability"), or email the
maintainer (address in the repo's GitHub profile).

You can expect:
- Acknowledgement within 5 working days.
- A coordinated disclosure timeline depending on severity, typically
  30–90 days.

## Threat model — what this project does and doesn't do

`openclaw-biohub` is intended to run **on a server you control**, against
data **about a single user (you)**. It is not designed to host multi-user
data or to be exposed unauthenticated on the public internet.

### What you should expect from this code

- All persistent data lives in two local SQLite files (`health.db`,
  `whoop_raw.db`) plus credential files under
  `$OPENCLAW_BIOHUB_HOME/secrets/`. No telemetry, no remote sync, no
  third-party analytics.
- The dashboard's API routes do not enforce authentication. They assume
  they are behind a reverse proxy (nginx, Caddy, …) that handles auth
  before requests reach the Next.js process.
- WHOOP OAuth tokens are stored on disk as plain JSON. They are
  refresh-token credentials and should be treated as secrets.

### What this project does not protect against

- An attacker who can read the files in `$OPENCLAW_BIOHUB_HOME` can read
  all of your health data and WHOOP OAuth tokens.
- An attacker who can reach the dashboard's API routes directly (without
  passing through your reverse proxy) can read all of your health data.
- The blood-panel parser (`pipeline/parse_blood_panel.py`) processes
  user-supplied PDFs/text. Treat input as untrusted; do not point it at
  files from sources you don't trust.

## Recommended hardening for self-hosters

If you're deploying this against real biometric data:

1. **Filesystem permissions.** Run the OAuth handler / sync scripts as a
   dedicated unprivileged user (the systemd unit ships as
   `User=openclaw-biohub`). Set `$OPENCLAW_BIOHUB_HOME` to mode `0750`
   and `secrets/` to `0700`, owned by that user.
2. **Full-disk encryption.** If the host can be physically accessed or
   lost (laptop, single-tenant VPS), use LUKS / FileVault / etc.
3. **Reverse proxy + auth.** Put the dashboard behind a proxy that
   requires authentication. Don't expose port 3000 (Next.js) or the
   OAuth handler's port 8893 directly.
4. **Backups.** If you back up `$OPENCLAW_BIOHUB_HOME`, encrypt the
   backups. The files contain your health history and live OAuth
   refresh tokens.
5. **Rotate the WHOOP client secret** if you ever check it into a
   non-private repo, paste it into a chat, or expose it in logs. The
   systemd unit ships templated specifically so this is easy to do.
6. **Don't run on a shared host** where other accounts can read your
   home directory.

## Cryptographic notes

- WHOOP webhook signatures are verified with HMAC-SHA256
  (`pipeline/adapters/whoop/webhook_handler.py`). If `WHOOP_CLIENT_SECRET` is
  unset, signature validation is **disabled** with a warning — don't
  run the webhook handler without the secret set in production.

## Out of scope

- Multi-user / multi-tenant deployments.
- Cloud-hosted "openclaw-biohub as a service" — the model is single-user
  self-hosted.
- Sharing data with healthcare providers, integrations with EHRs, or
  any other clinical workflow.
