import "server-only";

import type { SignAssessment } from "@/lib/discriminators";

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

export type HistoryChange = {
  field: string;
  before: number;
  after: number;
  before_obs_id: string;
  after_obs_id: string;
};

export type HistoryComparison = {
  schema_version: "1.0";
  case_id: string;
  status:
    | "differences_found"
    | "no_differences"
    | "insufficient_history"
    | "untrusted_reading";
  changes: HistoryChange[];
  not_comparable: string[];
  reason: string | null;
};

export type PriorityEvidence = {
  status: "complete" | "minimum_only" | "abstained";
  priority: string | null;
  priority_at_least: string | null;
  matched_sign_ids: string[];
  unknown_sign_ids: string[];
  tews: {
    status: string;
    total?: number | null;
    priority?: string | null;
    missing?: string[];
    unscorable?: Array<{ field: string }>;
  };
  reasons: string[];
  protocol_version: string;
};

export type ReassessmentResponse = {
  case_id: string;
  workflow_run_id: string;
  status: "awaiting_clinician_review" | "review_submission_failed";
  reason: string | null;
  observation_count: number;
  has_baseline: boolean;
  has_rechecks: boolean;
  latest_observation_id: string;
  comparison_status: string;
  comparison_result: HistoryComparison | null;
  comparison_error: string | null;
  priority_status:
    | "complete"
    | "minimum_only"
    | "abstained"
    | "tool_unavailable";
  priority_result: PriorityEvidence | null;
  priority_error: string | null;
  explanation: {
    status?: string;
    model?: string;
    selected_explanation_ids?: string[];
    statements?: string[];
  } | null;
  explanation_error: string | null;
  review_request_id: string | null;
  review_submission_status: "persisted" | "unconfirmed";
  review_submission_error: string | null;
  workflow_provenance: {
    time?: {
      status?: string;
      server?: string;
      tool?: string;
      result?: { datetime?: string; timezone?: string };
      error?: string;
      audit_status?: string;
    };
  };
  mcp_audit_errors: string[];
};

export type ReassessmentResult =
  | { status: "completed"; reassessment: ReassessmentResponse }
  | { status: "not_found"; reason: string }
  | { status: "unavailable" | "invalid"; reason: string };

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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isHistoryComparison(value: unknown): value is HistoryComparison {
  if (!isRecord(value)) return false;
  const allowed = new Set([
    "differences_found",
    "no_differences",
    "insufficient_history",
    "untrusted_reading",
  ]);
  return (
    value.schema_version === "1.0" &&
    typeof value.case_id === "string" &&
    allowed.has(String(value.status)) &&
    Array.isArray(value.changes) &&
    value.changes.every(
      (change) =>
        isRecord(change) &&
        typeof change.field === "string" &&
        typeof change.before === "number" &&
        Number.isFinite(change.before) &&
        typeof change.after === "number" &&
        Number.isFinite(change.after) &&
        typeof change.before_obs_id === "string" &&
        typeof change.after_obs_id === "string",
    ) &&
    isStringArray(value.not_comparable) &&
    isNullableString(value.reason)
  );
}

function isTewsEvidence(value: unknown): value is PriorityEvidence["tews"] {
  if (!isRecord(value) || typeof value.status !== "string") return false;
  if (
    "total" in value &&
    value.total !== null &&
    (typeof value.total !== "number" || !Number.isFinite(value.total))
  ) return false;
  if ("priority" in value && !isNullableString(value.priority)) return false;
  if ("missing" in value && !isStringArray(value.missing)) return false;
  return !(
    "unscorable" in value &&
    (!Array.isArray(value.unscorable) ||
      !value.unscorable.every(
        (issue) => isRecord(issue) && typeof issue.field === "string",
      ))
  );
}

function isPriorityEvidence(value: unknown): value is PriorityEvidence {
  if (!isRecord(value)) return false;
  const allowed = new Set(["complete", "minimum_only", "abstained"]);
  return (
    allowed.has(String(value.status)) &&
    isNullableString(value.priority) &&
    isNullableString(value.priority_at_least) &&
    isStringArray(value.matched_sign_ids) &&
    isStringArray(value.unknown_sign_ids) &&
    isTewsEvidence(value.tews) &&
    isStringArray(value.reasons) &&
    typeof value.protocol_version === "string"
  );
}

function isExplanation(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    (!("status" in value) || typeof value.status === "string") &&
    (!("model" in value) || typeof value.model === "string") &&
    (!("selected_explanation_ids" in value) ||
      isStringArray(value.selected_explanation_ids)) &&
    (!("statements" in value) || isStringArray(value.statements))
  );
}

function isTimeProvenance(value: unknown): boolean {
  if (!isRecord(value)) return false;
  if (
    !new Set(["captured", "tool_unavailable"]).has(String(value.status)) ||
    typeof value.server !== "string" ||
    typeof value.tool !== "string" ||
    ("error" in value && typeof value.error !== "string") ||
    ("audit_status" in value && typeof value.audit_status !== "string")
  ) return false;
  if (!("result" in value)) return value.status === "tool_unavailable";
  return (
    value.status === "captured" &&
    isRecord(value.result) &&
    typeof value.result.datetime === "string" &&
    typeof value.result.timezone === "string"
  );
}

function isReassessmentResponse(
  value: unknown,
  expectedCaseId: string,
): value is ReassessmentResponse {
  if (!isRecord(value)) return false;
  const workflowStatuses = new Set([
    "awaiting_clinician_review",
    "review_submission_failed",
  ]);
  const comparisonStatuses = new Set([
    "differences_found",
    "no_differences",
    "insufficient_history",
    "untrusted_reading",
    "tool_unavailable",
  ]);
  const priorityStatuses = new Set([
    "complete",
    "minimum_only",
    "abstained",
    "tool_unavailable",
  ]);
  if (
    value.case_id !== expectedCaseId ||
    typeof value.workflow_run_id !== "string" ||
    !value.workflow_run_id ||
    !workflowStatuses.has(String(value.status)) ||
    !isNullableString(value.reason) ||
    !Number.isInteger(value.observation_count) ||
    Number(value.observation_count) < 1 ||
    typeof value.has_baseline !== "boolean" ||
    typeof value.has_rechecks !== "boolean" ||
    typeof value.latest_observation_id !== "string" ||
    !comparisonStatuses.has(String(value.comparison_status)) ||
    !isNullableString(value.comparison_error) ||
    !priorityStatuses.has(String(value.priority_status)) ||
    !isNullableString(value.priority_error) ||
    !isNullableString(value.explanation_error) ||
    !isNullableString(value.review_request_id) ||
    !new Set(["persisted", "unconfirmed"]).has(
      String(value.review_submission_status),
    ) ||
    !isNullableString(value.review_submission_error) ||
    !isRecord(value.workflow_provenance) ||
    !isTimeProvenance(value.workflow_provenance.time) ||
    !isStringArray(value.mcp_audit_errors)
  ) return false;

  if (
    value.comparison_result !== null &&
    !isHistoryComparison(value.comparison_result)
  ) return false;
  if (
    value.priority_result !== null &&
    !isPriorityEvidence(value.priority_result)
  ) return false;
  if (value.explanation !== null && !isExplanation(value.explanation)) return false;

  if (value.priority_status === "tool_unavailable") {
    if (value.priority_result !== null) return false;
  } else if (
    !isPriorityEvidence(value.priority_result) ||
    value.priority_result.status !== value.priority_status
  ) return false;

  if (value.review_submission_status === "persisted") {
    return (
      typeof value.review_request_id === "string" &&
      value.review_request_id.length > 0 &&
      value.status === "awaiting_clinician_review"
    );
  }
  return value.review_request_id === null;
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

export async function requestCaseReassessment(
  caseId: string,
  signs: SignAssessment,
): Promise<ReassessmentResult> {
  const trimmedCaseId = caseId.trim();
  try {
    const response = await fetch(
      `${apiBaseUrl()}/api/v1/cases/${encodeURIComponent(trimmedCaseId)}/reassess`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ signs }),
        cache: "no-store",
        signal: AbortSignal.timeout(30000),
      },
    );
    const data: unknown = await response.json();

    if (response.status === 404) {
      return {
        status: "not_found",
        reason: errorDetail(data, "No observations found for this case"),
      };
    }
    if (response.status === 422) {
      return { status: "invalid", reason: "The case identifier is invalid" };
    }
    if (!response.ok) {
      return {
        status: "unavailable",
        reason: errorDetail(data, `API returned HTTP ${response.status}`),
      };
    }
    if (!isReassessmentResponse(data, trimmedCaseId)) {
      return {
        status: "unavailable",
        reason: "API returned an unexpected reassessment response",
      };
    }
    return {
      status: "completed",
      reassessment: data as ReassessmentResponse,
    };
  } catch {
    return {
      status: "unavailable",
      reason: "Unable to reach the local Tazama API",
    };
  }
}


export type DueReassessmentObligation = {
  obligation_id: string;
  case_id: string;
  due_at: string;
  created_at: string;
  status: "scheduled";
  policy_reference: string;
};

export type DueReassessmentsResult =
  | {
      status: "available";
      as_of: string;
      obligations: DueReassessmentObligation[];
    }
  | { status: "unavailable"; reason: string };

function isAwareTimestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;

  const timezonePattern = /(?:Z|[+-]\d{2}:\d{2})$/;

  return timezonePattern.test(value) && Number.isFinite(Date.parse(value));
}

function isDueReassessmentObligation(
  value: unknown,
  asOf: string,
): value is DueReassessmentObligation {
  return (
    isRecord(value) &&
    typeof value.obligation_id === "string" &&
    value.obligation_id.length > 0 &&
    typeof value.case_id === "string" &&
    value.case_id.length > 0 &&
    isAwareTimestamp(value.due_at) &&
    isAwareTimestamp(value.created_at) &&
    value.status === "scheduled" &&
    typeof value.policy_reference === "string" &&
    value.policy_reference.length > 0 &&
    Date.parse(value.due_at) <= Date.parse(asOf) &&
    Date.parse(value.created_at) <= Date.parse(value.due_at)
  );
}

export async function getDueReassessments(): Promise<DueReassessmentsResult> {
  try {
    const response = await fetch(
      `${apiBaseUrl()}/api/v1/reassessments/due`,
      {
        cache: "no-store",
        signal: AbortSignal.timeout(3000),
      },
    );

    if (!response.ok) {
      return {
        status: "unavailable",
        reason: `API returned HTTP ${response.status}`,
      };
    }

    const data: unknown = await response.json();

    if (
      !isRecord(data) ||
      !isAwareTimestamp(data.as_of) ||
      !Array.isArray(data.obligations) ||
      !data.obligations.every((item) =>
        isDueReassessmentObligation(item, String(data.as_of)),
      ) ||
      new Set(
        data.obligations.map(
          (item: DueReassessmentObligation) => item.obligation_id,
        ),
      ).size !== data.obligations.length
    ) {
      return {
        status: "unavailable",
        reason: "API returned an invalid reassessment queue",
      };
    }

    return {
      status: "available",
      as_of: data.as_of,
      obligations: data.obligations,
    };
  } catch {
    return {
      status: "unavailable",
      reason: "Unable to reach the local Tazama API",
    };
  }
}
