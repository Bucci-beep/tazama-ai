import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReassessmentActionState } from "@/app/actions";
import type { ReassessmentResponse } from "@/lib/api";

const action = vi.fn<
  (state: ReassessmentActionState, formData: FormData) => Promise<ReassessmentActionState>
>();

vi.mock("@/app/actions", () => ({
  requestReassessmentAction: (...args: [ReassessmentActionState, FormData]) =>
    action(...args),
}));

import { ReassessmentPanel } from "./reassessment-panel";

function response(
  overrides: Partial<ReassessmentResponse> = {},
): ReassessmentResponse {
  return {
    case_id: "SYNTHETIC-1",
    workflow_run_id: "RUN-001",
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
      changes: [
        {
          field: "heart_rate_bpm",
          before: 80,
          after: 90,
          before_obs_id: "OBS-1",
          after_obs_id: "OBS-2",
        },
      ],
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
      tews: { status: "scored", total: 0, priority: "routine", missing: [] },
      reasons: ["Signs have not been assessed by the nurse"],
      protocol_version: "2015-chart-1",
    },
    priority_error: null,
    explanation: {
      status: "generated",
      statements: ["The evidence requires clinician review."],
    },
    explanation_error: null,
    review_request_id: "REVIEW-001",
    review_submission_status: "persisted",
    review_submission_error: null,
    workflow_provenance: {
      time: {
        status: "captured",
        result: { datetime: "2026-10-15T09:00:00Z", timezone: "UTC" },
      },
    },
    mcp_audit_errors: [],
    ...overrides,
  };
}

function success(result = response()): ReassessmentActionState {
  return {
    status: "success",
    message: "Reassessment completed. Review status is shown below.",
    result,
  };
}

async function submit() {
  render(<ReassessmentPanel caseId="SYNTHETIC-1" />);
  await userEvent.click(screen.getByRole("button", { name: "Request reassessment" }));
}

describe("ReassessmentPanel", () => {
  beforeEach(() => action.mockReset());
  afterEach(cleanup);

  it("displays successful evidence and sends only the case identifier", async () => {
    action.mockResolvedValue(success());
    await submit();
    expect(await screen.findByText("Qualified minimum only")).toBeVisible();
    expect(screen.getByText(/heart rate bpm/).closest("li")).toHaveTextContent("80 → 90");
    expect(screen.getByText(/Reference:/)).toHaveTextContent("REVIEW-001");
    const submitted = action.mock.calls[0][1];
    expect([...submitted.keys()]).toEqual(["case_id"]);
  });

  it("shows loading and disables duplicate submission", async () => {
    let resolve!: (value: ReassessmentActionState) => void;
    action.mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<ReassessmentPanel caseId="SYNTHETIC-1" />);
    const button = screen.getByRole("button", { name: "Request reassessment" });
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole("button", { name: "Requesting reassessment..." })).toBeDisabled());
    expect(action).toHaveBeenCalledTimes(1);
    resolve(success());
    expect(await screen.findByText("Qualified minimum only")).toBeVisible();
  });

  it.each([
    ["missing observations", "No observations found for this case"],
    ["backend unavailable", "Unable to reach the local Tazama API"],
  ])("shows %s", async (_label, message) => {
    action.mockResolvedValue({ status: "error", message, result: null });
    await submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("distinguishes priority tool unavailability", async () => {
    action.mockResolvedValue(success(response({ priority_status: "tool_unavailable", priority_result: null, priority_error: "MCP_PRIORITY_TOOL_UNAVAILABLE" })));
    await submit();
    expect(await screen.findByText("Priority tool unavailable")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("MCP_PRIORITY_TOOL_UNAVAILABLE");
  });

  it("shows insufficient clinical evidence without inferring a priority", async () => {
    const result = response();
    result.priority_status = "abstained";
    result.priority_result = { ...result.priority_result!, status: "abstained", priority_at_least: null, reasons: ["TEWS not calculated: missing respiratory rate"], tews: { status: "unavailable", missing: ["respiratory_rate_bpm"] } };
    action.mockResolvedValue(success(result));
    await submit();
    expect(await screen.findByText("Assessment abstained")).toBeVisible();
    expect(screen.getByText("No priority was proposed from the available evidence.")).toBeVisible();
    expect(screen.getByText("Missing: respiratory rate bpm")).toBeVisible();
  });

  it("shows optional explanation unavailability", async () => {
    action.mockResolvedValue(success(response({ explanation: null, explanation_error: "NOT_CONFIGURED" })));
    await submit();
    expect(await screen.findByText("Explanation unavailable: NOT_CONFIGURED")).toBeVisible();
  });

  it("does not treat HTTP success as confirmed review persistence", async () => {
    action.mockResolvedValue(success(response({ status: "review_submission_failed", review_request_id: null, review_submission_status: "unconfirmed", review_submission_error: "MCP_REVIEW_SUBMISSION_UNCONFIRMED" })));
    await submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("Review persistence could not be verified");
    expect(screen.queryByText(/A pending review request was confirmed/)).not.toBeInTheDocument();
  });

  it("shows MCP audit coverage warnings", async () => {
    action.mockResolvedValue(success(response({ mcp_audit_errors: ["get_current_time:MCP_AUDIT_PERSISTENCE_FAILED"] })));
    await submit();
    expect(await screen.findByText("Audit coverage is incomplete")).toBeVisible();
    expect(screen.getByText("get_current_time:MCP_AUDIT_PERSISTENCE_FAILED")).toBeVisible();
  });

  it("allows a repeat reassessment that reuses an existing pending review", async () => {
    action.mockResolvedValue(success());
    render(<ReassessmentPanel caseId="SYNTHETIC-1" />);
    const button = screen.getByRole("button", { name: "Request reassessment" });
    await userEvent.click(button);
    expect(await screen.findByText(/Reference:/)).toHaveTextContent("REVIEW-001");
    await userEvent.click(button);
    expect(action).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/Reference:/)).toHaveTextContent("REVIEW-001");
  });
});
