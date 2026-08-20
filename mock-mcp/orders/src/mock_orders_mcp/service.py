"""Durable local order/refund domain logic used behind the MCP boundary.

The module is deliberately a mock, but its public data shape resembles a real
commerce domain closely enough for chat, tool timelines, and UI prototypes.
It never accepts a user id from a model-controlled argument: the MCP adapter
injects the authenticated actor id for every operation.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


_ORDER_STATUS_LABELS = {
    "paid": "已支付，待发货",
    "shipped": "已发货",
    "completed": "交易完成",
    "partial_refunded": "部分退款",
    "refunded": "已退款",
    "closed": "已关闭",
}

_REFUND_STATUS_LABELS = {
    "awaiting_confirmation": "等待用户确认",
    "completed": "退款已受理",
    "expired": "确认已过期",
}


class OrdersService:
    """SQLite-backed local demo service with rich order and refund records."""

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
                    subtotal_minor INTEGER NOT NULL DEFAULT 0,
                    discount_minor INTEGER NOT NULL DEFAULT 0,
                    shipping_minor INTEGER NOT NULL DEFAULT 0,
                    total_minor INTEGER NOT NULL,
                    paid_minor INTEGER NOT NULL DEFAULT 0,
                    refunded_minor INTEGER NOT NULL DEFAULT 0,
                    order_type TEXT NOT NULL DEFAULT 'physical',
                    sales_channel TEXT,
                    store_name TEXT,
                    payment_method TEXT,
                    payment_transaction_masked TEXT,
                    shipping_status TEXT,
                    recipient_name_masked TEXT,
                    recipient_phone_masked TEXT,
                    shipping_address_masked TEXT,
                    logistics_company TEXT,
                    tracking_number TEXT,
                    invoice_status TEXT,
                    invoice_title TEXT,
                    created_at TEXT NOT NULL,
                    paid_at TEXT,
                    shipped_at TEXT,
                    delivered_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT,
                    refund_deadline_at TEXT
                );
                CREATE TABLE IF NOT EXISTS order_items (
                    item_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    sku_id TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    product_subtitle TEXT,
                    product_url TEXT NOT NULL,
                    image_url TEXT,
                    category TEXT,
                    specifications_json TEXT,
                    quantity INTEGER NOT NULL,
                    unit_price_minor INTEGER NOT NULL,
                    discount_minor INTEGER NOT NULL DEFAULT 0,
                    paid_minor INTEGER NOT NULL,
                    fulfillment_status TEXT,
                    after_sale_status TEXT,
                    FOREIGN KEY(order_id) REFERENCES orders(order_id)
                );
                CREATE TABLE IF NOT EXISTS refunds (
                    approval_id TEXT PRIMARY KEY,
                    refund_no TEXT,
                    order_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    refund_type TEXT NOT NULL DEFAULT 'full',
                    reason_code TEXT,
                    reason TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    currency TEXT,
                    payment_method TEXT,
                    status TEXT NOT NULL,
                    confirmation_phrase TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    estimated_arrival_at TEXT,
                    executed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    FOREIGN KEY(order_id) REFERENCES orders(order_id)
                );
                CREATE TABLE IF NOT EXISTS refund_events (
                    event_id TEXT PRIMARY KEY,
                    approval_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY(approval_id) REFERENCES refunds(approval_id)
                );
                CREATE TABLE IF NOT EXISTS demo_seed_versions (
                    user_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    seeded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_orders_user ON orders(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS ix_order_items_order ON order_items(order_id);
                CREATE INDEX IF NOT EXISTS ix_refunds_user ON refunds(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS ix_refunds_order ON refunds(order_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS ix_refund_events_approval ON refund_events(approval_id, occurred_at ASC);
                """
            )
            # Existing local databases were created by the first small mock.
            # SQLite permits additive migrations, so they keep working instead
            # of requiring developers to delete their demo database.
            self._add_missing_columns(
                conn,
                "orders",
                {
                    "subtotal_minor": "INTEGER NOT NULL DEFAULT 0",
                    "discount_minor": "INTEGER NOT NULL DEFAULT 0",
                    "shipping_minor": "INTEGER NOT NULL DEFAULT 0",
                    "paid_minor": "INTEGER NOT NULL DEFAULT 0",
                    "order_type": "TEXT NOT NULL DEFAULT 'physical'",
                    "sales_channel": "TEXT",
                    "store_name": "TEXT",
                    "payment_method": "TEXT",
                    "payment_transaction_masked": "TEXT",
                    "shipping_status": "TEXT",
                    "recipient_name_masked": "TEXT",
                    "recipient_phone_masked": "TEXT",
                    "shipping_address_masked": "TEXT",
                    "logistics_company": "TEXT",
                    "tracking_number": "TEXT",
                    "invoice_status": "TEXT",
                    "invoice_title": "TEXT",
                    "paid_at": "TEXT",
                    "shipped_at": "TEXT",
                    "delivered_at": "TEXT",
                    "completed_at": "TEXT",
                    "updated_at": "TEXT",
                    "refund_deadline_at": "TEXT",
                },
            )
            self._add_missing_columns(
                conn,
                "refunds",
                {
                    "refund_no": "TEXT",
                    "refund_type": "TEXT NOT NULL DEFAULT 'full'",
                    "reason_code": "TEXT",
                    "currency": "TEXT",
                    "payment_method": "TEXT",
                    "estimated_arrival_at": "TEXT",
                    "updated_at": "TEXT",
                },
            )
            conn.execute(
                "UPDATE orders SET subtotal_minor = total_minor WHERE subtotal_minor = 0 AND total_minor > 0"
            )
            conn.execute("UPDATE orders SET paid_minor = total_minor WHERE paid_minor = 0 AND total_minor > 0")
            conn.execute("UPDATE orders SET updated_at = created_at WHERE updated_at IS NULL")

    @staticmethod
    def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, sql_type in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    @staticmethod
    def _minor(value: int | None) -> int:
        return int(value or 0)

    @staticmethod
    def _json_object(raw: str | None) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _serialize_item(self, row: sqlite3.Row) -> dict[str, Any]:
        unit_price = self._minor(row["unit_price_minor"])
        discount = self._minor(row["discount_minor"])
        return {
            "item_id": row["item_id"],
            "product_id": row["product_id"],
            "sku_id": row["sku_id"],
            "product_name": row["product_name"],
            "product_subtitle": row["product_subtitle"],
            "product_url": row["product_url"],
            "image_url": row["image_url"],
            "category": row["category"],
            "specifications": self._json_object(row["specifications_json"]),
            "quantity": self._minor(row["quantity"]),
            "unit_price_minor": unit_price,
            "discount_minor": discount,
            "paid_minor": self._minor(row["paid_minor"]),
            "line_total_minor": unit_price * self._minor(row["quantity"]),
            "fulfillment_status": row["fulfillment_status"],
            "after_sale_status": row["after_sale_status"],
        }

    def _items_for_order(self, conn: sqlite3.Connection, order_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM order_items WHERE order_id = ? ORDER BY rowid ASC", (order_id,)
        ).fetchall()
        return [self._serialize_item(row) for row in rows]

    def _refund_timeline(self, conn: sqlite3.Connection, approval_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM refund_events WHERE approval_id = ? ORDER BY occurred_at ASC, event_id ASC", (approval_id,)
        ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "status": row["status"],
                "message": row["message"],
                "details": self._json_object(row["details_json"]),
                "occurred_at": row["occurred_at"],
            }
            for row in rows
        ]

    def _serialize_refund(self, conn: sqlite3.Connection, row: sqlite3.Row, *, include_timeline: bool) -> dict[str, Any]:
        status = row["status"]
        payload = {
            "approval_id": row["approval_id"],
            "refund_no": row["refund_no"],
            "order_id": row["order_id"],
            "refund_type": row["refund_type"],
            "status": status,
            "status_label": _REFUND_STATUS_LABELS.get(status, status),
            "reason_code": row["reason_code"],
            "reason": row["reason"],
            "amount_minor": self._minor(row["amount_minor"]),
            "currency": row["currency"],
            "refund_to": row["payment_method"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "executed_at": row["executed_at"],
            "estimated_arrival_at": row["estimated_arrival_at"],
        }
        if include_timeline:
            payload["timeline"] = self._refund_timeline(conn, row["approval_id"])
        return payload

    def _refunds_for_order(self, conn: sqlite3.Connection, order_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM refunds WHERE order_id = ? ORDER BY created_at DESC", (order_id,)
        ).fetchall()
        return [self._serialize_refund(conn, row, include_timeline=True) for row in rows]

    def _is_refundable(self, order: sqlite3.Row) -> tuple[bool, str | None]:
        if order["status"] in {"refunded", "closed"}:
            return False, "订单当前状态不可退款。"
        if self._minor(order["total_minor"]) <= self._minor(order["refunded_minor"]):
            return False, "订单没有可退余额。"
        deadline = order["refund_deadline_at"]
        if deadline and self._now() > datetime.fromisoformat(deadline):
            return False, "已超过该订单的售后期限。"
        return True, None

    def _serialize_order(self, conn: sqlite3.Connection, row: sqlite3.Row, *, include_refunds: bool) -> dict[str, Any]:
        total = self._minor(row["total_minor"])
        refunded = self._minor(row["refunded_minor"])
        refundable = max(0, total - refunded)
        eligible, ineligible_reason = self._is_refundable(row)
        items = self._items_for_order(conn, row["order_id"])
        payload: dict[str, Any] = {
            # Keep original fields so existing chat prompts and tests remain compatible.
            "order_id": row["order_id"],
            "status": row["status"],
            "status_label": _ORDER_STATUS_LABELS.get(row["status"], row["status"]),
            "currency": row["currency"],
            "total_minor": total,
            "refunded_minor": refunded,
            "refundable_minor": refundable,
            "created_at": row["created_at"],
            "order_type": row["order_type"],
            "sales_channel": row["sales_channel"],
            "store_name": row["store_name"],
            "amounts": {
                "subtotal_minor": self._minor(row["subtotal_minor"]),
                "discount_minor": self._minor(row["discount_minor"]),
                "shipping_minor": self._minor(row["shipping_minor"]),
                "total_minor": total,
                "paid_minor": self._minor(row["paid_minor"]),
                "refunded_minor": refunded,
                "refundable_minor": refundable,
                "currency": row["currency"],
            },
            "payment": {
                "method": row["payment_method"],
                "transaction_masked": row["payment_transaction_masked"],
                "paid_at": row["paid_at"],
            },
            "fulfillment": {
                "status": row["shipping_status"],
                "recipient_name_masked": row["recipient_name_masked"],
                "recipient_phone_masked": row["recipient_phone_masked"],
                "shipping_address_masked": row["shipping_address_masked"],
                "logistics_company": row["logistics_company"],
                "tracking_number": row["tracking_number"],
                "shipped_at": row["shipped_at"],
                "delivered_at": row["delivered_at"],
                "completed_at": row["completed_at"],
            },
            "invoice": {"status": row["invoice_status"], "title": row["invoice_title"]},
            "refund_eligibility": {
                "eligible": eligible,
                "refundable_minor": refundable,
                "deadline_at": row["refund_deadline_at"],
                "ineligible_reason": ineligible_reason,
            },
            "items": items,
            "updated_at": row["updated_at"],
        }
        if include_refunds:
            payload["refunds"] = self._refunds_for_order(conn, row["order_id"])
        return payload

    def _append_refund_event(self, conn: sqlite3.Connection, approval_id: str, event_type: str, status: str, message: str, occurred_at: str, details: dict[str, Any] | None = None) -> None:
        conn.execute(
            """INSERT INTO refund_events(event_id, approval_id, event_type, status, message, details_json, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (f"RFE-{uuid.uuid4().hex[:16].upper()}", approval_id, event_type, status, message, json.dumps(details or {}, ensure_ascii=False), occurred_at),
        )

    def _ensure_extra_demo_orders(
        self, conn: sqlite3.Connection, user_id: str, suffix: str, now: datetime | None = None
    ) -> None:
        """Expand the original five examples to a 20-order rule-coverage set."""
        now = now or self._now()
        # Older mock rows did not have every presentation field. Populate safe
        # demo defaults so a detail UI can render a complete record for all 20.
        conn.execute(
            """UPDATE orders SET
                sales_channel = COALESCE(sales_channel, 'agenora-shop'),
                store_name = COALESCE(store_name, 'Agenora 官方店'),
                payment_method = COALESCE(payment_method, '微信支付'),
                payment_transaction_masked = COALESCE(payment_transaction_masked, '微信支付 ·· 8821'),
                shipping_status = COALESCE(shipping_status, '待发货'),
                recipient_name_masked = COALESCE(recipient_name_masked, '林*'),
                recipient_phone_masked = COALESCE(recipient_phone_masked, '138****0621'),
                shipping_address_masked = COALESCE(shipping_address_masked, '上海市浦东新区世纪大道***号'),
                logistics_company = COALESCE(logistics_company, 'Agenora 配送'),
                tracking_number = COALESCE(tracking_number, 'AGD-0000****0000'),
                invoice_status = COALESCE(invoice_status, '未开票'),
                invoice_title = COALESCE(invoice_title, '个人 · 林*'),
                paid_at = COALESCE(paid_at, created_at),
                shipped_at = COALESCE(shipped_at, created_at),
                delivered_at = COALESCE(delivered_at, created_at),
                completed_at = COALESCE(completed_at, created_at),
                refund_deadline_at = COALESCE(refund_deadline_at, updated_at),
                updated_at = COALESCE(updated_at, created_at)
            WHERE user_id = ?""",
            (user_id,),
        )
        count = conn.execute("SELECT COUNT(*) FROM orders WHERE user_id = ?", (user_id,)).fetchone()[0]
        if count >= 20:
            return

        products = (
            ("PRD-KEY-02", "机械键盘 87 键", "雾灰 · 茶轴", "数码", {"配列": "87 键", "轴体": "茶轴"}),
            ("PRD-MON-01", "27 英寸 4K 显示器", "雾银 · 60Hz", "办公", {"尺寸": "27 英寸", "分辨率": "3840×2160"}),
            ("PRD-MUG-01", "保温随行杯", "石墨灰 · 480ml", "生活方式", {"容量": "480ml", "颜色": "石墨灰"}),
            ("PRD-PLAN-02", "Agenora Team 季度订阅", "3 个成员席位", "数字服务", {"周期": "90 天", "席位": "3"}),
            ("PRD-CHG-01", "氮化镓 65W 充电器", "白色 · 双口", "数码", {"功率": "65W", "接口": "USB-C + USB-A"}),
            ("PRD-CHAIR-01", "人体工学腰靠", "深灰", "办公", {"颜色": "深灰", "材质": "记忆棉"}),
            ("PRD-BAG-02", "防水收纳包", "墨绿 · 中号", "生活方式", {"颜色": "墨绿", "尺寸": "中号"}),
            ("PRD-BOOK-01", "产品设计方法论", "纸质书", "图书", {"装帧": "平装", "页数": "286"}),
            ("PRD-PLAN-03", "Agenora API 额度包", "100 万 Token", "数字服务", {"额度": "100 万 Token", "有效期": "180 天"}),
            ("PRD-LAMP-02", "氛围阅读灯", "暖灰", "家居", {"色温": "2700K-5000K", "功率": "10W"}),
            ("PRD-CASE-01", "磁吸平板保护套", "藏蓝", "数码配件", {"颜色": "藏蓝", "尺寸": "11 英寸"}),
            ("PRD-PLAN-04", "Agenora Pro 年度订阅", "12 个月会员权益", "数字服务", {"周期": "365 天", "账号": "当前账号"}),
            ("PRD-MOUSE-01", "静音无线鼠标", "曜石黑", "数码", {"连接": "蓝牙 + 2.4G", "颜色": "曜石黑"}),
            ("PRD-TOTE-01", "帆布托特包", "原色", "生活方式", {"材质": "帆布", "颜色": "原色"}),
            ("PRD-STAND-02", "笔记本升降支架", "银色", "办公", {"材质": "铝合金", "颜色": "银色"}),
        )
        # Together with orders 1001-1005, the statuses cover every supported
        # state and each refund decision branch: eligible, deadline-expired,
        # partial refund, full refund, awaiting confirmation, and expired.
        statuses = (
            "closed", "paid", "shipped", "completed", "partial_refunded",
            "refunded", "paid", "shipped", "completed", "paid",
            "partial_refunded", "completed", "refunded", "closed", "paid",
        )
        payment_methods = ("微信支付", "支付宝", "银行卡", "云闪付")
        logistics = ("顺丰速运", "京东物流", "中通快递", "Agenora 配送")
        order_rows: list[tuple[Any, ...]] = []
        item_rows: list[tuple[Any, ...]] = []
        refund_rows: list[tuple[Any, ...]] = []
        refund_events: list[tuple[str, str, str, str, str, dict[str, Any]]] = []
        for offset, status in enumerate(statuses, start=6):
            product_id, product_name, subtitle, category, specs = products[offset - 6]
            order_id = f"ORD-{suffix}-{1000 + offset}"
            created = now - timedelta(days=offset * 3)
            paid_at = created + timedelta(minutes=2)
            shipped_at = paid_at + timedelta(days=1)
            delivered_at = shipped_at + timedelta(days=2)
            completed_at = delivered_at + timedelta(days=7)
            discount = 0 if offset % 3 else 500
            subtotal = 8900 + offset * 2170
            total = subtotal - discount
            refunded = total if status == "refunded" else (total // 3 if status == "partial_refunded" else 0)
            is_digital = category == "数字服务"
            deadline = now - timedelta(days=1) if offset == 14 else now + timedelta(days=30 - offset)
            method = payment_methods[offset % len(payment_methods)]
            logistics_company = "数字权益中心" if is_digital else logistics[offset % len(logistics)]
            tracking = f"DIGI-{offset:04d}" if is_digital else f"AGD-{offset:04d}****{9000 + offset}"
            shipping_status = "数字权益已发放" if is_digital else {
                "paid": "待发货", "shipped": "运输中", "completed": "已签收", "partial_refunded": "已签收",
                "refunded": "未发货", "closed": "交易关闭",
            }[status]
            order_rows.append(
                (
                    order_id, user_id, status, "CNY", subtotal, discount, 0, total, total, refunded,
                    "digital" if is_digital else "physical", "agenora-web" if is_digital else "agenora-shop",
                    "Agenora 数字内容" if is_digital else "Agenora 官方店", method, f"{method} ·· {1000 + offset}",
                    shipping_status, "林*" if not is_digital else "不适用", "138****0621" if not is_digital else "不适用",
                    "上海市浦东新区世纪大道***号" if not is_digital else "不适用", logistics_company, tracking,
                    "已开票" if offset % 2 else "未开票", "个人 · 林*", self._iso(created), self._iso(paid_at),
                    self._iso(shipped_at), self._iso(delivered_at), self._iso(completed_at), self._iso(now), self._iso(deadline),
                )
            )
            quantity = 2 if offset % 4 == 0 else 1
            item_rows.append(
                (
                    f"ITM-{suffix}-{1000 + offset}-1", order_id, product_id, f"SKU-{product_id}-{offset:02d}",
                    product_name, subtitle, f"https://demo.agenora.local/products/{product_id.lower()}",
                    f"https://images.agenora.local/products/{product_id.lower()}.jpg", category,
                    json.dumps(specs, ensure_ascii=False), quantity, subtotal // quantity, discount, total,
                    shipping_status, "已全额退款" if status == "refunded" else ("部分退款" if status == "partial_refunded" else "可申请退款"),
                )
            )
            if status in {"partial_refunded", "refunded"}:
                approval_id = f"RFD-HIST-{suffix}-{1000 + offset}"
                refund_rows.append(
                    (
                        approval_id, f"RFN-{suffix}-{1000 + offset}", order_id, user_id,
                        "full" if status == "refunded" else "partial", "mock_rule_coverage", "覆盖退款状态规则的历史退款",
                        refunded, "CNY", f"{method} ·· {1000 + offset}", "completed", f"确认退款 {approval_id}",
                        self._iso(created + timedelta(days=1)), self._iso(created + timedelta(days=5)),
                        self._iso(created + timedelta(days=2)), self._iso(created), self._iso(created + timedelta(days=2)),
                    )
                )
                refund_events.append((approval_id, "refund_completed", "completed", "退款已原路退回", self._iso(created + timedelta(days=2)), {"amount_minor": refunded, "currency": "CNY"}))
            if offset == 17:
                approval_id = f"RFD-PENDING-{suffix}-{1000 + offset}"
                phrase = f"确认退款 {approval_id}"
                refund_rows.append((approval_id, None, order_id, user_id, "partial", "awaiting_confirmation", "等待确认的部分退款", total // 2, "CNY", f"{method} ·· {1000 + offset}", "awaiting_confirmation", phrase, self._iso(now + timedelta(minutes=10)), None, None, self._iso(now), self._iso(now)))
                refund_events.append((approval_id, "refund_prepared", "awaiting_confirmation", "已创建退款确认单，等待用户确认", self._iso(now), {"amount_minor": total // 2, "currency": "CNY"}))
            if offset == 14:
                approval_id = f"RFD-EXPIRED-{suffix}-{1000 + offset}"
                refund_rows.append((approval_id, None, order_id, user_id, "partial", "confirmation_expired", "已过期的退款确认单", total // 2, "CNY", f"{method} ·· {1000 + offset}", "expired", f"确认退款 {approval_id}", self._iso(now - timedelta(minutes=1)), None, None, self._iso(now - timedelta(hours=1)), self._iso(now)))
                refund_events.append((approval_id, "confirmation_expired", "expired", "确认已过期，请重新发起退款", self._iso(now), {}))
        conn.executemany(
            """INSERT OR IGNORE INTO orders(order_id, user_id, status, currency, subtotal_minor, discount_minor, shipping_minor, total_minor, paid_minor, refunded_minor, order_type, sales_channel, store_name, payment_method, payment_transaction_masked, shipping_status, recipient_name_masked, recipient_phone_masked, shipping_address_masked, logistics_company, tracking_number, invoice_status, invoice_title, created_at, paid_at, shipped_at, delivered_at, completed_at, updated_at, refund_deadline_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            order_rows,
        )
        conn.executemany(
            """INSERT OR IGNORE INTO order_items(item_id, order_id, product_id, sku_id, product_name, product_subtitle, product_url, image_url, category, specifications_json, quantity, unit_price_minor, discount_minor, paid_minor, fulfillment_status, after_sale_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            item_rows,
        )
        conn.executemany(
            """INSERT OR IGNORE INTO refunds(approval_id, refund_no, order_id, user_id, refund_type, reason_code, reason, amount_minor, currency, payment_method, status, confirmation_phrase, expires_at, estimated_arrival_at, executed_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            refund_rows,
        )
        for approval_id, event_type, status, message, occurred_at, details in refund_events:
            self._append_refund_event(conn, approval_id, event_type, status, message, occurred_at, details)
        conn.execute(
            """INSERT INTO demo_seed_versions(user_id, version, seeded_at) VALUES (?, 2, ?)
            ON CONFLICT(user_id) DO UPDATE SET version = excluded.version, seeded_at = excluded.seeded_at""",
            (user_id, self._iso(now)),
        )

    def _ensure_demo_orders(self, conn: sqlite3.Connection, user_id: str) -> None:
        row = conn.execute("SELECT 1 FROM orders WHERE user_id = ? LIMIT 1", (user_id,)).fetchone()
        if row is not None:
            item = conn.execute(
                """SELECT 1 FROM order_items items
                JOIN orders ON orders.order_id = items.order_id
                WHERE orders.user_id = ? LIMIT 1""",
                (user_id,),
            ).fetchone()
            if item is not None:
                self._ensure_extra_demo_orders(conn, user_id, "".join(ch for ch in user_id if ch.isalnum())[:8] or "guest")
                return
            # Upgrade the original two-field mock in place. Existing order ids
            # and completed refunds remain valid; INSERT OR IGNORE below adds
            # the missing product records and the broader demo-state coverage.
        suffix = "".join(ch for ch in user_id if ch.isalnum())[:8] or "guest"
        now = self._now()
        t1, t2, t3, t4, t5 = (now - timedelta(days=2), now - timedelta(days=8), now - timedelta(days=15), now - timedelta(days=28), now - timedelta(days=45))
        orders = [
            (f"ORD-{suffix}-1001", user_id, "paid", "CNY", 12900, 1200, 0, 11700, 11700, 0, "physical", "agenora-shop", "Agenora 官方店", "微信支付", "微信支付 ·· 8821", "待发货", "林*", "138****0621", "上海市浦东新区世纪大道***号", None, None, "未开票", None, self._iso(t1), self._iso(t1 + timedelta(minutes=2)), None, None, None, self._iso(now), self._iso(now + timedelta(days=5))),
            (f"ORD-{suffix}-1002", user_id, "completed", "CNY", 5900, 0, 0, 5900, 5900, 0, "digital", "agenora-web", "Agenora 数字内容", "支付宝", "支付宝 ·· 2008", "无需物流", None, None, None, None, None, "已开票", "个人 · 林*", self._iso(t2), self._iso(t2 + timedelta(minutes=1)), None, self._iso(t2 + timedelta(minutes=3)), self._iso(t2 + timedelta(minutes=3)), self._iso(now), self._iso(now + timedelta(days=7))),
            (f"ORD-{suffix}-1003", user_id, "shipped", "CNY", 32900, 3000, 0, 29900, 29900, 0, "physical", "agenora-shop", "Agenora 生活馆", "微信支付", "微信支付 ·· 8821", "运输中", "林*", "138****0621", "上海市浦东新区世纪大道***号", "顺丰速运", "SF1548****931", "未开票", None, self._iso(t3), self._iso(t3 + timedelta(minutes=1)), self._iso(t3 + timedelta(days=1)), None, None, self._iso(now), self._iso(now + timedelta(days=15))),
            (f"ORD-{suffix}-1004", user_id, "partial_refunded", "CNY", 39800, 5000, 0, 34800, 34800, 9900, "physical", "agenora-shop", "Agenora 官方店", "银行卡", "招商银行储蓄卡 ·· 4812", "已签收", "林*", "138****0621", "上海市浦东新区世纪大道***号", "京东物流", "JDVA0045****108", "已开票", "个人 · 林*", self._iso(t4), self._iso(t4 + timedelta(minutes=2)), self._iso(t4 + timedelta(days=1)), self._iso(t4 + timedelta(days=3)), self._iso(t4 + timedelta(days=10)), self._iso(now), self._iso(now + timedelta(days=2))),
            (f"ORD-{suffix}-1005", user_id, "refunded", "CNY", 9900, 0, 0, 9900, 9900, 9900, "physical", "agenora-shop", "Agenora 官方店", "支付宝", "支付宝 ·· 2008", "未发货", "林*", "138****0621", "上海市浦东新区世纪大道***号", None, None, "未开票", None, self._iso(t5), self._iso(t5 + timedelta(minutes=1)), None, None, None, self._iso(now), self._iso(t5 + timedelta(days=7))),
        ]
        conn.executemany(
            """INSERT OR IGNORE INTO orders(order_id, user_id, status, currency, subtotal_minor, discount_minor, shipping_minor, total_minor, paid_minor, refunded_minor, order_type, sales_channel, store_name, payment_method, payment_transaction_masked, shipping_status, recipient_name_masked, recipient_phone_masked, shipping_address_masked, logistics_company, tracking_number, invoice_status, invoice_title, created_at, paid_at, shipped_at, delivered_at, completed_at, updated_at, refund_deadline_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            orders,
        )
        item_rows = [
            (f"ITM-{suffix}-1001-1", f"ORD-{suffix}-1001", "PRD-AIR-01", "SKU-AIR-01-BLK", "AeroPods 降噪耳机", "蓝牙 5.4 · 玄曜黑", "https://demo.agenora.local/products/aeropods-pro", "https://images.agenora.local/products/aeropods-pro-black.jpg", "数码", '{"颜色":"玄曜黑","保修":"2 年"}', 1, 12900, 1200, 11700, "待发货", "可申请退款"),
            (f"ITM-{suffix}-1002-1", f"ORD-{suffix}-1002", "PRD-PLAN-01", "SKU-PLAN-PRO-M", "Agenora Pro 月度订阅", "30 天会员权益", "https://demo.agenora.local/products/pro-monthly", "https://images.agenora.local/products/pro-monthly.jpg", "数字服务", '{"周期":"30 天","账号":"当前账号"}', 1, 5900, 0, 5900, "已发放", "可申请退款"),
            (f"ITM-{suffix}-1003-1", f"ORD-{suffix}-1003", "PRD-LIFE-01", "SKU-LIFE-01-L", "轻量防泼水通勤双肩包", "深灰 · 20L", "https://demo.agenora.local/products/commute-backpack", "https://images.agenora.local/products/commute-backpack.jpg", "生活方式", '{"颜色":"深灰","容量":"20L"}', 1, 32900, 3000, 29900, "运输中", "可申请退款"),
            (f"ITM-{suffix}-1004-1", f"ORD-{suffix}-1004", "PRD-DESK-01", "SKU-DESK-01-W", "铝合金桌面支架", "银色", "https://demo.agenora.local/products/desk-stand", "https://images.agenora.local/products/desk-stand.jpg", "办公", '{"颜色":"银色","材质":"铝合金"}', 1, 19900, 0, 19900, "已签收", "已退款 ¥99.00"),
            (f"ITM-{suffix}-1004-2", f"ORD-{suffix}-1004", "PRD-LIGHT-01", "SKU-LIGHT-01-W", "护眼桌面灯", "暖白光", "https://demo.agenora.local/products/desk-lamp", "https://images.agenora.local/products/desk-lamp.jpg", "办公", '{"色温":"4000K","功率":"12W"}', 1, 19900, 5000, 14900, "已签收", "可申请退款"),
            (f"ITM-{suffix}-1005-1", f"ORD-{suffix}-1005", "PRD-CABLE-01", "SKU-CABLE-01-2M", "编织 USB-C 快充线", "2 米 · 深蓝", "https://demo.agenora.local/products/braided-usbc-cable", "https://images.agenora.local/products/braided-usbc-cable.jpg", "数码配件", '{"长度":"2 米","颜色":"深蓝"}', 1, 9900, 0, 9900, "未发货", "已全额退款"),
        ]
        conn.executemany(
            """INSERT OR IGNORE INTO order_items(item_id, order_id, product_id, sku_id, product_name, product_subtitle, product_url, image_url, category, specifications_json, quantity, unit_price_minor, discount_minor, paid_minor, fulfillment_status, after_sale_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            item_rows,
        )
        completed_at = self._iso(now - timedelta(days=40))
        historical_refunds = [
            (f"RFD-HIST-{suffix}-1004", f"RFN-{suffix}-1004", f"ORD-{suffix}-1004", user_id, "partial", "wrong_item", "商品与描述不符", 9900, "CNY", "招商银行储蓄卡 ·· 4812", "completed", f"确认退款 RFD-HIST-{suffix}-1004", completed_at, self._iso(now - timedelta(days=39)), completed_at, completed_at, completed_at),
            (f"RFD-HIST-{suffix}-1005", f"RFN-{suffix}-1005", f"ORD-{suffix}-1005", user_id, "full", "no_longer_needed", "不再需要", 9900, "CNY", "支付宝 ·· 2008", "completed", f"确认退款 RFD-HIST-{suffix}-1005", completed_at, self._iso(now - timedelta(days=42)), self._iso(now - timedelta(days=44)), self._iso(now - timedelta(days=42)), self._iso(now - timedelta(days=42))),
        ]
        conn.executemany(
            """INSERT OR IGNORE INTO refunds(approval_id, refund_no, order_id, user_id, refund_type, reason_code, reason, amount_minor, currency, payment_method, status, confirmation_phrase, expires_at, estimated_arrival_at, executed_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            historical_refunds,
        )
        for approval_id, _, order_id, _, _, _, _, amount, currency, _, _, _, _, _, executed_at, created_at, _ in historical_refunds:
            self._append_refund_event(conn, approval_id, "refund_completed", "completed", "退款已原路退回", executed_at or created_at, {"order_id": order_id, "amount_minor": amount, "currency": currency})
        self._ensure_extra_demo_orders(conn, user_id, suffix, now)

    def list_orders(self, actor_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            self._ensure_demo_orders(conn, actor_id)
            rows = conn.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC, order_id ASC", (actor_id,)).fetchall()
            orders = [self._serialize_order(conn, row, include_refunds=False) for row in rows]
        return {"status": "ok", "total": len(orders), "orders": orders}

    def get_order(self, actor_id: str, order_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            self._ensure_demo_orders(conn, actor_id)
            row = conn.execute("SELECT * FROM orders WHERE order_id = ? AND user_id = ?", (order_id.strip(), actor_id)).fetchone()
            if row is None:
                return {"status": "not_found", "message": "未找到属于当前用户的订单。"}
            order = self._serialize_order(conn, row, include_refunds=True)
        return {"status": "ok", "order": order}

    def list_refunds(self, actor_id: str, order_id: str | None = None) -> dict[str, Any]:
        with self._connect() as conn:
            self._ensure_demo_orders(conn, actor_id)
            if order_id:
                rows = conn.execute("SELECT * FROM refunds WHERE user_id = ? AND order_id = ? ORDER BY created_at DESC", (actor_id, order_id.strip())).fetchall()
            else:
                rows = conn.execute("SELECT * FROM refunds WHERE user_id = ? ORDER BY created_at DESC", (actor_id,)).fetchall()
            refunds = [self._serialize_refund(conn, row, include_timeline=False) for row in rows]
        return {"status": "ok", "total": len(refunds), "refunds": refunds}

    def get_refund(self, actor_id: str, refund_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            self._ensure_demo_orders(conn, actor_id)
            row = conn.execute("SELECT * FROM refunds WHERE user_id = ? AND (approval_id = ? OR refund_no = ?) ORDER BY created_at DESC LIMIT 1", (actor_id, refund_id.strip(), refund_id.strip())).fetchone()
            if row is None:
                return {"status": "not_found", "message": "未找到属于当前用户的退款记录。"}
            refund = self._serialize_refund(conn, row, include_timeline=True)
        return {"status": "ok", "refund": refund}

    def _prepare_response(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        order = conn.execute("SELECT * FROM orders WHERE order_id = ?", (row["order_id"],)).fetchone()
        items = self._items_for_order(conn, row["order_id"])
        first_item = items[0] if items else {}
        return {
            "status": "awaiting_confirmation", "approval_id": row["approval_id"], "order_id": row["order_id"],
            "amount_minor": self._minor(row["amount_minor"]), "currency": row["currency"], "refund_type": row["refund_type"],
            "reason": row["reason"], "refund_to": row["payment_method"], "expires_at": row["expires_at"],
            "product_name": first_item.get("product_name"), "product_url": first_item.get("product_url"),
            "order_status_label": _ORDER_STATUS_LABELS.get(order["status"], order["status"]) if order else None,
            "confirmation_phrase": row["confirmation_phrase"],
            "message": "退款尚未执行。请让用户单独发送 confirmation_phrase 后再调用确认工具。",
        }

    def prepare_refund(self, actor_id: str, order_id: str, reason: str, amount_minor: int | None = None) -> dict[str, Any]:
        reason = reason.strip()
        if not reason:
            return {"status": "invalid", "message": "退款原因不能为空。"}
        if len(reason) > 500:
            return {"status": "invalid", "message": "退款原因不能超过 500 个字符。"}
        with self._connect() as conn:
            self._ensure_demo_orders(conn, actor_id)
            order = conn.execute("SELECT * FROM orders WHERE order_id = ? AND user_id = ?", (order_id.strip(), actor_id)).fetchone()
            if order is None:
                return {"status": "not_found", "message": "未找到属于当前用户的订单。"}
            eligible, ineligible_reason = self._is_refundable(order)
            if not eligible:
                return {"status": "invalid", "message": ineligible_reason or "订单当前不可退款。"}
            refundable = max(0, self._minor(order["total_minor"]) - self._minor(order["refunded_minor"]))
            requested = refundable if amount_minor is None else int(amount_minor)
            if requested <= 0 or requested > refundable:
                return {"status": "invalid", "message": f"可退款金额为 {refundable} 分。"}
            now = self._now()
            existing = conn.execute("SELECT * FROM refunds WHERE order_id = ? AND user_id = ? AND amount_minor = ? AND reason = ? AND status = 'awaiting_confirmation' ORDER BY created_at DESC LIMIT 1", (order["order_id"], actor_id, requested, reason)).fetchone()
            if existing is not None and now <= datetime.fromisoformat(existing["expires_at"]):
                # LangGraph may replay a node on resume; this makes prepare idempotent.
                return self._prepare_response(conn, existing)
            approval_id = f"RFD-{uuid.uuid4().hex[:12].upper()}"
            phrase = f"确认退款 {approval_id}"
            expires = now + timedelta(minutes=10)
            refund_type = "full" if requested == refundable else "partial"
            now_iso = now.isoformat()
            conn.execute(
                """INSERT INTO refunds(approval_id, order_id, user_id, refund_type, reason_code, reason, amount_minor, currency, payment_method, status, confirmation_phrase, expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'awaiting_confirmation', ?, ?, ?, ?)""",
                (approval_id, order["order_id"], actor_id, refund_type, "user_requested", reason, requested, order["currency"], order["payment_method"], phrase, expires.isoformat(), now_iso, now_iso),
            )
            self._append_refund_event(conn, approval_id, "refund_prepared", "awaiting_confirmation", "已创建退款确认单，等待用户确认", now_iso, {"order_id": order["order_id"], "amount_minor": requested, "currency": order["currency"]})
            row = conn.execute("SELECT * FROM refunds WHERE approval_id = ?", (approval_id,)).fetchone()
        return self._prepare_response(conn, row)

    def confirm_refund(self, actor_id: str, approval_id: str, confirmation_text: str) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            refund = conn.execute("SELECT * FROM refunds WHERE approval_id = ? AND user_id = ?", (approval_id.strip(), actor_id)).fetchone()
            if refund is None:
                return {"status": "not_found", "message": "未找到待确认退款。"}
            if refund["status"] == "completed":
                return {"status": "already_completed", "approval_id": refund["approval_id"], "refund_no": refund["refund_no"], "order_id": refund["order_id"]}
            if refund["status"] != "awaiting_confirmation":
                return {"status": "invalid", "message": "退款当前不可执行。"}
            if self._now() > datetime.fromisoformat(refund["expires_at"]):
                now = self._now().isoformat()
                conn.execute("UPDATE refunds SET status = 'expired', updated_at = ? WHERE approval_id = ?", (now, refund["approval_id"]))
                self._append_refund_event(conn, refund["approval_id"], "confirmation_expired", "expired", "确认已过期，请重新发起退款", now)
                return {"status": "expired", "message": "确认已过期，请重新发起退款。"}
            if confirmation_text.strip() != refund["confirmation_phrase"]:
                return {"status": "confirmation_mismatch", "message": "确认文本不匹配，退款未执行。"}
            order = conn.execute("SELECT * FROM orders WHERE order_id = ? AND user_id = ?", (refund["order_id"], actor_id)).fetchone()
            if order is None:
                return {"status": "not_found", "message": "原订单不存在。"}
            refundable = max(0, self._minor(order["total_minor"]) - self._minor(order["refunded_minor"]))
            if self._minor(refund["amount_minor"]) > refundable:
                return {"status": "invalid", "message": "订单可退款金额已变化，请重新发起退款。"}
            now = self._now()
            now_iso = now.isoformat()
            refund_no = f"RFN-{uuid.uuid4().hex[:12].upper()}"
            estimated = (now + timedelta(minutes=5)).isoformat()
            new_refunded = self._minor(order["refunded_minor"]) + self._minor(refund["amount_minor"])
            next_status = "refunded" if new_refunded >= self._minor(order["total_minor"]) else "partial_refunded"
            conn.execute("UPDATE orders SET refunded_minor = ?, status = ?, updated_at = ? WHERE order_id = ?", (new_refunded, next_status, now_iso, order["order_id"]))
            conn.execute("UPDATE refunds SET refund_no = ?, status = 'completed', executed_at = ?, estimated_arrival_at = ?, updated_at = ? WHERE approval_id = ?", (refund_no, now_iso, estimated, now_iso, refund["approval_id"]))
            self._append_refund_event(conn, refund["approval_id"], "refund_completed", "completed", "退款已受理，将原路退回", now_iso, {"refund_no": refund_no, "amount_minor": refund["amount_minor"], "currency": order["currency"]})
        return {"status": "completed", "approval_id": refund["approval_id"], "refund_no": refund_no, "order_id": refund["order_id"], "amount_minor": self._minor(refund["amount_minor"]), "currency": order["currency"], "refund_to": refund["payment_method"], "executed_at": now_iso, "estimated_arrival_at": estimated, "order_status": next_status}
