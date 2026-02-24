# Weekly Operational Playbook

## Monday: Weekly Planning Session

```bash
# Review last week's results + plan this week
python3 -m src.cli weekly-plan Q1_2026_initial

# Review the plan, decide:
# - How many new contacts to enroll?
# - Which templates to use (A vs B)?
# - Send newsletter this week?
```

## Daily (~10 minutes)

```bash
# 1. See today's actions
python3 -m src.cli queue Q1_2026_initial --limit 10

# 2. Export LinkedIn actions for Expandi
python3 -m src.cli export-expandi Q1_2026_initial
# Upload data/exports/expandi_YYYY-MM-DD.csv to Expandi (~2 min)

# 3. Preview today's emails
python3 -m src.cli send Q1_2026_initial --dry-run

# 4. Send today's emails (will ask for confirmation)
python3 -m src.cli send Q1_2026_initial
```

## As Replies Come In

```bash
# Positive reply (wants more info)
python3 -m src.cli status reply john@fund.com positive

# Booked a call via Calendly
python3 -m src.cli status reply john@fund.com call-booked

# Not interested
python3 -m src.cli status reply john@fund.com negative

# Mark as no response (after all steps exhausted)
python3 -m src.cli status reply john@fund.com no-response
```

## Friday: Sync Expandi Results

```bash
# Import results from Expandi
python3 -m src.cli import-expandi data/exports/expandi_results.csv Q1_2026_initial
```

## Monthly: Newsletter

```bash
# 1. Auto-subscribe eligible non-responders
python3 -m src.cli newsletter-subscribers auto-subscribe --campaign Q1_2026_initial

# 2. Check subscriber list
python3 -m src.cli newsletter-subscribers list

# 3. Write newsletter in data/newsletters/YYYY-MM-DD-topic.md

# 4. Preview
python3 -m src.cli newsletter-preview data/newsletters/2026-03-01-march-update.md

# 5. Send (will ask for confirmation)
python3 -m src.cli newsletter-send data/newsletters/2026-03-01-march-update.md
```

## First-Time Setup

```bash
# 1. Install dependencies
make install

# 2. Copy config
cp config.yaml.example config.yaml
# Edit config.yaml with your SMTP settings, physical address

# 3. Create .env
cp .env.example .env
# Add: SMTP_PASSWORD, EMAIL_VERIFY_API_KEY

# 4. Import data
make import

# 5. Verify emails (~$24 for 3,000 emails via ZeroBounce)
make verify

# 6. Create campaign
python3 -m src.cli create-campaign-cmd Q1_2026_initial --description "Q1 2026 initial outreach"

# 7. Set up sequence (standard 5-step or --gdpr for 4-step)
python3 -m src.cli setup-sequence Q1_2026_initial

# 8. Enroll first batch (start small, maybe 20-50)
python3 -m src.cli enroll Q1_2026_initial --limit 50

# 9. Check the queue
make queue

# 10. Start daily workflow
```

## Key Commands Reference

| Command | What It Does |
|---------|-------------|
| `stats` | Database overview |
| `queue <campaign>` | Today's actions |
| `send <campaign>` | Send today's emails |
| `send <campaign> --dry-run` | Preview without sending |
| `status reply <email> <outcome>` | Log a reply |
| `weekly-plan <campaign>` | Weekly check-in |
| `report <campaign>` | Full dashboard |
| `export-expandi <campaign>` | LinkedIn CSV for Expandi |
| `import-expandi <file> <campaign>` | Sync Expandi results |
| `enroll <campaign> --limit N` | Enroll more contacts |
| `newsletter-subscribers list` | Show subscribers |
| `newsletter-send <file>` | Send newsletter |
| `unsubscribe <email>` | Process unsubscribe |

## Outreach Sequence

**Standard (non-GDPR) - 5 steps:**

| Step | Channel | Timing |
|------|---------|--------|
| 1 | LinkedIn connect | Day 0 |
| 2 | LinkedIn message | +3 days after acceptance |
| 3 | Cold email | +5 days if no LI response |
| 4 | Follow-up email | +7 days |
| 5 | Break-up email | +14 days |

**GDPR (EU/UK) - 3 steps:**

| Step | Channel | Timing |
|------|---------|--------|
| 1 | LinkedIn connect | Day 0 |
| 2 | LinkedIn message | +3 days after acceptance |
| 3 | Cold email | +5 days if no LI response |

Max 2 emails for GDPR contacts. Focus on LinkedIn.
