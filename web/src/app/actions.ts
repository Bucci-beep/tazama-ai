"use server";

import { redirect } from "next/navigation";
import {
  createCaseObservation,
  type PatientObservations,
  requestCaseReassessment,
  type ReassessmentResponse,
} from "@/lib/api";
import {
  isKnownDiscriminatorId,
  type SignAssessment,
} from "@/lib/discriminators";

export type ObservationFormState = {
  status: "idle" | "error";
  message: string;
};

const caseIdPattern = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;

export type ReassessmentActionState =
  | { status: "idle"; message: ""; result: null }
  | { status: "error"; message: string; result: null }
  | { status: "success"; message: string; result: ReassessmentResponse };

function parseSignAssessment(formData: FormData): SignAssessment {
  const mode = formData.get("sign_assessment");
  const rawSigns = formData.getAll("signs");
  if (rawSigns.some((value) => typeof value !== "string")) {
    throw new Error("Invalid clinical sign selection.");
  }
  const signs = rawSigns as string[];
  if (signs.some((sign) => !isKnownDiscriminatorId(sign))) {
    throw new Error("One or more clinical sign selections are not recognised.");
  }
  if (mode === "not_assessed") {
    if (signs.length) throw new Error("Unassessed signs cannot include selections.");
    return null;
  }
  if (mode === "assessed_none") {
    if (signs.length) {
      throw new Error("No-sign assessment cannot include selections.");
    }
    return [];
  }
  if (mode === "assessed_selected") {
    if (!signs.length) {
      throw new Error("Select at least one chart-defined clinical sign.");
    }
    return [...new Set(signs)];
  }
  throw new Error("Select how clinical signs were assessed.");
}

export async function requestReassessmentAction(
  _previousState: ReassessmentActionState,
  formData: FormData,
): Promise<ReassessmentActionState> {
  const caseId = String(formData.get("case_id") ?? "").trim();
  if (!caseIdPattern.test(caseId)) {
    return {
      status: "error",
      message:
        "Case ID must use 1–100 letters, numbers, dots, underscores, or hyphens.",
      result: null,
    };
  }

  let signs: SignAssessment;
  try {
    signs = parseSignAssessment(formData);
  } catch (error) {
    return {
      status: "error",
      message:
        error instanceof Error ? error.message : "Invalid clinical sign selection.",
      result: null,
    };
  }

  const response = await requestCaseReassessment(caseId, signs);
  if (response.status !== "completed") {
    return { status: "error", message: response.reason, result: null };
  }
  return {
    status: "success",
    message: "Reassessment completed. Review status is shown below.",
    result: response.reassessment,
  };
}

function optionalNumber(formData: FormData, name: string): number | null {
  const raw = String(formData.get(name) ?? "").trim();
  if (!raw) return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) {
    throw new Error(`${name.replaceAll("_", " ")} must be a number`);
  }
  return value;
}

function optionalText(formData: FormData, name: string): string | null {
  const value = String(formData.get(name) ?? "").trim();
  return value || null;
}

export async function saveObservationAction(
  _previousState: ObservationFormState,
  formData: FormData,
): Promise<ObservationFormState> {
  const caseId = String(formData.get("case_id") ?? "").trim();
  if (!caseIdPattern.test(caseId)) {
    return {
      status: "error",
      message:
        "Case ID must use 1–100 letters, numbers, dots, underscores, or hyphens.",
    };
  }

  const observationType = formData.get("observation_type");
  if (observationType !== "baseline" && observationType !== "recheck") {
    return { status: "error", message: "Invalid observation type." };
  }

  const recordedAtInput = String(formData.get("recorded_at") ?? "").trim();
  const recordedAt = new Date(`${recordedAtInput}Z`);
  if (!recordedAtInput || Number.isNaN(recordedAt.getTime())) {
    return { status: "error", message: "Enter a valid recorded time in UTC." };
  }

  let observations: PatientObservations;
  try {
    const trauma = formData.get("trauma");
    if (trauma !== "" && trauma !== "true" && trauma !== "false") {
      throw new Error("Trauma must be yes, no, or not recorded");
    }
    observations = {
      heart_rate_bpm: optionalNumber(formData, "heart_rate_bpm"),
      respiratory_rate_bpm: optionalNumber(formData, "respiratory_rate_bpm"),
      systolic_bp_mmhg: optionalNumber(formData, "systolic_bp_mmhg"),
      temperature_c: optionalNumber(formData, "temperature_c"),
      spo2_percent: optionalNumber(formData, "spo2_percent"),
      consciousness: optionalText(formData, "consciousness"),
      mobility: optionalText(formData, "mobility"),
      trauma: trauma === "" ? null : trauma === "true",
    };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Invalid observation value.",
    };
  }

  const result = await createCaseObservation(caseId, {
    recorded_at: recordedAt.toISOString(),
    observation_type: observationType,
    observations,
  });

  if (result.status !== "created") {
    return { status: "error", message: result.reason };
  }

  redirect(
    `/?case_id=${encodeURIComponent(caseId)}&saved=${encodeURIComponent(observationType)}`,
  );
}
