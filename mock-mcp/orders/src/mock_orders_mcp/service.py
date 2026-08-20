"""Durable local order/refund domain logic used behind the MCP boundary."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class OrdersService:
    """A deliberately small SQLite order service for local MCP integration tests.

    All methods receive the authenticated actor ID from the MCP adapter.  It is
    never accepted from an LLM-controlled field.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = str(Path(db_path).expanduser())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    total_minor INTEGER NOT NULL,
                    refunded_minor INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS refunds (
                    approval_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    confirmation_phrase TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    executed_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES orders(order_id)
                );
                CREATE INDEX IF NOT EXISTS ix_orders_user ON orders(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS ix_refunds_user ON refunds(user_id, created_at DESC);
                """
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _serialize_order(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "order_id": row["order_id"],
            "status": row["status"],
            "currency": row["currency"],
            "total_minor": row["total_minor"],
            "refunded_minor": row["refunded_minor"],
            "refundable_minor": max(0, row["total_minor"] - row["refunded_minor"]),
            "created_at": row["created_at"],
        }

    def _ensure_demo_orders(self, conn: sqlite3.Connection, user_id: str) -> None:
        row = conn.execute("SELECT 1 FROM orders WHERE user_id = ? LIMIT 1", (user_id,)).fetchone()
        if row is not None:
            return
        suffix = "".join(ch for ch in user_id if ch.isalnum())[:8] or "guest"
        now = self._now().isoformat()
        conn.executemany(
            "INSERT INTO orders(order_id, user_id, status, currency, total_minor, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (f"ORD-{suffix}-1001", user_id, "paid", "CNY", 12900, now),
                (f"ORD-{suffix}-1002", user_id, "paid", "CNY", 5900, now),
            ],
        )

    def list_orders(self, actor_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            self._ensure_demo_orders(conn, actor_id)
            rows = conn.execute(
                "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC, order_id DESC",
                (actor_id,),
            ).fetchall()
        return {"status": "ok", "orders": [self._serialize_order(row) for row in rows]}

    def get_order(self, actor_id: str, order_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            self._ensure_demo_orders(conn, actor_id)
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id = ? AND user_id = ?", (order_id.strip(), actor_id)
            ).fetchone()
        if row is None:
            return {"status": "not_found", "message": "未找到属于当前用户的订单。"}
        return {"status": "ok", "order": self._serialize_order(row)}

    def prepare_refund(
        self, actor_id: str, order_id: str, reason: str, amount_minor: int | None = None
    ) -> dict[str, Any]:
        reason = reason.strip()
        if not reason:
            return {"status": "invalid", "message": "退款原因不能为空。"}
        with self._connect() as conn:
            self._ensure_demo_orders(conn, actor_id)
            order = conn.execute(
                "SELECT * FROM orders WHERE order_id = ? AND user_id = ?", (order_id.strip(), actor_id)
            ).fetchone()
            if order is None:
                return {"status": "not_found", "message": "未找到属于当前用户的订单。"}
            refundable = max(0, order["total_minor"] - order["refunded_minor"])
            requested = refundable if amount_minor is None else int(amount_minor)
            if requested <= 0 or requested > refundable:
                return {"status": "invalid", "message": f"可退款金额为 {refundable} 分。"}
            approval_id = f"RFD-{uuid.uuid4().hex[:12].upper()}"
            phrase = f"确认退款 {approval_id}"
            now = self._now()
            expires = now + timedelta(minutes=10)
            conn.execute(
                """INSERT INTO refunds(
                    approval_id, order_id, user_id, reason, amount_minor, status,
                    confirmation_phrase, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, 'awaiting_confirmation', ?, ?, ?)""",
                (approval_id, order["order_id"], actor_id, reason, requested, phrase, expires.isoformat(), now.isoformat()),
            )
        return {
            "status": "awaiting_confirmation",
            "approval_id": approval_id,
            "order_id": order_id.strip(),
            "amount_minor": requested,
            "currency": order["currency"],
            "reason": reason,
            "expires_at": expires.isoformat(),
            "confirmation_phrase": phrase,
            "message": "退款尚未执行。请让用户单独发送 confirmation_phrase 后再调用确认工具。",
        }

    def confirm_refund(self, actor_id: str, approval_id: str, confirmation_text: str) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            refund = conn.execute(
                "SELECT * FROM refunds WHERE approval_id = ? AND user_id = ?", (approval_id.strip(), actor_id)
            ).fetchone()
            if refund is None:
                return {"status": "not_found", "message": "未找到待确认退款。"}
            if refund["status"] == "completed":
                return {"status": "already_completed", "approval_id": refund["approval_id"], "order_id": refund["order_id"]}
            if refund["status"] != "awaiting_confirmation":
                return {"status": "invalid", "message": "退款当前不可执行。"}
            if self._now() > datetime.fromisoformat(refund["expires_at"]):
                conn.execute("UPDATE refunds SET status = 'expired' WHERE approval_id = ?", (refund["approval_id"],))
                return {"status": "expired", "message": "确认已过期，请重新发起退款。"}
            if confirmation_text.strip() != refund["confirmation_phrase"]:
                return {"status": "confirmation_mismatch", "message": "确认文本不匹配，退款未执行。"}
            order = conn.execute(
                "SELECT * FROM orders WHERE order_id = ? AND user_id = ?", (refund["order_id"], actor_id)
            ).fetchone()
            if order is None:
                return {"status": "not_found", "message": "原订单不存在。"}
            refundable = max(0, order["total_minor"] - order["refunded_minor"])
            if refund["amount_minor"] > refundable:
                return {"status": "invalid", "message": "订单可退款金额已变化，请重新发起退款。"}
            now = self._now().isoformat()
            conn.execute(
                "UPDATE orders SET refunded_minor = refunded_minor + ? WHERE order_id = ?",
                (refund["amount_minor"], order["order_id"]),
            )
            conn.execute(
                "UPDATE refunds SET status = 'completed', executed_at = ? WHERE approval_id = ?",
                (now, refund["approval_id"]),
            )
        return {
            "status": "completed",
            "approval_id": refund["approval_id"],
            "order_id": refund["order_id"],
            "amount_minor": refund["amount_minor"],
            "currency": order["currency"],
            "executed_at": now,
        }
