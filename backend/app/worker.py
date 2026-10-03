import asyncio, os, time
from psycopg.types.json import Jsonb
from .db import transaction, event
from .routing import case_locked, plan_demo, Conflict, expire, reserve, invalidate


def heartbeat(data):
    with transaction() as c:
        c.execute(
            "INSERT INTO worker_status VALUES(1,now(),%s) ON CONFLICT(id) DO UPDATE SET updated_at=now(),data=EXCLUDED.data",
            (Jsonb(data),),
        )


def claim():
    with transaction() as c:
        c.execute("SELECT pg_advisory_xact_lock(8111)")
        expire(c)
        overdue=c.execute("SELECT * FROM return_cases r WHERE status IN ('working','submitted') AND EXISTS (SELECT 1 FROM jobs j WHERE j.case_id=r.id AND j.version=r.version AND j.type='plan' AND j.status='done' AND j.available_at<now()-(%s * interval '1 second')) FOR UPDATE SKIP LOCKED", (600 if os.environ.get("EXECUTION_MODE") == "live" else 180,)).fetchall()
        for case in overdue:
            invalidate(c,case,'Routing deadline reached; merchant review required.')
            c.execute("UPDATE return_cases SET status='needs_review' WHERE id=%s",(case['id'],))
        return c.execute(
            "UPDATE jobs SET status='running',attempts=attempts+1,lease_until=now()+interval '180 seconds' WHERE id=(SELECT id FROM jobs WHERE (status='pending' AND available_at<=now()) OR (status='running' AND lease_until<now()) ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *"
        ).fetchone()


async def run():
    mode = os.environ.get("EXECUTION_MODE", "demo")
    bridge = None
    status = {
        "mode": mode,
        "state": "ready",
        "providers": "Demo simulation; no live sponsor execution",
    }
    if mode == "live":
        try:
            from .bridge import LiveBridge

            bridge = LiveBridge()
            await bridge.start()
            status = {
                "mode": mode,
                "state": "connected",
                "providers": "SDK connections started; inspect saved calls for actual use",
            }
        except Exception as exc:
            # Never leak provider keys or raw authentication responses.
            status = {
                "mode": mode,
                "state": "needs_configuration",
                "error": type(exc).__name__,
                "message": "Live providers unavailable. Check worker-only credentials and SDK setup.",
            }
    while True:
        heartbeat(status)
        job = claim()
        if not job:
            await asyncio.sleep(1)
            continue
        try:
            if mode == "live":
                if bridge is None:
                    raise Conflict("Live sponsor setup is incomplete. No demo fallback was run.")
                await bridge.initiate(job)
            elif mode == "demo":
                with transaction() as c:
                    c.execute("SELECT pg_advisory_xact_lock(8111)")
                    case = case_locked(c, job["case_id"], job["version"])
                    if case["status"] in ("approved", "exception", "rejected"):
                        pass
                    elif job["type"] == "research":
                        event(
                            c,
                            case,
                            "research_unavailable",
                            {
                                "message": "External research needs a Tavily key in live mode. No placeholder destination was added."
                            },
                            "fulfillment",
                        )
                    elif job["type"] == "expiry":
                        # Stop here so an expired plan cannot be immediately auto-reserved.
                        event(
                            c,
                            case,
                            "review_required",
                            {
                                "message": "Reservation expired. Start a fresh scenario or create a new return."
                            },
                            "system",
                        )
                    else:
                        ttl = case["data"].get("test_ttl")
                        if ttl:
                            from .routing import finding, routes, proposal

                            finding(
                                c,
                                case,
                                ["POL-002", "POL-007", "POL-008"],
                                "demo fixture lookup",
                            )
                            r = next(r for r in routes(c, case) if r["eligible"])
                            if r["type"] == "buyer":
                                reserve(c, case, r["destination_id"], ttl)
                            proposal(c, case, r["destination_id"])
                        else:
                            plan_demo(c, case)
            with transaction() as c:
                c.execute(
                    "UPDATE jobs SET status='done',lease_until=NULL,error=NULL WHERE id=%s", (job["id"],)
                )
        except Exception as exc:
            with transaction() as c:
                case = c.execute(
                    "SELECT * FROM return_cases WHERE id=%s", (job["case_id"],)
                ).fetchone()
                if case and case["version"] == job["version"]:
                    terminal = isinstance(exc, Conflict) or job["attempts"] >= 3
                    c.execute(
                        "UPDATE jobs SET status=%s,error=%s,available_at=now()+interval '5 seconds',lease_until=NULL WHERE id=%s",
                        (
                            "failed" if terminal else "pending",
                            str(exc) if isinstance(exc, Conflict) else type(exc).__name__,
                            job["id"],
                        ),
                    )
                    if terminal:
                        c.execute(
                            "UPDATE return_cases SET status='needs_review' WHERE id=%s AND status NOT IN ('approved','exception','rejected')",
                            (case["id"],),
                        )
                        event(
                            c,
                            case,
                            "worker_error",
                            {
                                "message": (
                                    str(exc)
                                    if isinstance(exc, Conflict)
                                    else "Provider or worker operation failed; review execution evidence."
                                ),
                                "error_type": type(exc).__name__,
                            },
                            "system",
                        )
                else:
                    c.execute("UPDATE jobs SET status='stale' WHERE id=%s", (job["id"],))
        await asyncio.sleep(0.1)


if __name__ == "__main__":
    asyncio.run(run())
