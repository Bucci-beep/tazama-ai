import { Suspense } from "react";
import { BackendStatus } from "@/components/dashboard/backend-status";
import { SafetyNotice } from "@/components/dashboard/safety-notice";
import {
  Activity,
  ClipboardList,
  FileClock,
  HeartPulse,
} from "lucide-react";

const capabilities = [
  {
    title: "Clinical scoring",
    description:
      "Deterministic TEWS-based assessment with explicit limitations and abstention.",
    icon: Activity,
  },
  {
    title: "Case history",
    description:
      "Observation comparisons and reassessment evidence, subject to backend availability.",
    icon: FileClock,
  },
  {
    title: "Review workflow",
    description:
      "Human review requirements remain separate from automated calculations.",
    icon: ClipboardList,
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="flex min-h-screen">
        <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white p-6 lg:flex lg:flex-col">
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-teal-700 p-2 text-white">
              <HeartPulse size={23} />
            </div>
            <div>
              <p className="text-lg font-bold tracking-tight">Tazama</p>
              <p className="text-xs text-slate-500">Clinical safety research</p>
            </div>
          </div>

          <div className="mt-12 rounded-xl bg-teal-50 p-4">
            <p className="text-sm font-semibold text-teal-900">
              Research environment
            </p>
            <p className="mt-2 text-xs leading-5 text-teal-800">
              Synthetic cases only. Not for clinical use.
            </p>
          </div>

          <div className="mt-auto border-t border-slate-200 pt-5 text-xs text-slate-500">
            Human-supervised decision support
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center justify-between border-b border-slate-200 bg-white px-5 py-5 sm:px-10">
            <div className="flex items-center gap-3">
              <HeartPulse className="text-teal-700 lg:hidden" size={25} />
              <div>
                <p className="text-sm font-semibold">Tazama Workspace</p>
                <p className="text-xs text-slate-500">
                  Development environment
                </p>
              </div>
            </div>
            <span className="rounded-full bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-800">
              Research prototype
            </span>
          </header>

          <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-10 sm:px-10">
            <div className="max-w-3xl">
              <p className="text-xs font-bold uppercase tracking-[0.2em] text-teal-700">
                System overview
              </p>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
                Clinical triage and reassessment
              </h1>
              <p className="mt-4 text-base leading-7 text-slate-600">
                A human-supervised research system designed to support
                structured observations, deterministic assessment, and
                traceable reassessment workflows.
              </p>
            </div>

            <SafetyNotice />

            <section className="mt-12">
              <h2 className="text-xl font-semibold">System capabilities</h2>
              <p className="mt-2 text-sm text-slate-500">
                Architecture overview, not live operational results.
              </p>
              <div className="mt-6 grid gap-5 md:grid-cols-3">
                {capabilities.map((item) => {
                  const Icon = item.icon;
                  return (
                    <article
                      key={item.title}
                      className="rounded-2xl border border-slate-200 bg-white p-6"
                    >
                      <div className="inline-flex rounded-xl bg-teal-50 p-3 text-teal-700">
                        <Icon size={22} />
                      </div>
                      <h3 className="mt-5 font-semibold">{item.title}</h3>
                      <p className="mt-2 text-sm leading-6 text-slate-600">
                        {item.description}
                      </p>
                    </article>
                  );
                })}
              </div>
            </section>

            <Suspense
              fallback={
                <section
                  role="status"
                  className="mt-10 rounded-2xl border border-slate-200 bg-white p-6 sm:p-8"
                >
                  <h2 className="text-lg font-semibold">
                    Backend connection
                  </h2>
                  <p className="mt-2 text-sm text-slate-500">
                    Checking local API availability...
                  </p>
                </section>
              }
            >
              <BackendStatus />
            </Suspense>
          </main>

          <footer className="border-t border-slate-200 px-5 py-5 text-xs text-slate-500 sm:px-10">
            Tazama AI · Synthetic-data research environment
          </footer>
        </div>
      </div>
    </div>
  );
}
