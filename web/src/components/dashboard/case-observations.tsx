import { getCaseTimeline, type PatientObservations } from "@/lib/api";
import { ReassessmentPanel } from "@/components/dashboard/reassessment-panel";

const measurementLabels: Record<keyof PatientObservations, string> = {
  heart_rate_bpm: "Heart rate",
  respiratory_rate_bpm: "Respiratory rate",
  systolic_bp_mmhg: "Systolic BP",
  temperature_c: "Temperature",
  spo2_percent: "SpO₂",
  consciousness: "Consciousness",
  mobility: "Mobility",
  trauma: "Trauma",
};

function displayValue(value: PatientObservations[keyof PatientObservations]) {
  if (value === null) return "Not recorded";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export async function CaseObservations({ caseId }: { caseId: string }) {
  const result = await getCaseTimeline(caseId);

  if (result.status === "not_found") {
    return (
      <p role="status" className="mt-5 text-sm text-slate-600">
        No observations were found for case <strong>{caseId}</strong>.
      </p>
    );
  }

  if (result.status === "unavailable") {
    return (
      <p role="alert" className="mt-5 text-sm text-rose-700">
        Observations are unavailable: {result.reason}
      </p>
    );
  }

  return (
    <div className="mt-6 space-y-4">
      <p className="text-sm text-slate-600">
        {result.timeline.records.length} persisted observation
        {result.timeline.records.length === 1 ? "" : "s"}, shown chronologically.
      </p>
      {result.timeline.records.map((record) => (
        <article
          key={record.observation_id}
          className="rounded-xl border border-slate-200 bg-slate-50 p-5"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="font-semibold capitalize">
                {record.observation_type}
              </h3>
              <p className="mt-1 text-xs text-slate-500">
                Observation {record.observation_id}
              </p>
            </div>
            <time className="text-xs text-slate-500" dateTime={record.recorded_at}>
              {new Intl.DateTimeFormat("en-GB", {
                dateStyle: "medium",
                timeStyle: "short",
                timeZone: "UTC",
              }).format(new Date(record.recorded_at))} UTC
            </time>
          </div>
          <dl className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(record.observations).map(([key, value]) => (
              <div key={key}>
                <dt className="text-xs font-medium text-slate-500">
                  {measurementLabels[key as keyof PatientObservations]}
                </dt>
                <dd className="mt-1 text-sm font-semibold text-slate-800">
                  {displayValue(value)}
                </dd>
              </div>
            ))}
          </dl>
        </article>
      ))}
      <ReassessmentPanel caseId={caseId} />
    </div>
  );
}
