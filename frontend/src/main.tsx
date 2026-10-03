import React, { useState, useEffect } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowUpRight,
  ArrowRight,
  Box,
  Check,
  ChevronRight,
  Clock,
  Leaf,
  LogOut,
  Plus,
  RotateCcw,
  Search,
  ShieldCheck,
  Truck,
  X,
} from "./icons";
import "./style.css";
type Row = Record<string, any>;
async function api(path: string, body?: unknown) {
  const r = await fetch("/api" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let msg = await r.text();
    try {
      msg = JSON.parse(msg).detail;
    } catch {}
    throw new Error(r.status === 401 ? "Please sign in" : msg);
  }
  return r.json();
}
const money = (n: number | null | undefined) =>
  n == null
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
      }).format(n / 100);
const label = (s: string) => ({submitted: "Ready for review", working: "Review in progress", awaiting_approval: "Ready for your approval", needs_review: "Review interrupted", approved: "Route approved", exception: "Shipment needs attention", rejected: "Route rejected", unknown: "Unsure"}[s] || s.replaceAll("_", " "));
async function readPhotos(files: FileList | null): Promise<string[]> {
  const chosen = Array.from(files || []);
  if (chosen.length > 3 || chosen.some(f => f.size > 2_000_000 || !["image/jpeg", "image/png", "image/webp"].includes(f.type))) throw new Error("Choose up to 3 JPEG, PNG or WebP photos, 2 MB each.");
  return Promise.all(chosen.map(file => new Promise<string>((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsDataURL(file);
  })));
}
function App() {
  const [logged, setLogged] = useState(false),
    [pass, setPass] = useState(""),
    [error, setError] = useState(""),
    [cases, setCases] = useState<Row[]>([]),
    [selected, setSelected] = useState("RET-001"),
    [detail, setDetail] = useState<Row | null>(null),
    [events, setEvents] = useState<Row[]>([]),
    [catalog, setCatalog] = useState<Row | null>(null),
    [busy, setBusy] = useState(false),
    [modal, setModal] = useState(""),
    [filter, setFilter] = useState(""),
    [confirm, setConfirm] = useState(false),
    [condition, setCondition] = useState("opened"),
    [note, setNote] = useState(""),
    [photos, setPhotos] = useState<string[]>([]),
    [conditionConfirmed, setConditionConfirmed] = useState(false),
    [evidence, setEvidence] = useState<Row | null>(null),
    [scenario, setScenario] = useState("normal");
  const load = async () => {
    try {
      const [cs, ct] = await Promise.all([api("/returns"), api("/catalog")]);
      setCases(cs);
      setCatalog(ct);
      setLogged(true);
    } catch (e) {
      if ((e as Error).message === "Please sign in") setLogged(false);
    }
  };
  const loadDetail = async () => {
    if (!logged) return;
    try {
      const [d, ev] = await Promise.all([
        api("/returns/" + selected),
        api("/returns/" + selected + "/events"),
      ]);
      setDetail(d);
      setEvents(ev);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    setConfirm(false);
    setDetail(null);
    void loadDetail();
    const timer = setInterval(() => {
      void load();
      void loadDetail();
    }, 2000);
    return () => clearInterval(timer);
  }, [logged, selected]);
  const act = async (fn: () => Promise<any>, close = true) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
      await loadDetail();
      if (close) setModal("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const p = detail?.proposals.find((p: Row) => p.status === "pending");
  const c = detail?.case;
  const active = detail?.reservations.find((r: Row) => r.status === "active");
  const product = (sku: string) =>
    catalog?.products.find((p: Row) => p.sku === sku)?.name || sku;
  const total = cases.filter((c) => c.status === "approved").length;
  if (!logged)
    return (
      <div className="login">
        <div className="login-card">
          <div className="brand">
            <Leaf /> Smarter Returns
          </div>
          <h1>Sign in</h1>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                await api("/login", { passcode: pass });
                setLogged(true);
              });
            }}
          >
            <label>
              Merchant passcode
              <input
                type="password"
                value={pass}
                onChange={(e) => setPass(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <button className="primary" disabled={busy}>
              Sign in <ArrowRight size={17} />
            </button>
          </form>
          {error && (
            <div role="alert" className="error">
              {error}
            </div>
          )}
        </div>
        <div className="login-art">
          <Leaf size={100} />
          <h2>
            Less backtracking.
            <br />
            More possibility.
          </h2>
        </div>
      </div>
    );
  return (
    <div className="app">
      <aside>
        <div className="brand">
          <Leaf /> smarter
          <br />
          <span>returns</span>
        </div>
        <div className="workspace">
          <span className="avatar">GH</span>
          <div>
            Gallery Home
          </div>
        </div>
        <nav>
          <button className="nav-active">
            <Box size={18} /> Return workspace <ChevronRight size={14} />
          </button>

        </nav>
        <div className="aside-bottom">
          <button
            onClick={() =>
              void act(async () => {
                await api("/logout");
                setLogged(false);
              })
            }
          >
            <LogOut size={15} /> Sign out
          </button>
        </div>
      </aside>
      <main>
        <header>
          <div>
            <h1>Return workspace</h1>
          </div>
          <button className="primary" onClick={() => setModal("new")}>
            <Plus size={17} /> New return
          </button>
        </header>
        <p className="demo-notice">Shipping uses fixed synthetic estimates. No carrier is connected; approvals save simulated shipment records and do not purchase labels.</p>
        {error && (
          <div role="alert" className="error">
            {error}
            <button onClick={() => setError("")} aria-label="Dismiss error">
              <X size={15} />
            </button>
          </div>
        )}
        <details className="secondary workspace-summary"><summary>Workspace summary</summary><section className="metrics">
          <div>
            <span>Returns in workspace</span>
            <strong>
              {cases.length}
              <small>items</small>
            </strong>
          </div>
          <div>
            <span>Ready for your review</span>
            <strong>
              {cases.filter((c) => c.status === "awaiting_approval").length}
              <small>proposals</small>
            </strong>
          </div>
          <div>
            <span>Approved routes</span>
            <strong>
              {total}
              <small>routes</small>
            </strong>
          </div>
          {catalog?.mode === "demo" && <div className="scenario">
            <label htmlFor="scenario">Scenario</label>
            <div>
              <select
                id="scenario"
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
              >
                {[
                  "normal",
                  "inspection-block",
                  "external-research",
                  "no-waiting-buyer",
                  "uncertain-condition",
                  "competing-returns",
                  "reservation-expiry",
                  "policy-change",
                  "duplicate-approval",
                  "worker-restart",
                ].map((s) => (
                  <option key={s} value={s}>{label(s).replace(/^./, c => c.toUpperCase())}</option>
                ))}
              </select>
              <button
                title="Reset cases and start scenario"
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    const r = await api("/demo/reset", {
                      scenario_id: scenario,
                    });
                    setSelected(r.case_ids[0]);
                  })
                }
              >
                <RotateCcw size={17} />
              </button>
            </div>
            <small>Resets cases and approvals</small>
            {scenario === 'policy-change' && <button className="text-button" disabled={busy} onClick={()=>void act(()=>api('/demo/policy',{direct_forwarding_enabled:false}))}>Disable forwarding</button>}
          </div>}
        </section></details>
        <div className="workspace-grid">
          <section className="return-list">
            <div className="section-head">
              <h2>
                Returns <span>{cases.length}</span>
              </h2>
            </div>
            <div className="search">
              <Search size={15} />
              <input
                placeholder="Find a return or product"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            </div>
            <div className="case-scroll">
              {cases
                .filter((c) =>
                  (c.id + " " + product(c.data.sku))
                    .toLowerCase()
                    .includes(filter.toLowerCase()),
                )
                .map((r) => (
                  <button
                    key={r.id}
                    className={
                      "case-row " + (selected === r.id ? "selected" : "")
                    }
                    onClick={() => setSelected(r.id)}
                  >
                    <div className="case-top">
                      <span>{r.id}</span>
                      <span className={"status " + r.status}>
                        {label(r.status)}
                      </span>
                    </div>
                    <strong>{product(r.data.sku)}</strong>
                    <div className="case-bottom">
                      <span>
                        {r.data.sku} ·{" "}
                        {label(r.data.inspection_condition || r.data.reported_condition)}
                      </span>
                      <ChevronRight size={15} />
                    </div>
                  </button>
                ))}
            </div>
          </section>
          <section className="decision">
            {!c ? (
              <div className="empty">Loading return…</div>
            ) : (
              <>
                <div className="item-head">
                  <div className="item-icon">
                    <Box size={28} />
                  </div>
                  <div>
                    <span className="eyebrow">
                      {c.id}
                    </span>
                    <h2>{product(c.data.sku)}</h2>
                    <p>
                      {c.data.sku} ·{" "}
                      {
                        catalog?.locations.find(
                          (l: Row) => l.id === c.data.origin_zone_id,
                        )?.area
                      }
                    </p>
                  </div>
                  <span className={"status " + c.status}>
                    {label(c.status)}
                  </span>
                </div>
                <div className="reason">
                  <span>Customer’s explanation</span>
                  <p>“{c.data.reason}”</p>
                </div>
                <details className="secondary"><summary>Item condition · {label(c.data.inspection_condition || c.data.reported_condition)}</summary><div className="condition">
                  <ShieldCheck size={19} />
                  <div>
                    <strong>
                      {c.data.inspection_condition
                        ? "Merchant inspection"
                        : "Reported condition · unverified"}
                    </strong>
                    <span>
                      {label(
                        c.data.inspection_condition ||
                          c.data.reported_condition,
                      )}
                      {c.data.inspection_note
                        ? " — " + c.data.inspection_note
                        : ""}
                    </span>
                  </div>
                  <button
                    className="text-button"
                    onClick={() => {
                      setNote(""); setPhotos([]); setConditionConfirmed(false); setCondition(c.data.inspection_condition || c.data.reported_condition);
                      setModal("inspection");
                    }}
                  >
                    Check item condition <ArrowUpRight size={14} />
                  </button>
                </div>{c.data.inspection_photos?.map((src: string, i: number) => <img className="inspection-photo" src={src} alt={`Condition evidence ${i + 1}`} key={i} />)}</details>
                {c.status === "submitted" && (
                  <div className="empty">
                    <h3>Ready to find the next destination</h3>
                    <p>
                      Start a review to compare routes and reserve matching
                      demand.
                    </p>
                    <button
                      className="primary"
                      disabled={busy}
                      onClick={() =>
                        void act(() =>
                          api("/returns/" + selected + "/start", {
                            expected_version: c.version,
                          }),
                        )
                      }
                    >
                      Start review <ArrowRight size={16} />
                    </button>
                  </div>
                )}
                {c.status === "working" && (
                  <div className="empty">
                    <Clock />
                    <h3>Review in progress</h3>
                    <p>Checking current policy and eligible destinations.</p>
                  </div>
                )}
                {c.status === "needs_review" && (
                  <div className="error">
                    <h3>Review interrupted</h3>
                    <p>{events.slice().reverse().find(e => ["worker_error", "agent_error", "review_required"].includes(e.type))?.payload.message || "The review stopped before a current recommendation was ready."}</p>
                    <p>Your approval is required before shipping.</p>
                    <button className="primary" disabled={busy} onClick={() => void act(() => api("/returns/" + selected + "/recover", {expected_version: c.version}))}>Resume review <ArrowRight size={15} /></button>
                  </div>
                )}
                {c.status === "rejected" && <div className="empty"><p>This recommendation was rejected. Check the item condition to start a fresh review.</p><button className="primary" onClick={() => {setNote(""); setPhotos([]); setConditionConfirmed(false); setCondition(c.data.inspection_condition || c.data.reported_condition); setModal("inspection");}}>Check item condition</button></div>}
                {c.status === "exception" && (
                  <div className="error">
                    Facts changed after shipment approval. A merchant must
                    resolve this exception; the shipment has not been undone.
                  </div>
                )}
                {p && (
                  <div className="proposal">
                    <div className="proposal-title">
                      <span className="eyebrow">
                        RECOMMENDED NEXT DESTINATION
                      </span>
                      <span className="pill">
                        <Check size={13} /> Eligible
                        {p.data.route.conditional ? " · conditional" : ""}
                      </span>
                    </div>
                    <h2>{p.data.route.name}</h2><div className="recommended-cost">{money(p.data.route.cost.total_cents)} <small>estimated total</small></div><p>{p.data.route.type === "buyer" ? "A waiting customer can receive this item directly, avoiding a trip through the warehouse." : "This destination accepts the current condition and is eligible under the return policy."} Shipping requires your approval.</p>
                    <p>
                      {p.data.route.type === "buyer"
                        ? "Matched waiting order · " + p.destination_id
                        : "Approved " + p.data.route.type + " destination"}
                    </p>
                    <details className="secondary"><summary>Cost breakdown & reservation</summary><div className="costs">
                      <div>
                        <span>Shipping</span>
                        <strong>
                          {money(p.data.route.cost.shipping_cost_cents)}
                        </strong>
                      </div>
                      <div>
                        <span>Handling / service</span>
                        <strong>
                          {money(p.data.route.cost.handling_fee_cents)}
                        </strong>
                      </div>
                      <div>
                        <span>Route total</span>
                        <strong>{money(p.data.route.cost.total_cents)}</strong>
                      </div>
                      <div className="savings">
                        <span>Potential estimated savings</span>
                        <strong>{money(p.data.estimated_saving_cents)}</strong>
                      </div>
                    </div>
                    <p className="comparison">
                      Compared with {money(p.data.warehouse_cost_cents)} for the
                      warehouse. Fixed synthetic estimates; no carrier quote or label is available.
                    </p>
                    {active && (
                      <div className="reservation">
                        <Clock size={15} /> Reserved for {active.buyer_id} until{" "}
                        {new Date(active.expires_at).toLocaleTimeString()}
                      </div>
                    )}
                    </details>
                    {p.data.route.conditional && (
                      <label className="confirmation">
                        <input
                          type="checkbox"
                          checked={confirm}
                          onChange={(e) => setConfirm(e.target.checked)}
                        />{" "}
                        I have verified that this item is sealed.
                      </label>
                    )}
                    <div className="actions">
                      <button
                        className="primary"
                        disabled={
                          busy || (p.data.route.conditional && !confirm)
                        }
                        onClick={() =>
                          void act(() =>
                            api("/returns/" + selected + "/approve", {
                              expected_version: c.version,
                              proposal_id: p.id,
                              request_key: "approve-" + p.id,
                              confirmed_condition: confirm,
                            }),
                          )
                        }
                      >
                        Approve route & simulated shipment <ArrowRight size={15} />
                      </button>
                      <details className="secondary"><summary>Other actions</summary><button disabled={busy} onClick={() => void act(() => api("/returns/" + selected + "/reject", {expected_version: c.version}))}>Reject recommendation</button></details>
                    </div>
                  </div>
                )}
                {detail?.shipments.map((s: Row) => (
                  <div className="approved" key={s.id}>
                    <Check />
                    <div>
                      <h3>Route approved</h3>
                      <p>
                        {s.id} · Simulated shipment to {s.data.route.name}
                      </p>
                      <strong>
                        {money(s.data.estimated_saving_cents)} approved
                        estimated savings
                      </strong>
                    </div>
                  </div>
                ))}
                <details className="secondary"><summary>Alternative destinations</summary><div className="section-head">
                  <h3>Route comparison</h3>
                  {(c.data.inspection_condition || c.data.reported_condition) === "damaged" && <button
                    className="text-button"
                    disabled={busy || ["approved", "exception", "rejected"].includes(c.status)}
                    onClick={() =>
                      void act(() =>
                        api("/returns/" + selected + "/research", {
                          expected_version: c.version,
                        }),
                      )
                    }
                  >
                    Research repair options <ArrowUpRight size={14} />
                  </button>}
                </div>
                <div className="route-table">
                  {detail?.routes.map((r: Row) => (
                    <div className="route-row" key={r.destination_id}>
                      <div className="route-icon">
                        <Truck size={17} />
                      </div>
                      <div>
                        <strong>{r.name}</strong>
                        <small>
                          {r.eligible
                            ? r.type === "buyer"
                              ? "Matching demand · " + r.destination_id
                              : "Verified " + r.type
                            : r.reason}
                        </small>
                      </div>
                      <span className={!r.eligible ? "muted" : ""}>
                        {money(r.cost?.total_cents)}
                      </span>
                      <span
                        className={"route-label " + (r.eligible ? "ok" : "")}
                      >
                        {r.eligible ? "Eligible" : "Blocked"}
                      </span>
                    </div>
                  ))}
                </div>
                {detail?.destinations
                  .filter((d: Row) => d.acceptance_status === "unverified")
                  .map((d: Row) => (
                    <div className="candidate" key={d.id}>
                      <h4>{d.name}</h4>
                      <p>{d.source_excerpt}</p>
                      <a href={d.source_url} target="_blank" rel="noreferrer">
                        Research source <ArrowUpRight size={13} />
                      </a>
                      <button
                        onClick={() => {
                          setEvidence(d);
                          setModal("verify");
                        }}
                      >
                        Verify acceptance & costs
                      </button>
                    </div>
                  ))}
                </details>
                {c.data.finding && (
                  <details className="secondary"><summary>Policy evidence</summary><div className="policy">
                    <div className="section-head">
                      <h3>
                        <ShieldCheck size={17} /> Policy evidence
                      </h3>
                      <span>{c.data.finding.policy_version}</span>
                    </div>
                    {c.data.finding.passages.map((e: Row) => (
                      <details key={e.id}>
                        <summary>
                          {e.id} · {e.title}
                        </summary>
                        <p>{e.text}</p>
                      </details>
                    ))}
                    <small>{c.data.finding.origin}</small>
                  </div></details>
                )}
                <details className="secondary"><summary>Activity & case versions</summary><p>Current case version: {c.version}</p><div className="section-head">
                  <h3>Activity</h3>
                  {c.data.band_room_url && (
                    <a
                      href={c.data.band_room_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open Band room <ArrowUpRight size={13} />
                    </a>
                  )}
                </div>
                <ol className="timeline">
                  {events
                    .slice()
                    .reverse()
                    .map((e) => (
                      <li key={e.id}>
                        <div className="timeline-dot" />
                        <div>
                          <strong>{e.payload.message === "Merchant approved one simulated shipment." ? "Route approved." : e.payload.message || label(e.type)}</strong>
                          <small>
                            Version {e.version} · {e.actor} ·{" "}
                            {new Date(e.created_at).toLocaleTimeString()}
                          </small>
                        </div>
                      </li>
                    ))}
                </ol></details>
                <details className="secondary"><summary>Integration activity</summary><button onClick={() => void act(async () => {setEvidence(await api("/integrations")); setModal("evidence");}, false)}>View activity</button></details>
              </>
            )}
          </section>
        </div>
        <footer>
          Smarter Returns
          <span>USD</span>
        </footer>
      </main>
      {modal && (
        <div className="overlay">
          <section className="modal">
            <button
              className="close"
              aria-label="Close dialog"
              onClick={() => setModal("")}
            >
              <X size={20} />
            </button>
            {modal === "inspection" && (
              <>
                <span className="eyebrow">CURRENT FACTS</span>
                <h2>Check item condition</h2>
                <p>
                  A condition change starts a new review.
                </p>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void act(() =>
                      api("/returns/" + selected + "/inspection", {
                        expected_version: c?.version,
                        condition,
                        note, photos, confirmed_condition: conditionConfirmed,
                      }),
                    );
                  }}
                >
                  <label>
                    Condition
                    <select
                      value={condition}
                      onChange={(e) => setCondition(e.target.value)}
                    >
                      {["sealed", "opened", "damaged", "unknown"].map((s) => (
                        <option key={s} value={s}>{label(s).replace(/^./, c => c.toUpperCase())}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Notes (optional)
                    <textarea
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      maxLength={1000}
                    />
                  </label>
                  <label>Photos (optional, up to 3)<input type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={e => {setPhotos([]); void readPhotos(e.target.files).then(setPhotos).catch(e => setError(e.message));}} /></label>
                  <div>{photos.map((src, i) => <img className="inspection-photo" src={src} alt={`Selected photo ${i + 1}`} key={i} />)}</div>
                  <label className="confirmation"><input type="checkbox" checked={conditionConfirmed} onChange={e => setConditionConfirmed(e.target.checked)} /> I confirm the condition selected above.</label>
                  <button className="primary" disabled={busy || !conditionConfirmed}>
                    Confirm condition & review
                  </button>
                </form>
              </>
            )}
            {modal === "new" && (
              <>
                <h2>New return</h2>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const f = new FormData(e.currentTarget);
                    void act(async () => {
                      const r = await api("/returns", Object.fromEntries(f));
                      setSelected(r.id);
                    });
                  }}
                >
                  <label>
                    Product
                    <select name="sku">
                      {catalog?.products.map((p: Row) => (
                        <option key={p.sku} value={p.sku}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    General location
                    <select name="origin_zone_id">
                      {catalog?.locations.map((l: Row) => (
                        <option key={l.id} value={l.id}>
                          {l.area}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Reported condition
                    <select name="reported_condition">
                      {["sealed", "opened", "damaged", "unknown"].map((s) => (
                        <option key={s} value={s}>{label(s).replace(/^./, c => c.toUpperCase())}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Explanation
                    <textarea name="reason" required maxLength={1000} />
                  </label>
                  <button className="primary" disabled={busy}>
                    Submit return
                  </button>
                </form>
              </>
            )}
            {modal === "verify" && (
              <>
                <h2>Verify {evidence?.name}</h2>
                <p>
                  Confirm this business accepts the item and enter its quoted
                  costs.
                </p>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const f = new FormData(e.currentTarget);
                    void act(() =>
                      api("/destinations/" + evidence?.id + "/verify", {
                        shipping_cost_cents: Math.round(
                          Number(f.get("shipping")) * 100,
                        ),
                        service_fee_cents: Math.round(
                          Number(f.get("service")) * 100,
                        ),
                        accepted_conditions: [f.get("condition")],
                        note: f.get("note"),
                      }),
                    );
                  }}
                >
                  <label>
                    Shipping estimate (USD)
                    <input
                      type="number"
                      min="0"
                      max="10000"
                      step="0.01"
                      name="shipping"
                      required
                    />
                  </label>
                  <label>
                    Service / handling fee (USD)
                    <input
                      type="number"
                      min="0"
                      max="10000"
                      step="0.01"
                      name="service"
                      required
                    />
                  </label>
                  <label>
                    Accepted condition
                    <select name="condition">
                      {["damaged", "opened", "sealed", "unknown"].map((s) => (
                        <option key={s} value={s}>{label(s).replace(/^./, c => c.toUpperCase())}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Acceptance confirmation
                    <textarea name="note" required />
                  </label>
                  <button className="primary" disabled={busy}>
                    Save verification & review routes
                  </button>
                </form>
              </>
            )}
            {modal === "evidence" && (
              <>
                <h2>Integration activity</h2>
                <h3>Worker status</h3>
                <pre>{JSON.stringify(evidence?.worker?.data, null, 2)}</pre>
                <h3>Provider calls</h3>
                {evidence?.calls?.length ? (
                  evidence.calls.map((r: Row) => (
                    <details key={r.request_key}>
                      <summary>
                        {r.provider} · {r.status}
                      </summary>
                      <pre>{JSON.stringify(r.data, null, 2)}</pre>
                    </details>
                  ))
                ) : (
                  <p>No provider calls recorded.</p>
                )}
                <h3>Saved sessions</h3>
                <pre>{JSON.stringify(evidence?.sessions, null, 2)}</pre>
              </>
            )}
            {error && <div className="error">{error}</div>}
          </section>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
