# Sample data for Smarter Returns

This folder contains **fictional demo data**. The merchant, customers, orders, policies, and prices are invented. Pittsburgh area names provide familiar location labels; shipping costs are not actual carrier quotes. No real merchant participation is implied.

The files are ready to use as input when implementing the seed loader. The application and loader do not exist yet. The scenario actions describe behavior to implement; they are not executable scripts.

## Included data

| File | Contents |
| --- | --- |
| [merchants.json](merchants.json) | One clearly named fictional merchant |
| [products.json](products.json) | Five lamp products with weights and prices |
| [locations.json](locations.json) | Three Pittsburgh area labels and a fictional warehouse zone |
| [returns.json](returns.json) | Ten return cases, including sealed, opened-on-inspection, damaged, and uncertain items |
| [buyer-orders.json](buyer-orders.json) | Four buyers waiting for matching products |
| [destinations.json](destinations.json) | Merchant-approved sample warehouse and inspection center |
| [shipping-costs.json](shipping-costs.json) | Six fixed shipping estimates, handling fees, and reservation settings |
| [policy-passages.json](policy-passages.json) | Eight policy passages with stable IDs for Moss |
| [scenarios.json](scenarios.json) | Ten exercises and the expected outcomes |
| [external-destination-example.json](external-destination-example.json) | An unverified placeholder for offline screen development |
| [Return policy](../policies/return-policy.md) | Readable fictional merchant policy |
| [Inspection instructions](../policies/inspection-rules.md) | Condition reporting and the failure exercise |
| [Routing rules](../policies/routing-rules.json) | Rules the application should enforce in code |

Every JSON file marks the data as synthetic. Fixture collections contain `metadata` and `records`. The routing-rules file contains settings directly instead of a records list.

## The three strongest presentation cases

### 1. A return finds its next buyer

Use **RET-001**, the unopened reading lamp, and **BUY-001**, a waiting buyer downtown.

- Warehouse: $12 shipping + $3 handling = **$15**.
- Waiting buyer: $5 shipping + $1 handling = **$6**.
- Difference: **$9 in estimated savings**, based entirely on sample costs.

The agents check policy, reserve the returned item, and prepare a proposal. The merchant confirms the relevant condition and approves it. The application saves one simulated shipment.

Show both the cost calculation and the saved reservation. Keep the claimed condition visibly separate from a verified inspection finding.

### 2. Inspection changes the destination

Use **RET-002**, the desk lamp, and **BUY-002**, the waiting buyer in Shadyside.

Initially, its form reports sealed:

- Buyer route: $7 shipping + $1 handling = **$8**.
- Warehouse route: **$15**.

After the proposal appears, record an inspection finding of **opened**, with the observation “Seal is broken.” Do this before approval or dispatch.

The old proposal must become invalid. The policy agent uses **POL-003** from Moss to explain the block. Fulfillment releases the buyer reservation and proposes inspection:

- Inspection route: $7 shipping + $4 handling = **$11**.
- Current difference from the warehouse route: **$4**.

A new merchant approval is required. No $8 shipment has taken place, so there is no earlier shipping leg to charge in this exercise. If a shipment had already happened, the app must include that cost and handle an exception.

### 3. A damaged return needs another option

Use **RET-003**, the ceramic lamp with a cracked base.

A waiting buyer exists, but policy blocks forwarding a damaged item. Ask the fulfillment agent to research repair or resale destinations with Tavily.

Suggested search input: **lamp repair Pittsburgh**. This is a suggested query, not a claim that a particular business exists or accepts returns.

Save actual search results with source URLs and lookup times. New candidates stay unverified until the merchant confirms acceptance and costs. While that review is pending, the sample inspection center and warehouse remain available.

Do not seed the external placeholder into the live results or present it as a real Tavily response. A search can return no usable result; that should be an understandable outcome.

## Other exercises

| Scenario | Case | What to demonstrate |
| --- | --- | --- |
| No waiting buyer | RET-004 | There is no matching buyer; use a known eligible destination |
| Uncertain condition | RET-005 | The system asks for evidence or inspection instead of inventing certainty |
| Competing returns | RET-006 and RET-007 | Both match BUY-005, but only one can reserve that waiting order |
| Reservation expiry | RET-008 | A 15-second test reservation expires and approval fails |
| Policy change | RET-009 | Disable forwarding in a new policy version; the old proposal becomes invalid |
| Duplicate approval | RET-010 | Repeat one approval request; the same shipment is returned |
| Worker restart | RET-001 | Restart after reservation; recover without creating duplicate effects |

## How the seed loader should work

1. Validate all file formats and references before writing anything.
2. Load the merchant, locations, products, approved destinations, shipping estimates, and buyer orders.
3. Load returns as submitted cases, without automatically starting every case.
4. Set each case’s creation time to the current scenario start. Calculate buyer deadlines relative to that start so fixtures do not become outdated.
5. Add policy passages to Moss with merchant ID, policy version, and source ID attached. Keep the structured routing rules in the application.
6. Start only the cases named in the selected scenario. Unstarted cases must not reserve items or consume waiting demand.
7. Run each scenario with a fresh copy of the synthetic data. Otherwise, an earlier case can consume a buyer needed by a later exercise.
8. For the race exercise, start RET-006 and RET-007 together in the same fresh dataset. Do not predetermine the winner.
9. Apply the short reservation setting only in a dedicated test/demo configuration, not through an unauthenticated public endpoint.
10. For the policy-change exercise, update the structured rule, increment the policy version, and update the Moss passages to match. Restoring the scenario also restores the original policy.

Implement a reset that is allowed only for the clearly marked synthetic dataset. It must not delete real merchant data. Use a separate demo database or enforce the synthetic merchant ID in every reset operation.

The selected route should be the lowest-cost eligible route among known, sufficiently verified options. Missing costs make a route unavailable rather than free. If a merchant chooses a different eligible route, show that choice explicitly instead of claiming automatic cost optimization.

## What is sample data and what must be real

| Part | Can be synthetic for the prototype? | Evidence needed for sponsor use |
| --- | --- | --- |
| Products, customers, orders, and shipping estimates | Yes, visibly labeled | Show their effect on the actual application state |
| Merchant policy | Yes for technical testing | Real merchant context remains a separate event requirement |
| ZooWork execution | Offline fixtures may support tests | Real agent session and tool execution for the submission |
| Band communication | Offline fixtures may support tests | Actual addressed messages and dependent handoffs |
| Moss | Uses this sample policy | Actual index query and saved passage IDs |
| Tavily research | Placeholder allowed for offline tests | Actual search result or a transparently reported live search failure |
| Entire development record | No fabricated record | Actual captured coding session connected to a commit |

No public retail dataset is needed for this small version. These fixtures cover the business rules without introducing real customer records. They do not replace the deck’s request to choose a real merchant.
