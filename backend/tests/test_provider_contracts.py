import asyncio
import pytest
from band import AgentTools
from band.client.rest import AsyncRestClient
from zoowork import normalize_event, custom_tool_use
from app.bridge import ZooWorkBandAdapter
from app.tools import declarations


def test_band_adapter_and_custom_tool_contracts():
    adapter = ZooWorkBandAdapter(object(), "returns")
    rest = AsyncRestClient(api_key="test-only")
    tools = AgentTools("room-test", rest)
    schemas = tools.get_tool_schemas("openai")
    messaging = [f for f in schemas if f["function"]["name"] == "band_send_message"]
    assert len(messaging) == 1
    assert "mentions" in messaging[0]["function"]["parameters"]["properties"]
    assert {d["name"] for d in declarations("policy")} == {
        "get_case",
        "search_policy",
        "record_policy_finding",
    }
    ev = normalize_event(
        {
            "seq": 3,
            "event_type": "agent.custom_tool_use",
            "payload": {"callId": "call-1", "name": "get_case", "input": {}},
        }
    )
    call = custom_tool_use(ev)
    assert call.call_id == "call-1"


def test_native_moss_and_tavily_imports():
    from moss import MossClient, DocumentInfo, QueryOptions
    from tavily import AsyncTavilyClient

    assert DocumentInfo(id="POL-001", text="Evidence").id == "POL-001"
    assert QueryOptions(top_k=3).top_k == 3
    assert AsyncTavilyClient(api_key="test-only") is not None


def test_band_rendered_mentions_preserve_trusted_envelope():
    import json
    from app.bridge import band_envelope
    payload = {'case_id':'RET-1','version':1}
    assert band_envelope('@[[returns]] @[[policy]] ' + json.dumps(payload), {'returns','policy'}) == payload
    with pytest.raises(ValueError):
        band_envelope('@[[stranger]] ' + json.dumps(payload), {'returns'})
    with pytest.raises(ValueError):
        band_envelope('untrusted prose ' + json.dumps(payload), {'returns'})
