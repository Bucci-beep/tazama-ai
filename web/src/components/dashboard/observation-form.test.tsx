import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/actions", () => ({
  saveObservationAction: vi.fn(),
}));

import { ObservationForm } from "./observation-form";

describe("ObservationForm adult SATS applicability", () => {
  afterEach(cleanup);

  it.each(["baseline", "recheck"] as const)(
    "starts with no selected applicability for %s",
    (observationType) => {
      render(
        <ObservationForm
          observationType={observationType}
          selectedCaseId="SYNTHETIC-1"
        />,
      );

      const selector = screen.getByRole("combobox", {
        name: "Adult SATS chart applicability",
      }) as HTMLSelectElement;

      expect(selector.value).toBe("");
      expect(screen.getByText(/Leaving this blank records not assessed/))
        .toBeVisible();
    },
  );

  it("allows the nurse to explicitly select applicability", async () => {
    const user = userEvent.setup();

    render(
      <ObservationForm
        observationType="baseline"
        selectedCaseId="SYNTHETIC-1"
      />,
    );

    const selector = screen.getByRole("combobox", {
      name: "Adult SATS chart applicability",
    }) as HTMLSelectElement;

    await user.selectOptions(selector, "yes");
    expect(selector.value).toBe("yes");

    await user.selectOptions(selector, "no");
    expect(selector.value).toBe("no");

    await user.selectOptions(selector, "not_assessed");
    expect(selector.value).toBe("not_assessed");
  });
});
