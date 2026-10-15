"use client";

import { useActionState, useState } from "react";
import {
  requestReassessmentAction,
  type ReassessmentActionState,
} from "@/app/actions";
import type { ReassessmentResponse } from "@/lib/api";
import {
  discriminatorGroups,
  discriminatorText,
} from "@/lib/discriminators";

const initialState: ReassessmentActionState = {
  status: "idle",
  message: "",
  result: null,
};

const priorityLabels: Record<ReassessmentResponse["priority_status"], string> = {
  complete: "Complete deterministic proposal",
  minimum_only: "Qualified minimum only",
  abstained: "Assessment abstained",
  tool_unavailable: "Priority tool unavailable",
};

function Evidence({ result }: { result: ReassessmentResponse }) {
  const time = result.workflow_provenance.time;
  const missing = result.priority_result?.tews.missing ?? [];
  const unscorable = result.priority_result?.tews.unscorable ?? [];

  return (
    <div className="mt-6 space-y-5" aria-label="Reassessment evidence">
      <div className="rounded-xl border border-teal-200 bg-teal-50 p-5">
        <p className="text-xs font-bold uppercase tracking-wide text-teal-800">
          Proposed assessment · clinician review required
        </p>
        <h4 className="mt-2 text-lg font-semibold text-slate-900">
          {priorityLabels[result.priority_status]}
        </h4>
        <p className="mt-2 text-sm text-slate-700">
          {result.priority_result?.priority
            ? `Proposed priority: ${result.priority_result.priority}`
            : result.priority_result?.priority_at_least
              ? `Priority is at least ${result.priority_result.priority_at_least}; incomplete evidence prevents a complete proposal.`
              : "No priority was proposed from the available evidence."}
        </p>
        {result.priority_error ? (
          <p role="alert" className="mt-3 text-sm font-medium text-rose-700">
            Priority evidence unavailable: {result.priority_error}
          </p>
        ) : null}
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 p-5">
          <h4 className="font-semibold">Case and observation context</h4>
          <dl className="mt-4 space-y-2 text-sm">
            <div className="flex justify-between gap-4"><dt className="text-slate-500">Case</dt><dd className="font-medium">{result.case_id}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-slate-500">Observations</dt><dd className="font-medium">{result.observation_count}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-slate-500">Latest observation</dt><dd className="font-mono text-xs">{result.latest_observation_id}</dd></div>
          </dl>
        </section>

        <section className="rounded-xl border border-slate-200 p-5">
          <h4 className="font-semibold">History comparison</h4>
          <p className="mt-2 text-sm text-slate-600">Status: {result.comparison_status.replaceAll("_", " ")}</p>
          {result.comparison_error ? <p role="alert" className="mt-2 text-sm text-rose-700">Comparison unavailable: {result.comparison_error}</p> : null}
          {result.comparison_result?.changes.length ? (
            <ul className="mt-3 space-y-2 text-sm">
              {result.comparison_result.changes.map((change) => (
                <li key={`${change.field}-${change.after_obs_id}`} className="rounded-lg bg-slate-50 px-3 py-2">
                  <span className="font-medium">{change.field.replaceAll("_", " ")}</span>: {change.before} → {change.after}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-slate-500">No comparable changes were returned. This is not evidence of a normal finding.</p>
          )}
        </section>
      </div>

      <section className="rounded-xl border border-slate-200 p-5">
        <h4 className="font-semibold">Evidence limitations</h4>
        {result.priority_result?.reasons.length || missing.length || unscorable.length ? (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-700">
            {result.priority_result?.reasons.map((reason) => <li key={reason}>{reason}</li>)}
            {missing.map((field) => <li key={`missing-${field}`}>Missing: {field.replaceAll("_", " ")}</li>)}
            {unscorable.map((issue) => <li key={`unscorable-${issue.field}`}>Not scorable: {issue.field.replaceAll("_", " ")}</li>)}
          </ul>
        ) : <p className="mt-2 text-sm text-slate-600">No missing evidence was reported.</p>}
        {result.priority_result?.matched_sign_ids.length ? (
          <div className="mt-4">
            <p className="text-sm font-semibold text-slate-800">Recognised nurse-assessed signs</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
              {result.priority_result.matched_sign_ids.map((signId) => (
                <li key={signId}>
                  {discriminatorText(signId) ?? signId}
                  <span className="ml-1 font-mono text-xs text-slate-500">({signId})</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {result.priority_result?.unknown_sign_ids.length ? (
          <div role="alert" className="mt-4 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-800">
            <p className="font-semibold">Unknown sign evidence caused abstention</p>
            <ul className="mt-1 list-disc pl-5">
              {result.priority_result.unknown_sign_ids.map((signId) => <li key={signId} className="font-mono text-xs">{signId}</li>)}
            </ul>
          </div>
        ) : null}
      </section>

      <section className="rounded-xl border border-slate-200 p-5">
        <h4 className="font-semibold">Bounded explanation</h4>
        {result.explanation?.statements?.length ? (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-700">
            {result.explanation.statements.map((statement) => <li key={statement}>{statement}</li>)}
          </ul>
        ) : <p className="mt-2 text-sm text-slate-600">Explanation unavailable: {result.explanation_error ?? "No explanation returned"}</p>}
      </section>

      <section className={`rounded-xl border p-5 ${result.review_submission_status === "persisted" ? "border-amber-200 bg-amber-50" : "border-rose-200 bg-rose-50"}`}>
        <h4 className="font-semibold">Pending clinician review</h4>
        {result.review_submission_status === "persisted" ? (
          <p className="mt-2 text-sm text-slate-700">A pending review request was confirmed. Reference: <span className="font-mono text-xs">{result.review_request_id}</span>. No decision has been approved.</p>
        ) : (
          <p role="alert" className="mt-2 text-sm font-bold text-rose-800">No new review has been confirmed. Review persistence could not be verified; do not assume a review request exists. {result.review_submission_error}</p>
        )}
      </section>

      <section className="rounded-xl border border-slate-200 p-5">
        <h4 className="font-semibold">Workflow provenance and audit</h4>
        <dl className="mt-3 space-y-2 text-sm">
          <div><dt className="text-slate-500">Workflow run ID</dt><dd className="mt-1 break-all font-mono text-xs">{result.workflow_run_id}</dd></div>
          <div><dt className="text-slate-500">Time MCP</dt><dd className="mt-1">{time?.status ?? "unavailable"}{time?.result?.datetime ? ` · ${time.result.datetime}` : ""}</dd></div>
        </dl>
        {result.mcp_audit_errors.length ? (
          <div role="alert" className="mt-4 rounded-lg bg-amber-100 px-4 py-3 text-sm text-amber-900">
            <p className="font-semibold">Audit coverage is incomplete</p>
            <ul className="mt-1 list-disc pl-5">{result.mcp_audit_errors.map((error) => <li key={error}>{error}</li>)}</ul>
          </div>
        ) : <p className="mt-4 text-sm text-emerald-700">No MCP audit coverage errors were reported.</p>}
      </section>
    </div>
  );
}

export function ReassessmentPanel({ caseId }: { caseId: string }) {
  const [assessmentMode, setAssessmentMode] = useState("not_assessed");
  const [state, action, pending] = useActionState(
    requestReassessmentAction,
    initialState,
  );

  return (
    <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5">
      <div>
        <div>
          <h3 className="font-semibold">Workflow reassessment</h3>
          <p className="mt-1 text-sm text-slate-600">Runs deterministic assessment and requests pending clinician review. It does not approve a decision or change a queue.</p>
        </div>
        <form action={action} className="mt-5 space-y-5">
          <input type="hidden" name="case_id" value={caseId} />
          <fieldset disabled={pending} className="space-y-3">
            <legend className="text-sm font-semibold text-slate-900">Nurse-assessed clinical discriminator signs</legend>
            <p className="text-sm text-slate-600">Select the explicit assessment state. Tazama does not infer signs from observations or history.</p>
            {[
              ["not_assessed", "Not assessed"],
              ["assessed_none", "Assessed, none identified"],
              ["assessed_selected", "Assessed, signs identified"],
            ].map(([value, label]) => (
              <label key={value} className="flex items-center gap-2 text-sm text-slate-800">
                <input
                  type="radio"
                  name="sign_assessment"
                  value={value}
                  checked={assessmentMode === value}
                  onChange={() => setAssessmentMode(value)}
                />
                {label}
              </label>
            ))}
          </fieldset>

          {assessmentMode === "assessed_selected" ? (
            <div className="grid gap-4 lg:grid-cols-3">
              {discriminatorGroups.map((group) => (
                <fieldset key={group.level} disabled={pending} className="rounded-xl border border-slate-200 p-4">
                  <legend className="px-1 text-sm font-semibold capitalize text-slate-900">{group.level.replaceAll("_", " ")}</legend>
                  <div className="mt-2 space-y-2">
                    {group.signs.map((sign) => (
                      <label key={sign.signId} className="flex items-start gap-2 text-sm text-slate-700">
                        <input type="checkbox" name="signs" value={sign.signId} className="mt-1" />
                        <span>{sign.chartText}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              ))}
            </div>
          ) : null}

          <p className="text-xs text-slate-500">Changing sign evidence after a review has been submitted for the same observation may be rejected. Review versioning is not implemented.</p>
          <button type="submit" disabled={pending} className="rounded-lg bg-teal-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-teal-800 focus:outline-none focus:ring-2 focus:ring-teal-300 disabled:cursor-not-allowed disabled:opacity-60">
            {pending ? "Requesting reassessment..." : "Request reassessment"}
          </button>
        </form>
      </div>
      {pending ? <p role="status" className="mt-4 text-sm text-slate-600">The LangGraph/MCP workflow is running. Duplicate submission is disabled.</p> : null}
      {state.status === "error" ? <p role="alert" className="mt-4 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-800">Reassessment unavailable: {state.message}</p> : null}
      {state.status === "success" ? (
        <>
          <p role="status" className="mt-4 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{state.message}</p>
          <Evidence result={state.result} />
        </>
      ) : null}
    </section>
  );
}
