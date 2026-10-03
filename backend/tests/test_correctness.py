import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from app.bootstrap import bootstrap, seed
from app.db import transaction
from app.routing import (
    case_locked,
    plan_demo,
    reserve,
    approve,
    Conflict,
    invalidate,
    merchant,
    finding,
    proposal,
)
from app.api import app


@pytest.fixture(autouse=True)
def fresh():
    bootstrap()
    with transaction() as c:
        for t in (
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
            c.execute(f"DELETE FROM {t}")
        seed(c)


def plan(case_id):
    with transaction() as c:
        return plan_demo(c, case_locked(c, case_id))


def test_normal_cost_and_duplicate_approval():
    p = plan("RET-001")
    assert p["destination_id"] == "BUY-001"
    assert p["data"]["route"]["cost"]["total_cents"] == 600
    assert p["data"]["estimated_saving_cents"] == 900
    with transaction() as c:
        first = approve(c, "RET-001", 1, p["id"], "same-key", True)
    with transaction() as c:
        second = approve(c, "RET-001", 1, p["id"], "same-key", True)
    assert first["id"] == second["id"]
    with transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM shipments").fetchone()["n"] == 1


def test_competing_returns_real_concurrency():
    def attempt(case_id):
        with transaction() as c:
            case = case_locked(c, case_id)
            try:
                reserve(c, case, "BUY-005")
                return True
            except Conflict:
                return False

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(attempt, ["RET-006", "RET-007"]))
    assert sum(outcomes) == 1
    with transaction() as c:
        assert (
            c.execute("SELECT count(*) AS n FROM reservations WHERE status='active'").fetchone()[
                "n"
            ]
            == 1
        )


def test_same_item_cannot_reserve_twice():
    with transaction() as c:
        case = case_locked(c, "RET-001")
        first = reserve(c, case, "BUY-001")
        second = reserve(c, case, "BUY-001")
        assert first["id"] == second["id"]


def client():
    cl = TestClient(app)
    cl.headers["origin"] = os.environ["APP_ORIGIN"]
    assert (
        cl.post("/api/login", json={"passcode": os.environ["MERCHANT_PASSCODE"]}).status_code == 200
    )
    return cl


def test_inspection_invalidates_before_worker():
    p = plan("RET-002")
    cl = client()
    assert (
        cl.post(
            "/api/returns/RET-002/inspection",
            json={"expected_version": 1, "condition": "opened", "note": "Seal is broken", "confirmed_condition": True},
        ).status_code
        == 200
    )
    result = cl.post(
        "/api/returns/RET-002/approve",
        json={
            "expected_version": 1,
            "proposal_id": p["id"],
            "request_key": "stale",
            "confirmed_condition": True,
        },
    )
    assert result.status_code == 409
    with transaction() as c:
        assert not c.execute("SELECT 1 FROM reservations WHERE status='active'").fetchone()
        revised = plan_demo(c, case_locked(c, "RET-002"))
    assert revised["destination_id"] == "dest-inspection"
    assert revised["data"]["route"]["cost"]["total_cents"] == 1100


def test_policy_change_blocks_old_approval():
    p = plan("RET-009")
    cl = client()
    assert cl.post("/api/demo/policy", json={"direct_forwarding_enabled": False}).status_code == 200
    assert (
        cl.post(
            "/api/returns/RET-009/approve",
            json={"expected_version": 1, "proposal_id": p["id"], "request_key": "old"},
        ).status_code
        == 409
    )
    with transaction() as c:
        revised = plan_demo(c, case_locked(c, "RET-009"))
    assert revised["destination_id"] == "dest-warehouse"


def test_expiry_blocks_approval_and_queues_review():
    p = plan("RET-008")
    with transaction() as c:
        c.execute("UPDATE reservations SET expires_at=now()-interval '1 second'")
    cl = client()
    assert (
        cl.post(
            "/api/returns/RET-008/approve",
            json={
                "expected_version": 1,
                "proposal_id": p["id"],
                "request_key": "expired",
                "confirmed_condition": True,
            },
        ).status_code
        == 409
    )
    with transaction() as c:
        assert c.execute("SELECT 1 FROM jobs WHERE type='expiry'").fetchone()
        assert not c.execute("SELECT 1 FROM shipments").fetchone()


def test_unknown_and_damaged_never_forward():
    assert plan("RET-003")["destination_id"] == "dest-inspection"
    assert plan("RET-005")["destination_id"] == "dest-inspection"
    assert plan("RET-004")["destination_id"] == "dest-warehouse"


def test_missing_quote_and_missing_evidence():
    with transaction() as c:
        c.execute("DELETE FROM quotes")
        case = case_locked(c, "RET-001")
        with pytest.raises(Conflict):
            plan_demo(c, case)
    with transaction() as c:
        with pytest.raises(Conflict):
            finding(c, case_locked(c, "RET-001"), ["POL-008"], "test")


def test_unverified_external_blocked():
    with transaction() as c:
        c.execute(
            "INSERT INTO destinations VALUES(%s,%s)",
            (
                "EXT",
                Jsonb(
                    {
                        "name": "Research candidate",
                        "type": "repair",
                        "acceptance_status": "unverified",
                        "accepted_conditions": ["damaged"],
                        "shipping_cost_cents": 0,
                        "service_fee_cents": 0,
                    }
                ),
            ),
        )
        case = case_locked(c, "RET-003")
        finding(c, case, ["POL-004"], "test")
        with pytest.raises(Conflict):
            proposal(c, case, "EXT")


def test_restart_repeated_plan_preserves_reservation():
    first = plan("RET-001")
    second = plan("RET-001")
    assert first["id"] == second["id"]
    with transaction() as c:
        assert (
            c.execute("SELECT count(*) AS n FROM reservations WHERE status='active'").fetchone()[
                "n"
            ]
            == 1
        )


def test_auth_origin_and_confirmation():
    cl = TestClient(app)
    assert cl.get("/api/returns").status_code == 401
    assert (
        cl.post("/api/login", json={"passcode": os.environ["MERCHANT_PASSCODE"]}).status_code == 403
    )
    p = plan("RET-001")
    cl = client()
    assert (
        cl.post(
            "/api/returns/RET-001/approve",
            json={"expected_version": 1, "proposal_id": p["id"], "request_key": "no-confirm"},
        ).status_code
        == 409
    )


def test_inspection_after_approval_creates_exception():
    p = plan("RET-001")
    with transaction() as c:
        approve(c, "RET-001", 1, p["id"], "approved", True)
    cl = client()
    assert (
        cl.post(
            "/api/returns/RET-001/inspection",
            json={"expected_version": 1, "condition": "damaged", "note": "New damage observed", "confirmed_condition": True},
        ).status_code
        == 200
    )
    with transaction() as c:
        assert case_locked(c, "RET-001")["status"] == "exception"
        assert c.execute("SELECT count(*) AS n FROM shipments").fetchone()["n"] == 1


def test_expired_job_lease_replays_without_duplicate_business_effects():
    from app.db import enqueue
    from app.worker import claim
    first = plan('RET-001')
    with transaction() as c:
        case = case_locked(c, 'RET-001')
        enqueue(c, case)
        c.execute("UPDATE jobs SET status='running',lease_until=now()-interval '1 second',attempts=1")
    job = claim()
    assert job['attempts'] == 2
    repeated = plan('RET-001')
    assert repeated['id'] == first['id']
    with transaction() as c:
        assert c.execute("SELECT count(*) AS n FROM reservations WHERE status='active'").fetchone()['n'] == 1


def test_old_agent_write_and_wrong_role_are_rejected():
    from app.tools import execute
    with transaction() as c:
        with pytest.raises(Conflict):
            execute(c, 'policy', 'RET-001', 1, 'reserve_item', {'buyer_order_id':'BUY-001','expected_version':1})
        c.execute("UPDATE return_cases SET version=2 WHERE id='RET-001'")
        with pytest.raises(Conflict):
            execute(c, 'fulfillment', 'RET-001', 1, 'reserve_item', {'buyer_order_id':'BUY-001','expected_version':1})
    with transaction() as c:
        assert not c.execute('SELECT 1 FROM reservations').fetchone()


@pytest.mark.parametrize("mode,deadline", [("demo", 180), ("live", 600)])
def test_run_deadline_requires_review(monkeypatch, mode, deadline):
    monkeypatch.setenv("EXECUTION_MODE", mode)
    from app.db import enqueue
    from app.worker import claim
    with transaction() as c:
        case = case_locked(c, 'RET-001')
        enqueue(c, case)
        c.execute("UPDATE return_cases SET status='working' WHERE id='RET-001'")
        c.execute("UPDATE jobs SET status='done',available_at=now()-(%s * interval '1 second')", (deadline + 1,))
    assert claim() is None
    with transaction() as c:
        assert case_locked(c, 'RET-001')['status'] == 'needs_review'


def test_moss_policy_search_filters_evidence_and_reuses_index(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from app.providers import moss_search

    created = []
    loaded = []
    queried = []

    class FakeMoss:
        def __init__(self, project_id, project_key):
            assert (project_id, project_key) == ("test-project", "test-key")

        async def list_indexes(self):
            return []

        async def create_index(self, name, docs):
            created.append((name, docs))

        async def load_index(self, name):
            loaded.append(name)

        async def query(self, name, query, options):
            queried.append((name, query, options.top_k))
            docs = [
                SimpleNamespace(id="POL-003", metadata={"merchant_id": "merchant-demo-01", "policy_version": "demo-policy-v1"}),
                SimpleNamespace(id="POL-004", metadata={"merchant_id": "other", "policy_version": "demo-policy-v1"}),
                SimpleNamespace(id="POL-005", metadata={"merchant_id": "merchant-demo-01", "policy_version": "old"}),
                SimpleNamespace(id="INVENTED", metadata={"merchant_id": "merchant-demo-01", "policy_version": "demo-policy-v1"}),
            ]
            return SimpleNamespace(docs=docs if query else [], time_taken_ms=2)

    monkeypatch.setenv("MOSS_PROJECT_ID", "test-project")
    monkeypatch.setenv("MOSS_PROJECT_KEY", "test-key")
    monkeypatch.setattr(moss_search, "MossClient", FakeMoss)
    with transaction() as c:
        for ident, tenant, version in [
            ("WRONG-TENANT", "other-merchant", "demo-policy-v1"),
            ("OLD-POLICY", "merchant-demo-01", "old-policy"),
        ]:
            c.execute("INSERT INTO policy_passages(id,data) VALUES(%s,%s)",
                      (ident, Jsonb({"id": ident, "merchant_id": tenant,
                       "policy_version": version, "title": "Damaged repair",
                       "text": "Damaged repair"})))

    async def run():
        search = moss_search.PolicySearch()
        result = await search.search("opened broken seal")
        empty = await search.search("")
        return result, empty

    result, empty = asyncio.run(run())
    assert [p["id"] for p in result["passages"]] == ["POL-003"]
    assert result["policy_version"] == "demo-policy-v1"
    assert empty["passages"] == []
    assert len(created) == len(loaded) == 1
    assert not {"WRONG-TENANT", "OLD-POLICY"} & {d.id for d in created[0][1]}
    assert len(queried) == 2 and queried[0][2] == 5


def test_moss_policy_finding_rejects_unretrieved_and_stale_evidence():
    from app.tools import execute

    with transaction() as c:
        case = case_locked(c, "RET-001")
        data = case["data"]
        data.update(policy_retrieval_provider="moss", policy_passage_ids=["POL-002"], policy_case_version=case["version"],
                    retrieval_policy_version=merchant(c)["policy_version"])
        c.execute("UPDATE return_cases SET data=%s WHERE id=%s", (Jsonb(data), case["id"]))
        args = {"expected_version": case["version"], "passage_ids": ["POL-003"]}
        with pytest.raises(Conflict, match="not retrieved"):
            execute(c, "policy", case["id"], case["version"], "record_policy_finding", args)
        data["retrieval_policy_version"] = "old-policy"
        c.execute("UPDATE return_cases SET data=%s WHERE id=%s", (Jsonb(data), case["id"]))
        args["passage_ids"] = ["POL-002"]
        with pytest.raises(Conflict, match="older facts or policy"):
            execute(c, "policy", case["id"], case["version"], "record_policy_finding", args)


def test_recovery_keeps_version_and_shipping_gate():
    with transaction() as c:
        c.execute("UPDATE return_cases SET status='needs_review' WHERE id='RET-001'")
        c.execute("INSERT INTO jobs(case_id,version,type,status) VALUES('RET-001',1,'plan','failed') ON CONFLICT(case_id,version,type) DO UPDATE SET status='failed'")
    cl = client()
    assert cl.post('/api/returns/RET-001/recover', json={'expected_version': 1}).status_code == 200
    assert cl.post('/api/returns/RET-001/recover', json={'expected_version': 1}).status_code == 200
    with transaction() as c:
        assert case_locked(c, 'RET-001')['version'] == 1
        assert c.execute("SELECT count(*) AS n FROM jobs WHERE case_id='RET-001' AND type='plan'").fetchone()['n'] == 1
        assert c.execute('SELECT count(*) AS n FROM shipments').fetchone()['n'] == 0
        assert c.execute("SELECT count(*) AS n FROM case_events WHERE type='recovery_requested'").fetchone()['n'] == 1


def test_band_setup_models_and_uncertain_send(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import app.bridge as module
    sends = []
    present = {'r'}
    class Tools:
        def __init__(self, room, rest, agent_id):
            self.participants = []
        async def get_participants(self):
            self.participants = [{'id': x} for x in present]
            return [SimpleNamespace(id=x) for x in present]
        async def send_message(self, **kwargs):
            sends.append(kwargs)
            return SimpleNamespace(model_dump=lambda: {'id': 'message-1'})
    async def add(**kwargs):
        present.add(kwargs['participant'].participant_id)
    bridge = module.LiveBridge.__new__(module.LiveBridge)
    bridge.band_ids = {'returns': 'r', 'policy': 'p', 'fulfillment': 'f'}
    bridge.rest = {r: SimpleNamespace(agent_api_participants=SimpleNamespace(add_agent_chat_participant=add)) for r in bridge.band_ids}
    monkeypatch.setattr(module, 'AgentTools', Tools)
    job = {'case_id':'RET-001','version':1,'type':'plan'}
    key = 'band-init-RET-001-1-plan'
    with transaction() as c:
        case = case_locked(c, 'RET-001'); case['data']['band_room_id'] = 'room'
        c.execute("UPDATE return_cases SET data=%s WHERE id='RET-001'", (Jsonb(case['data']),))
    module.save_call(key, 'band', 'pending', {'case_id':'RET-001','version':1})
    asyncio.run(bridge.initiate(job))
    assert len(sends) == 1
    assert present == {'r','p','f'}
    async def receipt(*args): return None
    monkeypatch.setattr(bridge, 'initiation_receipt', receipt)
    module.save_call(key, 'band', 'pending', {'case_id':'RET-001','version':1,'phase':'sending'})
    with pytest.raises(Conflict, match='No message was resent'):
        asyncio.run(bridge.initiate(job))
    assert len(sends) == 1
    async def found(*args): return {'id':'message-1'}
    async def resume(*args): pass
    monkeypatch.setattr(bridge, 'initiation_receipt', found)
    monkeypatch.setattr(bridge, 'recover_deliveries', resume)
    asyncio.run(bridge.initiate(job))
    asyncio.run(bridge.initiate(job))
    assert len(sends) == 1


def test_condition_confirmation_and_optional_photo_evidence():
    import base64
    cl = client()
    body = {'expected_version':1,'condition':'unknown'}
    assert cl.post('/api/returns/RET-005/inspection', json=body).status_code == 422
    photo = 'data:image/jpeg;base64,' + base64.b64encode(b'\xff\xd8\xfftest-evidence').decode()
    body.update(confirmed_condition=True, photos=[photo])
    assert cl.post('/api/returns/RET-005/inspection', json=body).status_code == 200
    from app.tools import execute
    with transaction() as c:
        case = case_locked(c, 'RET-005')
        assert case['version'] == 2
        assert case['data']['inspection_condition'] == 'unknown'
        assert case['data']['inspection_photos'] == [photo]
        context = execute(c, 'returns', case['id'], 2, 'get_case', {})
        assert 'inspection_photos' not in context['facts']
        assert context['inspection_photo_count'] == 1
        assert c.execute('SELECT count(*) AS n FROM shipments').fetchone()['n'] == 0
    body.update(expected_version=2, photos=['data:image/jpeg;base64,not-base64'])
    assert cl.post('/api/returns/RET-005/inspection', json=body).status_code == 422


def test_recovery_resumes_original_delivery_id(monkeypatch):
    import asyncio, json
    from types import SimpleNamespace
    import app.bridge as module
    processed = []
    received = []
    msg = SimpleNamespace(id='original-message', sender_id='f', sender_name='Fulfillment', content=json.dumps({'case_id':'RET-001','version':1}), metadata={'delivery_status':{'r':{'status':'failed'}}})
    msg.metadata = SimpleNamespace(model_dump=lambda: {'delivery_status':{'r':{'status':'failed'}}})
    async def listing(*args, **kwargs):
        assert kwargs['status'] == 'all'
        return SimpleNamespace(data=[msg], metadata=SimpleNamespace(has_more=False))
    async def marking(room, msg_id, **kwargs): processed.append(msg_id)
    class Tools:
        def __init__(self, room, rest, agent_id): self.participants = [{'id':'r'}]
        async def get_participants(self): return [SimpleNamespace(id='r')]
    bridge = module.LiveBridge.__new__(module.LiveBridge)
    bridge.band_ids = {'returns':'r','policy':'p','fulfillment':'f'}
    bridge.rest = {role: SimpleNamespace(agent_api_messages=SimpleNamespace(list_agent_messages=listing, mark_agent_message_processing=marking, mark_agent_message_processed=marking)) for role in bridge.band_ids}
    async def receive(role, message, *args): received.append((role,message.id))
    monkeypatch.setattr(module, 'AgentTools', Tools)
    monkeypatch.setattr(bridge, 'receive', receive)
    asyncio.run(bridge.recover_deliveries({'id':'RET-001','version':1}, 'room'))
    assert received == [('returns','original-message')]
    assert processed == ['original-message','original-message']


def test_uncertain_handoff_stays_pending_until_receipt(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import app.bridge as module
    with transaction() as c:
        case = case_locked(c, 'RET-001'); case['data']['band_room_id'] = 'room'
        c.execute("UPDATE return_cases SET data=%s WHERE id='RET-001'", (Jsonb(case['data']),))
    key = 'zoo-tool-original-call'
    module.save_call(key, 'band', 'pending', {'case_id':'RET-001','has_message_marker':True})
    bridge = module.LiveBridge.__new__(module.LiveBridge)
    bridge.band_ids = {'returns':'r','policy':'p','fulfillment':'f'}
    bridge.zoo_ids = {'returns':'zoo-r'}
    resolutions = []
    async def resolved(*args, **kwargs): resolutions.append(kwargs)
    bridge.zoo = SimpleNamespace(resolve_custom_tool_call=resolved)
    async def absent(*args): return None
    monkeypatch.setattr(bridge, 'initiation_receipt', absent)
    tools = SimpleNamespace(room_id='room', participants=[{'id':'p'}])
    args = {'mentions':['p'],'content':'Policy review'}
    with pytest.raises(Conflict, match='no automatic resend'):
        asyncio.run(bridge.resolve('returns','RET-001',1,'original-call','band_send_message',args,tools))
    assert not resolutions
    with transaction() as c:
        assert not c.execute('SELECT 1 FROM tool_results WHERE request_key=%s', (key,)).fetchone()
        assert c.execute('SELECT status FROM provider_calls WHERE request_key=%s', (key,)).fetchone()['status'] == 'pending'
    async def receipt(*args): return {'id':'original-band-message'}
    monkeypatch.setattr(bridge, 'initiation_receipt', receipt)
    asyncio.run(bridge.resolve('returns','RET-001',1,'original-call','band_send_message',args,tools))
    asyncio.run(bridge.resolve('returns','RET-001',1,'original-call','band_send_message',args,tools))
    assert len(resolutions) == 2
    assert resolutions[0]['content'][0]['value']['receipt']['id'] == 'original-band-message'


def test_zoo_input_ack_reconciles_without_reposting(monkeypatch):
    import asyncio, json
    from types import SimpleNamespace
    import app.bridge as module
    from zoowork.events import normalize_event
    bridge = module.LiveBridge.__new__(module.LiveBridge)
    bridge.zoo_ids = {'returns':'zoo-r'}
    msg=SimpleNamespace(id='original', sender_id='f', sender_name='Fulfillment', room_id='room', content='original-content')
    context={'trusted_case_id':'RET-001','expected_version':1,'band_message_id':msg.id,'sender_id':msg.sender_id,'message':msg.content}
    history=[{'seq':9,'entry':{'message':{'role':'user','content':[{'type':'text','text':json.dumps(context)}]}}}]
    posts=[]
    async def session(*args,**kwargs): return {'history':history}
    async def post(*args,**kwargs): posts.append(args); raise AssertionError('Never repost accepted input')
    async def pending(*args,**kwargs): return []
    async def events(*args,**kwargs): return [normalize_event({'seq':10,'event_type':'run.finished','payload':{'status':'succeeded'}})]
    bridge.zoo=SimpleNamespace(get_session=session,post_events=post,list_custom_tool_calls=pending,list_events=events)
    with transaction() as c:
        case=case_locked(c,'RET-001'); case['data']['band_room_id']='room'
        c.execute("UPDATE return_cases SET data=%s WHERE id='RET-001'",(Jsonb(case['data']),))
    module.save_session(case['id'],'returns',{'session_id':'existing-session','agent_id':'zoo-r','room_id':'room','after':0,'active_message':'original','version':1,'posted':False})
    module.save_call('band-delivery-returns-original','band','posting',{'case_id':case['id']})
    tools=SimpleNamespace(room_id='room',participants=[])
    asyncio.run(bridge.run_role('returns',msg,tools,[],case))
    asyncio.run(bridge.run_role('returns',msg,tools,[],case))
    assert posts==[]
    with transaction() as c:
        d=c.execute("SELECT data FROM agent_sessions WHERE case_id='RET-001' AND role='returns'").fetchone()['data']
        assert d['session_id']=='existing-session' and d['input_receipt']['history_seq']==9
        assert 'active_message' not in d
        assert c.execute("SELECT status FROM provider_calls WHERE request_key='band-delivery-returns-original'").fetchone()['status']=='done'
        assert c.execute('SELECT count(*) AS n FROM shipments').fetchone()['n']==0


def test_zoo_missing_or_duplicate_input_requires_evidence(monkeypatch):
    import asyncio,json
    from types import SimpleNamespace
    import app.bridge as module
    bridge=module.LiveBridge.__new__(module.LiveBridge); bridge.zoo_ids={'returns':'zoo-r'}
    msg=SimpleNamespace(id='original',sender_id='f',content='original-content')
    data={'session_id':'existing','version':1}; case={'id':'RET-001'}
    context={'trusted_case_id':'RET-001','expected_version':1,'band_message_id':'original','sender_id':'f','message':'original-content'}
    row={'seq':1,'entry':{'message':{'role':'user','content':json.dumps(context)}}}
    history=[]
    async def session(*args,**kwargs): return {'history':history}
    bridge.zoo=SimpleNamespace(get_session=session)
    assert asyncio.run(bridge.input_receipt('returns',data,case,msg)) is None
    history.extend([row,row])
    with pytest.raises(Conflict,match='Duplicate ZooWork input'):
        asyncio.run(bridge.input_receipt('returns',data,case,msg))
    history.pop(); context['expected_version']=2; history[0]['entry']['message']['content']=json.dumps(context)
    assert asyncio.run(bridge.input_receipt('returns',data,case,msg)) is None


def test_invalid_band_ack_does_not_resolve_or_repeat(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import app.bridge as module
    bridge=module.LiveBridge.__new__(module.LiveBridge); bridge.band_ids={'returns':'r','policy':'p','fulfillment':'f'}; bridge.zoo_ids={'returns':'z'}
    sends=[]; resolutions=[]
    async def send(*args): sends.append(args); return 'network failure'
    async def resolved(*args,**kwargs): resolutions.append(args)
    async def absent(*args): return None
    bridge.zoo=SimpleNamespace(resolve_custom_tool_call=resolved)
    monkeypatch.setattr(bridge,'initiation_receipt',absent)
    tools=SimpleNamespace(room_id='room',participants=[{'id':'p'}],execute_tool_call=send)
    with transaction() as c:
        case=case_locked(c,'RET-001'); case['data']['band_room_id']='room'
        c.execute("UPDATE return_cases SET data=%s WHERE id='RET-001'",(Jsonb(case['data']),))
    for _ in range(2):
        with pytest.raises(Conflict,match='no automatic resend'):
            asyncio.run(bridge.resolve('returns','RET-001',1,'uncertain','band_send_message',{'mentions':['p'],'content':'review'},tools))
    assert len(sends)==1 and not resolutions
    with transaction() as c:
        assert case_locked(c,'RET-001')['data']['handoffs']==1
        assert not c.execute("SELECT 1 FROM tool_results WHERE request_key='zoo-tool-uncertain'").fetchone()


def test_band_receipt_recovery_at_handoff_limit(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import app.bridge as module
    with transaction() as c:
        case=case_locked(c,'RET-001'); case['data'].update(band_room_id='room',handoffs=8)
        c.execute("UPDATE return_cases SET data=%s WHERE id='RET-001'",(Jsonb(case['data']),))
    module.save_call('zoo-tool-last','band','pending',{'case_id':'RET-001','has_message_marker':True})
    bridge=module.LiveBridge.__new__(module.LiveBridge); bridge.band_ids={'returns':'r','policy':'p','fulfillment':'f'}; bridge.zoo_ids={'returns':'z'}
    resolutions=[]
    async def resolved(*args,**kwargs): resolutions.append(kwargs)
    async def found(*args): return {'id':'original'}
    bridge.zoo=SimpleNamespace(resolve_custom_tool_call=resolved)
    monkeypatch.setattr(bridge,'initiation_receipt',found)
    asyncio.run(bridge.resolve('returns','RET-001',1,'last','band_send_message',{'mentions':['p'],'content':'review'},SimpleNamespace(room_id='room',participants=[{'id':'p'}])))
    assert resolutions[0]['content'][0]['value']['receipt']['id']=='original'
    with transaction() as c: assert case_locked(c,'RET-001')['data']['handoffs']==8


def test_sealed_case_cannot_queue_unused_repair_research():
    cl=client()
    assert cl.post('/api/returns/RET-001/research',json={'expected_version':1}).status_code==409
    with transaction() as c:
        assert not c.execute("SELECT 1 FROM jobs WHERE case_id='RET-001' AND type='research'").fetchone()
        assert case_locked(c,'RET-001')['version']==1


def test_terminal_cursor_restart_finishes_original_delivery(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import app.bridge as module
    bridge=module.LiveBridge.__new__(module.LiveBridge); bridge.zoo_ids={'returns':'z'}
    bridge.zoo=SimpleNamespace()  # No provider call should be necessary.
    with transaction() as c:
        case=case_locked(c,'RET-001'); case['data']['band_room_id']='room'
        c.execute("UPDATE return_cases SET data=%s WHERE id='RET-001'",(Jsonb(case['data']),))
    module.save_session('RET-001','returns',{'session_id':'original-session','version':1,'room_id':'room','active_message':'original','posted':True,'after':10,'run_finished':True})
    module.save_call('band-delivery-returns-original','band','running',{'case_id':'RET-001'})
    asyncio.run(bridge.run_role('returns',SimpleNamespace(id='original',sender_id='f'),SimpleNamespace(room_id='room'),[],case))
    with transaction() as c:
        assert c.execute("SELECT status FROM provider_calls WHERE request_key='band-delivery-returns-original'").fetchone()['status']=='done'
        assert c.execute('SELECT count(*) AS n FROM shipments').fetchone()['n']==0


def test_band_callback_and_history_mentions_share_envelope():
    from app.bridge import band_envelope,band_tokens
    tokens=band_tokens(['r','p'],[{'id':'p','handle':'merchant/policy'},{'id':'outsider','handle':'other/policy'}])
    body='{"case_id":"RET-001","version":1,"request_key":"original"}'
    assert band_envelope('@merchant/policy '+body,tokens)==band_envelope('@[[p]] '+body,tokens)
    with pytest.raises(ValueError): band_envelope('@other/policy '+body,tokens)


def test_ambiguous_zoo_input_missing_from_history_never_reposts():
    import asyncio
    from types import SimpleNamespace
    import app.bridge as module
    bridge=module.LiveBridge.__new__(module.LiveBridge); bridge.zoo_ids={'returns':'z'}
    async def session(*args,**kwargs): return {'history':[]}
    bridge.zoo=SimpleNamespace(get_session=session)  # No post or new session API exists.
    with transaction() as c:
        case=case_locked(c,'RET-001'); case['data']['band_room_id']='room'
        c.execute("UPDATE return_cases SET data=%s WHERE id='RET-001'",(Jsonb(case['data']),))
    module.save_session('RET-001','returns',{'session_id':'original-session','version':1,'room_id':'room','active_message':'original','posted':False,'after':0})
    module.save_call('band-delivery-returns-original','band','posting',{'case_id':'RET-001'})
    with pytest.raises(Conflict,match='External session evidence is required'):
        asyncio.run(bridge.run_role('returns',SimpleNamespace(id='original',sender_id='f',content='original'),SimpleNamespace(room_id='room'),[],case))
    with transaction() as c:
        assert c.execute("SELECT status FROM provider_calls WHERE request_key='band-delivery-returns-original'").fetchone()['status']=='posting'
        assert c.execute('SELECT count(*) AS n FROM shipments').fetchone()['n']==0


def test_band_receipt_pagination_and_json_safe_dates():
    import asyncio,json
    from types import SimpleNamespace
    import app.bridge as module
    key='original-handoff'; cursors=[]
    item={'id':'original-message','sender_id':'r','content':json.dumps({'case_id':'RET-001','version':1,'request_key':key}),'inserted_at':datetime.now(timezone.utc)}
    async def history(**kwargs):
        cursors.append(kwargs['cursor'])
        return SimpleNamespace(data=[] if kwargs['cursor'] is None else [SimpleNamespace(model_dump=lambda:item)],metadata=SimpleNamespace(has_more=kwargs['cursor'] is None,next_cursor='second-page'))
    bridge=module.LiveBridge.__new__(module.LiveBridge); bridge.band_ids={'returns':'r'}
    bridge.rest={'returns':SimpleNamespace(agent_api_context=SimpleNamespace(get_agent_chat_context=history))}
    receipt=asyncio.run(bridge.initiation_receipt('room',key,{'case_id':'RET-001','version':1,'type':'handoff'},'returns'))
    assert receipt['id']=='original-message' and isinstance(receipt['inserted_at'],str)
    assert cursors==[None,'second-page']
    module.save_call(key,'band','sent',{'receipt':receipt})
