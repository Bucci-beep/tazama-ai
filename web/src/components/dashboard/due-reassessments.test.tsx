import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DueReassessments } from "./due-reassessments";
import { getDueReassessments } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getDueReassessments: vi.fn(),
}));

const mockedGetDueReassessments = vi.mocked(getDueReassessments);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function renderQueue() {
  const component = await DueReassessments();
  render(component);
}

describe("DueReassessments", () => {
  it("displays an overdue synthetic obligation", async () => {
    mockedGetDueReassessments.mockResolvedValue({
      status: "available",
      as_of: "2026-10-29T12:00:00+00:00",
      obligations: [
        {
          obligation_id: "OBL-SYNTHETIC-1",
          case_id: "SYNTHETIC-API-1",
          created_at: "2026-10-29T09:00:00+00:00",
          due_at: "2026-10-29T11:00:00+00:00",
          status: "scheduled",
          policy_reference: "SYNTHETIC-TEST",
        },
      ],
    });

    await renderQueue();

    expect(screen.getByText("SYNTHETIC-API-1")).toBeInTheDocument();
    expect(screen.getByText("SYNTHETIC-TEST")).toBeInTheDocument();
    expect(
      screen.getByText("Scheduled — overdue at snapshot"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not a live clinical alerting system/i),
    ).toBeInTheDocument();
  });

  it("displays an explicit empty-queue message", async () => {
    mockedGetDueReassessments.mockResolvedValue({
      status: "available",
      as_of: "2026-10-29T12:00:00+00:00",
      obligations: [],
    });

    await renderQueue();

    expect(
      screen.getByText(/no overdue reassessment obligations were found/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Reassessment queue unavailable"),
    ).not.toBeInTheDocument();
  });

  it("displays an unavailable warning instead of an empty queue", async () => {
    mockedGetDueReassessments.mockResolvedValue({
      status: "unavailable",
      reason: "API returned HTTP 503",
    });

    await renderQueue();

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Reassessment queue unavailable",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Queue status cannot be confirmed",
    );
    expect(
      screen.queryByText(/no overdue reassessment obligations were found/i),
    ).not.toBeInTheDocument();
  });
});
