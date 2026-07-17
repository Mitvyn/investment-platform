import type { FinancialMetric } from "@iros/types";
import { redirect } from "next/navigation";

import { loadTickerContext } from "../lib/context";
import { loadEvidenceTrace } from "../lib/evidence";
import { createClient } from "../lib/supabase/server";
import { loadWatchlist } from "../lib/watchlist";
import { signOut, toggleRxrxWatchlist } from "./actions";

export const dynamic = "force-dynamic";

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

function formatMetric(metric: FinancialMetric) {
  if (metric.unit === "USD_millions") {
    return `$${metric.value.toFixed(1)}m`;
  }
  if (metric.unit === "percent") {
    return `${metric.value > 0 ? "+" : ""}${metric.value.toFixed(2)}%`;
  }
  return `${metric.value.toFixed(2)} qtrs`;
}

function ageLabel(value: string) {
  const elapsedHours = Math.max(
    0,
    Math.floor((Date.now() - new Date(value).getTime()) / 3_600_000),
  );
  if (elapsedHours < 1) return "under 1h old";
  if (elapsedHours < 48) return `${elapsedHours}h old`;
  return `${Math.floor(elapsedHours / 24)}d old`;
}

export default async function TickerWorkspace() {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  if (error || !data?.claims) {
    redirect("/login");
  }

  const [{ trace }, context, watchlist] = await Promise.all([
    loadEvidenceTrace("RXRX"),
    loadTickerContext("RXRX"),
    loadWatchlist(),
  ]);
  const issuerRetrievedAt = context.financialMetrics[0]?.retrievedAt;
  const hasResearch = Boolean(
    trace ||
      context.financialMetrics.length ||
      context.catalyst ||
      context.risk ||
      context.market,
  );
  const sourceCount = Number(Boolean(trace)) + Number(Boolean(issuerRetrievedAt));
  const isWatched = watchlist.some((item) => item.ticker === "RXRX");

  return (
    <main>
      <nav>
        <span className="brand">IROS / Ticker Workspace</span>
        <div className="nav-actions">
          <span className="mode">Authenticated research ledger</span>
          <form action={signOut}>
            <button className="text-button" type="submit">
              Sign out
            </button>
          </form>
        </div>
      </nav>

      {!hasResearch ? (
        <section className="empty-state">
          <p className="eyebrow">Hosted research spine ready</p>
          <h1>RXRX</h1>
          <p>
            No hosted research context yet. Ingest the SEC filing and official
            issuer release after operator identity is available.
          </p>
        </section>
      ) : (
        <>
          <header className="hero">
            <div>
              <p className="eyebrow">Evidence-backed ticker workspace</p>
              <h1>RXRX</h1>
              <p className="company">
                {trace?.companyName ?? "Recursion Pharmaceuticals, Inc."}
              </p>
            </div>
            <div className="status">
              <span>Primary source classes</span>
              <strong>{sourceCount} / 2</strong>
              <small>SEC filing + issuer release</small>
            </div>
          </header>

          <section className="watchlist-dock" aria-label="Watchlist">
            <div>
              <span>Watchlist</span>
              {watchlist.length ? (
                <ul>
                  {watchlist.map((item) => (
                    <li key={item.ticker}>
                      <strong>{item.ticker}</strong>
                      <small>{item.disposition.replace("_", " ")}</small>
                    </li>
                  ))}
                </ul>
              ) : (
                <small>No monitored tickers</small>
              )}
            </div>
            <form action={toggleRxrxWatchlist}>
              <button className="watchlist-button" type="submit">
                {isWatched ? "Remove RXRX" : "Monitor RXRX"}
              </button>
            </form>
          </section>

          <section className="provenance-rail" aria-label="Source health">
            <div className={trace ? "source-live" : "source-missing"}>
              <span className="source-pulse" aria-hidden="true" />
              <div>
                <strong>SEC filing</strong>
                <small>
                  {trace ? `Retrieved ${ageLabel(trace.retrievedAt)}` : "Missing"}
                </small>
              </div>
            </div>
            <div className={issuerRetrievedAt ? "source-live" : "source-missing"}>
              <span className="source-pulse" aria-hidden="true" />
              <div>
                <strong>Issuer release</strong>
                <small>
                  {issuerRetrievedAt
                    ? `Retrieved ${ageLabel(issuerRetrievedAt)}`
                    : "Missing"}
                </small>
              </div>
            </div>
            <div className={context.market ? "source-live" : "source-gated"}>
              <span className="source-pulse" aria-hidden="true" />
              <div>
                <strong>Market snapshot</strong>
                <small>
                  {context.market
                    ? `Retrieved ${ageLabel(context.market.retrievedAt)}`
                    : "Licensed feed required"}
                </small>
              </div>
            </div>
          </section>

          <section className="context-grid" aria-label="Ticker context">
            <article className="market-panel">
              <p className="section-label">Market context</p>
              {context.market ? (
                <>
                  <div className="quote-line">
                    <strong>
                      {new Intl.NumberFormat("en-US", {
                        style: "currency",
                        currency: context.market.currency,
                      }).format(context.market.close)}
                    </strong>
                    <span
                      className={context.market.change >= 0 ? "positive" : "negative"}
                    >
                      {context.market.change >= 0 ? "+" : ""}
                      {context.market.change.toFixed(2)} (
                      {context.market.percentChange.toFixed(2)}%)
                    </span>
                  </div>
                  <dl className="compact-list">
                    <div>
                      <dt>Venue</dt>
                      <dd>{context.market.exchange}</dd>
                    </div>
                    <div>
                      <dt>As of</dt>
                      <dd>{formatDate(context.market.marketTime)}</dd>
                    </div>
                    <div>
                      <dt>Market</dt>
                      <dd>{context.market.isMarketOpen ? "Open" : "Closed"}</dd>
                    </div>
                  </dl>
                  <p className="source-note">Twelve Data licensed snapshot</p>
                </>
              ) : (
                <div className="gated-state">
                  <span>Feed gated</span>
                  <h2>No licensed snapshot available.</h2>
                  <p>
                    Configure a display-licensed market plan and ingest a quote;
                    this dashboard never calls the provider directly.
                  </p>
                </div>
              )}
            </article>

            <article className="financial-panel">
              <div className="section-heading">
                <div>
                  <p className="section-label">Financial health</p>
                  <h2>Reported facts and transparent arithmetic</h2>
                </div>
                {issuerRetrievedAt ? (
                  <span className="as-of">
                    Release published {formatDate(context.financialMetrics[0].publishedAt)}
                  </span>
                ) : null}
              </div>
              {context.financialMetrics.length ? (
                <div className="metric-grid">
                  {context.financialMetrics.map((metric) => (
                    <div className="metric" key={metric.metricKey}>
                      <span>{metric.metricLabel}</span>
                      <strong>{formatMetric(metric)}</strong>
                      <small>{metric.sourcePeriod}</small>
                      {metric.formula ? (
                        <code>{metric.formula}</code>
                      ) : (
                        <code>Reported by issuer</code>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="panel-empty">No issuer financial metrics ingested.</p>
              )}
              {context.financialMetrics[0] ? (
                <a
                  className="source-link"
                  href={context.financialMetrics[0].sourceUrl}
                  rel="noreferrer"
                  target="_blank"
                >
                  Open issuer release
                </a>
              ) : null}
            </article>

            <article className="catalyst-panel">
              <p className="section-label">Forward catalyst</p>
              {context.catalyst ? (
                <>
                  <div className="catalyst-window">
                    <span>{context.catalyst.status}</span>
                    <strong>
                      {formatDate(context.catalyst.windowStart)} —{" "}
                      {formatDate(context.catalyst.windowEnd)}
                    </strong>
                  </div>
                  <h2>{context.catalyst.title}</h2>
                  <blockquote>{context.catalyst.passage}</blockquote>
                  <p className="locator">{context.catalyst.locator}</p>
                  <a
                    className="source-link"
                    href={context.catalyst.sourceUrl}
                    rel="noreferrer"
                    target="_blank"
                  >
                    Verify at source
                  </a>
                </>
              ) : (
                <p className="panel-empty">No source-backed catalyst ingested.</p>
              )}
            </article>

            <article className="risk-panel">
              <p className="section-label">Source-backed risk</p>
              {context.risk ? (
                <>
                  <div className="risk-meta">
                    <span>{context.risk.severity} severity</span>
                    <strong>{context.risk.status}</strong>
                  </div>
                  <h2>{context.risk.title}</h2>
                  <blockquote>{context.risk.passage}</blockquote>
                  <p className="locator">{context.risk.locator}</p>
                  <a
                    className="source-link"
                    href={context.risk.sourceUrl}
                    rel="noreferrer"
                    target="_blank"
                  >
                    Verify risk at source
                  </a>
                </>
              ) : (
                <p className="panel-empty">No source-backed active risk ingested.</p>
              )}
            </article>
          </section>

          {trace ? (
            <section className="evidence-section" aria-label="SEC evidence chain">
              <div className="section-heading evidence-heading">
                <div>
                  <p className="section-label">Claim evidence</p>
                  <h2>Follow the assertion to the filing.</h2>
                </div>
                <span className="verification-badge">{trace.verificationState}</span>
              </div>
              <div className="chain">
                <article>
                  <p className="step">01 / Verified claim</p>
                  <h2>{trace.claim}</h2>
                  <dl>
                    <div>
                      <dt>Research run</dt>
                      <dd>{trace.researchRunId}</dd>
                    </div>
                    <div>
                      <dt>Run status</dt>
                      <dd>{trace.runStatus}</dd>
                    </div>
                  </dl>
                </article>
                <div className="connector" aria-hidden="true">supports</div>
                <article>
                  <p className="step">02 / Exact passage</p>
                  <blockquote>{trace.passage}</blockquote>
                  <p className="locator">{trace.locator}</p>
                  <p className="hash">SHA-256 {trace.passageSha256}</p>
                </article>
                <div className="connector" aria-hidden="true">from</div>
                <article>
                  <p className="step">03 / Original source</p>
                  <h2>
                    {trace.filingForm} for period ended {formatDate(trace.periodEnd)}
                  </h2>
                  <dl>
                    <div>
                      <dt>Filed</dt>
                      <dd>{formatDate(trace.filedAt)}</dd>
                    </div>
                    <div>
                      <dt>Accession</dt>
                      <dd>{trace.accessionNumber}</dd>
                    </div>
                    <div>
                      <dt>Retrieved</dt>
                      <dd>{formatDate(trace.retrievedAt)}</dd>
                    </div>
                  </dl>
                  <a className="source-link" href={trace.sourceUrl} rel="noreferrer" target="_blank">
                    Open filing on SEC.gov
                  </a>
                </article>
              </div>
            </section>
          ) : null}
        </>
      )}
    </main>
  );
}
