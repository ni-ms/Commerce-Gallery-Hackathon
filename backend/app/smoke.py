"""Live thin-path diagnostic. Requires worker-only provider credentials.
Does not claim live success unless actual evidence exists.
"""

import asyncio
from .bridge import LiveBridge
from .db import transaction
from .routing import case_locked


async def main():
    bridge = LiveBridge()
    await bridge.start()
    with transaction() as c:
        case = case_locked(c, "RET-001")
        job = {"case_id": case["id"], "version": case["version"], "type": "plan"}
    await bridge.initiate(job)
    for _ in range(150):
        with transaction() as c:
            result = c.execute("SELECT * FROM return_cases WHERE id='RET-001'").fetchone()
            calls = c.execute(
                "SELECT provider,count(*) FROM provider_calls WHERE status IN ('done','succeeded','sent') GROUP BY provider"
            ).fetchall()
        if result["status"] == "awaiting_approval":
            print({"status": result["status"], "providers": calls})
            return
        await asyncio.sleep(1)
    raise RuntimeError(
        "No live proposal completed. Inspect execution evidence; this is not a passed sponsor round trip."
    )


if __name__ == "__main__":
    asyncio.run(main())
