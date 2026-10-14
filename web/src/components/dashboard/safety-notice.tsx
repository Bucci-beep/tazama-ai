import { ShieldCheck } from "lucide-react";

export function SafetyNotice() {
  return (
    <section
      aria-labelledby="clinical-safety-heading"
      className="mt-9 rounded-2xl border border-amber-200 bg-amber-50 p-5"
    >
      <div className="flex gap-3">
        <ShieldCheck
          aria-hidden="true"
          className="shrink-0 text-amber-800"
          size={22}
        />
        <div>
          <h2
            id="clinical-safety-heading"
            className="font-semibold text-amber-950"
          >
            Clinical safety boundary
          </h2>
          <p className="mt-1 text-sm leading-6 text-amber-900">
            This is an unvalidated research prototype. It must not
            be used for patient care, diagnosis, treatment, or
            autonomous triage decisions.
          </p>
        </div>
      </div>
    </section>
  );
}
