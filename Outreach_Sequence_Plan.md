# Interconnected Email + LinkedIn Outreach Sequence

**Campaign:** Metaworld Fund — Crypto Fund Allocator Outreach
**Audience:** Portfolio managers, CIOs, and allocators at crypto-focused funds ($50M–$5B+ AUM)
**Goal:** Book an introductory call to present the Metaworld Fund factsheet
**Channels:** Email (via Gmail Drafts) + LinkedIn (manual via Sales Navigator)

---

## Sequence Strategy

### Narrative Arc

The sequence tells a story of **credibility → differentiation → proof → graceful exit**:

1. **Warm entry** (LinkedIn) — Establish a human connection before hitting their inbox
2. **Credibility anchor** (Email) — Lead with numbers: 12 years live, every year positive
3. **Relationship building** (LinkedIn) — Deepen the connection with a relevant follow-up
4. **Value reinforcement** (Email) — Highlight regime resilience (2022, 2025 drawdowns)
5. **Social proof touch** (LinkedIn) — Share relevant insight or engage their content
6. **Final value prop** (Email) — Last email, door open, no pressure
7. **Soft close** (LinkedIn) — Gentle final touch for those who connected but didn't reply

### Why This Channel Alternation Works

Email-only sequences get lost in inbox noise. LinkedIn-only feels too informal for institutional allocators. Alternating creates the perception of **omnipresence without volume** — they see you in two places, which builds familiarity faster than either channel alone.

The sequence is designed so that LinkedIn warms the relationship and email delivers the substance. LinkedIn is where they see you're a real person; email is where they evaluate your fund.

---

## Sequence Overview

| Step | Day | Channel | Purpose | Subject / Action |
|------|-----|---------|---------|-----------------|
| 1 | 0 | LinkedIn | Open door | Connection request with note |
| 2 | 2 | Email | Establish credibility | Cold outreach — A/B tested |
| 3 | 5 | LinkedIn | Build relationship | Follow-up DM (if connected) or re-engage |
| 4 | 9 | Email | Reinforce value | Regime resilience proof point |
| 5 | 14 | LinkedIn | Add value | Share insight or engage their content |
| 6 | 18 | Email | Graceful close | Breakup — door open |
| 7 | 25 | LinkedIn | Final soft touch | Light closing message |

**Total touchpoints:** 4 LinkedIn + 3 Email = 7 over 25 days
**GDPR variant:** 4 LinkedIn + 2 Email = 6 over 25 days (skip Step 4 follow-up email)

---

## Sequence Flow Diagram

```
[Contact Enrolled] ──▶ Step 1: LinkedIn Connect (Day 0)
                           │
                     Connected?
                      │         │
                     Yes        No
                      │         │
                      ▼         ▼
               Step 2: Email Cold Outreach (Day 2)
                           │
                     Reply received?
                      │         │
                  Positive    No reply
                      │         │
                [EXIT ✅]       ▼
              Call booked   Step 3: LinkedIn DM (Day 5)
                              (if connected) / Profile visit (if not)
                                  │
                            Reply received?
                             │         │
                         Positive    No reply
                             │         │
                       [EXIT ✅]       ▼
                                  Step 4: Email Follow-up (Day 9)
                                  [GDPR: Skip → go to Step 5]
                                      │
                                Reply received?
                                 │         │
                             Positive    No reply / Negative
                                 │         │        │
                           [EXIT ✅]       ▼    [EXIT ❌]
                                      Step 5: LinkedIn Insight (Day 14)
                                          │
                                    Reply received?
                                     │         │
                                 Positive    No reply
                                     │         │
                               [EXIT ✅]       ▼
                                          Step 6: Email Breakup (Day 18)
                                              │
                                        Reply received?
                                         │         │
                                     Positive    No reply
                                         │         │
                                   [EXIT ✅]       ▼
                                              Step 7: LinkedIn Final Touch (Day 25)
                                                  │
                                            [EXIT: Sequence Complete]
                                            → auto-activate next contact
                                            → add to newsletter (non-GDPR)
```

---

## Full Email & Message Drafts

---

### Step 1 — LinkedIn Connection Request (Day 0)

**Channel:** LinkedIn
**Action:** Send connection request with note via Sales Navigator
**LinkedIn profile URL:** `{{linkedin_url}}` (open in new tab)
**Sales Navigator deep link:** `https://www.linkedin.com/sales/people/{{linkedin_url_slug}}`

**Connection Note (300 char limit):**

```
Hi {{first_name}}, I run Metaworld Fund — systematic momentum across crypto, gold & FX.
12 years live, every year positive. Would value connecting with {{company_name}}.
```

**Operator instructions:**
1. Open the LinkedIn profile URL in Sales Navigator
2. Click "Connect" and paste the note above
3. Mark as "Done" in the dashboard

---

### Step 2 — Cold Outreach Email (Day 2)

**Channel:** Email (→ Gmail Draft)
**Purpose:** Establish credibility with hard numbers

#### Variant A — Numbers-Led (Direct)

**Subject Line Options:**
1. `Quick introduction — Metaworld Fund`
2. `75.8% CAGR, every year positive since 2014`
3. `Systematic momentum across crypto, gold & FX`

**Preview Text:** `12 years live performance, daily liquidity, no lock-up`

**Body:**

```
Hi {{first_name}},

I run Metaworld Fund — a quantitative momentum strategy trading BTC, ETH, gold and FX.
We have been live since 2014 across FX and since 2020 in crypto, every single year positive.

A few numbers on our Standard Risk config: 75.8% CAGR, 1.37 Sharpe, max drawdown under 20%.
We also offer a capital-preservation variant at 36% CAGR with sub-10% drawdown for allocators
who prioritize stability.

The strategy runs 2,000+ sub-strategies fully automated — daily liquidity, no lock-up, SMA format.

Given the focus at {{company_name}}, happy to share the full factsheet and walk through the
methodology. Here is my calendar: {{calendly_url}}

Helmut
Founder, Metaworld Fund
```

**Primary CTA:** Book a call via Calendly link

#### Variant B — Context-Led (Consultative)

**Subject Line Options:**
1. `Systematic momentum — a different approach to crypto allocation`
2. `Diversification beyond crypto-native strategies`
3. `Metaworld Fund — 12 years of live performance`

**Preview Text:** `Not crypto-only: momentum across crypto, gold, and FX`

**Body:**

```
Hi {{first_name}},

I came across {{company_name}} while mapping allocators in digital assets, and wanted to
introduce what we are building at Metaworld Fund.

We run a systematic momentum strategy across crypto, gold and FX — not crypto-only, which gives
us diversification most quant crypto funds lack. The system trades 2,000+ sub-strategies fully
automated, exploiting volatility compression-expansion cycles across liquid markets.

We have 12 years of live performance across asset classes, every year positive. The strategy is
available in three risk configurations from 10% to 40% max drawdown, all via SMA with daily
liquidity and no lock-up.

Would be glad to share our factsheet and discuss whether it could complement what
{{company_name}} already has in place. Feel free to pick a time: {{calendly_url}}

Either way, I appreciate your time.

Helmut
Founder, Metaworld Fund
```

**Primary CTA:** Book a call via Calendly link

**A/B Test Plan:**
- Split: 50/50 by contact_id (deterministic, existing `ab_testing.py`)
- Measure: Reply rate and positive reply rate after 14 days
- Winner criteria: Higher positive reply rate with >20 sends per variant

---

### Step 3 — LinkedIn Follow-Up DM (Day 5)

**Channel:** LinkedIn
**Condition:** Send only if connection was accepted. If not connected, visit their profile (trigger "viewed your profile" notification) and skip to Step 4.

**Message (if connected):**

```
Hi {{first_name}},

Thanks for connecting. Wanted to share a bit more about what we do at Metaworld Fund.

We run a fully automated momentum strategy across BTC, ETH, gold and FX — 2,000+ sub-strategies
built from 12 years of live trading. Every single year positive across both FX (2014-2018) and
crypto (2020-2025).

Standard config: 75.8% CAGR, 1.37 Sharpe, sub-20% max drawdown. Also available in a capital-
preservation variant (36% CAGR, sub-10% DD) for more conservative mandates. SMA format, daily
liquidity, no lock-up.

Would be great to walk through the factsheet — happy to jump on a quick call if it could be
relevant for {{company_name}}: {{calendly_url}}

Helmut
```

**Operator instructions (if connected):**
1. Open LinkedIn conversation
2. Paste the message above
3. Mark as "Done"

**Operator instructions (if NOT connected):**
1. Visit their LinkedIn profile (creates a "viewed your profile" notification)
2. Mark as "Done — Not Connected" (system advances to Step 4)

---

### Step 4 — Follow-Up Email (Day 9)

**Channel:** Email (→ Gmail Draft)
**Purpose:** Reinforce value with regime resilience proof
**GDPR:** Skip this step for GDPR contacts (flag: `non_gdpr_only = 1`)

**Subject Line Options:**
1. `Following up — regime resilience data`
2. `Quick follow-up on Metaworld Fund`
3. `Positive returns in 2022 and 2025 drawdowns`

**Preview Text:** `Most crypto strategies struggled — we didn't`

**Body:**

```
Hi {{first_name}},

Wanted to follow up briefly. I know inboxes get busy.

One thing worth highlighting: our multimarket strategy delivered positive returns in both 2022
and the 2025 drawdown — periods where most crypto-native strategies struggled. That kind of
regime resilience is the core of what we do.

Happy to send over our factsheet or hop on a 15-minute call to walk through the numbers:
{{calendly_url}}

Helmut
Founder, Metaworld Fund
```

**Primary CTA:** 15-minute call via Calendly

---

### Step 5 — LinkedIn Value-Add Touch (Day 14)

**Channel:** LinkedIn
**Purpose:** Add value, stay visible, demonstrate thought leadership
**Condition:** If connected, send a relevant message. If not connected, skip.

**Message Option A — Share Insight:**

```
Hi {{first_name}}, came across some data on cross-asset momentum that reinforced our thesis —
volatility compression in gold and BTC tends to lead breakouts within 45 days. Happy to share
the full analysis if you're interested.
```

**Message Option B — Engage Their Content:**
(Operator should check if the contact recently posted on LinkedIn and like/comment on their post instead of sending a DM. If no recent content, use Option A.)

**Operator instructions:**
1. Check contact's recent LinkedIn activity
2. If they posted recently: like and leave a thoughtful comment. Mark as "Done — Engaged Content"
3. If no recent activity: send Message Option A. Mark as "Done — Sent Insight"

---

### Step 6 — Breakup Email (Day 18)

**Channel:** Email (→ Gmail Draft)
**Purpose:** Final email, no pressure, leave door open

**Subject Line Options:**
1. `Last note from me`
2. `Closing the loop`
3. `Not the right time?`

**Preview Text:** `Happy to reconnect whenever the timing is right`

**Body:**

```
Hi {{first_name}},

I have reached out a couple of times and have not heard back — no worries, I understand the
timing may not be right.

If {{company_name}} ever explores systematic strategies that trade across crypto, gold and FX
with uncorrelated returns, I would be happy to reconnect. We will keep compounding in the
meantime.

Calendar is always open: {{calendly_url}}

All the best to you and the team.

Helmut
Founder, Metaworld Fund
```

**Primary CTA:** Calendly link (soft)

---

### Step 7 — LinkedIn Final Soft Touch (Day 25)

**Channel:** LinkedIn
**Condition:** Only if connected. If not connected, skip entirely.
**Purpose:** Gentle close, keep relationship warm

**Message:**

```
{{first_name}}, just wanted to say — no pressure on the fund side. Always happy to stay
connected and share market observations when something interesting comes up. Wishing you
and the {{company_name}} team a great quarter.
```

**Operator instructions:**
1. Only send if connected on LinkedIn
2. Paste message, send
3. Mark as "Done"
4. Sequence complete — system auto-transitions to `no_response` or `completed`

---

## Branching Logic Summary

| Condition | Action |
|---|---|
| **Positive reply** (any channel, any step) | EXIT → mark `replied_positive` → log `call_booked` if applicable |
| **Negative reply** (any channel, any step) | EXIT → mark `replied_negative` → auto-activate next contact at company |
| **Call booked** (any channel, any step) | EXIT → mark `replied_positive` + log `call_booked` event |
| **Unsubscribe request** | EXIT → mark `unsubscribed` → remove from all active sequences |
| **Email bounced** | Mark `bounced` → auto-activate next contact → skip remaining email steps |
| **LinkedIn not connected** (Step 3, 5, 7) | Skip LinkedIn DM → advance to next step |
| **GDPR contact** (Step 4) | Skip follow-up email → advance to Step 5 |
| **Sequence complete** (after Step 7) | Mark `no_response` → auto-activate next contact → add to newsletter (non-GDPR only) |

---

## Exit Conditions

- **Conversion:** Contact replies positively or books a call → removed from sequence
- **Explicit rejection:** Contact replies negatively → removed from sequence
- **Unsubscribe:** Contact requests unsubscribe → removed from all sequences
- **Bounce:** Email bounces → removed, next contact activated
- **Sequence complete:** All 7 steps done with no reply → marked as no_response

## Re-Entry Rules

- A contact who completed a sequence with `no_response` may be re-enrolled in a new campaign (e.g., Q2_2026) after a **90-day cooling period**
- A contact who replied negatively should **not** be re-enrolled unless they reach out proactively
- Unsubscribed contacts are **never** re-enrolled

## Suppression Rules

- Do not send email to contacts with `email_status != 'valid'`
- Do not send email to `unsubscribed = 1` contacts
- Do not exceed 2 emails for GDPR contacts (3 for non-GDPR)
- Do not action contacts whose company already has an active contact in the sequence (one-per-company rule)

---

## Performance Benchmarks (B2B Financial Services Cold Outreach)

| Metric | Target | Good | Excellent |
|--------|--------|------|-----------|
| LinkedIn connection acceptance rate | 25-35% | 35-45% | >45% |
| Email open rate | 35-50% | 50-60% | >60% |
| Overall reply rate (any channel) | 5-10% | 10-15% | >15% |
| Positive reply rate | 2-5% | 5-8% | >8% |
| Call booking rate (of total enrolled) | 1-3% | 3-5% | >5% |
| Unsubscribe rate | <1% | <0.5% | <0.3% |

---

## A/B Test Recommendations

### Test 1: Email Subject Line (Step 2)
- **Variant A:** Numbers-first (`75.8% CAGR, every year positive since 2014`)
- **Variant B:** Context-first (`Systematic momentum — a different approach`)
- **Measure:** Open rate + reply rate
- **Sample:** 50 contacts per variant minimum

### Test 2: Email Opening (Step 2)
- **Variant A:** Lead with fund description ("I run Metaworld Fund")
- **Variant B:** Lead with contact context ("I came across {{company_name}}")
- **Measure:** Positive reply rate
- **Sample:** Run after Test 1 winner is identified

### Test 3: LinkedIn Connection Note Length
- **Variant A:** Full note (current — ~280 chars)
- **Variant B:** Short note ("Hi {{first_name}}, would love to connect — I run a systematic fund across crypto & gold with 12 years of live returns.")
- **Measure:** Connection acceptance rate
- **Sample:** 40 contacts per variant

---

## Metrics to Track

**Per-step metrics:**
- Emails: draft created, draft sent (via Gmail), reply received, reply type
- LinkedIn: connection sent, connection accepted, message sent, reply received

**Sequence-level metrics:**
- Enrolled → completed funnel conversion
- Average steps to first reply
- Channel that generated the reply (email vs LinkedIn)
- Time from enrollment to call booked

**Iteration metrics:**
- A/B variant performance comparison (weekly)
- Firm-type response heatmap
- AUM-tier response rates

**Review cadence:** Weekly for the first month, then bi-weekly.

---

## Template Files for Implementation

These should be created/updated in `src/templates/`:

```
src/templates/
├── email/
│   ├── cold_outreach_v1_a.txt    ✅ EXISTS — matches Variant A above
│   ├── cold_outreach_v1_b.txt    ✅ EXISTS — matches Variant B above
│   ├── follow_up_v1.txt          ✅ EXISTS — matches Step 4 above
│   ├── breakup_v1.txt            ✅ EXISTS — matches Step 6 above
│   └── (future A/B variants)
└── linkedin/
    ├── connect_note_v1.txt       ✅ EXISTS — matches Step 1 above
    ├── message_v1.txt            ✅ EXISTS — matches Step 3 above
    ├── insight_v1.txt            🆕 CREATE — Step 5 insight message
    └── final_touch_v1.txt        🆕 CREATE — Step 7 closing message
```

---

## Sequence Setup in Database

To implement this sequence in the existing schema, run these sequence steps for a new campaign:

```sql
-- Campaign: Q2_2026_multichannel (example)
-- Step 1: LinkedIn connect (Day 0)
INSERT INTO sequence_steps (campaign_id, step_order, channel, template_id, delay_days)
VALUES (?, 1, 'linkedin_connect', ?, 0);

-- Step 2: Cold email (Day 2)
INSERT INTO sequence_steps (campaign_id, step_order, channel, template_id, delay_days)
VALUES (?, 2, 'email', ?, 2);

-- Step 3: LinkedIn message (Day 5)
INSERT INTO sequence_steps (campaign_id, step_order, channel, template_id, delay_days)
VALUES (?, 3, 'linkedin_message', ?, 3);

-- Step 4: Follow-up email (Day 9, non-GDPR only)
INSERT INTO sequence_steps (campaign_id, step_order, channel, template_id, delay_days, non_gdpr_only)
VALUES (?, 4, 'email', ?, 4, 1);

-- Step 5: LinkedIn insight (Day 14)
INSERT INTO sequence_steps (campaign_id, step_order, channel, template_id, delay_days)
VALUES (?, 5, 'linkedin_message', ?, 5);

-- Step 6: Breakup email (Day 18)
INSERT INTO sequence_steps (campaign_id, step_order, channel, template_id, delay_days)
VALUES (?, 6, 'email', ?, 4);

-- Step 7: LinkedIn final touch (Day 25)
INSERT INTO sequence_steps (campaign_id, step_order, channel, template_id, delay_days)
VALUES (?, 7, 'linkedin_message', ?, 7);
```

This maps directly to the existing `sequence_steps` schema with no modifications needed.
