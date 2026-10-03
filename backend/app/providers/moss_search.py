import asyncio
import os

from moss import DocumentInfo, MossClient, QueryOptions

from ..db import transaction
from ..routing import merchant


class PolicySearch:
    def __init__(self):
        self.client = MossClient(os.environ["MOSS_PROJECT_ID"], os.environ["MOSS_PROJECT_KEY"])
        self.loaded = set()
        self.load_lock = asyncio.Lock()

    async def search(self, query):
        with transaction() as conn:
            current = merchant(conn)
            passages = [
                row["data"]
                for row in conn.execute("SELECT data FROM policy_passages").fetchall()
                if row["data"].get("merchant_id") == current["id"]
                and row["data"].get("policy_version") == current["policy_version"]
            ]
        name = "smarter-returns-" + current["policy_version"]
        async with self.load_lock:
            if name not in self.loaded:
                indexes = await self.client.list_indexes()
                if name not in [index.name for index in indexes]:
                    await self.client.create_index(
                        name,
                        [
                            DocumentInfo(
                                id=passage["id"],
                                text=passage["title"] + ". " + passage["text"],
                                metadata={
                                    "merchant_id": current["id"],
                                    "policy_version": current["policy_version"],
                                },
                            )
                            for passage in passages
                        ],
                    )
                await self.client.load_index(name)
                self.loaded.add(name)
        result = await self.client.query(name, query, QueryOptions(top_k=5))
        ids = {
            doc.id
            for doc in result.docs
            if doc.metadata
            and doc.metadata.get("merchant_id") == current["id"]
            and doc.metadata.get("policy_version") == current["policy_version"]
        }
        return {
            "policy_version": current["policy_version"],
            "passages": [passage for passage in passages if passage["id"] in ids],
            "latency_ms": result.time_taken_ms,
        }
