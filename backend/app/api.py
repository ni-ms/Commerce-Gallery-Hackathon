import os, time, secrets
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Literal
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from itsdangerous import URLSafeTimedSerializer, BadSignature
from psycopg.types.json import Jsonb
from .db import transaction, event, enqueue, uid
from .routing import Conflict, case_locked, merchant, routes, approve, invalidate
from .bootstrap import fixtures, seed

app = FastAPI(title="Smarter Returns", docs_url=None, redoc_url=None)
signer = URLSafeTimedSerializer(os.environ["APP_SESSION_SECRET"])
limits = defaultdict(deque)


@app.middleware("http")
async def protect(request: Request, call_next):
    public = request.url.path in ("/api/login", "/api/health/live", "/api/health/ready")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("origin") != os.environ.get("APP_ORIGIN", "http://localhost:8080"):
            return Response("Origin rejected", status_code=403)
        ip = request.client.host if request.client else "unknown"
        bucket = limits[ip]
        now = time.monotonic()
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= 60:
            return Response("Too many requests", status_code=429)
        bucket.append(now)
    if not public:
        try:
            signer.loads(request.cookies.get("merchant_session", ""), max_age=43200)
        except BadSignature:
            return Response("Please sign in", status_code=401)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(Conflict)
async def conflict_handler(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": str(exc)}, status_code=409)


class Login(BaseModel):
    passcode: str = Field(max_length=200)


@app.post("/api/login")
def login(body: Login, response: Response):
    if not secrets.compare_digest(body.passcode, os.environ["MERCHANT_PASSCODE"]):
        raise HTTPException(401, "Incorrect passcode")
    response.set_cookie(
        "merchant_session",
        signer.dumps("merchant-demo-01"),
        httponly=True,
        samesite="strict",
        secure=os.environ.get("APP_ORIGIN", "").startswith("https:"),
        max_age=43200,
    )
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("merchant_session")
    return {"ok": True}


@app.get("/api/health/live")
def live():
    return {"ok": True}


@app.get("/api/health/ready")
def ready():
    with transaction() as c:
        c.execute("SELECT version FROM schema_versions WHERE version=1").fetchone()
    return {"ok": True}


@app.get("/api/catalog")
def catalog():
    with transaction() as c:
        return {
            "products": [r["data"] for r in c.execute("SELECT data FROM products").fetchall()],
            "locations": [r["data"] for r in c.execute("SELECT data FROM locations").fetchall()],
            "merchant": merchant(c),
            "mode": os.environ.get("EXECUTION_MODE", "demo"),
        }


@app.get("/api/returns")
def list_returns():
    with transaction() as c:
        return c.execute("SELECT * FROM return_cases ORDER BY id").fetchall()


@app.get("/api/returns/{case_id}")
def detail(case_id: str):
    with transaction() as c:
        case = case_locked(c, case_id)
        return {
            "case": case,
            "routes": routes(c, case),
            "proposals": c.execute(
                "SELECT * FROM route_proposals WHERE case_id=%s", (case_id,)
            ).fetchall(),
            "reservations": c.execute(
                "SELECT * FROM reservations WHERE case_id=%s", (case_id,)
            ).fetchall(),
            "shipments": c.execute(
                "SELECT * FROM shipments WHERE case_id=%s", (case_id,)
            ).fetchall(),
            "destinations": [
                r["data"]
                for r in c.execute(
                    "SELECT data FROM destinations WHERE data->>'source_url' IS NOT NULL"
                ).fetchall()
            ],
        }


@app.get("/api/returns/{case_id}/events")
def events(case_id: str, after: int = 0):
    with transaction() as c:
        return c.execute(
            "SELECT * FROM case_events WHERE case_id=%s AND id>%s ORDER BY id", (case_id, after)
        ).fetchall()


class NewReturn(BaseModel):
    sku: str
    origin_zone_id: str
    reported_condition: Literal["sealed", "opened", "damaged", "unknown"]
    reason: str = Field(min_length=1, max_length=1000)
    elapsed_since_purchase_days: int = Field(default=10, ge=0, le=365)


@app.post("/api/returns")
def create_return(body: NewReturn):
    with transaction() as c:
        if (
            not c.execute("SELECT 1 FROM products WHERE id=%s", (body.sku,)).fetchone()
            or not c.execute(
                "SELECT 1 FROM locations WHERE id=%s", (body.origin_zone_id,)
            ).fetchone()
        ):
            raise HTTPException(422, "Unknown product or location")
        data = body.model_dump()
        data.update(
            merchant_id="merchant-demo-01",
            customer_alias="Demo returner",
            inspection_condition=None,
        )
        case = c.execute(
            "INSERT INTO return_cases(id,data) VALUES(%s,%s) RETURNING *", (uid("RET"), Jsonb(data))
        ).fetchone()
        enqueue(c, case)
        event(c, case, "submitted", {"message": "Return submitted for review."})
        return case


class Version(BaseModel):
    expected_version: int = Field(ge=1)


@app.post("/api/returns/{case_id}/start")
def start(case_id: str, body: Version):
    with transaction() as c:
        case = case_locked(c, case_id, body.expected_version)
        if case["status"] == "submitted":
            enqueue(c, case)
            c.execute("UPDATE return_cases SET status='working' WHERE id=%s", (case_id,))
            event(c, case, "started", {"message": "Routing review started."})
        return {"ok": True}


@app.post("/api/returns/{case_id}/recover")
def recover(case_id: str, body: Version):
    with transaction() as c:
        case = case_locked(c, case_id, body.expected_version)
        if case["status"] != "needs_review":
            return {"ok": True}
        job = c.execute("SELECT * FROM jobs WHERE case_id=%s AND version=%s AND type='plan' FOR UPDATE", (case_id, case["version"])).fetchone()
        if not job or job["status"] not in ("failed", "done"):
            raise Conflict("The review needs a condition check or provider investigation. No messages or shipping actions were repeated.")
        c.execute("UPDATE jobs SET status='pending',available_at=now(),lease_until=NULL WHERE id=%s", (job["id"],))
        c.execute("UPDATE return_cases SET status='working' WHERE id=%s", (case_id,))
        event(c, case, "recovery_requested", {"message": "Checking saved Band receipt and resuming safe setup. Shipping still requires merchant approval."})
        return {"ok": True}


class Approval(Version):
    proposal_id: str
    request_key: str = Field(min_length=1, max_length=100)
    confirmed_condition: bool = False


@app.post("/api/returns/{case_id}/approve")
def approve_route(case_id: str, body: Approval):
    # Expiry effects commit independently of the refused approval.
    from .routing import expire

    with transaction() as c:
        expire(c)
    with transaction() as c:
        return approve(
            c,
            case_id,
            body.expected_version,
            body.proposal_id,
            body.request_key,
            body.confirmed_condition,
        )


@app.post("/api/returns/{case_id}/reject")
def reject(case_id: str, body: Version):
    with transaction() as c:
        case = case_locked(c, case_id, body.expected_version)
        if case["status"] == "approved":
            raise Conflict("Approved shipment requires human exception handling.")
        invalidate(c, case, "Merchant rejected proposal.")
        c.execute(
            "UPDATE return_cases SET version=version+1,status='rejected' WHERE id=%s", (case_id,)
        )
        return {"ok": True}


class Inspection(Version):
    condition: Literal["sealed", "opened", "damaged", "unknown"]
    note: str = Field(default="", max_length=1000)
    confirmed_condition: bool = False
    photos: list[str] = Field(default_factory=list, max_length=3)


@app.post("/api/returns/{case_id}/inspection")
def inspect(case_id: str, body: Inspection):
    import base64, binascii
    if not body.confirmed_condition:
        raise HTTPException(422, "Confirm the item condition before saving your check.")
    # Photos are evidence, never inferred condition.
    for photo in body.photos:
        try:
            header, encoded = photo.split(",", 1)
            if header not in ("data:image/jpeg;base64", "data:image/png;base64", "data:image/webp;base64"):
                raise ValueError()
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) > 2_000_000 or not (raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"\x89PNG\r\n\x1a\n") or (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP")):
                raise ValueError()
        except (ValueError, binascii.Error):
            raise HTTPException(422, "Use JPEG, PNG or WebP photos up to 2 MB each.")
    with transaction() as c:
        case = case_locked(c, case_id, body.expected_version)
        data = dict(case["data"])
        data.update(
            handoffs=0,
            policy_passage_ids=[],
            inspection_condition=body.condition,
            inspection_note=body.note,
            inspection_actor="merchant",
            inspection_photos=body.photos,
            condition_confirmed=body.confirmed_condition,
        )
        case["version"] += 1
        if case["status"] == "approved":
            c.execute(
                "UPDATE return_cases SET data=%s,version=%s,status='exception' WHERE id=%s",
                (Jsonb(data), case["version"], case_id),
            )
            event(
                c,
                case,
                "shipment_exception",
                {
                    "message": "Inspection changed after shipment approval. Human intervention required; shipment was not undone."
                },
            )
        else:
            data.pop("finding", None)
            invalidate(
                c,
                case,
                "Inspection changed the facts; reservation released and old approval blocked.",
            )
            c.execute(
                "UPDATE return_cases SET data=%s,version=%s,status='working' WHERE id=%s",
                (Jsonb(data), case["version"], case_id),
            )
            enqueue(c, case)
            event(c, case, "inspection", {"message": body.note or "Merchant checked item condition.", "condition": body.condition})
        return {"ok": True}


@app.post("/api/returns/{case_id}/research")
def research(case_id: str, body: Version):
    with transaction() as c:
        case = case_locked(c, case_id, body.expected_version)
        enqueue(c, case, "research")
        return {"ok": True}


class Verification(BaseModel):
    shipping_cost_cents: int = Field(ge=0, le=1000000)
    service_fee_cents: int = Field(ge=0, le=1000000)
    accepted_conditions: list[Literal["sealed", "opened", "damaged", "unknown"]] = Field(
        min_length=1
    )
    note: str = Field(min_length=1, max_length=1000)


@app.post("/api/destinations/{destination_id}/verify")
def verify(destination_id: str, body: Verification):
    with transaction() as c:
        row = c.execute(
            "SELECT * FROM destinations WHERE id=%s FOR UPDATE", (destination_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Destination not found")
        if row["data"]["type"] not in ("repair", "resale") or not row["data"].get("source_url"):
            raise Conflict("Only researched external destinations need this verification action.")
        data = row["data"]
        data.update(
            body.model_dump(),
            acceptance_status="verified",
            verified_by="merchant",
            verified_at=datetime.now(timezone.utc).isoformat(),
        )
        c.execute("UPDATE destinations SET data=%s WHERE id=%s", (Jsonb(data), destination_id))
        for case in c.execute(
            "SELECT * FROM return_cases WHERE status IN ('awaiting_approval','needs_review','working') ORDER BY id FOR UPDATE"
        ).fetchall():
            case["version"] += 1
            invalidate(c, case, "Destination verification changed available routes.")
            c.execute(
                "UPDATE return_cases SET version=%s,status='working' WHERE id=%s",
                (case["version"], case["id"]),
            )
            enqueue(c, case)
        return {"ok": True}


@app.get("/api/integrations")
def integrations():
    with transaction() as c:
        status = c.execute("SELECT * FROM worker_status WHERE id=1").fetchone()
        return {
            "mode": os.environ.get("EXECUTION_MODE", "demo"),
            "worker": status,
            "calls": c.execute(
                "SELECT * FROM provider_calls ORDER BY created_at DESC LIMIT 40"
            ).fetchall(),
            "sessions": c.execute("SELECT * FROM agent_sessions").fetchall(),
        }


class Scenario(BaseModel):
    scenario_id: str


@app.post("/api/demo/reset")
def reset(body: Scenario):
    files, _ = fixtures()
    scenario = next((s for s in files["scenarios"]["records"] if s["id"] == body.scenario_id), None)
    if not scenario:
        raise HTTPException(422, "Unknown scenario")
    with transaction() as c:
        c.execute("SELECT pg_advisory_xact_lock(8111)")
        if (
            not merchant(c).get("synthetic")
            or c.execute(
                "SELECT 1 FROM return_cases WHERE data->>'merchant_id'!='merchant-demo-01'"
            ).fetchone()
        ):
            raise Conflict("Reset is restricted to the synthetic database.")
        # Worker claims share this advisory lock, so reset cannot race with a demo transaction.
        for table in (
            "tool_results",
            "provider_calls",
            "agent_sessions",
            "shipments",
            "route_proposals",
            "reservations",
            "case_events",
            "jobs",
            "return_cases",
            "buyer_orders",
            "policy_passages",
            "destinations",
            "quotes",
            "products",
            "locations",
            "merchants",
        ):
            c.execute(f"DELETE FROM {table}")
        seed(c)
        for case_id in scenario["case_ids"]:
            case = case_locked(c, case_id)
            if scenario.get("test_overrides"):
                d = case["data"]
                d["test_ttl"] = 15
                c.execute("UPDATE return_cases SET data=%s WHERE id=%s", (Jsonb(d), case_id))
            enqueue(c, case)
            c.execute("UPDATE return_cases SET status='working' WHERE id=%s", (case_id,))
        return {"ok": True, "case_ids": scenario["case_ids"]}


class PolicyPatch(BaseModel):
    direct_forwarding_enabled: bool


@app.post("/api/demo/policy")
def policy_patch(body: PolicyPatch):
    with transaction() as c:
        m = merchant(c)
        if not m.get("synthetic"):
            raise Conflict("Demo policy action requires synthetic merchant.")
        m["policy_version"] = uid("demo-policy")
        m["rules"]["policy_version"] = m["policy_version"]
        m["rules"]["direct_forwarding_enabled"] = body.direct_forwarding_enabled
        c.execute("UPDATE merchants SET data=%s WHERE id=%s", (Jsonb(m), m["id"]))
        for row in c.execute("SELECT * FROM policy_passages").fetchall():
            d = row["data"]
            d["policy_version"] = m["policy_version"]
            if d["id"] == "POL-002":
                d["text"] = (
                    "Direct forwarding is disabled."
                    if not body.direct_forwarding_enabled
                    else "Sealed items may forward to matching waiting buyers after approval."
                )
            c.execute("UPDATE policy_passages SET data=%s WHERE id=%s", (Jsonb(d), row["id"]))
        for case in c.execute(
            "SELECT * FROM return_cases WHERE status IN ('awaiting_approval','working','needs_review') ORDER BY id FOR UPDATE"
        ).fetchall():
            case["version"] += 1
            invalidate(c, case, "Policy changed; fresh review and approval required.")
            c.execute(
                "UPDATE return_cases SET version=%s,status='working' WHERE id=%s",
                (case["version"], case["id"]),
            )
            enqueue(c, case)
        return {"ok": True}
