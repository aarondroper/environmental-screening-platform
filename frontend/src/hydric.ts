// Sequential ramp: more hydric components → darker blue. Colors for the NRCS
// "Hydric Rating by Map Unit" classes returned by the API.
export const HYDRIC_COLORS: Record<string, string> = {
  hydric_100: "#08306b",
  hydric_66_99: "#2171b5",
  hydric_33_65: "#6baed6",
  hydric_1_32: "#c6dbef",
  hydric_0: "#ece7dc",
  not_rated: "#a8a8a8",
};

export const HYDRIC_NOTE =
  "Soil indicator only (share of each soil map unit made up of hydric soil components). " +
  "Not a wetland delineation or jurisdictional determination.";
