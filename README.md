# Smarter Returns

A merchant workspace that recommends eligible destinations for returned items, compares estimated costs, and requires merchant approval. Built with React/TypeScript, FastAPI, PostgreSQL, a Python worker, and Caddy.

The merchant, orders, policies, and costs are synthetic. Shipments are simulated; savings are estimates.

## Run locally

Requires Docker with Compose and a browser. From the project directory:

```sh
docker run --rm -v "$PWD:/workspace" alpine:3.21 sh -c 'apk add --no-cache openssl >/dev/null && sh /workspace/infra/setup.sh'
docker compose up -d --build
```

Open [localhost:8080](http://localhost:8080) and sign in with `MERCHANT_PASSCODE` from `.env`. Setup creates private `.env` and `.env.providers` files without overwriting existing settings. Do not commit them.

The default `EXECUTION_MODE=demo` uses a labeled simulation and needs no provider accounts. Database data persists across restarts. `docker compose down -v` deletes it.

## Use the demo

Choose a return and click **Start review**. Review the recommendation, confirm the item's condition, then approve or reject it. Recording a changed condition invalidates a pending proposal and triggers another review.

Use **Fresh demo scenario** to try buyer matching, inspection changes, damaged-item research, reservation conflicts, and expiry. Resetting a scenario erases the synthetic dataset, including previous approvals.

## Live integrations

Fill in `.env.providers` using [.env.providers.example](.env.providers.example):

- ZooWork API key and available model.
- Three distinct Band remote agents for returns, policy, and fulfillment, each with an ID and API key.
- Moss project ID and key.
- Tavily API key for repair research.

Set `EXECUTION_MODE=live` in `.env`, then recreate the services:

```sh
docker compose up -d --force-recreate api worker
```

Live mode never falls back to the demo simulation. **Execution evidence** shows provider receipts and failures. Research destinations require merchant confirmation of acceptance and costs before use. Shipments and shipping quotes remain synthetic in live mode.

See the [verification record](verification/README.md) for tested behavior and remaining limitations.

## Tests and maintenance

Create the test database once, then run the suite:

```sh
docker compose exec -T db createdb -U returns returns_test
docker compose --profile test run --rm --build --no-deps test
```

Skip `createdb` if `returns_test` already exists. Tests reset only that separate database. The web image runs TypeScript checks and a production build.

Inspect services or restart them:

```sh
docker compose ps
docker compose logs --tail=100 worker api
docker compose restart worker api web
```
