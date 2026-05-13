// Shared types across the map and cohort-builder layers.
// Keep this file boring: shape definitions only, no logic.

export interface Cohort {
  id: string;
  name: string;
  color: string;
  // Optional editorial vibe. Library entries have it (from
  // library.json), form-authored cohorts have it from the modal's
  // vibe field.
  vibe?: string | null;
  tract_scores: Record<string, Record<string, number>>;
  stats: Record<string, unknown>;
}
