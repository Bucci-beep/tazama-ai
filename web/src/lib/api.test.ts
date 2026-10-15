import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { requestCaseReassessment } from "./api";

function validResponse(): Record<string, unknown> {
  return {
    case_id: "SYNTHETIC-1",
    workflow_run_id: "RUN-1",
    status: "awaiting_clinician_review",
    reason: null,
    observation_count: 2,
    has_baseline: true,
    has_rechecks: true,
    latest_observation_id: "OBS-2",
    comparison_status: "differences_found",
    comparison_result: {
      schema_version: "1.0",
      case_id: "SYNTHETIC-1",
      status: "differences_found",
      changes: [{ field: "heart_rate_bpm", before: 80, after: 90, before_obs_id: "OBS-1", after_obs_id: "OBS-2" }],
      not_comparable: [],
      reason: null,
    },
    comparison_error: null,
    priority_status: "minimum_only",
    priority_result: {
      status: "minimum_only",
      priority: null,
      priority_at_least: "routine",
      matched_sign_ids: [],
      unknown_sign_ids: [],
      tews: { status: "scored", total: 0, priority: "routine", missing: [], unscorable: [] },
      reasons: ["Signs have not been assessed"],
      protocol_version: "2015-chart-1",
    },
    priority_error: null,
    explanation: { status: "generated", statements: ["Clinician review is required."] },
    explanation_error: null,
    review_request_id: "REVIEW-1",
    review_submission_status: "persisted",
    review_submission_error: null,
    workflow_provenance: {
      time: {
        status: "captured",
        server: "mcp-server-time",
        tool: "get_current_time",
        result: { datetime: "2026-10-15T09:00:00Z", timezone: "UTC" },
      },
    },
    mcp_audit_errors: [],
  };
}

function respondWith(payload: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
}

describe("requestCaseReassessment response validation", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("accepts a complete valid response", async () => {
    respondWith(validResponse());
    expect((await requestCaseReassessment("SYNTHETIC-1", null)).status).toBe("completed");
  });

  it.each([
    ["missing Time provenance", (body: Record<string, unknown>) => { body.workflow_provenance = {}; }],
    ["invalid priority evidence", (body: Record<string, unknown>) => { (body.priority_result as Record<string, unknown>).reasons = "none"; }],
    ["malformed history changes", (body: Record<string, unknown>) => { ((body.comparison_result as Record<string, unknown>).changes as unknown[]) = [{ field: "heart_rate_bpm", before: "80", after: 90 }]; }],
    ["confirmed review without reference", (body: Record<string, unknown>) => { body.review_request_id = null; }],
    ["inconsistent confirmed review state", (body: Record<string, unknown>) => { body.status = "review_submission_failed"; }],
    ["malformed explanation statements", (body: Record<string, unknown>) => { (body.explanation as Record<string, unknown>).statements = [42]; }],
    ["malformed audit warnings", (body: Record<string, unknown>) => { body.mcp_audit_errors = [null]; }],
  ])("returns unavailable for %s", async (_label, mutate) => {
    const body = validResponse();
    mutate(body);
    respondWith(body);

    await expect(requestCaseReassessment("SYNTHETIC-1", null)).resolves.toEqual({
      status: "unavailable",
      reason: "API returned an unexpected reassessment response",
    });
  });

  it("preserves a valid unavailable priority with null evidence", async () => {
    const body = validResponse();
    body.priority_status = "tool_unavailable";
    body.priority_result = null;
    body.priority_error = "MCP_PRIORITY_TOOL_UNAVAILABLE";
    respondWith(body);

    const result = await requestCaseReassessment("SYNTHETIC-1", null);
    expect(result.status).toBe("completed");
    if (result.status === "completed") {
      expect(result.reassessment.priority_result).toBeNull();
      expect(result.reassessment.priority_error).toBe("MCP_PRIORITY_TOOL_UNAVAILABLE");
    }
  });

  it("posts the explicit signs state as JSON", async () => {
    respondWith(validResponse());

    await requestCaseReassessment("SYNTHETIC-1", [
      "DISC/URGENT/MODERATE_PAIN",
    ]);

    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/cases/SYNTHETIC-1/reassess",
      expect.objectContaining({
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ signs: ["DISC/URGENT/MODERATE_PAIN"] }),
      }),
    );
  });
});
