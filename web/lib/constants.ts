// Shared constants. Keep this file boring: no logic, no derivations,
// just the values that more than one module needs.

// Base URL of the FastAPI scoring backend. Server-to-server only (no
// NEXT_PUBLIC_ prefix). Defaults to the local dev address; override via
// env in deployed environments.
export const COHORT_API_BASE =
  process.env.COHORT_API_BASE ?? "http://localhost:8000";

// Color for form-authored cohorts on the map. Single fixed value
// chosen to be distinct from all six library colors (#0d9488 teal,
// #a78bfa purple, #f97316 orange, #ec4899 pink, #15803d dark green,
// #2e3745 slate). The cohort builder modal does not let the user
// pick a color; form-authored cohorts always render in this one.
export const AUTHORED_COHORT_COLOR = "#38bdf8";
