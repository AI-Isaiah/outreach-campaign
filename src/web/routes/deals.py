"""Deal pipeline API routes — CRUD, stage transitions, kanban grouping."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.enums import DealStage
from src.web.dependencies import get_current_user, get_db
from src.web.query_builder import QueryBuilder
from src.models.database import get_cursor

router = APIRouter(prefix="/deals", tags=["deals"])

VALID_STAGES = tuple(DealStage)


class DealCreate(BaseModel):
    company_id: int
    contact_id: Optional[int] = None
    campaign_id: Optional[int] = None
    title: str = Field(max_length=200)
    stage: str = Field(default="cold", max_length=50)
    amount_millions: Optional[float] = None
    expected_close_date: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=5000)


class DealUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    contact_id: Optional[int] = None
    campaign_id: Optional[int] = None
    amount_millions: Optional[float] = None
    expected_close_date: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=5000)


class StageUpdate(BaseModel):
    stage: str = Field(max_length=50)


@router.get("/pipeline")
def get_pipeline(
    campaign_id: Optional[int] = None,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """All deals grouped by stage for kanban view."""
    with get_cursor(conn) as cur:
        qb = QueryBuilder()
        qb.add_condition("co.user_id = %s", user["id"])
        if campaign_id is not None:
            qb.add_condition("d.campaign_id = %s", campaign_id)

        cur.execute(
            f"""SELECT d.*, co.name AS company_name, co.aum_millions,
                       c.full_name AS contact_name
                FROM deals d
                JOIN companies co ON co.id = d.company_id
                LEFT JOIN contacts c ON c.id = d.contact_id
                {qb.where_clause}
                ORDER BY d.updated_at DESC""",
            qb.params,
        )
        rows = cur.fetchall()

        pipeline: dict[str, list] = {s: [] for s in VALID_STAGES}
        for row in rows:
            stage = row["stage"]
            if stage in pipeline:
                pipeline[stage].append(dict(row))

        return {"pipeline": pipeline}


@router.get("")
def list_deals(
    stage: Optional[str] = None,
    company_id: Optional[int] = None,
    min_amount: Optional[float] = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """List deals with optional filters."""
    offset = (page - 1) * per_page
    qb = QueryBuilder()
    qb.add_condition("co.user_id = %s", user["id"])

    if stage:
        qb.add_condition("d.stage = %s", stage)
    if company_id is not None:
        qb.add_condition("d.company_id = %s", company_id)
    if min_amount is not None:
        qb.add_condition("d.amount_millions >= %s", min_amount)

    with get_cursor(conn) as cur:
        cur.execute(
            f"""SELECT d.*, co.name AS company_name, co.aum_millions,
                       c.full_name AS contact_name
                FROM deals d
                JOIN companies co ON co.id = d.company_id
                LEFT JOIN contacts c ON c.id = d.contact_id
                {qb.where_clause}
                ORDER BY d.updated_at DESC
                LIMIT %s OFFSET %s""",
            qb.params + [per_page, offset],
        )
        rows = cur.fetchall()

        cur.execute(
            f"""SELECT COUNT(*) AS cnt FROM deals d
                JOIN companies co ON co.id = d.company_id
                {qb.where_clause}""",
            qb.params,
        )
        total = cur.fetchone()["cnt"]

        return {
            "deals": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page if total else 0,
        }


@router.post("")
def create_deal(
    body: DealCreate,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a new deal."""
    if body.stage not in VALID_STAGES:
        raise HTTPException(400, f"Invalid stage: {body.stage}")

    with get_cursor(conn) as cur:
        # Verify company exists and belongs to user
        cur.execute("SELECT id FROM companies WHERE id = %s AND user_id = %s", (body.company_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, f"Company {body.company_id} not found")

        # Verify contact if provided
        if body.contact_id is not None:
            cur.execute("SELECT id FROM contacts WHERE id = %s AND user_id = %s", (body.contact_id, user["id"]))
            if not cur.fetchone():
                raise HTTPException(404, f"Contact {body.contact_id} not found")

        cur.execute(
            """INSERT INTO deals (company_id, contact_id, campaign_id, title, stage,
                                  amount_millions, expected_close_date, notes, user_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                body.company_id,
                body.contact_id,
                body.campaign_id,
                body.title,
                body.stage,
                body.amount_millions,
                body.expected_close_date,
                body.notes,
                user["id"],
            ),
        )
        deal_id = cur.fetchone()["id"]

        # Log initial stage
        cur.execute(
            "INSERT INTO deal_stage_log (deal_id, from_stage, to_stage) VALUES (%s, NULL, %s)",
            (deal_id, body.stage),
        )
        conn.commit()

        return {"id": deal_id, "success": True}


@router.get("/{deal_id}")
def get_deal(
    deal_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Deal detail with company, contact, and stage history."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT d.*, co.name AS company_name, co.aum_millions,
                      c.full_name AS contact_name, c.email AS contact_email
               FROM deals d
               JOIN companies co ON co.id = d.company_id
               LEFT JOIN contacts c ON c.id = d.contact_id
               WHERE d.id = %s AND co.user_id = %s""",
            (deal_id, user["id"]),
        )
        deal = cur.fetchone()
        if not deal:
            raise HTTPException(404, f"Deal {deal_id} not found")

        cur.execute(
            """SELECT * FROM deal_stage_log
               WHERE deal_id = %s
               ORDER BY changed_at DESC""",
            (deal_id,),
        )
        history = cur.fetchall()

        return {
            "deal": dict(deal),
            "stage_history": [dict(h) for h in history],
        }


@router.put("/{deal_id}")
def update_deal(
    deal_id: int,
    body: DealUpdate,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Update deal fields (not stage — use PATCH /stage for that)."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT d.id FROM deals d
               JOIN companies co ON co.id = d.company_id
               WHERE d.id = %s AND co.user_id = %s""",
            (deal_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Deal {deal_id} not found")

        updates = []
        params: list = []
        for field in ("title", "contact_id", "campaign_id", "amount_millions", "expected_close_date", "notes"):
            val = getattr(body, field)
            if val is not None:
                updates.append(f"{field} = %s")
                params.append(val)

        if not updates:
            raise HTTPException(400, "No fields to update")

        updates.append("updated_at = NOW()")
        params.append(deal_id)

        cur.execute(
            f"UPDATE deals SET {', '.join(updates)} WHERE id = %s",
            params,
        )
        conn.commit()

        return {"success": True}


@router.patch("/{deal_id}/stage")
def update_deal_stage(
    deal_id: int,
    body: StageUpdate,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Move deal to a new stage, logging the transition."""
    if body.stage not in VALID_STAGES:
        raise HTTPException(400, f"Invalid stage: {body.stage}")

    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT d.id, d.stage FROM deals d
               JOIN companies co ON co.id = d.company_id
               WHERE d.id = %s AND co.user_id = %s""",
            (deal_id, user["id"]),
        )
        deal = cur.fetchone()
        if not deal:
            raise HTTPException(404, f"Deal {deal_id} not found")

        old_stage = deal["stage"]
        if old_stage == body.stage:
            return {"success": True, "stage": body.stage, "changed": False}

        cur.execute(
            "UPDATE deals SET stage = %s, updated_at = NOW() WHERE id = %s",
            (body.stage, deal_id),
        )
        cur.execute(
            "INSERT INTO deal_stage_log (deal_id, from_stage, to_stage) VALUES (%s, %s, %s)",
            (deal_id, old_stage, body.stage),
        )
        conn.commit()

        return {"success": True, "stage": body.stage, "from_stage": old_stage, "changed": True}


@router.delete("/{deal_id}")
def delete_deal(
    deal_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a deal."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT d.id FROM deals d
               JOIN companies co ON co.id = d.company_id
               WHERE d.id = %s AND co.user_id = %s""",
            (deal_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Deal {deal_id} not found")

        cur.execute("DELETE FROM deals WHERE id = %s", (deal_id,))
        conn.commit()

        return {"success": True}
