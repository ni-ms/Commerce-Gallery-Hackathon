# Smarter Returns

A merchant workspace for choosing a returned item's next eligible destination. Built with React/TypeScript, FastAPI, PostgreSQL 16, a persistent Python worker, and Caddy. The laptop needs Docker with Compose and a browser; language runtimes, SDKs, database utilities, and development tools run in containers.

**This is a synthetic prototype.** Gallery Home Lighting is fictional. Customers, policy, costs, and shipments are synthetic. Savings are estimates, not measured savings. A real merchant, actual carrier/order integrations, event eligibility, live sponsor round trips, a genuine Entire checkpoint, and an external HTTPS deployment remain separate requirements until verified.

## Start locally

From this directory, initialize private local settings:

```sh
docker run --rm -v "$PWD:/workspace" alpine:3.21 sh -c 'apk add --no-cache openssl >/dev/null && sh /workspace/infra/setup.sh'
docker compose up -d --build
```

Open [http://localhost:8080](http://localhost:8080). Read `MERCHANT_PASSCODE` from the generated `.env` in your editor and sign in. The setup script leaves existing files untouched, creates random secrets, and gives both environment files private permissions. Do not commit them. Set your preferred passcode in `.env` and recreate the API if desired.

The default `EXECUTION_MODE=demo` runs a deterministic, visibly labeled fixture simulation. It lets you verify business behavior without accounts. It does **not** establish sponsor use. The live worker never substitutes this simulation when a provider fails.

Only Caddy publishes ports. PostgreSQL, the API, and the worker remain on the Compose network. Volumes preserve database data and Caddy certificates across restarts and rebuilds. Do not use `docker compose down -v` unless you intentionally want to erase this installation.

## Use the application

Seeded cases start as submitted; none reserves a buyer until started. Click **Start review**, or select a **Fresh demo scenario** and click its reset button. Reset erases the synthetic dataset, including earlier approvals. It is authenticated and restricted to the synthetic merchant/database.

- **normal**: RET-001 matches BUY-001; $6 route vs. $15 warehouse, $9 potential estimated savings. Confirm the sealed condition and approve one simulated shipment.
- **inspection-block**: RET-002 initially proposes BUY-002 at $8. Record opened / “Seal is broken” before approval. The old plan is immediately invalid, the reservation released, and the worker proposes inspection at $11. Approve the new plan separately.
- **external-research**: RET-003 cannot forward to a buyer. In live mode, research repair options through Tavily. Candidates retain their source and lookup time and require merchant confirmation of acceptance and costs. Demo mode explicitly reports research unavailable, without seeding the external placeholder.
- **no-waiting-buyer** and **uncertain-condition**: warehouse and inspection fallbacks.
- **competing-returns**: RET-006 and RET-007 compete for BUY-005. Only one can reserve it.
- **reservation-expiry**: a synthetic-only 15-second reservation. After expiry approval fails and review is required; it does not silently extend a buyer's hold.
- **policy-change**: start RET-009, then use the authenticated demo policy endpoint below to disable forwarding. Current proposals and holds become invalid immediately.
- **duplicate-approval**: repeat an approval; it returns the same shipment.
- **worker-restart**: start RET-001, restart the worker, then approve. A completed proposal is preserved.

Recording an inspection after approval creates a human exception. It never undoes a dispatched/approved shipment by editing its record. Rejecting a proposal closes that review and releases the hold.

## Sponsor setup and honest status

Put credentials in `.env.providers` using `.env.providers.example`. Moss requires `MOSS_PROJECT_ID` and `MOSS_PROJECT_KEY`. Only the worker loads that file. Set `EXECUTION_MODE=live` in `.env`, choose a selectable `ZOOWORK_MODEL`, and recreate services:

```sh
docker compose up -d --force-recreate api worker
```

Register **three distinct Band remote agents** in your account and supply each ID and private key. They should have role descriptions and handles corresponding to returns, policy, and fulfillment. Account provisioning remains in sponsor dashboards; this project never invents registrations or participation. `BAND_ROOM_URL_TEMPLATE` is optional and must be the actual room URL pattern for your tenant, containing `{room_id}`.

The worker validates all required credentials, checks the ZooWork model catalog, idempotently creates three configured ZooWork agents, and connects three Band adapters. Band delivers addressed messages. ZooWork requests custom tools and selects addressed Band handoffs; the backend does not hard-code the role sequence in live mode. Tool permissions bind to configured role identity and the trusted room/case, with expected versions on writes. No agent has an approval tool.

Moss creates and loads a versioned index of policy passages from the application database. Retrieved IDs must be present in the saved query results, and a condition-specific passage is required before a finding or proposal can proceed. Structured rules independently enforce policy. Tavily searches only category and general city, caches repeated lookups for one hour, and stores at most three unverified candidates. Verification recalculates pending plans.

The separate **Execution evidence** view shows actual provider receipts, failures, and saved session IDs. SDK import/schema tests are not live integration proof. No live call has been verified merely by installing an SDK. With credentials configured, use the browser's normal and damaged cases to verify the round trip. A diagnostic is also available (stop the regular worker first to avoid competing Band connections):

```sh
docker compose stop worker
docker compose run --rm worker python -m app.smoke
docker compose start worker
```

Official integration references: [ZooWork SDK](https://zoowork.ai/docs/en/reference/python-sdk), [Band adapter interface](https://docs.band.ai/integrations/sdks/tutorials/creating-framework-integrations), [Moss SDK](https://github.com/usemoss/moss), [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search).

## Verification in containers

Create the separate test database once, then run tests:

```sh
docker compose exec -T db createdb -U returns returns_test
docker compose --profile test run --rm --build --no-deps test
```

If the database already exists, skip `createdb`. The test service points only at `returns_test` and resets it between tests. It cannot erase the application's `returns` database. Tests use real PostgreSQL transactions and simultaneous threads for reservation contention. They cover cost math, uniqueness, idempotent shipments, inspection and policy changes, expiry, unknown/damaged conditions, missing quotes/evidence, unverified destinations, simulated restart/repeated plan, and session/origin enforcement. Provider contract tests instantiate the pinned Band adapter/tool schemas, parse a ZooWork event, and import Moss/Tavily; they do not contact sponsors.

The web image runs the TypeScript check and production build. The final web server contains static assets and Caddy, without a Node runtime or development server.

## Recovery and durability

Jobs are claimed with row locks and a three-minute lease. An expired lease is reclaimed; transient job failures retry up to three times. Expired reservations invalidate their proposal and enqueue review. Case/version checks protect against late work. Database uniqueness enforces one active reservation per item/buyer and one shipment per case/proposal.

ZooWork agent IDs, case/role sessions, pending tool calls, delivery state, and event cursors are saved. Business tools record their result in the same transaction as their effect. Band outgoing sends are recorded as pending before network use. An ambiguous acknowledgement requires review rather than indefinite resends. Exactly-once external delivery is not promised. Live recovery and adapter behavior still require account-backed testing.

Inspect status without revealing environment values:

```sh
docker compose ps
docker compose logs --tail=100 worker api
docker compose restart worker api web
```

## Development and Entire

Use the separate development-tools container locally, never on the hosting machine:

```sh
docker compose -f compose.devtools.yaml build
docker compose -f compose.devtools.yaml run --rm devtools
```

Git, Node, Python, PostgreSQL client utilities, Codex CLI, and Entire are inside this container. A private volume persists login state. Inside it, initialize Git if this directory has no repository, authenticate the coding CLI, and enable Entire **before** the coding work to be captured:

```sh
git init
codex login --device-auth
entire login --device
entire enable --agent codex --skip-push-sessions --telemetry=false
codex
```

Device authentication can require workspace enablement; follow [official Codex authentication guidance](https://learn.chatgpt.com/docs/auth). Entire uses its file-backed token store inside this container. Inspect `entire status`, make a real correctness change through the authenticated coding session, run its tests, commit that work, and inspect `entire checkpoint list` / `entire checkpoint explain <id>`. Do not fabricate transcripts or present this app timeline as an Entire checkpoint. This desktop coding session was not running in that container, so installing Entire cannot retroactively make it a captured session. See [Entire's official workflow](https://github.com/entireio/cli).

## Host on a Linux machine

Copy this source to a Docker-capable Linux server. Configure secrets through protected files, point a domain at the server, and allow public ports 80 and 443. In `.env`, set actual values:

```dotenv
SITE_ADDRESS=returns.your-domain.example
APP_ORIGIN=https://returns.your-domain.example
HTTP_BIND=80:80
HTTPS_BIND=443:443
EXECUTION_MODE=live
```

Then `docker compose up -d --build`. Caddy obtains HTTPS when DNS and inbound connectivity are correct. Keep `caddy_data` persistent. Secure session cookies are enabled for an HTTPS origin. Never expose database/API ports; do not start the devtools container there. Verify login, normal forwarding, inspection blocking, live sponsor evidence, and persistence through a restart at the real domain. No public deployment has been claimed without doing this.

Before migrations, take a PostgreSQL backup with the container's own tools:

```sh
mkdir -p backups
docker compose exec -T db pg_dump -U returns -d returns -Fc > backups/returns.dump
```

Restore into a separate empty database first and verify it. The bootstrap migration and seed are idempotent; rebuilds leave existing data intact. The shared merchant passcode supports a controlled prototype; real multi-merchant operation needs individual users, tenancy enforcement, audit controls, real destination acceptance, and carrier/order connections.

## API

All case, evidence, and mutation endpoints require a signed, HttpOnly merchant session. Write requests also require `Origin` equal to `APP_ORIGIN`; a process-local limiter restricts requests. Log in with `POST /api/login`, then use:

- `GET /api/catalog`, `GET /api/returns`, `GET /api/returns/{id}`
- `POST /api/returns` (SKU, origin zone, reported condition, reason, purchase age)
- `POST /api/returns/{id}/start` and `/research` (`expected_version`)
- `POST /api/returns/{id}/approve` (`expected_version`, `proposal_id`, `request_key`, `confirmed_condition`)
- `POST /api/returns/{id}/reject` (`expected_version`)
- `POST /api/returns/{id}/inspection` (`expected_version`, `condition`, `note`)
- `GET /api/returns/{id}/events?after=0`, `GET /api/integrations`
- `POST /api/destinations/{id}/verify` (integer shipping/service cents, accepted conditions, note)
- `POST /api/demo/reset` (`scenario_id`), synthetic data only
- `POST /api/demo/policy` (`direct_forwarding_enabled`), synthetic merchant only
- `POST /api/logout`; public `GET /api/health/live` and `/ready`

Money uses integer cents. Missing quotes block a route. Approval rechecks case and policy versions, current route eligibility/costs, condition confirmation, and a live reservation within one transaction. It creates one **simulated** shipment.
