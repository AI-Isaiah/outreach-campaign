---
name: fund-outreach-sequence
description: Generate institutional-grade investor outreach sequences for fund marketing. Use this skill whenever the user mentions outreach, investor sequences, LP outreach, fundraising emails, LinkedIn prospecting, cold outreach to allocators, capital introduction, investor drip campaigns, or wants to create a series of messages targeting institutional investors, family offices, or HNWI allocators. Also trigger when the user provides fund data (CAGR, Sharpe, drawdown, strategy description) and wants to turn it into outreach content.
---

# Fund Outreach Sequence Generator

Generate 3, 5, or 7 message investor outreach sequences that sound like a senior Goldman Sachs Private Wealth Manager — not a crypto bro, not a cold email spammer.

## Voice & Tone

The voice is **institutional credibility meets intellectual curiosity**. Think: a partner at a top-tier fund admin writing to a CIO they respect.

### DO
- Lead with insight, not pitch
- Reference specific metrics naturally (not dumped in a list)
- Use precise financial language: "positively skewed return profile", "deterministic execution", "volatility compression"
- Create genuine intellectual hooks — make the reader think
- Build a narrative arc across the sequence — each message advances the conversation
- Close with soft, confident CTAs — never desperate
- Keep LinkedIn messages under 300 chars for connection requests, under 600 for InMail/follow-ups
- Keep emails concise: 4-8 sentences max for body, clear subject lines

### DON'T
- Use "exciting opportunity", "revolutionary", "game-changing", "unique alpha"
- Sound like a pitch deck being read aloud
- Use exclamation marks (one per entire sequence maximum)
- Reference "to the moon", emojis, or retail crypto language
- Over-explain the strategy in a single message — distribute across the arc
- Use "I hope this email finds you well" or any greeting cliché
- Stack multiple questions in one message

## Sequence Architecture

### Message Arc Design

Each sequence follows a **narrative funnel**:

| Phase | Purpose | Channel preference |
|-------|---------|-------------------|
| **Hook** (Msg 1) | Establish credibility + one compelling data point | LinkedIn |
| **Depth** (Msg 2-3) | Expand on edge — what makes this different | Alternate LinkedIn/Email |
| **Proof** (Msg 3-5) | Risk-adjusted metrics, structural advantage | Email preferred |
| **Close** (Msg 5-7) | Direct ask, time-bound if appropriate | Email |

### Cadence

- **3-message sequence**: Day 0, Day 3, Day 7
- **5-message sequence**: Day 0, Day 3, Day 5, Day 10, Day 17
- **7-message sequence**: Day 0, Day 3, Day 5, Day 7, Day 10, Day 14, Day 21

Alternate between LinkedIn and Email. Start on LinkedIn. Never send two emails in a row unless the sequence is email-only.

### Channel-Specific Rules

**LinkedIn (connection request / DM)**
- Connection request: Max 300 characters. One hook. One metric. One question or CTA.
- Follow-up DM: Max 600 characters. Expand on one specific angle.
- No subject lines. No signatures.
- Reference something from their profile if {{company_name}} or {{title}} suggests relevance.

**Email**
- Always include a subject line.
- Subject lines: 4-8 words max. No clickbait. Lowercase-start is acceptable for a casual-professional tone.
- Body: 4-8 sentences. One core idea per email.
- Sign off with first name only, no title block in the sequence (they can look you up).

## Input Requirements

The user MUST provide:
1. **Fund/strategy description** — what it trades, how it trades
2. **Key metrics** — at minimum: CAGR, Sharpe, Max Drawdown. Ideal: also Calmar, Sortino, win rate, longest drawdown

The user MAY provide:
- Target audience (allocators, family offices, fund of funds, etc.)
- Specific angle or emphasis (risk management, uncorrelated returns, etc.)
- Number of messages (3, 5, or 7 — default to 5)
- Channel preference (LinkedIn-only, email-only, or mixed — default to mixed)
- Variable placeholders to include: {{first_name}}, {{company_name}}, {{title}}

If the user doesn't specify the number of messages, ask. If they don't specify a target audience, default to "institutional allocators and family offices looking at alternative strategies."

## Strategy-to-Angle Extraction

Before writing, extract the **top 3 selling angles** from the fund data. Rank by distinctiveness — what would make a CIO stop scrolling?

Common angle categories for quantitative crypto/multi-asset funds:
- **Positive skew** — rare in crypto; most strategies have negative skew (many small wins, catastrophic losses). If this fund has positive skew, lead with it.
- **Drawdown discipline** — if max DD is under 25% in crypto, that's exceptional. Highlight vs. buy-and-hold.
- **Sharpe/Calmar quality** — Sharpe >1.5 or Calmar >3 is institutional-grade. Frame relative to traditional alternatives.
- **Uncorrelated returns** — if the strategy has low beta to BTC or traditional markets, this is the institutional pitch.
- **Structural edge** — volatility compression, mean-reversion of vol itself, Bollinger mechanics, etc. Frame as exploiting a market microstructure feature.
- **Win rate paradox** — if the fund has a low win rate but high CAGR, the pyramiding/position-sizing story is compelling and counterintuitive.

## Output Format

Output as a structured sequence. For each message:

```
### Step [N] · Day [X] · [LinkedIn/Email]

**Subject:** [email only]

[Message body]

---
```

After the full sequence, add a **Sequence Notes** section:
- Which angles were used and why
- Suggested personalization points per message (what to customize per recipient)
- One alternative opening for A/B testing on message 1

## Example Angle Extraction

Given:
- CAGR 87.3%, Sharpe 1.74, Calmar 4.59, Max DD 19%, Longest DD 111 days
- Momentum strategy across FX, Commodities, Digital Assets
- Bollinger Band squeeze entry, aggressive pyramiding

**Extracted angles (ranked):**
1. **Positive skew + low win rate paradox** — "Most crypto strategies blow up on the downside. Ours flips the distribution: modest win rate, outsized gains, capped losses."
2. **Drawdown discipline** — "19% max drawdown in a market where 60%+ drawdowns are normal. The Calmar of 4.59 tells the story."
3. **Volatility compression edge** — "We don't predict direction. We wait for vol to compress, then ride the expansion. It's a structural feature of markets, not a forecast."

## Personalization Variables

Always include these as placeholders — the outreach tool will merge them:
- `{{first_name}}` — recipient first name
- `{{company_name}}` — recipient company
- `{{title}}` — recipient title
- `{{calendly_url}}` — sender's meeting booking link (use in CTAs when suggesting a call)

Use `{{first_name}}` in message 1 (LinkedIn) only if it's a connection request. In emails, use it in the greeting.

Include `{{calendly_url}}` in at least one email CTA (typically the final email or the first email with a meeting ask). Format: "Book a time: {{calendly_url}}" or weave naturally into the CTA.

## Signature Rules

- Do NOT sign emails with the recipient's name or any assumed sender name.
- Do NOT add a signature block. The outreach tool appends the sender's signature automatically.
- End email messages with the CTA only — no "Best," no "Regards," no name.
- For LinkedIn messages: never sign off. Just end with the message.

## Quality Checklist (self-verify before output)

Before presenting the sequence, verify:
- [ ] No two consecutive messages use the same channel
- [ ] Message 1 contains exactly ONE metric, not a data dump
- [ ] No message contains more than two questions
- [ ] Subject lines are under 8 words
- [ ] LinkedIn messages respect character limits (300 / 600)
- [ ] Each message introduces a NEW angle or deepens a prior one — no repetition
- [ ] The sequence builds — a reader who saw all messages would have a complete picture
- [ ] No clichés from the DON'T list appear anywhere
- [ ] CTA in final message is specific (e.g., "15-minute call next week" not "let's connect sometime")
- [ ] Tone is peer-to-peer, not salesperson-to-prospect
