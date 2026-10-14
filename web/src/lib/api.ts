import "server-only";

export type ApiHealth = {
  status: "ok";
  service: "tazama-api";
  environment: "synthetic-research";
  clinical_use_permitted: false;
};

export type ApiConnection =
  | { connected: true; health: ApiHealth }
  | { connected: false; reason: string };

export type PatientObservations = {
  heart_rate_bpm: number | null;
  respiratory_rate_bpm: number | null;
  systolic_bp_mmhg: number | null;
  temperature_c: number | null;
  spo2_percent: number | null;
  consciousness: string | null;
  mobility: string | null;
  trauma: boolean | null;
};

export type ObservationRecord = {
  observation_id: string;
  case_id: string;
  recorded_at: string;
  observation_type: "baseline" | "recheck";
  observations: PatientObservations;
};

export type CaseTimeline = {
  case_id: string;
  records: ObservationRecord[];
};

export type CaseTimelineResult =
  | { status: "found"; timeline: CaseTimeline }
  | { status: "not_found" }
  | { status: "unavailable"; reason: string };

function apiBaseUrl(): string {
  return process.env.TAZAMA_API_URL ?? "http://127.0.0.1:8000";
}

export async function getApiHealth(): Promise<ApiConnection> {
  const baseUrl = apiBaseUrl();

  try {
    const response = await fetch(`${baseUrl}/api/v1/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });

    if (!response.ok) {
      return {
        connected: false,
        reason: `API returned HTTP ${response.status}`,
      };
    }

    const data: unknown = await response.json();

    if (
      typeof data !== "object" ||
      data === null ||
      !("status" in data) ||
      data.status !== "ok" ||
      !("service" in data) ||
      data.service !== "tazama-api" ||
      !("environment" in data) ||
      data.environment !== "synthetic-research" ||
      !("clinical_use_permitted" in data) ||
      data.clinical_use_permitted !== false
    ) {
      return {
        connected: false,
        reason: "API returned an unexpected health response",
      };
    }

    return {
      connected: true,
      health: data as ApiHealth,
    };
  } catch {
    return {
      connected: false,
      reason: "Unable to reach the local Tazama API",
    };
  }
}

export async function getCaseTimeline(
  caseId: string,
): Promise<CaseTimelineResult> {
  const trimmedCaseId = caseId.trim();
  if (!trimmedCaseId) {
    return { status: "not_found" };
  }

  try {
    const response = await fetch(
      `${apiBaseUrl()}/api/v1/cases/${encodeURIComponent(trimmedCaseId)}/observations`,
      {
        cache: "no-store",
        signal: AbortSignal.timeout(3000),
      },
    );

    if (response.status === 404) {
      return { status: "not_found" };
    }
    if (!response.ok) {
      return {
        status: "unavailable",
        reason: `API returned HTTP ${response.status}`,
      };
    }

    const data: unknown = await response.json();
    if (
      typeof data !== "object" ||
      data === null ||
      !("case_id" in data) ||
      data.case_id !== trimmedCaseId ||
      !("records" in data) ||
      !Array.isArray(data.records)
    ) {
      return {
        status: "unavailable",
        reason: "API returned an unexpected observation response",
      };
    }

    return { status: "found", timeline: data as CaseTimeline };
  } catch {
    return {
      status: "unavailable",
      reason: "Unable to reach the local Tazama API",
    };
  }
}
