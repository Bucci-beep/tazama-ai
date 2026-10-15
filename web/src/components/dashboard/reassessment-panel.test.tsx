import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReassessmentActionState } from "@/app/actions";
import type { ReassessmentResponse } from "@/lib/api";
import { discriminatorGroups } from "@/lib/discriminators";

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

  it("displays successful evidence and submits signs as not assessed", async () => {
    action.mockResolvedValue(success());
    await submit();
    expect(await screen.findByText("Qualified minimum only")).toBeVisible();
    expect(screen.getByText(/heart rate bpm/).closest("li")).toHaveTextContent("80 → 90");
    expect(screen.getByText(/Reference:/)).toHaveTextContent("REVIEW-001");
    const submitted = action.mock.calls[0][1];
    expect(submitted.get("case_id")).toBe("SYNTHETIC-1");
    expect(submitted.get("sign_assessment")).toBe("not_assessed");
    expect(submitted.getAll("signs")).toEqual([]);
  });

  it("submits assessed-none and selected chart signs explicitly", async () => {
    action.mockResolvedValue(success());
    const user = userEvent.setup();
    render(<ReassessmentPanel caseId="SYNTHETIC-1" />);

    await user.click(screen.getByLabelText("Assessed, none identified"));
    await user.click(screen.getByRole("button", { name: "Request reassessment" }));
    expect(action.mock.calls[0][1].get("sign_assessment")).toBe("assessed_none");
    expect(action.mock.calls[0][1].getAll("signs")).toEqual([]);

    await user.click(screen.getByLabelText("Assessed, signs identified"));
    const selected = discriminatorGroups[0].signs.slice(0, 2);
    await user.click(screen.getByLabelText(selected[0].chartText));
    await user.click(screen.getByLabelText(selected[1].chartText));
    await user.click(screen.getByRole("button", { name: "Request reassessment" }));
    expect(action.mock.calls[1][1].getAll("signs")).toEqual(
      selected.map((sign) => sign.signId),
    );
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

  it("shows a complete proposal with recognised sign evidence", async () => {
    const sign = discriminatorGroups[2].signs[0];
    const result = response();
    result.priority_status = "complete";
    result.priority_result = {
      ...result.priority_result!,
      status: "complete",
      priority: "urgent",
      priority_at_least: null,
      matched_sign_ids: [sign.signId],
      reasons: [],
    };
    action.mockResolvedValue(success(result));
    await submit();
    expect(await screen.findByText("Complete deterministic proposal")).toBeVisible();
    expect(screen.getByText(sign.chartText)).toBeVisible();
    expect(screen.getByText(`(${sign.signId})`)).toBeVisible();
  });

  it("shows unknown sign evidence with abstention", async () => {
    const result = response();
    result.priority_status = "abstained";
    result.priority_result = {
      ...result.priority_result!,
      status: "abstained",
      priority: null,
      priority_at_least: null,
      unknown_sign_ids: ["DISC/NOT/A_REAL_SIGN"],
      reasons: ["Unknown sign ids; nothing was guessed"],
    };
    action.mockResolvedValue(success(result));
    await submit();
    expect(await screen.findByText("Assessment abstained")).toBeVisible();
    expect(screen.getByText("Unknown sign evidence caused abstention")).toBeVisible();
    expect(screen.getByText("DISC/NOT/A_REAL_SIGN")).toBeVisible();
  });

  it("shows optional explanation unavailability", async () => {
    action.mockResolvedValue(success(response({ explanation: null, explanation_error: "NOT_CONFIGURED" })));
    await submit();
    expect(await screen.findByText("Explanation unavailable: NOT_CONFIGURED")).toBeVisible();
  });

  it("does not treat HTTP success as confirmed review persistence", async () => {
    action.mockResolvedValue(success(response({ status: "review_submission_failed", review_request_id: null, review_submission_status: "unconfirmed", review_submission_error: "MCP_REVIEW_SUBMISSION_UNCONFIRMED" })));
    await submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("No new review has been confirmed");
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
