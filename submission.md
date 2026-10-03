# Smarter Returns — implementation evidence

“We help a merchant find a cheaper eligible destination for a return, and change the plan safely when inspection changes the facts.”

## Implemented

Docker Compose services for a React/TypeScript merchant screen, FastAPI API, PostgreSQL persistence, leased background worker, and Caddy hosting. Container-only development tools. Authenticated merchant approval, transaction-enforced buyer/item reservations, current policy evidence, cost comparison, inspection invalidation, destination verification, timelines, and repeat-safe simulated shipment creation.

Live sponsor code uses separate Band identities and ZooWork sessions, model-selected addressed Band handoffs, custom tools bound to trusted role/case/version, Moss search, and Tavily discovery. A separate execution view exposes recorded receipts. Demo mode openly runs a deterministic simulation; it never claims live provider use.

## Verified locally

See README and the verification record for the actual executed checks. Business tests use PostgreSQL and a real concurrent reservation race. SDK compatibility tests check installed interfaces on Linux ARM64; this is different from live sponsor execution.

## Presentation cases

1. RET-001 → BUY-001: $6 estimated route against a $15 warehouse route; $9 potential savings, later approved estimated savings after one simulated shipment.
2. RET-002: an opened inspection finding immediately invalidates the $8 buyer plan, releases the hold, and enables an $11 inspection plan requiring new approval.
3. RET-003: damaged condition prevents buyer forwarding. In configured live mode Tavily candidates require merchant verification; demo mode reports research unavailable and keeps approved inspection/warehouse options.

## Unmet external requirements

- Real merchant participation and supplied policy: not established. Gallery Home Lighting and all fixture customer/order records are fictional.
- Event-specific award/submission rules: not verified from an organizer-provided submission URL.
- Live ZooWork/Band/Moss/Tavily round trip: not verified without sponsor credentials and account access.
- Genuine Entire development checkpoint: not captured by this desktop session. The separate development container supports the actual future captured workflow.
- Public HTTPS deployment: not performed without a server/domain and hosting access. The complete application can be hosted using the documented Compose/Caddy configuration.
- Real shipping, refunds, customer messages, product safety assessment, or measured financial savings: not provided.

Do not mark the full sponsor-prize definition of done complete until those requirements have evidence. Do not replace missing live executions with fabricated transcripts, synthetic search sources, or placeholder destinations.
