import { beforeEach, describe, expect, it, vi } from "vitest";
import { discriminatorGroups } from "@/lib/discriminators";

const { requestCaseReassessment, createCaseObservation } = vi.hoisted(() => ({
  requestCaseReassessment: vi.fn(),
  createCaseObservation: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ requestCaseReassessment, createCaseObservation }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

import { requestReassessmentAction, saveObservationAction, type ReassessmentActionState } from "./actions";

const idle: ReassessmentActionState = { status: "idle", message: "", result: null };

function form(mode: string, signs: string[] = []): FormData {
  const data = new FormData();
  data.set("case_id", "SYNTHETIC-1");
  data.set("sign_assessment", mode);
  for (const sign of signs) data.append("signs", sign);
  return data;
}

describe("requestReassessmentAction sign validation", () => {
  beforeEach(() => {
    requestCaseReassessment.mockReset();
    requestCaseReassessment.mockResolvedValue({
      status: "unavailable",
      reason: "synthetic response",
    });
  });

  it.each([
    ["not assessed", "not_assessed", null],
    ["assessed with none found", "assessed_none", []],
  ])("submits %s", async (_label, mode, expected) => {
    await requestReassessmentAction(idle, form(mode));
    expect(requestCaseReassessment).toHaveBeenCalledWith("SYNTHETIC-1", expected);
  });

  it("submits one and multiple chart-defined sign IDs", async () => {
    const first = discriminatorGroups[0].signs[0].signId;
    const second = discriminatorGroups[1].signs[0].signId;

    await requestReassessmentAction(idle, form("assessed_selected", [first]));
    expect(requestCaseReassessment).toHaveBeenLastCalledWith("SYNTHETIC-1", [first]);

    await requestReassessmentAction(
      idle,
      form("assessed_selected", [first, second]),
    );
    expect(requestCaseReassessment).toHaveBeenLastCalledWith("SYNTHETIC-1", [
      first,
      second,
    ]);
  });

  it("rejects tampered unknown IDs before calling FastAPI", async () => {
    const result = await requestReassessmentAction(
      idle,
      form("assessed_selected", ["DISC/UNKNOWN/TAMPERED"]),
    );

    expect(result).toEqual({
      status: "error",
      message: "One or more clinical sign selections are not recognised.",
      result: null,
    });
    expect(requestCaseReassessment).not.toHaveBeenCalled();
  });

  it("does not describe a failed review submission as completed", async () => {
    requestCaseReassessment.mockResolvedValue({
      status: "completed",
      reassessment: { status: "review_submission_failed" },
    });
    const result = await requestReassessmentAction(idle, form("assessed_none"));
    expect(result.status).toBe("success");
    expect(result.message).toContain("no review was confirmed");
  });
});


describe("saveObservationAction adult SATS applicability", () => {
  beforeEach(() => {
    createCaseObservation.mockReset();
    createCaseObservation.mockResolvedValue({
      status: "created",
      record: {},
    });
  });

  function observationForm(value?: string): FormData {
    const data = new FormData();
    data.set("case_id", "SYNTHETIC-1");
    data.set("observation_type", "baseline");
    data.set("recorded_at", "2026-10-14T10:00:00");
    data.set("trauma", "");
    if (value !== undefined) {
      data.set("adult_chart_applies", value);
    }
    return data;
  }

  it.each([
    ["omitted", undefined, "not_assessed"],
    ["blank", "", "not_assessed"],
    ["confirmed yes", "yes", "yes"],
    ["confirmed no", "no", "no"],
    ["explicit not assessed", "not_assessed", "not_assessed"],
  ])("submits %s applicability correctly", async (_label, value, expected) => {
    await saveObservationAction(
      { status: "idle", message: "" },
      observationForm(value),
    );

    expect(createCaseObservation).toHaveBeenCalledWith(
      "SYNTHETIC-1",
      expect.objectContaining({
        observations: expect.objectContaining({
          adult_chart_applies: expected,
        }),
      }),
    );
  });

  it("rejects a file submitted as applicability", async () => {
    const data = observationForm();
    data.set(
      "adult_chart_applies",
      new File(["invalid"], "tampered.txt"),
    );

    const result = await saveObservationAction(
      { status: "idle", message: "" },
      data,
    );

    expect(result).toEqual({
      status: "error",
      message: "Invalid adult SATS chart applicability.",
    });
    expect(createCaseObservation).not.toHaveBeenCalled();
  });

  it.each(["unknown", "YES", "true"])(
    "rejects invalid applicability %s before API submission",
    async (value) => {
      const result = await saveObservationAction(
        { status: "idle", message: "" },
        observationForm(value),
      );

      expect(result).toEqual({
        status: "error",
        message: "Invalid adult SATS chart applicability.",
      });
      expect(createCaseObservation).not.toHaveBeenCalled();
    },
  );
});
