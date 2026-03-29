"""CRM API routes — contacts, companies, timeline, search."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.constants import CRM_SEARCH_LIMIT
from src.web.dependencies import get_current_user, get_db
from src.web.query_builder import QueryBuilder
from src.models.database import get_cursor

router = APIRouter(prefix="/crm", tags=["crm"])


_CRM_SORT_ALLOWLIST = {"full_name", "email", "aum_millions", "lifecycle_stage", "created_at"}


@router.get("/contacts")
def list_crm_contacts(
    search: Optional[str] = None,
    status: Optional[str] = None,
    company_type: Optional[str] = None,
    min_aum: Optional[float] = None,
    max_aum: Optional[float] = None,
    tag: Optional[str] = None,
    lifecycle_stage: Optional[str] = None,
    newsletter_subscriber: Optional[bool] = None,
    product_id: Optional[int] = None,
    sort_by: Optional[str] = Query(default=None),
    sort_dir: Optional[str] = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Searchable, filterable contact list for CRM view."""
    offset = (page - 1) * per_page
    qb = QueryBuilder()

    qb.add_condition("co.user_id = %s", user["id"])

    if search:
        like = f"%{search}%"
        qb.add_condition(
            "(c.full_name ILIKE %s OR c.email ILIKE %s OR co.name ILIKE %s)",
            like, like, like,
        )

    if status:
        qb.add_condition("ccs.status = %s", status)

    if company_type:
        qb.add_condition("co.firm_type = %s", company_type)

    if min_aum is not None:
        qb.add_condition("co.aum_millions >= %s", min_aum)

    if max_aum is not None:
        qb.add_condition("co.aum_millions <= %s", max_aum)

    if tag:
        qb.add_join(
            "JOIN entity_tags et ON et.entity_type = 'contact' AND et.entity_id = c.id "
            "JOIN tags tg ON tg.id = et.tag_id"
        )
        qb.add_condition("tg.name = %s", tag)

    if lifecycle_stage:
        qb.add_condition("c.lifecycle_stage = %s", lifecycle_stage)

    if newsletter_subscriber is not None:
        if newsletter_subscriber:
            qb.add_condition("c.newsletter_status = 'subscribed'")
        else:
            qb.add_condition("(c.newsletter_status IS NULL OR c.newsletter_status != 'subscribed')")

    if product_id is not None:
        qb.add_join(
            "JOIN contact_products cprod ON cprod.contact_id = c.id"
        )
        qb.add_condition("cprod.product_id = %s", product_id)

    where = qb.where_clause

    # Use INNER JOIN when filtering by status, LEFT JOIN otherwise
    ccs_join = (
        "JOIN contact_campaign_status ccs ON ccs.contact_id = c.id"
        if status
        else "LEFT JOIN contact_campaign_status ccs ON ccs.contact_id = c.id"
    )

    joins = qb.join_clause

    # Build ORDER BY clause
    if sort_by and sort_by in _CRM_SORT_ALLOWLIST:
        direction = "ASC" if sort_dir and sort_dir.lower() == "asc" else "DESC"
        # Map column names to qualified references
        sort_col_map = {
            "full_name": "c.full_name",
            "email": "c.email",
            "aum_millions": "co.aum_millions",
            "lifecycle_stage": "c.lifecycle_stage",
            "created_at": "c.created_at",
        }
        order_clause = f"ORDER BY {sort_col_map[sort_by]} {direction} NULLS LAST"
    else:
        order_clause = "ORDER BY co.aum_millions DESC NULLS LAST"

    query = f"""
        SELECT DISTINCT c.*, co.name AS company_name, co.aum_millions, co.firm_type,
               ccs.status AS campaign_status, ccs.current_step
        FROM contacts c
        LEFT JOIN companies co ON co.id = c.company_id
        {ccs_join}
        {joins}
        {where}
        {order_clause}
        LIMIT %s OFFSET %s
    """
    params = qb.params + [per_page, offset]

    with get_cursor(conn) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

        # Count query
        count_query = f"""
            SELECT COUNT(DISTINCT c.id) AS cnt
            FROM contacts c
            LEFT JOIN companies co ON co.id = c.company_id
            {ccs_join}
            {joins}
            {where}
        """
        cur.execute(count_query, qb.params)
        total = cur.fetchone()["cnt"]

        return {
            "contacts": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        }


@router.get("/contacts/{contact_id}/timeline")
def get_contact_timeline(
    contact_id: int,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get unified interaction timeline for a contact."""
    with get_cursor(conn) as cur:
        # Verify contact exists and belongs to user
        cur.execute(
            """SELECT c.id FROM contacts c
               JOIN companies co ON co.id = c.company_id
               WHERE c.id = %s AND co.user_id = %s""",
            (contact_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Contact {contact_id} not found")

        offset = (page - 1) * per_page
        cur.execute(
            """SELECT * FROM interaction_timeline_view
               WHERE contact_id = %s
               ORDER BY occurred_at DESC
               LIMIT %s OFFSET %s""",
            (contact_id, per_page, offset),
        )
        rows = cur.fetchall()

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM interaction_timeline_view WHERE contact_id = %s",
            (contact_id,),
        )
        total = cur.fetchone()["cnt"]

        return {
            "entries": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        }


@router.get("/companies")
def list_companies(
    search: Optional[str] = None,
    firm_type: Optional[str] = None,
    tag: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Company list with aggregated contact stats."""
    offset = (page - 1) * per_page
    qb = QueryBuilder()

    qb.add_condition("co.user_id = %s", user["id"])

    if search:
        qb.add_condition("co.name ILIKE %s", f"%{search}%")

    if firm_type:
        qb.add_condition("co.firm_type = %s", firm_type)

    if tag:
        qb.add_join(
            "JOIN entity_tags et ON et.entity_type = 'company' AND et.entity_id = co.id "
            "JOIN tags tg ON tg.id = et.tag_id"
        )
        qb.add_condition("tg.name = %s", tag)

    where = qb.where_clause
    joins = qb.join_clause

    query = f"""
        SELECT co.*,
               COUNT(c.id) AS contact_count,
               COUNT(CASE WHEN ccs.status IS NOT NULL THEN 1 END) AS enrolled_count,
               COUNT(CASE WHEN ccs.status = 'replied_positive' THEN 1 END) AS positive_replies
        FROM companies co
        LEFT JOIN contacts c ON c.company_id = co.id
        LEFT JOIN contact_campaign_status ccs ON ccs.contact_id = c.id
        {joins}
        {where}
        GROUP BY co.id
        ORDER BY co.aum_millions DESC NULLS LAST
        LIMIT %s OFFSET %s
    """
    params = qb.params + [per_page, offset]

    with get_cursor(conn) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

        count_query = f"""
            SELECT COUNT(DISTINCT co.id) AS cnt FROM companies co
            {joins}
            {where}
        """
        cur.execute(count_query, qb.params)
        total = cur.fetchone()["cnt"]

        return {
            "companies": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        }


@router.get("/companies/{company_id}")
def get_company_detail(
    company_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Company detail with all contacts."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT * FROM companies WHERE id = %s AND user_id = %s", (company_id, user["id"]))
        company = cur.fetchone()
        if not company:
            raise HTTPException(404, f"Company {company_id} not found")

        cur.execute(
            """SELECT c.*, ccs.status AS campaign_status, ccs.current_step
               FROM contacts c
               LEFT JOIN contact_campaign_status ccs ON ccs.contact_id = c.id
               WHERE c.company_id = %s AND c.user_id = %s
               ORDER BY c.priority_rank""",
            (company_id, user["id"]),
        )
        contacts = cur.fetchall()

        # Activity stats
        cur.execute(
            """SELECT COUNT(*) AS cnt FROM events e
               JOIN contacts c ON c.id = e.contact_id
               WHERE c.company_id = %s AND e.user_id = %s""",
            (company_id, user["id"]),
        )
        event_count = cur.fetchone()["cnt"]

        return {
            "company": dict(company),
            "contacts": [dict(c) for c in contacts],
            "event_count": event_count,
        }


@router.get("/search")
def global_search(
    q: str = Query(..., min_length=1),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Global search across contacts, companies, and messages."""
    like = f"%{q}%"
    with get_cursor(conn) as cur:
        # Search contacts
        cur.execute(
            """SELECT c.id, c.full_name, c.email, co.name AS company_name, 'contact' AS result_type
               FROM contacts c
               JOIN companies co ON co.id = c.company_id
               WHERE co.user_id = %s AND (c.full_name ILIKE %s OR c.email ILIKE %s)
               LIMIT %s""",
            (user["id"], like, like, CRM_SEARCH_LIMIT),
        )
        contacts = [dict(r) for r in cur.fetchall()]

        # Search companies
        cur.execute(
            """SELECT id, name, firm_type, aum_millions, 'company' AS result_type
               FROM companies
               WHERE user_id = %s AND name ILIKE %s
               LIMIT %s""",
            (user["id"], like, CRM_SEARCH_LIMIT),
        )
        companies = [dict(r) for r in cur.fetchall()]

        # Search messages (events metadata, response notes)
        cur.execute(
            """SELECT rn.id, rn.contact_id, rn.content, c.full_name AS contact_name,
                      'note' AS result_type
               FROM response_notes rn
               JOIN contacts c ON c.id = rn.contact_id
               JOIN companies co ON co.id = c.company_id
               WHERE co.user_id = %s AND rn.content ILIKE %s
               LIMIT 5""",
            (user["id"], like),
        )
        messages = [dict(r) for r in cur.fetchall()]

        return {
            "contacts": contacts,
            "companies": companies,
            "messages": messages,
            "total": len(contacts) + len(companies) + len(messages),
        }
