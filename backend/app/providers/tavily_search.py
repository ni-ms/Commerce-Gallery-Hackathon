import os
from datetime import datetime, timezone
from tavily import AsyncTavilyClient


class DestinationSearch:
    def __init__(self):
        self.client = AsyncTavilyClient(api_key=os.environ["TAVILY_API_KEY"])

    async def search(self, category, city):
        response = await self.client.search(
            query=f"{category} repair resale {city}", max_results=3, search_depth="basic"
        )
        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                "name": r["title"],
                "source_url": r["url"],
                "source_excerpt": r.get("content", "")[:1500],
                "lookup_time": now,
                "type": "repair",
                "accepted_categories": [category],
                "accepted_conditions": [],
                "acceptance_status": "unverified",
                "shipping_cost_cents": None,
                "service_fee_cents": None,
                "evidence_origin": "live_tavily",
            }
            for r in response.get("results", [])[:3]
            if r.get("url", "").startswith(("https://", "http://"))
        ]
