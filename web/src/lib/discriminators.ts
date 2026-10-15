import chart from "../../../data/protocol/discriminators_adult.json";

export type SignAssessment = string[] | null;

export const discriminatorGroups = chart.levels.map((level) => ({
  level: level.level,
  signs: level.signs.map((sign) => ({
    signId: sign.sign_id,
    chartText: sign.chart_text,
  })),
}));

const discriminatorIdSet = new Set(
  discriminatorGroups.flatMap((group) =>
    group.signs.map((sign) => sign.signId),
  ),
);

export function isKnownDiscriminatorId(value: string): boolean {
  return discriminatorIdSet.has(value);
}

export function discriminatorText(signId: string): string | null {
  for (const group of discriminatorGroups) {
    const sign = group.signs.find((item) => item.signId === signId);
    if (sign) return sign.chartText;
  }
  return null;
}
