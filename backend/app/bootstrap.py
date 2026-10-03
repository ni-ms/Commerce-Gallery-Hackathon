import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from psycopg.types.json import Jsonb
from .db import transaction

ROOT = Path("/app")


def fixtures():
    files = {p.stem: json.loads(p.read_text()) for p in (ROOT / "fixtures").glob("*.json")}
    rules = json.loads((ROOT / "policies/routing-rules.json").read_text())
    for value in files.values():
        assert value["metadata"]["synthetic"] is True
    assert rules["metadata"]["synthetic"] is True
    products = {x["sku"] for x in files["products"]["records"]}
    zones = {x["id"] for x in files["locations"]["records"]}
    for case in files["returns"]["records"]:
        assert case["sku"] in products and case["origin_zone_id"] in zones
    for buyer in files["buyer-orders"]["records"]:
        assert buyer["sku"] in products and buyer["destination_zone_id"] in zones
    for dest in files["destinations"]["records"]:
        assert dest["zone_id"] in zones
    for quote in files["shipping-costs"]["records"]:
        assert quote["origin_zone_id"] in zones and quote["destination_zone_id"] in zones
    ids = {x["id"] for x in files["returns"]["records"]}
    for scenario in files["scenarios"]["records"]:
        assert set(scenario["case_ids"]) <= ids
    return files, rules


def seed(conn):
    files, rules = fixtures()
    mapping = {
        "merchants": "merchants",
        "products": "products",
        "locations": "locations",
        "destinations": "destinations",
        "quotes": "shipping-costs",
        "policy_passages": "policy-passages",
    }
    for table, name in mapping.items():
        for record in files[name]["records"]:
            data = dict(record)
            if table == "merchants":
                data["rules"] = rules
                data["cost_rules"] = files["shipping-costs"]["rules"]
                data["synthetic"] = True
            conn.execute(
                f"INSERT INTO {table}(id,data) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (data.get("id", data.get("sku")), Jsonb(data)),
            )
    now = datetime.now(timezone.utc)
    for record in files["buyer-orders"]["records"]:
        conn.execute(
            "INSERT INTO buyer_orders(id,data,deadline) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                record["id"],
                Jsonb(record),
                now + timedelta(hours=record["delivery_deadline_hours_from_start"]),
            ),
        )
    for record in files["returns"]["records"]:
        conn.execute(
            "INSERT INTO return_cases(id,data) VALUES(%s,%s) ON CONFLICT DO NOTHING",
            (record["id"], Jsonb(record)),
        )


def bootstrap():
    with transaction() as conn:
        conn.execute((ROOT / "migrations/001.sql").read_text())
        seed(conn)


if __name__ == "__main__":
    bootstrap()
