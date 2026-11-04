"""Read-only database checks. Every query of the suite lives here, behind the `qa_readonly` role.

Table names follow Medusa 2.22.2 (explored with `information_schema` before writing these queries):
`order`, `order_item` (quantities), `order_line_item` (prices), `order_summary` (totals JSON),
`order_cart`, `reservation_item` (links to `order_line_item`), `inventory_level`, `product`, `cart`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row


class ReadOnlyDb:
    def __init__(self, url: str) -> None:
        self.url = url

    @contextmanager
    def _cursor(self) -> Iterator[psycopg.Cursor[dict[str, Any]]]:
        # Without a timeout an unreachable address hangs the test forever instead of failing it (libpq on
        # Windows does not notice a refused connection to ::1 when the URL says "localhost").
        with (
            psycopg.connect(self.url, autocommit=True, row_factory=dict_row, connect_timeout=10) as conn,
            conn.cursor() as cur,
        ):
            yield cur

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    # ---- orders -------------------------------------------------------------------------------

    def order(self, order_id: str) -> dict[str, Any] | None:
        return self.one(
            'SELECT id, email, currency_code, status, customer_id, deleted_at FROM "order" WHERE id = %s',
            (order_id,),
        )

    def order_lines(self, order_id: str) -> list[dict[str, Any]]:
        return self.all(
            """
            SELECT li.variant_id, li.unit_price, oi.quantity
            FROM order_item oi JOIN order_line_item li ON li.id = oi.item_id
            WHERE oi.order_id = %s AND oi.deleted_at IS NULL
            ORDER BY li.variant_id
            """,
            (order_id,),
        )

    def order_total(self, order_id: str) -> Decimal:
        row = self.one(
            "SELECT totals->'raw_current_order_total'->>'value' AS total FROM order_summary"
            " WHERE order_id = %s ORDER BY version DESC LIMIT 1",
            (order_id,),
        )
        if row is None:
            raise LookupError(f"no order_summary for {order_id}")
        return Decimal(row["total"])

    def orders_for_cart(self, cart_id: str) -> int:
        row = self.one(
            "SELECT count(*) AS n FROM order_cart WHERE cart_id = %s AND deleted_at IS NULL", (cart_id,)
        )
        return int(row["n"]) if row else 0

    # ---- inventory --------------------------------------------------------------------------

    def reservations_for_order(self, order_id: str) -> list[dict[str, Any]]:
        return self.all(
            """
            SELECT r.inventory_item_id, r.quantity
            FROM reservation_item r
            JOIN order_item oi ON oi.item_id = r.line_item_id
            WHERE oi.order_id = %s AND r.deleted_at IS NULL
            """,
            (order_id,),
        )

    def inventory_level(self, inventory_item_id: str, location_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT stocked_quantity, reserved_quantity FROM inventory_level"
            " WHERE inventory_item_id = %s AND location_id = %s AND deleted_at IS NULL",
            (inventory_item_id, location_id),
        )

    # ---- catalog and carts ---------------------------------------------------------------------

    def product(self, product_id: str) -> dict[str, Any] | None:
        return self.one("SELECT id, handle, deleted_at FROM product WHERE id = %s", (product_id,))

    def cart_owner(self, cart_id: str) -> dict[str, Any] | None:
        return self.one("SELECT customer_id, email FROM cart WHERE id = %s", (cart_id,))

    def line_quantity(self, cart_id: str, variant_id: str) -> int:
        row = self.one(
            "SELECT coalesce(sum(quantity), 0) AS q, count(*) AS lines FROM cart_line_item"
            " WHERE cart_id = %s AND variant_id = %s AND deleted_at IS NULL",
            (cart_id, variant_id),
        )
        return int(row["q"]) if row else 0
