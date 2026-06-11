# Developer Handoff Checklist

- [ ] Confirm `.env` exists locally.
- [ ] Confirm `.env` is ignored by Git.
- [ ] Confirm DATABASE_URL is available in password vault.
- [ ] Confirm ADMIN_API_TOKEN is available in password vault.
- [ ] Run `start-dev.ps1`.
- [ ] Test `/health`.
- [ ] Test `/settings` with Bearer token.
- [ ] Commit documentation only if no secrets are present.
