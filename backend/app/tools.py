from .db import transaction, event, uid
from .routing import case_locked, routes, reserve, proposal, finding, Conflict, merchant
from psycopg.types.json import Jsonb

PERMISSIONS = {
    "returns": {"get_case", "create_proposal"},
    "policy": {"get_case", "search_policy", "record_policy_finding"},
    "fulfillment": {
        "get_case",
        "find_waiting_orders",
        "compare_routes",
        "reserve_item",
        "release_reservation",
        "discover_destinations",
    },
}
SCHEMAS = {
    "get_case": {},
    "search_policy": {"query": {"type": "string", "maxLength": 500}},
    "find_waiting_orders": {},
    "compare_routes": {},
    "reserve_item": {"buyer_order_id": {"type": "string"}, "expected_version": {"type": "integer"}},
    "release_reservation": {
        "reservation_id": {"type": "string"},
        "expected_version": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "discover_destinations": {},
    "record_policy_finding": {
        "expected_version": {"type": "integer"},
        "passage_ids": {"type": "array", "items": {"type": "string"}},
    },
    "create_proposal": {
        "expected_version": {"type": "integer"},
        "destination_id": {"type": "string"},
    },
}


def declarations(role):
    return [
        {
            "name": name,
            "description": name.replace("_", " ") + " for the trusted current return only.",
            "input_schema": {
                "type": "object",
                "properties": SCHEMAS[name],
                "required": list(SCHEMAS[name]),
                "additionalProperties": False,
            },
        }
        for name in sorted(PERMISSIONS[role])
    ]


def execute(conn, role, case_id, delivery_version, name, args):
    if name not in PERMISSIONS[role]:
        raise Conflict("This agent cannot use that tool.")
    case = case_locked(conn, case_id, delivery_version)
    if "expected_version" in SCHEMAS[name] and args.get("expected_version") != case["version"]:
        raise Conflict("Stale tool request.")
    if case["status"] in ("approved", "exception", "rejected") and name != "get_case":
        raise Conflict("Case is closed for agent mutations.")
    if name == "get_case":
        return {
            "id": case["id"],
            "version": case["version"],
            "status": case["status"],
            "facts": {k: v for k, v in case["data"].items() if k != "inspection_photos"},
            "inspection_photo_count": len(case["data"].get("inspection_photos", [])),
            "current_routes": routes(conn, case),
        }
    if name == "find_waiting_orders":
        return conn.execute(
            "SELECT * FROM buyer_orders WHERE data->>'sku'=%s AND fulfilled=false",
            (case["data"]["sku"],),
        ).fetchall()
    if name == "compare_routes":
        return routes(conn, case)
    if name == "reserve_item":
        return reserve(conn, case, args["buyer_order_id"])
    if name == "release_reservation":
        row = conn.execute(
            "UPDATE reservations SET status='released' WHERE id=%s AND case_id=%s AND status='active' RETURNING *",
            (args["reservation_id"], case_id),
        ).fetchone()
        event(conn, case, "reservation_released", {"message": args["reason"]}, role)
        return row or {"already_released": True}
    if name == "record_policy_finding":
        # IDs must have been retrieved by this case/version's Moss query.
        fetched = case["data"].get("policy_passage_ids", [])
        if (
            case["data"].get("policy_case_version") != case["version"]
            or case["data"].get("retrieval_policy_version") != merchant(conn)["policy_version"]
            or case["data"].get("policy_retrieval_provider") != "moss"
        ):
            raise Conflict("Policy evidence belongs to older facts or policy.")
        if not set(args["passage_ids"]) <= set(fetched):
            raise Conflict("Evidence was not retrieved for this review.")
        return finding(conn, case, args["passage_ids"], "live Moss retrieval")
    if name == "create_proposal":
        return proposal(conn, case, args["destination_id"])
    raise Conflict("Tool needs provider execution.")
