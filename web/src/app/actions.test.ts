import { beforeEach, describe, expect, it, vi } from "vitest";
import { discriminatorGroups } from "@/lib/discriminators";

const { requestCaseReassessment } = vi.hoisted(() => ({
  requestCaseReassessment: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ requestCaseReassessment }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

import { requestReassessmentAction, type ReassessmentActionState } from "./actions";

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
});
