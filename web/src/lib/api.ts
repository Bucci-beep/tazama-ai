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

export type CreateObservationInput = {
  recorded_at: string;
  observation_type: "baseline" | "recheck";
  observations: PatientObservations;
};

export type CreateObservationResult =
  | { status: "created"; record: ObservationRecord }
  | { status: "invalid" | "conflict" | "unavailable"; reason: string };

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

function errorDetail(data: unknown, fallback: string): string {
  if (
    typeof data === "object" &&
    data !== null &&
    "detail" in data &&
    typeof data.detail === "string"
  ) {
    return data.detail;
  }
  return fallback;
}

export async function createCaseObservation(
  caseId: string,
  input: CreateObservationInput,
): Promise<CreateObservationResult> {
  try {
    const response = await fetch(
      `${apiBaseUrl()}/api/v1/cases/${encodeURIComponent(caseId)}/observations`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(input),
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      },
    );
    const data: unknown = await response.json();

    if (response.status === 409) {
      return {
        status: "conflict",
        reason: errorDetail(data, "Observation conflicts with this timeline"),
      };
    }
    if (response.status === 422) {
      return {
        status: "invalid",
        reason: "The API rejected one or more observation fields",
      };
    }
    if (!response.ok) {
      return {
        status: "unavailable",
        reason: errorDetail(data, `API returned HTTP ${response.status}`),
      };
    }

    if (
      typeof data !== "object" ||
      data === null ||
      !("observation_id" in data) ||
      !("case_id" in data) ||
      data.case_id !== caseId
    ) {
      return {
        status: "unavailable",
        reason: "API returned an unexpected observation response",
      };
    }

    return { status: "created", record: data as ObservationRecord };
  } catch {
    return {
      status: "unavailable",
      reason: "Unable to reach the local Tazama API",
    };
  }
}
