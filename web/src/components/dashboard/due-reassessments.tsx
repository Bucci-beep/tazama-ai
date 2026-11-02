import { getDueReassessments } from "@/lib/api";

export async function DueReassessments() {
  const result = await getDueReassessments();

  return (
    <section
      aria-labelledby="due-reassessments-heading"
      className="mt-10 rounded-2xl border border-slate-200 bg-white p-6 sm:p-8"
    >
      <h2
        id="due-reassessments-heading"
        className="text-lg font-semibold"
      >
        Overdue reassessment obligations
      </h2>

      <p className="mt-2 text-sm leading-6 text-slate-600">
        Read-only snapshot of persisted reassessment schedules for synthetic
        cases. This is not a live clinical alerting system.
      </p>

      {result.status === "unavailable" ? (
        <div
          role="alert"
          className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-4"
        >
          <p className="font-medium text-amber-900">
            Reassessment queue unavailable
          </p>
          <p className="mt-1 text-sm text-amber-800">
            {result.reason}. Queue status cannot be confirmed.
          </p>
        </div>
      ) : (
        <>
          <p className="mt-4 text-xs text-slate-500">
            Snapshot as of{" "}
            <time dateTime={result.as_of}>
              {new Date(result.as_of).toISOString()}
            </time>
          </p>

          {result.obligations.length === 0 ? (
            <p
              role="status"
              className="mt-5 rounded-lg bg-slate-50 p-4 text-sm text-slate-600"
            >
              No overdue reassessment obligations were found at this snapshot.
            </p>
          ) : (
            <div className="mt-5 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-200 text-slate-600">
                  <tr>
                    <th scope="col" className="px-3 py-3 font-medium">
                      Synthetic case
                    </th>
                    <th scope="col" className="px-3 py-3 font-medium">
                      Due at (UTC)
                    </th>
                    <th scope="col" className="px-3 py-3 font-medium">
                      Policy reference
                    </th>
                    <th scope="col" className="px-3 py-3 font-medium">
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {result.obligations.map((obligation) => (
                    <tr
                      key={obligation.obligation_id}
                      className="border-b border-slate-100"
                    >
                      <td className="px-3 py-3 font-medium">
                        {obligation.case_id}
                      </td>
                      <td className="px-3 py-3">
                        <time dateTime={obligation.due_at}>
                          {new Date(obligation.due_at).toISOString()}
                        </time>
                      </td>
                      <td className="px-3 py-3">
                        {obligation.policy_reference}
                      </td>
                      <td className="px-3 py-3">
                        Scheduled — overdue at snapshot
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
