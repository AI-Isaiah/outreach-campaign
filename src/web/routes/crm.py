"""CRM API routes — contacts, companies, timeline, search."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.web.dependencies import get_db

router = APIRouter(prefix="/crm", tags=["crm"])


@router.get("/contacts")
def list_crm_contacts(
    search: Optional[str] = None,
    status: Optional[str] = None,
    company_type: Optional[str] = None,
    min_aum: Optional[float] = None,
    max_aum: Optional[float] = None,
    page: int = 1,
    per_page: int = 50,
    conn=Depends(get_db),
):
    """Searchable, filterable contact list for CRM view."""
    offset = (page - 1) * per_page
    conditions = []
    params = []

    if search:
        conditions.append(
            "(c.full_name ILIKE %s OR c.email ILIKE %s OR co.name ILIKE %s)"
        )
        like = f"%{search}%"
        params.extend([like, like, like])

    if status:
        conditions.append("ccs.status = %s")
        params.append(status)

    if company_type:
        conditions.append("co.firm_type = %s")
        params.append(company_type)

    if min_aum is not None:
        conditions.append("co.aum_millions >= %s")
        params.append(min_aum)

    if max_aum is not None:
        conditions.append("co.aum_millions <= %s")
        params.append(max_aum)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    # Use LEFT JOIN to ccs so we can filter by status but still show unenrolled contacts
    join_type = "JOIN" if status else "LEFT JOIN"

    query = f"""
        SELECT c.*, co.name AS company_name, co.aum_millions, co.firm_type,
               ccs.status AS campaign_status, ccs.current_step,
               (SELECT MAX(e.created_at) FROM events e WHERE e.contact_id = c.id) AS last_activity
        FROM contacts c
        LEFT JOIN companies co ON co.id = c.company_id
        {join_type} contact_campaign_status ccs ON ccs.contact_id = c.id
        {where}
        ORDER BY co.aum_millions DESC NULLS LAST
        LIMIT %s OFFSET %s
    """
    params.extend([per_page, offset])

    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()

    # Count query
    count_query = f"""
        SELECT COUNT(*) AS cnt
        FROM contacts c
        LEFT JOIN companies co ON co.id = c.company_id
        {join_type} contact_campaign_status ccs ON ccs.contact_id = c.id
        {where}
    """
    cur.execute(count_query, params[:-2])  # exclude LIMIT/OFFSET params
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
    page: int = 1,
    per_page: int = 50,
    conn=Depends(get_db),
):
    """Get unified interaction timeline for a contact."""
    cur = conn.cursor()

    # Verify contact exists
    cur.execute("SELECT id FROM contacts WHERE id = %s", (contact_id,))
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
    page: int = 1,
    per_page: int = 50,
    conn=Depends(get_db),
):
    """Company list with aggregated contact stats."""
    offset = (page - 1) * per_page
    conditions = []
    params = []

    if search:
        conditions.append("co.name ILIKE %s")
        params.append(f"%{search}%")

    if firm_type:
        conditions.append("co.firm_type = %s")
        params.append(firm_type)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    query = f"""
        SELECT co.*,
               COUNT(c.id) AS contact_count,
               COUNT(CASE WHEN ccs.status IS NOT NULL THEN 1 END) AS enrolled_count,
               COUNT(CASE WHEN ccs.status = 'replied_positive' THEN 1 END) AS positive_replies
        FROM companies co
        LEFT JOIN contacts c ON c.company_id = co.id
        LEFT JOIN contact_campaign_status ccs ON ccs.contact_id = c.id
        {where}
        GROUP BY co.id
        ORDER BY co.aum_millions DESC NULLS LAST
        LIMIT %s OFFSET %s
    """
    params.extend([per_page, offset])

    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()

    count_query = f"SELECT COUNT(*) AS cnt FROM companies co {where}"
    cur.execute(count_query, params[:-2])
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
):
    """Company detail with all contacts."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM companies WHERE id = %s", (company_id,))
    company = cur.fetchone()
    if not company:
        raise HTTPException(404, f"Company {company_id} not found")

    cur.execute(
        """SELECT c.*, ccs.status AS campaign_status, ccs.current_step
           FROM contacts c
           LEFT JOIN contact_campaign_status ccs ON ccs.contact_id = c.id
           WHERE c.company_id = %s
           ORDER BY c.priority_rank""",
        (company_id,),
    )
    contacts = cur.fetchall()

    # Activity stats
    cur.execute(
        """SELECT COUNT(*) AS cnt FROM events e
           JOIN contacts c ON c.id = e.contact_id
           WHERE c.company_id = %s""",
        (company_id,),
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
):
    """Global search across contacts, companies, and messages."""
    like = f"%{q}%"
    cur = conn.cursor()

    # Search contacts
    cur.execute(
        """SELECT c.id, c.full_name, c.email, co.name AS company_name, 'contact' AS result_type
           FROM contacts c
           LEFT JOIN companies co ON co.id = c.company_id
           WHERE c.full_name ILIKE %s OR c.email ILIKE %s
           LIMIT 10""",
        (like, like),
    )
    contacts = [dict(r) for r in cur.fetchall()]

    # Search companies
    cur.execute(
        """SELECT id, name, firm_type, aum_millions, 'company' AS result_type
           FROM companies
           WHERE name ILIKE %s
           LIMIT 10""",
        (like,),
    )
    companies = [dict(r) for r in cur.fetchall()]

    # Search messages (events metadata, response notes, whatsapp)
    cur.execute(
        """SELECT rn.id, rn.contact_id, rn.content, c.full_name AS contact_name,
                  'note' AS result_type
           FROM response_notes rn
           JOIN contacts c ON c.id = rn.contact_id
           WHERE rn.content ILIKE %s
           LIMIT 5""",
        (like,),
    )
    messages = [dict(r) for r in cur.fetchall()]

    return {
        "contacts": contacts,
        "companies": companies,
        "messages": messages,
        "total": len(contacts) + len(companies) + len(messages),
    }
