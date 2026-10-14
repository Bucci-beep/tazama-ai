"use client";

import { useActionState } from "react";
import {
  saveObservationAction,
  type ObservationFormState,
} from "@/app/actions";

type ObservationFormProps = {
  observationType: "baseline" | "recheck";
  selectedCaseId: string;
};

const numericFields = [
  { name: "heart_rate_bpm", label: "Heart rate (bpm)" },
  { name: "respiratory_rate_bpm", label: "Respiratory rate (bpm)" },
  { name: "systolic_bp_mmhg", label: "Systolic BP (mmHg)" },
  { name: "temperature_c", label: "Temperature (°C)" },
  { name: "spo2_percent", label: "SpO₂ (%)" },
] as const;

const initialObservationFormState: ObservationFormState = {
  status: "idle",
  message: "",
};

export function ObservationForm({
  observationType,
  selectedCaseId,
}: ObservationFormProps) {
  const [state, formAction, pending] = useActionState(
    saveObservationAction,
    initialObservationFormState,
  );
  const isBaseline = observationType === "baseline";

  return (
    <form action={formAction} className="mt-5 space-y-5">
      <input type="hidden" name="observation_type" value={observationType} />
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm font-medium text-slate-700">
          Synthetic case ID
          <input
            name="case_id"
            defaultValue={selectedCaseId}
            pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,99}"
            placeholder="SYNTHETIC-DEMO-001"
            required
            className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
          />
        </label>
        <label className="text-sm font-medium text-slate-700">
          Recorded at (UTC)
          <input
            type="datetime-local"
            name="recorded_at"
            step="1"
            required
            className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
          />
        </label>
      </div>

      <fieldset>
        <legend className="text-sm font-semibold text-slate-800">
          Structured observations
        </legend>
        <p className="mt-1 text-xs text-slate-500">
          Leave a field blank when it was not recorded. Missing values are not
          inferred.
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {numericFields.map((field) => (
            <label key={field.name} className="text-sm text-slate-700">
              {field.label}
              <input
                type="number"
                inputMode="decimal"
                step="any"
                name={field.name}
                className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
              />
            </label>
          ))}
          <label className="text-sm text-slate-700">
            Consciousness
            <input
              name="consciousness"
              className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
            />
          </label>
          <label className="text-sm text-slate-700">
            Mobility
            <select
              name="mobility"
              defaultValue=""
              className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
            >
              <option value="">Not recorded</option>
              <option value="walking">Walking</option>
              <option value="with_help">With help</option>
              <option value="stretcher_immobile">Stretcher / immobile</option>
            </select>
          </label>
          <label className="text-sm text-slate-700">
            Trauma
            <select
              name="trauma"
              defaultValue=""
              className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
            >
              <option value="">Not recorded</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
          </label>
        </div>
      </fieldset>

      {state.status === "error" ? (
        <p role="alert" className="text-sm text-rose-700">
          {state.message}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={pending}
        className="rounded-lg bg-teal-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-teal-800 focus:outline-none focus:ring-2 focus:ring-teal-300 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {pending
          ? "Saving observation..."
          : isBaseline
            ? "Create case and save baseline"
            : "Save reassessment"}
      </button>
    </form>
  );
}
