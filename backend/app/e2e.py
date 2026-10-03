"""Exercise the actual running HTTP API and worker, without revealing credentials.
Run through the api container. This adds a uniquely named synthetic return.
"""

import os, time, json
import httpx


def main():
    origin = os.environ["APP_ORIGIN"]
    with httpx.Client(base_url="http://api:8000", headers={"Origin": origin}, timeout=10) as client:
        assert client.get("/api/returns").status_code == 401
        assert (
            client.post(
                "/api/login", json={"passcode": os.environ["MERCHANT_PASSCODE"]}
            ).status_code
            == 200
        )
        result = client.post(
            "/api/returns",
            json={
                "sku": "LAMP-04",
                "origin_zone_id": "zone-oakland",
                "reported_condition": "sealed",
                "reason": "Container HTTP persistence verification",
            },
        )
        result.raise_for_status()
        case = result.json()
        cid = case["id"]
        for _ in range(30):
            d = client.get("/api/returns/" + cid).json()
            if d["case"]["status"] == "awaiting_approval":
                break
            time.sleep(1)
        assert d["case"]["status"] == "awaiting_approval", d
        p = next(p for p in d["proposals"] if p["status"] == "pending")
        payload = {
            "expected_version": 1,
            "proposal_id": p["id"],
            "request_key": "http-" + cid,
            "confirmed_condition": True,
        }
        first = client.post("/api/returns/" + cid + "/approve", json=payload)
        first.raise_for_status()
        second = client.post("/api/returns/" + cid + "/approve", json=payload)
        second.raise_for_status()
        assert first.json()["id"] == second.json()["id"]
        print(
            json.dumps(
                {
                    "case_id": cid,
                    "shipment_id": first.json()["id"],
                    "duplicate_approval": "same shipment",
                    "warehouse_cost_cents": p["data"]["warehouse_cost_cents"],
                }
            )
        )


if __name__ == "__main__":
    main()
