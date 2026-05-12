// Shared constants. Keep this file boring: no logic, no derivations,
// just the values that more than one module needs.

// Base URL of the FastAPI scoring backend. Server-to-server only (no
// NEXT_PUBLIC_ prefix). Defaults to the local dev address; override via
// env in deployed environments.
export const COHORT_API_BASE =
  process.env.COHORT_API_BASE ?? "http://localhost:8000";
