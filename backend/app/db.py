import os
import uuid
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@contextmanager
def transaction():
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        with conn.transaction():
            yield conn


def event(conn, case, kind, payload, actor="merchant"):
    conn.execute(
        "INSERT INTO case_events(case_id,version,actor,type,payload) VALUES(%s,%s,%s,%s,%s)",
        (case["id"], case["version"], actor, kind, Jsonb(payload)),
    )


def enqueue(conn, case, kind="plan"):
    conn.execute(
        "INSERT INTO jobs(case_id,version,type) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
        (case["id"], case["version"], kind),
    )
