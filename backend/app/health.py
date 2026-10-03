import sys, urllib.request
from .db import transaction

if sys.argv[1] == "api":
    urllib.request.urlopen("http://localhost:8000/api/health/ready", timeout=4)
else:
    with transaction() as c:
        row = c.execute(
            "SELECT 1 FROM worker_status WHERE id=1 AND updated_at>now()-interval '30 seconds'"
        ).fetchone()
        if not row:
            sys.exit(1)
