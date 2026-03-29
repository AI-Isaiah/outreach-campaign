"""Product interest tracking API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.enums import ProductStage
from src.web.dependencies import get_current_user, get_db
from src.models.database import get_cursor

router = APIRouter(tags=["products"])

VALID_STAGES = set(ProductStage)


class ProductCreate(BaseModel):
    name: str = Field(max_length=200)
    description: Optional[str] = Field(default=None, max_length=500)


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=500)


class ContactProductLink(BaseModel):
    product_id: int
    stage: str = Field(default="discussed", max_length=50)
    notes: Optional[str] = Field(default=None, max_length=5000)


class StageUpdate(BaseModel):
    stage: str = Field(max_length=50)


@router.get("/products")
def list_products(conn=Depends(get_db), user=Depends(get_current_user)):
    """List all active products."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT * FROM products WHERE is_active = true AND user_id = %s ORDER BY name", (user["id"],))
        return [dict(r) for r in cur.fetchall()]


@router.post("/products")
def create_product(body: ProductCreate, conn=Depends(get_db), user=Depends(get_current_user)):
    """Create a new product."""
    with get_cursor(conn) as cur:
        cur.execute(
            "INSERT INTO products (name, description, user_id) VALUES (%s, %s, %s) RETURNING id",
            (body.name, body.description, user["id"]),
        )
        product_id = cur.fetchone()["id"]
        conn.commit()
        return {"id": product_id, "success": True}


@router.put("/products/{product_id}")
def update_product(product_id: int, body: ProductUpdate, conn=Depends(get_db), user=Depends(get_current_user)):
    """Update a product."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT id FROM products WHERE id = %s AND user_id = %s", (product_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, f"Product {product_id} not found")

        updates = []
        params = []
        if body.name is not None:
            updates.append("name = %s")
            params.append(body.name)
        if body.description is not None:
            updates.append("description = %s")
            params.append(body.description)

        if updates:
            params.append(product_id)
            cur.execute(
                f"UPDATE products SET {', '.join(updates)} WHERE id = %s",
                params,
            )
            conn.commit()
        return {"success": True}


@router.delete("/products/{product_id}")
def delete_product(product_id: int, conn=Depends(get_db), user=Depends(get_current_user)):
    """Soft-delete a product (set is_active = false)."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT id FROM products WHERE id = %s AND user_id = %s", (product_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, f"Product {product_id} not found")

        cur.execute("UPDATE products SET is_active = false WHERE id = %s", (product_id,))
        conn.commit()
        return {"success": True}


@router.get("/contacts/{contact_id}/products")
def list_contact_products(contact_id: int, conn=Depends(get_db), user=Depends(get_current_user)):
    """List product interests for a contact with product details."""
    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT c.id FROM contacts c
               JOIN companies co ON co.id = c.company_id
               WHERE c.id = %s AND co.user_id = %s""",
            (contact_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Contact {contact_id} not found")

        cur.execute(
            """SELECT cp.*, p.name AS product_name, p.description AS product_description
               FROM contact_products cp
               JOIN products p ON p.id = cp.product_id
               WHERE cp.contact_id = %s
               ORDER BY cp.created_at DESC""",
            (contact_id,),
        )
        return [dict(r) for r in cur.fetchall()]


@router.post("/contacts/{contact_id}/products")
def link_contact_product(
    contact_id: int,
    body: ContactProductLink,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Link a product interest to a contact."""
    if body.stage not in VALID_STAGES:
        raise HTTPException(400, f"Invalid stage. Must be one of: {', '.join(sorted(VALID_STAGES))}")

    with get_cursor(conn) as cur:
        cur.execute(
            """SELECT c.id FROM contacts c
               JOIN companies co ON co.id = c.company_id
               WHERE c.id = %s AND co.user_id = %s""",
            (contact_id, user["id"]),
        )
        if not cur.fetchone():
            raise HTTPException(404, f"Contact {contact_id} not found")

        cur.execute("SELECT id FROM products WHERE id = %s AND user_id = %s", (body.product_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, f"Product {body.product_id} not found")

        cur.execute(
            """INSERT INTO contact_products (contact_id, product_id, stage, notes)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (contact_id, product_id) DO UPDATE SET stage = %s, notes = %s, updated_at = NOW()
               RETURNING id""",
            (contact_id, body.product_id, body.stage, body.notes, body.stage, body.notes),
        )
        cp_id = cur.fetchone()["id"]
        conn.commit()
        return {"id": cp_id, "success": True}


@router.patch("/contacts/{contact_id}/products/{product_id}/stage")
def update_contact_product_stage(
    contact_id: int,
    product_id: int,
    body: StageUpdate,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Update the stage of a contact's product interest."""
    if body.stage not in VALID_STAGES:
        raise HTTPException(400, f"Invalid stage. Must be one of: {', '.join(sorted(VALID_STAGES))}")

    with get_cursor(conn) as cur:
        cur.execute("SELECT id FROM contacts WHERE id = %s AND user_id = %s", (contact_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, "Contact not found")

        cur.execute(
            "SELECT id FROM contact_products WHERE contact_id = %s AND product_id = %s",
            (contact_id, product_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Contact-product link not found")

        cur.execute(
            "UPDATE contact_products SET stage = %s, updated_at = NOW() WHERE contact_id = %s AND product_id = %s",
            (body.stage, contact_id, product_id),
        )
        conn.commit()
        return {"success": True}


@router.delete("/contacts/{contact_id}/products/{product_id}")
def remove_contact_product(
    contact_id: int,
    product_id: int,
    conn=Depends(get_db),
    user=Depends(get_current_user),
):
    """Remove a product interest from a contact."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT id FROM contacts WHERE id = %s AND user_id = %s", (contact_id, user["id"]))
        if not cur.fetchone():
            raise HTTPException(404, "Contact not found")

        cur.execute(
            "DELETE FROM contact_products WHERE contact_id = %s AND product_id = %s",
            (contact_id, product_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Contact-product link not found")
        conn.commit()
        return {"success": True}
