import { useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import {
  ArrowLeft,
  ArrowLeftRight,
  Check,
  Gavel,
  HelpCircle,
  Lightbulb,
  Microscope,
  Play,
  FlaskConical,
  RotateCcw,
  X,
} from "lucide-react";
import { api } from "../api/client";
import type { HypothesisRanking, ReviewDecision } from "../api/types";
import { useApi } from "../hooks/useApi";
import { useToast } from "../components/Toast";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  ProgressBar,
  SectionHeader,
} from "../components/ui";
import {
  Badge,
  ConflictStatusBadge,
  HypothesisStatusBadge,
  SeverityBadge,
  VerificationBadge,
} from "../components/badges";
import { percent, relativeTime, titleCase } from "../lib/format";

export default function ConflictDetail() {
  const { id } = useParams();
  const conflictId = Number(id);
  const toast = useToast();
  const navigate = useNavigate();
  const { data, loading, error, refetch } = useApi(() => api.getConflict(conflictId), [conflictId]);
  const { data: ranking } = useApi(
    () => api.rankHypotheses(conflictId),
    [conflictId]
  );
  const { data: reviews, refetch: refetchReviews } = useApi(
    () => api.conflictReviews(conflictId),
    [conflictId]
  );
  const [reviewer, setReviewer] = useState("human reviewer");
  const [reviewNote, setReviewNote] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (loading && !data) return <Loading />;
  if (error) return <ErrorState message={error} onRetry={refetch} />;
  const c = data!;

  const investigate = async () => {
    try {
      const inv = await api.createInvestigation({
        name: `Investigation: conflict #${c.id}`,
        research_question: c.description,
        conflict_ids: [c.id],
      });
      await api.investigationAction(inv.id, "start");
      toast.success("Investigation started.");
      navigate(`/investigations/${inv.id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to start investigation");
    }
  };

  const setStatus = async (status: string) => {
    try {
      await api.updateConflict(c.id, { status });
      toast.success(`Status set to ${titleCase(status)}.`);
      refetch();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Update failed");
    }
  };

  const submitDecision = async (decision: ReviewDecision) => {
    if (!c.conclusion) return;
    setSubmitting(true);
    try {
      const res = await api.submitReview(c.conclusion.id, {
        decision,
        reviewer,
        note: reviewNote,
      });
      toast.success(res.message || "Review recorded.");
      setReviewNote("");
      refetch();
      refetchReviews();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Review failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <Link
        to="/conflicts"
        className="inline-flex items-center gap-2 text-sm text-[var(--color-muted)] hover:text-[var(--color-ink)]"
      >
        <ArrowLeft size={14} /> All conflicts
      </Link>

      <SectionHeader
        title={`Conflict #C${c.id}`}
        subtitle={titleCase(c.conflict_type)}
        action={
          <div className="flex items-center gap-2">
            <SeverityBadge severity={c.severity} />
            <ConflictStatusBadge status={c.status} />
            <Button size="sm" onClick={investigate}>
              <Play size={14} /> Investigate
            </Button>
          </div>
        }
      />

      <Card className="border-l-2 border-l-[var(--color-warning)]">
        <div className="flex items-start gap-3">
          <Microscope size={18} className="mt-0.5 text-[var(--color-warning)]" />
          <div>
            <p className="text-sm font-medium text-[var(--color-ink)]">
              Why this was flagged
            </p>
            <p className="mt-1 text-sm text-[var(--color-muted)]">{c.why_flagged}</p>
            <p className="mt-2 text-sm text-[var(--color-ink)]">{c.description}</p>
            <div className="mt-3 flex flex-wrap gap-3 text-xs text-[var(--color-faint)]">
              <span>Detection: {c.detection_method || "rule-based"}</span>
              <span>Confidence: {percent(c.confidence)}</span>
              <span>Created {relativeTime(c.created_at)}</span>
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        {[c.claim_a, c.claim_b].map((claim, i) => (
          <Card key={i}>
            <div className="mb-3 flex items-center justify-between">
              <Badge tone="primary">Claim {i === 0 ? "A" : "B"}</Badge>
              {claim && <span className="text-xs text-[var(--color-faint)]">{claim.document_filename}</span>}
            </div>
            {claim ? (
              <>
                <p className="text-sm text-[var(--color-ink)]">{claim.claim_text}</p>
                <dl className="mt-3 space-y-1.5 text-xs">
                  <Row label="Subject" value={claim.subject} />
                  <Row
                    label="Value"
                    value={
                      claim.numeric_value !== null
                        ? `${claim.numeric_value} ${claim.unit}`
                        : claim.object_value || "—"
                    }
                  />
                  <Row label="Type" value={claim.claim_type} />
                  <Row
                    label="Time"
                    value={claim.timestamp_value ? relativeTime(claim.timestamp_value) : "—"}
                  />
                  <Row label="Confidence" value={percent(claim.confidence)} />
                </dl>
              </>
            ) : (
              <p className="text-sm text-[var(--color-faint)]">Claim not available.</p>
            )}
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionHeader
            title="Evidence"
            subtitle={`${c.evidence.length} item(s) gathered`}
          />
          {c.evidence.length === 0 ? (
            <EmptyState title="No evidence yet" description="Run an investigation to collect evidence." />
          ) : (
            <ul className="space-y-2">
              {c.evidence.map((e) => (
                <li
                  key={e.id}
                  className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/40 p-3"
                >
                  <div className="mb-1.5 flex flex-wrap items-center gap-2">
                    <Badge tone={e.origin === "user" ? "violet" : "info"}>{e.origin}</Badge>
                    <Badge tone="neutral">{e.evidence_type}</Badge>
                    <VerificationBadge status={e.verification_status} />
                  </div>
                  <p className="text-sm text-[var(--color-ink)]">{e.description}</p>
                  <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-[var(--color-faint)]">
                    <span>relevance {percent(e.relevance_score)}</span>
                    <span>reliability {percent(e.reliability_score)}</span>
                    {e.document_filename && <span>source: {e.document_filename}</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <SectionHeader
            title="Hypotheses"
            subtitle={`${c.hypotheses.length} competing explanation(s)`}
          />
          {c.hypotheses.length === 0 ? (
            <EmptyState title="No hypotheses yet" description="The Hypothesis Generator will propose explanations." />
          ) : (
            <ul className="space-y-3">
              {c.hypotheses.map((h) => (
                <li
                  key={h.id}
                  className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/40 p-3"
                >
                  <div className="mb-1.5 flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-[var(--color-ink)]">{h.title}</p>
                    <HypothesisStatusBadge status={h.status} />
                  </div>
                  {h.explanation && (
                    <p className="text-xs text-[var(--color-muted)]">{h.explanation}</p>
                  )}
                  <div className="mt-2">
                    <div className="mb-1 flex items-center justify-between text-[11px] text-[var(--color-faint)]">
                      <span>Support</span>
                      <span>{percent(h.support_score)}</span>
                    </div>
                    <ProgressBar
                      value={h.support_score}
                      tone={
                        h.status === "supported"
                          ? "success"
                          : h.status === "contradicted"
                          ? "danger"
                          : "primary"
                      }
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {ranking && ranking.length > 0 && (
        <Card>
          <SectionHeader
            title="Hypothesis Ranking"
            subtitle="Ranked by documented evidence weight — transparent and reproducible"
          />
          <ul className="space-y-3">
            {ranking.map((r) => (
              <RankingRow key={r.hypothesis_id} r={r} />
            ))}
          </ul>
          <p className="mt-4 text-[11px] leading-relaxed text-[var(--color-faint)]">
            {ranking[0]?.confidence_caveat}
          </p>
        </Card>
      )}

      <Card>
        <SectionHeader title="Conclusion" subtitle="The Decision Agent's final assessment" />
        {!c.conclusion ? (
          <EmptyState
            icon={<Gavel size={22} />}
            title="No conclusion reached"
            description="Start an investigation to drive the blackboard to a decision."
          />
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                tone={
                  c.conclusion.decision_type === "supported_conclusion"
                    ? "success"
                    : c.conclusion.decision_type === "human_review_required"
                    ? "violet"
                    : "warning"
                }
              >
                {titleCase(c.conclusion.decision_type)}
              </Badge>
              <span className="text-xs text-[var(--color-faint)]">
                confidence {percent(c.conclusion.confidence)}
              </span>
            </div>
            <p className="text-sm text-[var(--color-ink)]">{c.conclusion.conclusion}</p>
            {c.conclusion.unresolved_questions.length > 0 && (
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-faint)]">
                  Unresolved questions
                </p>
                <ul className="mt-1 list-inside list-disc text-sm text-[var(--color-muted)]">
                  {c.conclusion.unresolved_questions.map((u, i) => (
                    <li key={i}>{u}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-2 rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/40 p-3">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-faint)]">
                Human review
              </p>
              <p className="mt-1 text-xs text-[var(--color-muted)]">
                Record an explicit decision on this conclusion. The conflict status is
                updated accordingly and the decision is written to the audit trail.
              </p>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <input
                  value={reviewer}
                  onChange={(e) => setReviewer(e.target.value)}
                  placeholder="Reviewer name"
                  className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm text-[var(--color-ink)] outline-none placeholder:text-[var(--color-faint)]"
                />
                <input
                  value={reviewNote}
                  onChange={(e) => setReviewNote(e.target.value)}
                  placeholder="Note (optional)"
                  className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm text-[var(--color-ink)] outline-none placeholder:text-[var(--color-faint)]"
                />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  disabled={submitting}
                  onClick={() => submitDecision("approved")}
                >
                  <Check size={14} /> Approve
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={submitting}
                  onClick={() => submitDecision("rejected")}
                >
                  <X size={14} /> Reject
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={submitting}
                  onClick={() => submitDecision("inconclusive")}
                >
                  <HelpCircle size={14} /> Mark inconclusive
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={submitting}
                  onClick={() => submitDecision("request_more_investigation")}
                >
                  <Microscope size={14} /> Request more investigation
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={submitting}
                  onClick={() => submitDecision("reopen")}
                >
                  <RotateCcw size={14} /> Reopen
                </Button>
              </div>
            </div>

            {reviews && reviews.length > 0 && (
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-faint)]">
                  Recorded decisions
                </p>
                <ul className="mt-2 space-y-2">
                  {reviews.map((r) => (
                    <li
                      key={r.id}
                      className="flex flex-wrap items-center gap-2 text-sm text-[var(--color-muted)]"
                    >
                      <Badge
                        tone={
                          r.decision === "approved"
                            ? "success"
                            : r.decision === "rejected"
                            ? "danger"
                            : r.decision === "reopen"
                            ? "info"
                            : "warning"
                        }
                      >
                        {titleCase(r.decision)}
                      </Badge>
                      <span className="text-[var(--color-ink)]">{r.reviewer}</span>
                      <span className="text-[var(--color-faint)]">
                        {relativeTime(r.created_at)}
                      </span>
                      {r.note && <span className="w-full text-xs">{r.note}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs uppercase tracking-wide text-[var(--color-faint)]">
          Manual review
        </span>
        <Button variant="outline" size="sm" onClick={() => setStatus("resolved")}>
          Mark resolved
        </Button>
        <Button variant="outline" size="sm" onClick={() => setStatus("inconclusive")}>
          Mark inconclusive
        </Button>
        <Button variant="outline" size="sm" onClick={() => setStatus("human_review")}>
          Escalate to human review
        </Button>
      </div>

      {c.investigations.length > 0 && (
        <Card>
          <SectionHeader title="Related investigations" />
          <ul className="divide-y divide-[var(--color-border-soft)]">
            {c.investigations.map((inv) => (
              <li key={inv.id} className="flex items-center justify-between py-2.5">
                <Link
                  to={`/investigations/${inv.id}`}
                  className="flex items-center gap-2 text-sm hover:text-[var(--color-primary-soft)]"
                >
                  <ArrowLeftRight size={14} /> {inv.name}
                </Link>
                <div className="flex items-center gap-3 text-xs text-[var(--color-faint)]">
                  <span>{inv.iteration_count} iterations</span>
                  <Badge tone="neutral">{titleCase(inv.status)}</Badge>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function RankingRow({ r }: { r: HypothesisRanking }) {
  return (
    <li className="rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/40 p-3">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <Badge tone="primary">#{r.rank}</Badge>
        <span className="text-sm font-medium text-[var(--color-ink)]">{r.title}</span>
        <HypothesisStatusBadge status={r.status} />
        {r.margin_to_next !== null && (
          <span className="ml-auto text-[11px] text-[var(--color-faint)]">
            margin to next: {r.margin_to_next.toFixed(2)}
          </span>
        )}
      </div>
      <ProgressBar
        value={r.support_score}
        tone={r.rank === 1 ? "success" : "primary"}
      />
      <div className="mt-2 grid gap-1 text-[11px] text-[var(--color-faint)] sm:grid-cols-2">
        <span>support {percent(r.support_score)}</span>
        <span>confidence {percent(r.confidence)}</span>
        <span>+ evidence weight {r.criteria.supporting_evidence_weight.toFixed(2)}</span>
        <span>- evidence weight {r.criteria.contradicting_evidence_weight.toFixed(2)}</span>
        <span>distinct sources {r.criteria.distinct_supporting_sources}</span>
        <span>
          direct evidence: {r.criteria.has_direct_supporting_evidence ? "yes" : "no"}
        </span>
      </div>
      {r.supporting_evidence.length > 0 && (
        <div className="mt-2">
          <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-faint)]">
            Supporting evidence
          </p>
          <ul className="mt-1 space-y-1">
            {r.supporting_evidence.map((e) => (
              <li key={e.id} className="text-xs text-[var(--color-muted)]">
                <span className="text-[var(--color-ink)]">E{e.id}</span>{" "}
                <span className="text-[var(--color-faint)]">[{e.evidence_type}]</span>{" "}
                {e.description}
                {e.document_filename && (
                  <span className="text-[var(--color-faint)]"> — {e.document_filename}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {r.contradicting_evidence.length > 0 && (
        <div className="mt-2">
          <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-faint)]">
            Contradicting evidence
          </p>
          <ul className="mt-1 space-y-1">
            {r.contradicting_evidence.map((e) => (
              <li key={e.id} className="text-xs text-[var(--color-muted)]">
                <span className="text-[var(--color-ink)]">E{e.id}</span>{" "}
                <span className="text-[var(--color-faint)]">[{e.evidence_type}]</span>{" "}
                {e.description}
              </li>
            ))}
          </ul>
        </div>
      )}
      {r.missing_information.length > 0 && (
        <p className="mt-2 text-[11px] text-[var(--color-warning)]">
          Missing information: {r.missing_information.join("; ")}
        </p>
      )}
    </li>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-[var(--color-faint)]">{label}</dt>
      <dd className="text-right text-[var(--color-muted)]">{value || "—"}</dd>
    </div>
  );
}
