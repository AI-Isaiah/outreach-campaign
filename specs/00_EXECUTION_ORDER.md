# Spec Execution Order — Claude Code Handoff

**Date:** March 3, 2026
**Context:** These specs bring the outreach platform from ~75% to production-ready.
**Method:** Hand each spec to Claude Code as a session prompt, in order.

---

## Execution Sequence

| Order | Spec | Est. Time | Why This Order |
|-------|------|-----------|----------------|
| 1 | `01_PRODUCTION_HARDENING.md` | 2–3 hours | Fix critical bugs that affect all other work. Must be done first. |
| 2 | `02_SECURITY_AUTH.md` | 3–4 hours | Auth must exist before deploying anything publicly. |
| 3 | `03_API_HARDENING.md` | 2–3 hours | Rate limiting, validation, error handling — builds on auth. |
| 4 | `04_EMAIL_COMPLIANCE.md` | 2–3 hours | Fix email bugs before sending real campaigns. |
| 5 | `05_CRM.md` | 8–12 hours | Largest feature gap. Needs stable backend (specs 1–4). |
| 6 | `06_DEPLOYMENT.md` | 4–6 hours | Only deploy after everything above is solid. |

**Total estimated:** 21–31 hours of Claude Code work (across multiple sessions)

---

## How to Use These Specs

### For each spec:

1. Open a new Claude Code session
2. Paste the spec contents as your first message
3. Let Claude Code execute — it has exact file paths, code patterns, and acceptance criteria
4. Run `make test` after each spec to verify nothing broke
5. Commit the changes: `git add -A && git commit -m "spec-XX: <description>"`

### Important rules:

- **Do specs IN ORDER.** Spec 2 depends on Spec 1. Spec 5 depends on Specs 1–4.
- **Run tests between specs.** Each spec includes test requirements.
- **Don't skip the verification steps.** Each spec ends with a checklist.
- **If a spec fails mid-way**, fix the issue and continue — don't start over.

---

## Current Codebase State (for reference)

```
src/cli.py              → 1,103 lines, 24 commands
src/models/campaigns.py → 340 lines, all CRUD
src/models/database.py  → 31 lines (needs pooling)
src/web/app.py          → 55 lines (needs auth middleware)
src/web/routes/         → 12 route modules
src/services/           → 21 service modules
frontend/src/pages/     → 10 React pages
tests/                  → 24 test files, 13,443 LOC
migrations/pg/          → 4 SQL files
```

## Dependencies to Install (across all specs)

```bash
# Add to pyproject.toml dependencies:
pip install pyjwt>=2.8 --break-system-packages       # Spec 2 (auth)
pip install slowapi>=0.1 --break-system-packages      # Spec 3 (rate limiting)
```
