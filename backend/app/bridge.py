"""Band delivers work; ZooWork selects tools and addressed handoffs.
No backend role sequence is used in live mode.
"""

import os, asyncio, json, re
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from band import Agent, AgentTools, Emit
from band.core import SimpleAdapter
from band.client.rest import AsyncRestClient, ChatRoomRequest, ParticipantRequest
from zoowork import ZooworkClient, custom_tool_use, is_run_finished
from psycopg.types.json import Jsonb
from .db import transaction, uid, event
from .routing import Conflict, case_locked, merchant
from .tools import declarations, execute, PERMISSIONS
from .providers.moss_search import PolicySearch
from .providers.tavily_search import DestinationSearch

ROLES = ("returns", "policy", "fulfillment")


def band_envelope(content, participant_ids):
    # Band prepends rendered mention tokens to content. Strip only known
    # participant tokens at the start; never extract arbitrary embedded JSON.
    while True:
        token = re.match(r"^\s*@\[\[([^\]]+)\]\]\s*", content)
        if not token or token.group(1) not in participant_ids:
            break
        content = content[token.end():]
    return json.loads(content)


def save_call(key, provider, status, data):
    with transaction() as c:
        c.execute(
            "INSERT INTO provider_calls(request_key,provider,status,data) VALUES(%s,%s,%s,%s) ON CONFLICT(request_key) DO UPDATE SET status=EXCLUDED.status,data=EXCLUDED.data",
            (key, provider, status, Jsonb(data)),
        )


def save_session(case_id, role, data):
    with transaction() as c:
        c.execute(
            "INSERT INTO agent_sessions VALUES(%s,%s,%s) ON CONFLICT(case_id,role) DO UPDATE SET data=EXCLUDED.data",
            (case_id, role, Jsonb(data)),
        )


class ZooWorkBandAdapter(SimpleAdapter):
    SUPPORTED_EMIT = frozenset({Emit.TOOL_CALLS})
    SUPPORTED_CAPABILITIES = frozenset()

    def __init__(self, bridge, role):
        super().__init__()
        self.bridge = bridge
        self.role = role

    async def on_message(
        self, msg, tools, history, participants_msg, contacts_msg, *, is_session_bootstrap, room_id
    ):
        try:
            await self.bridge.receive(self.role, msg, tools, participants_msg, room_id)
        except Exception as exc:
            if isinstance(exc, Conflict) and str(exc).startswith("Older Band delivery"):
                return
            with transaction() as c:
                case = c.execute(
                    "SELECT * FROM return_cases WHERE data->>'band_room_id'=%s FOR UPDATE",
                    (room_id,),
                ).fetchone()
                if case and case["status"] not in ("approved", "exception", "rejected"):
                    c.execute(
                        "UPDATE return_cases SET status='needs_review' WHERE id=%s", (case["id"],)
                    )
                    event(
                        c,
                        case,
                        "agent_error",
                        {
                            "message": (
                                str(exc)
                                if isinstance(exc, Conflict)
                                else "Live agent execution failed; inspect provider configuration."
                            ),
                            "error_type": type(exc).__name__,
                        },
                        self.role,
                    )
            raise


class LiveBridge:
    def __init__(self):
        required = [
            "ZOOWORK_API_KEY",
            "ZOOWORK_MODEL",
            "MOSS_PROJECT_ID",
            "MOSS_PROJECT_KEY",
            "TAVILY_API_KEY",
        ] + [f"BAND_{r.upper()}_{s}" for r in ROLES for s in ("AGENT_ID", "API_KEY")]
        if any(not os.environ.get(k) for k in required):
            raise ValueError("Missing sponsor configuration")
        self.band_ids = {r: os.environ[f"BAND_{r.upper()}_AGENT_ID"] for r in ROLES}
        if len(set(self.band_ids.values())) != 3:
            raise ValueError("Three distinct identities required")
        self.zoo = ZooworkClient()
        self.policy = PolicySearch()
        self.research = DestinationSearch()
        self.agents = []
        self.zoo_ids = {}
        self.locks = defaultdict(asyncio.Lock)
        self.rest = {
            r: AsyncRestClient(api_key=os.environ[f"BAND_{r.upper()}_API_KEY"]) for r in ROLES
        }

    async def start(self):
        models = await self.zoo.list_models()
        if not any(
            m["model"] == os.environ["ZOOWORK_MODEL"] and m.get("selectable", True) for m in models
        ):
            raise ValueError("Model unavailable")
        for role in ROLES:
            key = "zoo-agent-" + role
            with transaction() as c:
                saved = c.execute(
                    "SELECT * FROM provider_calls WHERE request_key=%s", (key,)
                ).fetchone()
            if saved:
                agent_id = saved["data"]["agent_id"]
            else:
                band_schema = AgentTools("bootstrap", self.rest[role]).get_tool_schemas("openai")
                messaging = [
                    {
                        "name": f["function"]["name"],
                        "description": f["function"]["description"],
                        "input_schema": f["function"]["parameters"],
                    }
                    for f in band_schema
                    if f["function"]["name"] == "band_send_message"
                ]
                created = await self.zoo.create_agent(
                    {
                        "name": "Smarter Returns " + role,
                        "model": {"primary": os.environ["ZOOWORK_MODEL"]},
                        "custom_tools": declarations(role) + messaging,
                        "include_global_skills": False,
                    },
                    idempotency_key=key,
                )
                agent_id = created["agent_id"]
                save_call(key, "zoowork", "created", {"agent_id": agent_id, "role": role})
            await self.zoo.start_agent(agent_id)
            await self.zoo.wait_until_running(agent_id)
            self.zoo_ids[role] = agent_id
            agent = Agent.create(
                adapter=ZooWorkBandAdapter(self, role),
                agent_id=self.band_ids[role],
                api_key=os.environ[f"BAND_{role.upper()}_API_KEY"],
            )
            await agent.start()
            self.agents.append(agent)

    async def initiation_receipt(self, room, key, job, initiator):
        """Read every context page, including authored messages. Never infer a resend
        is safe from absence alone after a send may have crossed the network."""
        cursor, seen = None, set()
        while True:
            response = await self.rest[initiator].agent_api_context.get_agent_chat_context(
                chat_id=room, cursor=cursor, request_options={"max_retries": 0}
            )
            for message in response.data or []:
                item = message.model_dump() if hasattr(message, "model_dump") else message
                try:
                    envelope = band_envelope(item.get("content", ""), self.band_ids.values())
                except (ValueError, TypeError):
                    continue
                if (isinstance(envelope, dict)
                    and envelope.get("case_id") == job["case_id"]
                    and envelope.get("version") == job["version"]
                    and (envelope.get("request_key") == key or envelope.get("event") == job["type"])
                    and item.get("sender_id") == self.band_ids[initiator]):
                    return item
            if not response.metadata.has_more:
                return None
            cursor = response.metadata.next_cursor
            if not cursor or cursor in seen:
                raise Conflict("Band history is incomplete; no message was resent.")
            seen.add(cursor)

    async def initiate(self, job):
        # The database lock spans network work, preventing concurrent leased jobs
        # or multiple workers from sending the same initiation.
        key = f"band-init-{job['case_id']}-{job['version']}-{job['type']}"
        with transaction() as guard:
            if not guard.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s)) AS acquired", (key,)).fetchone()["acquired"]:
                raise Conflict("This review is already being recovered.")
            await self._initiate(job, key)

    async def _initiate(self, job, key):
        with transaction() as c:
            case = case_locked(c, job["case_id"], job["version"])
            if case["status"] in ("approved", "exception", "rejected", "awaiting_approval"):
                return
            room = case["data"].get("band_room_id")
            saved = c.execute("SELECT * FROM provider_calls WHERE request_key=%s", (key,)).fetchone()
        target = "fulfillment" if job["type"] == "research" else ("policy" if job["version"] > 1 else "returns")
        initiator = "fulfillment" if target == "returns" else "returns"
        state = dict(saved["data"]) if saved else {"case_id": case["id"], "version": case["version"], "phase": "setup"}
        if saved and saved["status"] == "sent":
            await self.recover_deliveries(case, room)
            return
        if saved and state.get("phase") != "setup":
            if not room:
                raise Conflict("Band room creation acknowledgement is uncertain; no new room was created.")
            # Legacy records were written before setup. Only the exact old
            # pre-participant crash can be proved safe to retry automatically.
            setup = AgentTools(room, self.rest["returns"], agent_id=self.band_ids["returns"])
            await setup.get_participants()
            legacy_setup = not state.get("phase") and {p["id"] for p in setup.participants} == {self.band_ids["returns"]}
            if not legacy_setup:
                receipt = await self.initiation_receipt(room, key, job, initiator)
                if receipt:
                    save_call(key, "band", "sent", {**state, "room_id": room, "message_id": receipt.get("id"), "reconciled": True})
                    await self.recover_deliveries(case, room)
                    return
                raise Conflict("Band send acknowledgement is uncertain. No message was resent; check the Band room before continuing.")
            state.update(phase="setup", recovered_from="ChatParticipant TypeError before participant setup")
        save_call(key, "band", "pending", state)
        if not room:
            state["phase"] = "creating_room"
            save_call(key, "band", "pending", state)
            response = await self.rest["returns"].agent_api_chats.create_agent_chat(
                chat=ChatRoomRequest(), request_options={"max_retries": 0}
            )
            room = response.data.id
            with transaction() as c:
                current = case_locked(c, case["id"], case["version"])
                data = current["data"]
                data["band_room_id"] = room
                if os.environ.get("BAND_ROOM_URL_TEMPLATE"):
                    data["band_room_url"] = os.environ["BAND_ROOM_URL_TEMPLATE"].replace("{room_id}", room)
                c.execute("UPDATE return_cases SET data=%s WHERE id=%s", (Jsonb(data), case["id"]))
            state.update(phase="setup", room_id=room)
            save_call(key, "band", "pending", state)
        try:
            setup = AgentTools(room, self.rest["returns"], agent_id=self.band_ids["returns"])
            await setup.get_participants()
            present = {p["id"] for p in setup.participants}
            for role in ROLES:
                if self.band_ids[role] not in present:
                    await self.rest["returns"].agent_api_participants.add_agent_chat_participant(
                        chat_id=room,
                        participant=ParticipantRequest(participant_id=self.band_ids[role], role="member"),
                        request_options={"max_retries": 0},
                    )
            tools = AgentTools(room, self.rest[initiator], agent_id=self.band_ids[initiator])
            await tools.get_participants()
            state.update(phase="sending", room_id=room, addressed_role=target)
            save_call(key, "band", "pending", state)
            sent = await tools.send_message(
                content=json.dumps({"event": job["type"], "case_id": case["id"], "version": case["version"], "request_key": key,
                    "request": "Review current facts. Coordinate with your colleagues through addressed Band tools."}),
                mentions=[self.band_ids[target]],
            )
            if sent is None:
                raise Conflict("Band refused the initiation message.")
            save_call(key, "band", "sent", {**state, "phase": "sent", "receipt": json.loads(json.dumps(sent.model_dump() if hasattr(sent, "model_dump") else sent, default=str))})
        except Exception as exc:
            save_call(key, "band", "pending", {**state, "error_type": type(exc).__name__})
            raise

    async def recover_deliveries(self, case, room):
        # Resume the exact failed Band delivery, with its original ID. Tool and
        # ZooWork input caches therefore apply; no new initiation is sent.
        resumed = 0
        for role in ROLES:
            cursor, seen = None, set()
            while True:
                response = await self.rest[role].agent_api_messages.list_agent_messages(
                    room, cursor=cursor, limit=100, request_options={"max_retries": 0}
                )
                for msg in response.data or []:
                    delivery = (msg.metadata or {}).get("delivery_status", {}).get(self.band_ids[role], {})
                    if delivery.get("status") not in ("failed", "processing"):
                        continue
                    try:
                        envelope = band_envelope(msg.content, self.band_ids.values())
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(envelope, dict) or envelope.get("case_id") != case["id"] or envelope.get("version") != case["version"]:
                        continue
                    resumed += 1
                    tools = AgentTools(room, self.rest[role], agent_id=self.band_ids[role])
                    await tools.get_participants()
                    await self.rest[role].agent_api_messages.mark_agent_message_processing(room, msg.id, request_options={"max_retries": 0})
                    try:
                        await self.receive(role, SimpleNamespace(id=msg.id, room_id=room, content=msg.content, sender_id=msg.sender_id, sender_name=msg.sender_name), tools, tools.participants, room)
                        await self.rest[role].agent_api_messages.mark_agent_message_processed(room, msg.id, request_options={"max_retries": 0})
                    except Exception as exc:
                        await self.rest[role].agent_api_messages.mark_agent_message_failed(room, msg.id, error=type(exc).__name__, request_options={"max_retries": 0})
                        raise
                if not response.metadata.has_more:
                    break
                cursor = response.metadata.next_cursor
                if not cursor or cursor in seen:
                    raise Conflict("Band delivery history is incomplete; recovery stopped.")
                seen.add(cursor)
        if not resumed:
            with transaction() as c:
                current = case_locked(c, case["id"], case["version"])
                if current["status"] != "awaiting_approval":
                    raise Conflict("No interrupted delivery remains to resume. Check item condition to start a fresh review; no messages or shipping actions were repeated.")

    async def receive(self, role, msg, tools, participants, room):
        with transaction() as c:
            row = c.execute(
                "SELECT * FROM return_cases WHERE data->>'band_room_id'=%s", (room,)
            ).fetchone()
        if not row:
            raise Conflict("Room has no trusted return binding.")
        if msg.sender_id not in self.band_ids.values():
            raise Conflict("Sender is not a configured participant.")
        try:
            envelope = band_envelope(msg.content, self.band_ids.values())
        except (ValueError, TypeError):
            raise Conflict("Band message must carry the trusted case version.")
        if not isinstance(envelope, dict) or envelope.get("case_id") != row["id"] or envelope.get("version") != row["version"]:
            save_call(
                f"band-stale-{role}-{msg.id}",
                "band",
                "stale",
                {"case_id": row["id"], "message_id": msg.id},
            )
            return
        async with self.locks[(row["id"], role)]:
            await self.run_role(role, msg, tools, participants, row)

    async def run_role(self, role, msg, tools, participants, case):
        delivery_key = f"band-delivery-{role}-{msg.id}"
        with transaction() as c:
            done = c.execute(
                "SELECT * FROM provider_calls WHERE request_key=%s", (delivery_key,)
            ).fetchone()
            saved = c.execute(
                "SELECT data FROM agent_sessions WHERE case_id=%s AND role=%s", (case["id"], role)
            ).fetchone()
        if done and done["status"] == "done":
            return
        data = saved["data"] if saved else {}
        if data.get("version") is not None and data["version"] != case["version"]:
            data = {"previous_sessions": data.get("previous_sessions", []) + [data["session_id"]]}
        if data.get("active_message") and data["active_message"] != msg.id:
            raise Conflict("Previous role execution requires recovery before another delivery.")
        if not data.get("session_id"):
            session = await self.zoo.create_session(
                self.zoo_ids[role],
                idempotency_key=f"session-{case['id']}-{role}-{case['version']}-{case['created_at'].isoformat()}",
            )
            data = {
                **data,
                "session_id": session["session_id"],
                "agent_id": self.zoo_ids[role],
                "room_id": msg.room_id,
                "after": 0,
            }
        if not data.get("active_message"):
            data.update(
                active_message=msg.id,
                version=case["version"],
                posted=False,
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            save_session(case["id"], role, data)
        version = data["version"]
        if not data["posted"]:
            # Save pending before network. An ambiguous response stops rather than blindly reposting.
            if done and done["status"] == "posting":
                raise Conflict(
                    "ZooWork input acknowledgement uncertain; inspect session before retry."
                )
            save_call(
                delivery_key,
                "band",
                "posting",
                {"sender_id": msg.sender_id, "case_id": case["id"], "role": role},
            )
            context = {
                "trusted_case_id": case["id"],
                "expected_version": version,
                "sender_id": msg.sender_id,
                "sender_name": msg.sender_name,
                "participants": tools.participants,
                "band_message_id": msg.id,
                "message": msg.content,
                "role_instructions": Path("/app/prompts/" + role + ".md").read_text(),
            }
            await self.zoo.post_events(
                self.zoo_ids[role],
                data["session_id"],
                [
                    {
                        "type": "user.message",
                        "content": json.dumps(context, default=str),
                        "idempotency_key": delivery_key,
                    }
                ],
            )
            data["posted"] = True
            save_session(case["id"], role, data)
            save_call(
                delivery_key,
                "band",
                "running",
                {"case_id": case["id"], "role": role, "sender_id": msg.sender_id},
            )
        for _ in range(150):
            with transaction() as c:
                current = case_locked(c, case["id"])
                if current["version"] != version or current['data'].get('band_room_id')!=tools.room_id:
                    raise Conflict("Older Band delivery cannot change current facts.")
            # Pending REST calls cover a restart between request and event cursor persistence.
            pending = await self.zoo.list_custom_tool_calls(
                self.zoo_ids[role], session_id=data["session_id"], status="pending"
            )
            for call in pending:
                await self.resolve(
                    role, case["id"], version, call["call_id"], call["name"], call["input"], tools
                )
            events = await self.zoo.list_events(
                self.zoo_ids[role], data["session_id"], after=data["after"], limit=100
            )
            finished = False
            for ev in events:
                call = custom_tool_use(ev)
                if call and call.phase == "requested":
                    await self.resolve(
                        role, case["id"], version, call.call_id, call.name, call.input or {}, tools
                    )
                data["after"] = max(data["after"], ev.seq)
                save_session(case["id"], role, data)
                if is_run_finished(ev):
                    finished = True
            if finished:
                data.pop("active_message", None)
                save_session(case["id"], role, data)
                save_call(
                    delivery_key,
                    "band",
                    "done",
                    {
                        "case_id": case["id"],
                        "role": role,
                        "sender_id": msg.sender_id,
                        "session_id": data["session_id"],
                    },
                )
                return
            await asyncio.sleep(1)
        raise Conflict("Agent run deadline reached; merchant review required.")

    def bound_case(self, conn, case_id, version, room_id):
        case=case_locked(conn,case_id,version)
        if case['data'].get('band_room_id')!=room_id:
            raise Conflict('Older Band delivery belongs to a prior demo dataset.')
        return case

    async def resolve(self, role, case_id, version, call_id, name, args, tools):
        key = "zoo-tool-" + call_id
        with transaction() as c:
            self.bound_case(c,case_id,version,tools.room_id)
            cached = c.execute(
                "SELECT data FROM tool_results WHERE request_key=%s", (key,)
            ).fetchone()
        if cached:
            result = cached["data"]
        else:
            try:
                if name == "band_send_message":
                    with transaction() as c:
                        case = self.bound_case(c, case_id, version, tools.room_id)
                        if case["data"].get("handoffs", 0) >= 8:
                            raise Conflict("Eight handoffs reached; merchant review required.")
                    allowed=set(self.band_ids.values())
                    for participant in tools.participants:
                        if participant.get('id') in self.band_ids.values():
                            for field in ('name','handle'):
                                value=participant.get(field)
                                if value:
                                    allowed.update((value,'@'+value.lstrip('@')))
                    if not args.get("mentions") or any(m not in allowed for m in args["mentions"]):
                        raise Conflict("Explicit configured recipient required.")
                    with transaction() as c:
                        uncertain = c.execute(
                            "SELECT * FROM provider_calls WHERE request_key=%s", (key,)
                        ).fetchone()
                    if uncertain:
                        if uncertain["status"] == "sent":
                            result = {"ok": True, "receipt": uncertain["data"].get("receipt", {"saved_acknowledgement": True})}
                        elif uncertain["data"].get("has_message_marker"):
                            receipt = await self.initiation_receipt(tools.room_id, key, {"case_id": case_id, "version": version, "type": "handoff"}, role)
                            if not receipt:
                                raise Conflict("Outgoing message acknowledgement uncertain; no automatic resend.")
                            result = {"ok": True, "receipt": receipt}
                            save_call(key, "band", "sent", {**uncertain["data"], "receipt": receipt, "reconciled": True})
                        else:
                            raise Conflict("Outgoing message acknowledgement uncertain; no automatic resend.")
                        with transaction() as c:
                            c.execute("INSERT INTO tool_results VALUES(%s,%s) ON CONFLICT DO NOTHING", (key, Jsonb(result)))
                        await self.zoo.resolve_custom_tool_call(self.zoo_ids[role], call_id, content=[{"type":"json","value":result}], is_error=False, resolved_by="smarter-returns-worker")
                        return
                    with transaction() as c:
                        case=self.bound_case(c,case_id,version,tools.room_id)
                        d=case['data']
                        if d.get('handoffs',0)>=8: raise Conflict('Eight handoffs reached; merchant review required.')
                        d['handoffs']=d.get('handoffs',0)+1
                        c.execute('UPDATE return_cases SET data=%s WHERE id=%s',(Jsonb(d),case_id))
                        c.execute('INSERT INTO provider_calls(request_key,provider,status,data) VALUES(%s,%s,%s,%s)',(key,'band','pending',Jsonb({'case_id':case_id,'version':version,'room_id':tools.room_id,'mentions':args['mentions'],'has_message_marker':True})))
                    addressed = dict(args)
                    addressed["content"] = json.dumps(
                        {"version": version, "case_id": case_id, "request_key": key, "message": args["content"]}
                    )
                    sent = await tools.execute_tool_call(name, addressed)
                    result = {"ok": True, "receipt": json.loads(json.dumps(sent, default=str))}
                    save_call(
                        key, "band", "sent", {"case_id": case_id, "mentions": args["mentions"], "receipt": result["receipt"]}
                    )
                    with transaction() as c:
                        case = self.bound_case(c, case_id, version, tools.room_id)
                        event(
                            c,
                            case,
                            "band_handoff",
                            {"message": f"{role} sent an addressed Band handoff."},
                            role,
                        )
                elif name == "search_policy" and role == "policy":
                    result = await self.policy.search(args["query"])
                    with transaction() as c:
                        case = self.bound_case(c, case_id, version, tools.room_id)
                        d = case["data"]
                        if result["policy_version"] != merchant(c)["policy_version"]:
                            raise Conflict("Policy changed during retrieval; search again.")
                        if (
                            d.get("policy_case_version") != version
                            or d.get("retrieval_policy_version") != result["policy_version"]
                            or d.get("policy_retrieval_provider") != "moss"
                        ):
                            d["policy_passage_ids"] = []
                        d["policy_passage_ids"] = list(
                            set(d.get("policy_passage_ids", []))
                            | {p["id"] for p in result["passages"]}
                        )
                        d["policy_case_version"] = version
                        d["retrieval_policy_version"] = result["policy_version"]
                        d["policy_retrieval_provider"] = "moss"
                        c.execute(
                            "UPDATE return_cases SET data=%s WHERE id=%s", (Jsonb(d), case_id)
                        )
                    save_call(key, "moss", "succeeded", {"case_id": case_id, **result})
                elif name == "discover_destinations" and role == "fulfillment":
                    with transaction() as c:
                        case = self.bound_case(c, case_id, version, tools.room_id)
                        product = c.execute(
                            "SELECT data FROM products WHERE id=%s", (case["data"]["sku"],)
                        ).fetchone()["data"]
                        location = c.execute(
                            "SELECT data FROM locations WHERE id=%s",
                            (case["data"]["origin_zone_id"],),
                        ).fetchone()["data"]
                        cache = c.execute(
                            "SELECT data FROM provider_calls WHERE provider='tavily' AND status='succeeded' AND data->>'category'=%s AND data->>'city'=%s AND created_at>now()-interval '1 hour' LIMIT 1",
                            (product["category"], location["city"]),
                        ).fetchone()
                    results = (
                        cache["data"]["results"]
                        if cache
                        else await self.research.search(product["category"], location["city"])
                    )
                    with transaction() as c:
                        self.bound_case(c, case_id, version, tools.room_id)
                        for candidate in results:
                            existing = c.execute(
                                "SELECT id FROM destinations WHERE data->>'source_url'=%s",
                                (candidate["source_url"],),
                            ).fetchone()
                            if not existing:
                                candidate["id"] = uid("EXT"); candidate["merchant_id"] = "merchant-demo-01"
                                c.execute(
                                    "INSERT INTO destinations VALUES(%s,%s)",
                                    (candidate["id"], Jsonb(candidate)),
                                )
                        event(
                            c,
                            case,
                            "external_research",
                            {
                                "message": f"{len(results)} Tavily candidates saved for merchant verification."
                            },
                            role,
                        )
                    result = {"results": results}
                    save_call(
                        key,
                        "tavily",
                        "succeeded",
                        {
                            "case_id": case_id,
                            "category": product["category"],
                            "city": location["city"],
                            **result,
                        },
                    )
                else:
                    with transaction() as c:
                        self.bound_case(c,case_id,version,tools.room_id)
                        result = execute(c, role, case_id, version, name, args)
                        result = json.loads(json.dumps(result, default=str))
                        c.execute(
                            "INSERT INTO tool_results VALUES(%s,%s) ON CONFLICT DO NOTHING",
                            (key, Jsonb(result)),
                        )
                result = json.loads(json.dumps(result, default=str))
            except Conflict as exc:
                if str(exc).startswith("Outgoing message acknowledgement uncertain"):
                    # Keep the ZooWork tool pending and fail this Band delivery.
                    # Resolving an ambiguous send as an ordinary tool error would
                    # let the model issue another call and duplicate the message.
                    raise
                result = {"error": str(exc)}
                if name == "create_proposal":
                    # Return exact trusted identifiers so a model can correct a
                    # rejected destination rather than guessing ID formats.
                    from .routing import routes
                    with transaction() as c:
                        current = self.bound_case(c, case_id, version, tools.room_id)
                        result["current_routes"] = routes(c, current)
            except Exception as exc:
                with transaction() as c:
                    pending_send = c.execute("SELECT 1 FROM provider_calls WHERE request_key=%s AND provider='band' AND status='pending'", (key,)).fetchone()
                if pending_send:
                    raise
                save_call(
                    key,
                    "provider",
                    "failed",
                    {"case_id": case_id, "error_type": type(exc).__name__},
                )
                raise
            with transaction() as c:
                c.execute(
                    "INSERT INTO tool_results VALUES(%s,%s) ON CONFLICT DO NOTHING",
                    (key, Jsonb(result)),
                )
        await self.zoo.resolve_custom_tool_call(
            self.zoo_ids[role],
            call_id,
            content=[{"type": "json", "value": result}],
            is_error="error" in result,
            resolved_by="smarter-returns-worker",
        )
