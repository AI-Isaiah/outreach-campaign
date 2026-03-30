"""Response analysis for the adaptive outreach engine.

Computes performance metrics per template, channel, AUM segment, and timing
to inform the contact scorer and template selector.
"""

from __future__ import annotations

from src.models.database import get_cursor


def get_template_performance(conn, campaign_id: int, *, user_id: int | None = None) -> list[dict]:
    """Positive rate per template with confidence levels.

    Confidence: low (<20 sends), medium (20-50), high (50+).
    Campaign ownership provides tenant isolation via FK.
    """
    with get_cursor(conn) as cursor:
        cursor.execute(
            """
            SELECT
                cth.template_id,
                t.name AS template_name,
                t.channel,
                COUNT(*) AS total_sends,
                SUM(CASE WHEN cth.outcome = 'positive' THEN 1 ELSE 0 END) AS positive,
                SUM(CASE WHEN cth.outcome = 'negative' THEN 1 ELSE 0 END) AS negative,
                SUM(CASE WHEN cth.outcome IS NULL THEN 1 ELSE 0 END) AS pending
            FROM contact_template_history cth
            JOIN templates t ON t.id = cth.template_id
            WHERE cth.campaign_id = %s
            GROUP BY cth.template_id, t.name, t.channel
            ORDER BY total_sends DESC
            """,
            (campaign_id,),
        )
        rows = cursor.fetchall()

        results = []
        for row in rows:
            total = row["total_sends"]
            positive = row["positive"]
            resolved = positive + row["negative"]
            positive_rate = positive / resolved if resolved > 0 else 0.0

            if total < 20:
                confidence = "low"
            elif total < 50:
                confidence = "medium"
            else:
                confidence = "high"

            results.append({
                "template_id": row["template_id"],
                "template_name": row["template_name"],
                "channel": row["channel"],
                "total_sends": total,
                "positive": positive,
                "negative": row["negative"],
                "pending": row["pending"],
                "positive_rate": round(positive_rate, 4),
                "confidence": confidence,
            })

        return results


def annotate_is_winning(results: list[dict], min_sends: int = 5) -> list[dict]:
    """Annotate each template result with ``is_winning`` flag.

    The template with the highest ``positive_rate`` among those with
    ``total_sends >= min_sends`` gets ``is_winning=True``.
    Tiebreaker: highest ``total_sends``.
    """
    best_id = None
    best_rate = -1.0
    best_sends = -1
    for r in results:
        if r["total_sends"] >= min_sends:
            rate = r["positive_rate"]
            sends = r["total_sends"]
            if rate > best_rate or (rate == best_rate and sends > best_sends):
                best_rate = rate
                best_sends = sends
                best_id = r["template_id"]
    for r in results:
        r["is_winning"] = r["template_id"] == best_id and best_id is not None
    return results


def get_channel_performance(conn, campaign_id: int, *, user_id: int) -> list[dict]:
    """Positive rate per channel (email, linkedin_*)."""
    with get_cursor(conn) as cursor:
        cursor.execute(
            """
            SELECT
                cth.channel,
                COUNT(*) AS total_sends,
                SUM(CASE WHEN cth.outcome = 'positive' THEN 1 ELSE 0 END) AS positive,
                SUM(CASE WHEN cth.outcome = 'negative' THEN 1 ELSE 0 END) AS negative
            FROM contact_template_history cth
            JOIN campaigns cam ON cam.id = cth.campaign_id
            WHERE cth.campaign_id = %s AND cam.user_id = %s
            GROUP BY cth.channel
            """,
            (campaign_id, user_id),
        )
        rows = cursor.fetchall()

        results = []
        for row in rows:
            resolved = row["positive"] + row["negative"]
            positive_rate = row["positive"] / resolved if resolved > 0 else 0.0
            results.append({
                "channel": row["channel"],
                "total_sends": row["total_sends"],
                "positive": row["positive"],
                "negative": row["negative"],
                "positive_rate": round(positive_rate, 4),
            })

        return results


def get_segment_performance(conn, campaign_id: int, *, user_id: int) -> list[dict]:
    """Reply rate by AUM tier: $0-100M, $100M-500M, $500M-1B, $1B+."""
    with get_cursor(conn) as cursor:
        cursor.execute(
            """
            SELECT
                CASE
                    WHEN comp.aum_millions IS NULL THEN 'Unknown'
                    WHEN comp.aum_millions < 100 THEN '$0-100M'
                    WHEN comp.aum_millions < 500 THEN '$100M-500M'
                    WHEN comp.aum_millions < 1000 THEN '$500M-1B'
                    ELSE '$1B+'
                END AS aum_tier,
                COUNT(*) AS total,
                SUM(CASE WHEN ccs.status = 'replied_positive' THEN 1 ELSE 0 END) AS positive,
                SUM(CASE WHEN ccs.status = 'replied_negative' THEN 1 ELSE 0 END) AS negative,
                SUM(CASE WHEN ccs.status NOT IN ('queued') THEN 1 ELSE 0 END) AS contacted
            FROM contact_campaign_status ccs
            JOIN contacts c ON c.id = ccs.contact_id
            LEFT JOIN companies comp ON comp.id = c.company_id
            WHERE ccs.campaign_id = %s AND c.user_id = %s
            GROUP BY aum_tier
            ORDER BY aum_tier
            """,
            (campaign_id, user_id),
        )
        rows = cursor.fetchall()

        results = []
        for row in rows:
            contacted = row["contacted"]
            positive = row["positive"]
            reply_rate = (positive + row["negative"]) / contacted if contacted > 0 else 0.0
            results.append({
                "aum_tier": row["aum_tier"],
                "total": row["total"],
                "contacted": contacted,
                "positive": positive,
                "negative": row["negative"],
                "reply_rate": round(reply_rate, 4),
            })

        return results


def get_timing_performance(conn, campaign_id: int) -> list[dict]:
    """Reply rate by inter-touch delay (days between events)."""
    with get_cursor(conn) as cursor:
        # Compute average delay between events per contact, then bucket
        cursor.execute(
            """
            WITH event_pairs AS (
                SELECT
                    e1.contact_id,
                    e1.created_at AS first_event,
                    e2.created_at AS second_event
                FROM events e1
                JOIN events e2 ON e1.contact_id = e2.contact_id
                    AND e1.campaign_id = e2.campaign_id
                    AND e2.created_at > e1.created_at
                    AND e1.event_type IN ('email_sent', 'linkedin_connect_done', 'linkedin_message_done')
                    AND e2.event_type IN ('email_sent', 'linkedin_connect_done', 'linkedin_message_done',
                                           'status_replied_positive', 'status_replied_negative')
                WHERE e1.campaign_id = %s
            ),
            delays AS (
                SELECT
                    contact_id,
                    EXTRACT(EPOCH FROM (second_event::timestamp - first_event::timestamp)) / 86400 AS delay_days
                FROM event_pairs
            ),
            bucketed AS (
                SELECT
                    contact_id,
                    AVG(delay_days) AS avg_delay,
                    CASE
                        WHEN AVG(delay_days) < 3 THEN '0-3 days'
                        WHEN AVG(delay_days) < 7 THEN '3-7 days'
                        WHEN AVG(delay_days) < 14 THEN '7-14 days'
                        ELSE '14+ days'
                    END AS delay_bucket
                FROM delays
                GROUP BY contact_id
            )
            SELECT
                b.delay_bucket,
                COUNT(*) AS total,
                SUM(CASE WHEN ccs.status = 'replied_positive' THEN 1 ELSE 0 END) AS positive,
                SUM(CASE WHEN ccs.status IN ('replied_positive', 'replied_negative') THEN 1 ELSE 0 END) AS replied
            FROM bucketed b
            JOIN contact_campaign_status ccs ON ccs.contact_id = b.contact_id AND ccs.campaign_id = %s
            GROUP BY b.delay_bucket
            ORDER BY b.delay_bucket
            """,
            (campaign_id, campaign_id),
        )
        rows = cursor.fetchall()

        results = []
        for row in rows:
            total = row["total"]
            reply_rate = row["replied"] / total if total > 0 else 0.0
            results.append({
                "delay_bucket": row["delay_bucket"],
                "total": total,
                "positive": row["positive"],
                "replied": row["replied"],
                "reply_rate": round(reply_rate, 4),
            })

        return results
