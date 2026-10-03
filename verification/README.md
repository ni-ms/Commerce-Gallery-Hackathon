# Verification record — October 3, 2026

Verified on Docker Desktop, Linux ARM64 containers. Host language/database runtimes were not used to build or run the application.

- PostgreSQL business and SDK contract suite: **17 passed**. One library deprecation warning, no failed tests.
- TypeScript check and Vite production build: passed. The frontend dependency audit reported zero known vulnerabilities. This is not a complete security audit.
- Original verification before local policy search replacement: all four sponsor runtime SDKs installed and imported in the actual Linux image: ZooWork 0.5.2, Band SDK 4.0.0, Moss 1.14.0, Tavily Python 0.8.4.
- Pinned development container built and verified with its persistent home volume: Entire 0.11.3, Codex CLI 0.128.0, Git, PostgreSQL client utilities.
- Browser login and cookie session: passed. Unauthorized API reads and incorrect/missing write Origin: rejected by tests.
- Browser normal case: RET-001 proposed BUY-001 at $6 against $15 warehouse; approval required sealed confirmation, then saved SHIP-362fc9d37cf8 with $9 approved estimated savings.
- Browser inspection conflict: RET-002 initially proposed BUY-002 at $8. Opened inspection immediately invalidated that plan; buyer became blocked, hold was released, and a new $11 inspection proposal required approval with case version 2 and POL-003 evidence. See `inspection-reroute.jpg`.
- Real running HTTP API + worker check: created RET-eeaa1aecca77, processed its warehouse proposal, approved SHIP-1ac7c5bfa112, and returned that same shipment on repeated approval.
- Restarted PostgreSQL, API, worker, and Caddy. Queries before and after contained the identical case statuses/versions and both shipment IDs. Browser login session and saved decisions also survived reload.
- Execution-evidence screen showed demo mode and **no live provider calls recorded**, correctly distinguishing simulations from sponsor executions.
- Mobile breakpoint at 390 CSS pixels: body/main/document width 390 and scroll width 390; no horizontal overflow. Normal viewport restored after verification. See `mobile.jpg`.

The reservation race uses concurrent database connections. A separate expired-job-lease test reclaims a running job and replays a plan without duplicating the active reservation/proposal. Tool permission and version tests reject unauthorized/stale agent writes. Run-deadline test stops incomplete work for merchant review.

**Not verified:** live sponsor calls, actual remote message/session recovery, real merchant participation, organizer award rules, genuine Entire captured coding checkpoint, and public HTTPS hosting. No sponsor credentials, authenticated container coding session, or hosting target were supplied. See `../submission.md` and `../README.md` for exact remaining steps. Fixture lookups and UI timelines are not live Moss/Band/ZooWork/Entire evidence.

## Local policy search replacement

Moss SDKs and credential requirements were removed. Policy retrieval now uses keyword ranking over current merchant/version passages in PostgreSQL. The rebuilt container suite passed **23 tests**, including condition retrieval, tenant/version filtering, unmatched queries, and rejection of stale/unretrieved evidence. This does not establish live ZooWork/Band/Tavily execution.

## Moss restored

Moss 1.14.0 and its native runtime were restored, with versioned index loading and provider receipts. Retrieval retains merchant/version filtering and stale-evidence checks. The rebuilt container suite passed **19 tests**, including mocked Moss indexing/query behavior and native SDK imports. Live Moss access remains unverified until the new project credentials are supplied.

## Live review recovery and simplified UI — October 3, 2026

This section supersedes the earlier live-provider limitations for the review of RET-115451f05dd0. Historical demo results above remain historical; the live run was not replaced with a simulation.

- Original failure reproduced against the saved Band room: `get_participants()` returns `ChatParticipant` models; dictionary indexing raised `TypeError: 'ChatParticipant' object is not subscriptable`. The room had only Returns and no message history. Its pending record made the next attempt report an uncertain acknowledgement instead of the original exception.
- Setup now uses normalized participant snapshots and records durable setup/creation/send phases. Recovery reuses the existing room, reconciles authored messages across all history pages, and resumes failed/processing deliveries by their original message IDs. Uncertain sends are never blindly repeated. Outgoing handoffs retain a pending ZooWork tool until a saved or reconciled Band receipt is available.
- Live execution also exposed Band's rendered mention prefix and missing destination IDs in handoff text. The envelope parser accepts only configured prefix mentions and validates both case ID and version. Agent case context and rejected-proposal responses now expose exact route IDs; prompts require them in route handoffs.
- Actual live result: all three ZooWork role sessions completed, Band delivered the handoffs, and two Moss queries succeeded. The case retained version 1 and its original item, reason and reported condition. Proposal `PLAN-3f342b2861b6` recommends `dest-warehouse` (Sample merchant warehouse) for $15 estimated total: $12 shipping plus $3 handling. Status: `awaiting_approval`. Zero shipments exist for this case. No approval was submitted.
- Existing credentials, database volume, 12 cases, prior shipments, and evidence were preserved. The old failed research job was not replayed; repair research is irrelevant to this sealed item and its legacy acknowledgement remains unresolved. Unmarked legacy ambiguous sends still require external receipt investigation.
- Final isolated PostgreSQL/SDK regression suite: **26 passed**, with one dependency deprecation warning. Checks include exact receipt reuse, uncertain initiation and handoff sends, original delivery resumption, repeat recovery, confirmation and optional photo storage, stale approvals, concurrent reservations, duplicate shipping prevention, and demo/live review deadlines.
- TypeScript checking and Vite production build passed inside Docker. API, worker and web were rebuilt; API/worker/database health checks passed. HTML is revalidated after rebuilds to avoid stale screens.
- Browser verification used the live case: safe recovery, final recommendation and cost, secondary alternatives/policy/activity/versions/provider evidence, four condition choices, optional photo preview, disabled save until merchant confirmation, and repair research present only for damaged items. Photo persistence/validation was checked in the isolated database; the live case's condition was not changed. See `live-review.jpg` and `condition-check.jpg`.

Remaining limits: merchant approval is still required. Shipping creation and cost estimates remain the application's existing simulation/fixed synthetic quotes; no carrier label or physical shipment was created. Tavily research was not part of this live review verification.
