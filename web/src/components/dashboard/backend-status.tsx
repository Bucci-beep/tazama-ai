import { Database, Wifi, WifiOff } from "lucide-react";
import { getApiHealth } from "@/lib/api";

export async function BackendStatus() {
  const connection = await getApiHealth();

  return (
    <section className="mt-10 rounded-2xl border border-slate-200 bg-white p-6 sm:p-8">
      <div className="flex items-start gap-4">
        <div className="rounded-xl bg-slate-100 p-3">
          <Database
            size={22}
            className="text-slate-700"
            aria-hidden="true"
          />
        </div>

        <div className="flex-1">
          <h2 className="text-lg font-semibold">
            Backend connection
          </h2>

          <p className="mt-2 text-sm leading-6 text-slate-600">
            HTTP service connectivity only. This does not verify
            clinical scoring, database availability, or workflow
            readiness.
          </p>

          {connection.connected ? (
            <div
              role="status"
              className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-teal-700"
            >
              <Wifi size={16} aria-hidden="true" />
              API connected · Synthetic research environment
            </div>
          ) : (
            <div role="status" className="mt-4">
              <div className="inline-flex items-center gap-2 text-sm font-medium text-rose-700">
                <WifiOff size={16} aria-hidden="true" />
                API unavailable
              </div>
              <p className="mt-2 text-xs text-slate-500">
                {connection.reason}
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
