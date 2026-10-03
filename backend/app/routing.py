from datetime import datetime, timezone, timedelta
from .db import event, enqueue, uid
from psycopg.types.json import Jsonb


class Conflict(Exception):
    pass


def case_locked(conn, case_id, version=None):
    case = conn.execute("SELECT * FROM return_cases WHERE id=%s FOR UPDATE", (case_id,)).fetchone()
    if not case:
        raise Conflict("Return not found")
    if version is not None and case["version"] != version:
        raise Conflict("Facts changed. Refresh this return before continuing.")
    return case


def merchant(conn):
    return conn.execute("SELECT data FROM merchants WHERE id='merchant-demo-01'").fetchone()["data"]


def expire(conn):
    expired = conn.execute(
        "UPDATE reservations SET status='expired' WHERE status='active' AND expires_at<=now() RETURNING case_id"
    ).fetchall()
    for r in expired:
        conn.execute(
            "UPDATE route_proposals SET status='expired' WHERE case_id=%s AND status='pending'",
            (r["case_id"],),
        )
        c = conn.execute("SELECT * FROM return_cases WHERE id=%s", (r["case_id"],)).fetchone()
        conn.execute(
            "UPDATE return_cases SET status='needs_review' WHERE id=%s AND status!='approved'",
            (c["id"],),
        )
        # A new job type allows recovery even when the original plan job is done.
        enqueue(conn, c, "expiry")
        event(
            conn,
            c,
            "reservation_expired",
            {"message": "Reservation expired; fresh review required."},
            "system",
        )


def routes(conn, case):
    m = merchant(conn)
    data = case["data"]
    condition = data.get("inspection_condition") or data["reported_condition"]
    product = conn.execute("SELECT data FROM products WHERE id=%s", (data["sku"],)).fetchone()[
        "data"
    ]
    quotes = [r["data"] for r in conn.execute("SELECT data FROM quotes").fetchall()]

    def cost(zone, fee):
        q = next(
            (
                q
                for q in quotes
                if q["origin_zone_id"] == data["origin_zone_id"]
                and q["destination_zone_id"] == zone
                and q["max_weight_g"] >= product["weight_g"]
            ),
            None,
        )
        if q is None:
            return None
        return {
            "shipping_cost_cents": q["shipping_cost_cents"],
            "handling_fee_cents": fee,
            "total_cents": q["shipping_cost_cents"] + fee,
            "transit_hours": q["estimated_transit_hours"],
            "quote_source": q["quote_source"],
        }

    result = []
    in_window = data.get("elapsed_since_purchase_days", 0) <= m["rules"]["return_window_days"]
    for row in conn.execute("SELECT * FROM destinations ORDER BY id").fetchall():
        d = row["data"]
        c = (
            cost(d.get("zone_id"), d.get("handling_fee_cents", 0))
            if d.get("type") in ("warehouse", "inspection")
            else (
                {
                    "shipping_cost_cents": d["shipping_cost_cents"],
                    "handling_fee_cents": d["service_fee_cents"],
                    "total_cents": d["shipping_cost_cents"] + d["service_fee_cents"],
                    "transit_hours": d.get("transit_hours", 24),
                    "quote_source": "merchant_verified_estimate",
                }
                if d.get("shipping_cost_cents") is not None
                and d.get("service_fee_cents") is not None
                else None
            )
        )
        reason = None
        if not in_window:
            reason = "Outside the 30-day return window; merchant review required."
        elif d["acceptance_status"] not in ("merchant_approved", "verified"):
            reason = "Merchant must verify acceptance and costs."
        elif condition not in d.get("accepted_conditions", []):
            reason = f"{condition.capitalize()} items are not accepted here."
        elif product["category"] not in d.get("accepted_categories", [product["category"]]):
            reason = "Category not accepted."
        elif c is None:
            reason = "No shipping estimate is available."
        result.append(
            {
                "destination_id": row["id"],
                "name": d["name"],
                "type": d["type"],
                "eligible": reason is None,
                "reason": reason,
                "cost": c,
                "source_url": d.get("source_url"),
            }
        )
    for b in conn.execute(
        "SELECT * FROM buyer_orders WHERE data->>'sku'=%s ORDER BY id", (data["sku"],)
    ).fetchall():
        d = b["data"]
        c = cost(d["destination_zone_id"], m["cost_rules"]["buyer_handling_fee_cents"])
        reason = None
        reserved = conn.execute(
            "SELECT case_id FROM reservations WHERE buyer_id=%s AND status='active' AND expires_at>now()",
            (b["id"],),
        ).fetchone()
        if not in_window:
            reason = "Outside return window."
        elif not m["rules"]["direct_forwarding_enabled"]:
            reason = "Current policy disables forwarding."
        elif condition not in m["rules"]["direct_forwarding_conditions"]:
            reason = (
                f"{condition.capitalize()} condition blocks direct forwarding; inspection required."
            )
        elif condition != d["required_condition"]:
            reason = "Condition does not meet the waiting buyer requirement."
        elif b["fulfilled"]:
            reason = "Buyer order already fulfilled."
        elif reserved and reserved["case_id"] != case["id"]:
            reason = "Reserved for another return."
        elif c is None:
            reason = "No shipping estimate is available."
        elif datetime.now(timezone.utc) + timedelta(hours=c["transit_hours"]) > b["deadline"]:
            reason = "Arrival would miss the buyer deadline."
        result.append(
            {
                "destination_id": b["id"],
                "name": d["customer_alias"],
                "type": "buyer",
                "eligible": reason is None,
                "reason": reason,
                "cost": c,
                "conditional": not data.get("inspection_condition"),
            }
        )
    return sorted(
        result, key=lambda r: (not r["eligible"], (r["cost"] or {}).get("total_cents", 10**12))
    )


def reserve(conn, case, buyer_id, ttl=None):
    # Serialize buyer assignment; uniqueness protects against independent callers too.
    conn.execute("SELECT id FROM buyer_orders WHERE id=%s FOR UPDATE", (buyer_id,)).fetchone()
    expire(conn)
    existing = conn.execute(
        "SELECT * FROM reservations WHERE case_id=%s AND status='active'", (case["id"],)
    ).fetchone()
    if existing:
        if existing["buyer_id"] == buyer_id and existing["version"] == case["version"]:
            return existing
        raise Conflict("This item already has a reservation.")
    if not any(r["destination_id"] == buyer_id and r["eligible"] for r in routes(conn, case)):
        raise Conflict("Buyer route is no longer eligible.")
    if conn.execute(
        "SELECT 1 FROM reservations WHERE buyer_id=%s AND status='active'", (buyer_id,)
    ).fetchone():
        raise Conflict("Another return reserved this buyer.")
    return conn.execute(
        "INSERT INTO reservations VALUES(%s,%s,%s,%s,'active',%s) RETURNING *",
        (
            uid("RSV"),
            case["id"],
            buyer_id,
            case["version"],
            datetime.now(timezone.utc)
            + timedelta(seconds=ttl or merchant(conn)["cost_rules"]["reservation_ttl_seconds"]),
        ),
    ).fetchone()


def invalidate(conn, case, reason):
    conn.execute(
        "UPDATE route_proposals SET status='invalidated' WHERE case_id=%s AND status='pending'",
        (case["id"],),
    )
    conn.execute(
        "UPDATE reservations SET status='released' WHERE case_id=%s AND status='active'",
        (case["id"],),
    )
    event(conn, case, "plan_invalidated", {"message": reason}, "system")


def finding(conn, case, passage_ids, origin):
    m = merchant(conn)
    evidence = [
        r["data"]
        for r in conn.execute(
            "SELECT data FROM policy_passages WHERE id=ANY(%s)", (passage_ids,)
        ).fetchall()
    ]
    condition = case["data"].get("inspection_condition") or case["data"]["reported_condition"]
    required = {
        "sealed": "POL-002",
        "opened": "POL-003",
        "damaged": "POL-004",
        "unknown": "POL-005",
    }[condition]
    if required not in passage_ids or any(
        p["policy_version"] != m["policy_version"] for p in evidence
    ):
        raise Conflict("Usable current policy evidence is missing. Merchant review required.")
    data = dict(case["data"])
    data["finding"] = {
        "condition": condition,
        "direct_forwarding": condition == "sealed" and m["rules"]["direct_forwarding_enabled"],
        "passages": evidence,
        "policy_version": m["policy_version"],
        "origin": origin,
        "case_version": case["version"],
    }
    conn.execute("UPDATE return_cases SET data=%s WHERE id=%s", (Jsonb(data), case["id"]))
    case["data"] = data
    event(
        conn,
        case,
        "policy_review",
        {
            "message": f"Policy reviewed {condition} condition.",
            "passage_ids": passage_ids,
            "origin": origin,
        },
        "policy",
    )
    return data["finding"]


def proposal(conn, case, destination_id):
    if case["status"] == "approved":
        raise Conflict("Shipment is already approved; human exception handling required.")
    m = merchant(conn)
    f = case["data"].get("finding")
    if not f or f["case_version"] != case["version"] or f["policy_version"] != m["policy_version"]:
        raise Conflict("Current policy review is required.")
    options = routes(conn, case)
    route = next(
        (r for r in options if r["destination_id"] == destination_id and r["eligible"]), None
    )
    if not route:
        raise Conflict("Destination is not eligible.")
    if route["type"] == "buyer":
        reserve(conn, case, destination_id)
    else:
        conn.execute(
            "UPDATE reservations SET status='released' WHERE case_id=%s AND status='active'",
            (case["id"],),
        )
    old = conn.execute(
        "SELECT * FROM route_proposals WHERE case_id=%s AND status='pending'", (case["id"],)
    ).fetchone()
    if old and old["case_version"] == case["version"] and old["destination_id"] == destination_id:
        return old
    conn.execute(
        "UPDATE route_proposals SET status='superseded' WHERE case_id=%s AND status='pending'",
        (case["id"],),
    )
    warehouse = next((r for r in options if r["type"] == "warehouse" and r["eligible"]), None)
    data = {
        "route": route,
        "evidence": f,
        "warehouse_cost_cents": warehouse["cost"]["total_cents"] if warehouse else None,
        "estimated_saving_cents": (
            warehouse["cost"]["total_cents"] - route["cost"]["total_cents"] if warehouse else None
        ),
        "simulated": True,
    }
    p = conn.execute(
        "INSERT INTO route_proposals(id,case_id,case_version,policy_version,destination_id,data) VALUES(%s,%s,%s,%s,%s,%s) RETURNING *",
        (
            uid("PLAN"),
            case["id"],
            case["version"],
            m["policy_version"],
            destination_id,
            Jsonb(data),
        ),
    ).fetchone()
    conn.execute("UPDATE return_cases SET status='awaiting_approval' WHERE id=%s", (case["id"],))
    event(
        conn,
        case,
        "proposal_ready",
        {
            "message": f"Proposed {route['name']}; merchant approval required.",
            "proposal_id": p["id"],
        },
        "returns",
    )
    return p


def plan_demo(conn, case):
    if case["status"] == "approved":
        return
    condition = case["data"].get("inspection_condition") or case["data"]["reported_condition"]
    ids = [
        {"sealed": "POL-002", "opened": "POL-003", "damaged": "POL-004", "unknown": "POL-005"}[
            condition
        ],
        "POL-007",
        "POL-008",
    ]
    finding(conn, case, ids, "demo fixture lookup")
    options = routes(conn, case)
    for r in options:
        if r["eligible"]:
            try:
                return proposal(conn, case, r["destination_id"])
            except Conflict:
                continue
    raise Conflict("No eligible route; merchant review required.")


def approve(conn, case_id, version, proposal_id, key, confirmed):
    case = case_locked(conn, case_id)
    key_owner = conn.execute(
        "SELECT case_id FROM shipments WHERE approval_key=%s", (key,)
    ).fetchone()
    if key_owner and key_owner["case_id"] != case_id:
        raise Conflict("Approval request key belongs to another return.")
    existing = conn.execute("SELECT * FROM shipments WHERE case_id=%s", (case_id,)).fetchone()
    if existing:
        if existing["proposal_id"] == proposal_id:
            return existing
        raise Conflict("A different plan was already shipped.")
    if case["version"] != version:
        raise Conflict("Facts changed; the old plan cannot be approved.")
    p = conn.execute(
        "SELECT * FROM route_proposals WHERE id=%s AND case_id=%s", (proposal_id, case_id)
    ).fetchone()
    if (
        not p
        or p["status"] != "pending"
        or p["case_version"] != version
        or p["policy_version"] != merchant(conn)["policy_version"]
    ):
        raise Conflict("Plan is no longer current. Request a fresh review.")
    r = next(
        (
            r
            for r in routes(conn, case)
            if r["destination_id"] == p["destination_id"] and r["eligible"]
        ),
        None,
    )
    if r is None or r["cost"] != p["data"]["route"]["cost"]:
        raise Conflict("Eligibility or costs changed; fresh proposal required.")
    if r["type"] == "buyer":
        if not case["data"].get("inspection_condition") and not confirmed:
            raise Conflict("Confirm that the item is sealed before forwarding.")
        reservation = conn.execute(
            "SELECT * FROM reservations WHERE case_id=%s AND buyer_id=%s AND status='active' AND expires_at>now() AND version=%s FOR UPDATE",
            (case_id, p["destination_id"], version),
        ).fetchone()
        if not reservation:
            raise Conflict("Reservation expired or was released; fresh review required.")
        conn.execute("UPDATE reservations SET status='consumed' WHERE id=%s", (reservation["id"],))
        conn.execute("UPDATE buyer_orders SET fulfilled=true WHERE id=%s", (p["destination_id"],))
    s = conn.execute(
        "INSERT INTO shipments VALUES(%s,%s,%s,%s,%s) RETURNING *",
        (
            uid("SHIP"),
            case_id,
            proposal_id,
            key,
            Jsonb(
                {
                    "status": "simulated",
                    "route": r,
                    "estimated_saving_cents": p["data"]["estimated_saving_cents"],
                }
            ),
        ),
    ).fetchone()
    conn.execute("UPDATE route_proposals SET status='approved' WHERE id=%s", (proposal_id,))
    conn.execute("UPDATE return_cases SET status='approved' WHERE id=%s", (case_id,))
    event(
        conn,
        case,
        "shipment_created",
        {"message": "Merchant approved one simulated shipment.", "shipment_id": s["id"]},
    )
    return s
