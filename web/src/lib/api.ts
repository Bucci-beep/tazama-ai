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

export async function getApiHealth(): Promise<ApiConnection> {
  const baseUrl =
    process.env.TAZAMA_API_URL ?? "http://127.0.0.1:8000";

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
