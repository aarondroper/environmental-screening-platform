const hectares = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const percent = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

export const formatHa = (m2: number) => `${hectares.format(m2 / 10_000)} ha`;
export const formatPct = (value: number) => `${percent.format(value)}%`;
export const formatDateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
