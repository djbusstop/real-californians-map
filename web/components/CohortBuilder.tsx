"use client";

// CohortBuilder
//
// Modal form for authoring a single user-defined cohort and rendering
// it on the map. Replaces the LLM chat flow. UX shape:
//
//   - "+ new cohort" button below the legend opens the modal.
//   - Modal has a title, a vibe, and a set of quick controls covering
//     the dimensions used most often in the existing library (age,
//     income, education, kids, single/family).
//   - On "save", the form state is translated into a /score request
//     and POSTed; the response cohort is handed back to MapView for
//     rendering. The modal closes on success and stays open with an
//     error on failure.
//   - Draft form state is held in localStorage so reloads do not
//     lose work in progress.
//   - "delete cohort" clears the rendered cohort from the map and
//     resets the draft state.
//
// v0 deliberately ships only the quick controls. The full topic
// accordion (Pattern B) lands in v0.1; the field-control plumbing
// inside this file is set up so adding it later is mostly per-field
// configuration, not a rewrite.

import { useEffect, useState } from "react";
import type { Cohort } from "@/lib/types";
import { COHORT_API_BASE } from "@/lib/constants";

interface Props {
  onCohort: (cohort: Omit<Cohort, "color"> | null) => void;
  hasCohort: boolean;
}

// ---------------------------------------------------------------------
// Draft state shape and defaults
// ---------------------------------------------------------------------

// AGEP is integer years; PUMS top-codes at 99. We cap the slider at 95
// because real population is sparse above that and the cap keeps the
// slider's perceived precision useful.
const AGE_MIN = 0;
const AGE_MAX = 95;
// HINCP is annual household income in dollars. Capping at $500k handles
// the 99th percentile gracefully; the top-coded values themselves go
// higher but no slider needs that resolution.
const INCOME_MIN = 0;
const INCOME_MAX = 500_000;
const INCOME_STEP = 5_000;
// SCHL is ordinal: 1 = no schooling through 24 = doctorate.
const SCHL_MIN = 1;
const SCHL_MAX = 24;
// NOP is integer count of own children. PUMS allows up to ~17 but real
// distribution is well under 6.
const KIDS_MIN = 0;
const KIDS_MAX = 6;

// HHT (Household Type) value sets for the living-arrangement pills.
// Family = married couple, single-parent, or other family household.
// Single = nonfamily household (alone or with non-relatives).
const HHT_FAMILY = [1, 2, 3];
const HHT_SINGLE = [4, 5, 6, 7];

// MAR (Marital Status) codes used by the identity pills. MAR=4
// (separated) and MAR=5 (never married) are omitted from the UI for
// now; the four below cover the dimensions the existing library
// cohorts gate on.
const MAR_MARRIED = 1;
const MAR_WIDOWED = 2;
const MAR_DIVORCED = 3;

// TEN (Tenure) codes for the housing pills. 1 = owned with mortgage,
// 2 = owned free and clear, 3 = rented, 4 = occupied without payment.
const TEN_OWN = [1, 2];
const TEN_RENT = [3];

type Living = "single" | "family";
type IdentityPill = "queer" | "married" | "divorced" | "widowed";
type HousingPill = "owns" | "rents";

interface DraftState {
  title: string;
  vibe: string;
  ageRange: [number, number];
  incomeRange: [number, number];
  // Education is a range over SCHL codes (1-24). Lets the user express
  // "high school only" or "some college through bachelor's" without
  // being limited to gte. Labels are bucketed concepts not raw codes
  // (see fmtSchlConcept).
  educationRange: [number, number];
  kidsRange: [number, number];
  living: Living[];
  // Mixed-field pill group. `queer` maps to SAME_SEX = 1. The other
  // three collapse into one MAR in [...] condition at vector-build
  // time so multi-select reads as "married OR divorced OR widowed."
  identity: IdentityPill[];
  // TEN tenure pills. Multi-select; collapse into one TEN in [...]
  // condition. Both selected is equivalent to "any tenure" so the
  // condition is omitted.
  housing: HousingPill[];
}

const DEFAULT_DRAFT: DraftState = {
  title: "",
  vibe: "",
  ageRange: [AGE_MIN, AGE_MAX],
  incomeRange: [INCOME_MIN, INCOME_MAX],
  educationRange: [SCHL_MIN, SCHL_MAX],
  kidsRange: [KIDS_MIN, KIDS_MAX],
  living: [],
  identity: [],
  housing: [],
};

const STORAGE_KEY = "cohort_draft_v1";

function readDraft(): DraftState {
  if (typeof window === "undefined") return DEFAULT_DRAFT;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_DRAFT;
    const parsed = JSON.parse(raw);
    return { ...DEFAULT_DRAFT, ...parsed };
  } catch {
    return DEFAULT_DRAFT;
  }
}

function writeDraft(draft: DraftState) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
}

// ---------------------------------------------------------------------
// Vector and marginal construction
// ---------------------------------------------------------------------

// Map each "active" quick control to the corresponding vector entry.
// "Active" means the control's value diverges from the default; sliders
// at full range and empty pill groups produce no entries.
interface VectorEntry {
  field: string;
  op: string;
  value: unknown;
  weight: number;
  required?: boolean;
}

function buildVector(draft: DraftState): VectorEntry[] {
  const v: VectorEntry[] = [];
  const [aLo, aHi] = draft.ageRange;
  if (aLo > AGE_MIN || aHi < AGE_MAX) {
    v.push({ field: "AGEP", op: "range", value: [aLo, aHi], weight: 1 });
  }
  const [iLo, iHi] = draft.incomeRange;
  if (iLo > INCOME_MIN || iHi < INCOME_MAX) {
    v.push({ field: "HINCP", op: "range", value: [iLo, iHi], weight: 1 });
  }
  const [eLo, eHi] = draft.educationRange;
  if (eLo > SCHL_MIN || eHi < SCHL_MAX) {
    v.push({ field: "SCHL", op: "range", value: [eLo, eHi], weight: 1 });
  }
  const [kLo, kHi] = draft.kidsRange;
  if (kLo > KIDS_MIN || kHi < KIDS_MAX) {
    v.push({ field: "NOP", op: "range", value: [kLo, kHi], weight: 1 });
  }
  if (draft.living.length > 0 && draft.living.length < 2) {
    // Only meaningful if exactly one of the two pills is active. Both
    // selected = "any household type" = no condition needed.
    const codes =
      draft.living[0] === "family" ? HHT_FAMILY : HHT_SINGLE;
    v.push({ field: "HHT", op: "in", value: codes, weight: 1 });
  }
  // Identity pills: `queer` is its own field (SAME_SEX). The three
  // marital pills collapse into a single MAR condition.
  const identitySet = new Set(draft.identity);
  if (identitySet.has("queer")) {
    v.push({ field: "SAME_SEX", op: "eq", value: 1, weight: 1 });
  }
  const marCodes: number[] = [];
  if (identitySet.has("married")) marCodes.push(MAR_MARRIED);
  if (identitySet.has("widowed")) marCodes.push(MAR_WIDOWED);
  if (identitySet.has("divorced")) marCodes.push(MAR_DIVORCED);
  if (marCodes.length > 0) {
    v.push({ field: "MAR", op: "in", value: marCodes, weight: 1 });
  }
  // Housing tenure pills. Both selected = "any tenure" = omit.
  if (draft.housing.length > 0 && draft.housing.length < 2) {
    const codes = draft.housing[0] === "owns" ? TEN_OWN : TEN_RENT;
    v.push({ field: "TEN", op: "in", value: codes, weight: 1 });
  }
  // The API requires at least one required: true condition. Auto-
  // promote the first active condition so the user does not have to
  // think about it in v0.
  if (v.length > 0) v[0].required = true;
  return v;
}

// Marginal tables to pull, picked based on which quick controls are
// active. The /score endpoint accepts up to 8; the five quick controls
// generate at most five, well inside the cap.
function buildMarginals(draft: DraftState): string[] {
  const m: string[] = [];
  // Age uses Sex by Age (population pyramid). One of the densest,
  // most reliably published ACS tables; safe default.
  if (
    draft.ageRange[0] > AGE_MIN ||
    draft.ageRange[1] < AGE_MAX
  ) {
    m.push("B01001_002E"); // Total male population
  }
  if (
    draft.incomeRange[0] > INCOME_MIN ||
    draft.incomeRange[1] < INCOME_MAX
  ) {
    m.push("B19001_001E"); // Households with income reported
  }
  if (
    draft.educationRange[0] > SCHL_MIN ||
    draft.educationRange[1] < SCHL_MAX
  ) {
    m.push("B15003_022E"); // Bachelor's degree count
  }
  if (
    draft.kidsRange[0] > KIDS_MIN ||
    draft.kidsRange[1] < KIDS_MAX
  ) {
    m.push("B11003_001E"); // Family households by presence of children
  }
  if (draft.living.length === 1) {
    m.push("B11001_001E"); // Households by type
  }
  if (draft.identity.length > 0 && !m.includes("B11001_001E")) {
    // Identity-gated cohorts benefit from a household-type density
    // signal; add the same marginal we use for living arrangement if
    // not already included.
    m.push("B11001_001E");
  }
  if (draft.housing.length === 1) {
    m.push("B25003_001E"); // Total occupied housing units
  }
  // If the user activated nothing (shouldn't happen because Save is
  // disabled in that case), fall back to a generic baseline.
  if (m.length === 0) {
    m.push("B01001_001E"); // Total population
  }
  return m;
}

// ---------------------------------------------------------------------
// Small UI atoms
// ---------------------------------------------------------------------

const monoFont = "ui-monospace, monospace";

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        color: "#6a7283",
        fontFamily: monoFont,
        marginBottom: 4,
      }}
    >
      {children}
    </div>
  );
}

function RangeSlider({
  min,
  max,
  step = 1,
  value,
  onChange,
  format,
}: {
  min: number;
  max: number;
  step?: number;
  value: [number, number];
  onChange: (v: [number, number]) => void;
  format: (n: number) => string;
}) {
  const [lo, hi] = value;
  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 11,
          color: "#1a1f2e",
          fontFamily: monoFont,
          marginBottom: 2,
        }}
      >
        <span>{format(lo)}</span>
        <span>{format(hi)}</span>
      </div>
      <div style={{ position: "relative", height: 14 }}>
        <div className="builder-slider-track" />
        <input
          type="range"
          className="builder-slider builder-slider-stacked"
          min={min}
          max={max}
          step={step}
          value={lo}
          onChange={(e) => {
            const newLo = Math.min(parseFloat(e.target.value), hi);
            onChange([newLo, hi]);
          }}
          style={{ position: "absolute", top: 0, left: 0 }}
          aria-label="minimum"
        />
        <input
          type="range"
          className="builder-slider builder-slider-stacked"
          min={min}
          max={max}
          step={step}
          value={hi}
          onChange={(e) => {
            const newHi = Math.max(parseFloat(e.target.value), lo);
            onChange([lo, newHi]);
          }}
          style={{ position: "absolute", top: 0, left: 0 }}
          aria-label="maximum"
        />
      </div>
    </div>
  );
}

// Section wrapper: label on the left, "any" reset button on the right.
// "any" is greyed out when the section is already at its default
// (= the section already means "doesn't matter for this dimension")
// and underlined / clickable when the section has been modified.
function Section({
  label,
  isModified,
  onReset,
  children,
}: {
  label: string;
  isModified: boolean;
  onReset: () => void;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 4,
        }}
      >
        <span
          style={{
            fontSize: 11,
            color: "#6a7283",
            fontFamily: monoFont,
          }}
        >
          {label}
        </span>
        <button
          type="button"
          onClick={onReset}
          disabled={!isModified}
          style={{
            background: "transparent",
            border: "none",
            cursor: isModified ? "pointer" : "default",
            fontSize: 11,
            color: isModified ? "#6a7283" : "#d1d5db",
            fontFamily: monoFont,
            padding: 0,
            textDecoration: isModified ? "underline" : "none",
          }}
        >
          any
        </button>
      </div>
      {children}
    </div>
  );
}

function PillGroup<T extends string>({
  options,
  value,
  onChange,
}: {
  options: T[];
  value: T[];
  onChange: (v: T[]) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 6 }}>
      {options.map((opt) => {
        const active = value.includes(opt);
        return (
          <button
            key={opt}
            type="button"
            onClick={() =>
              onChange(active ? value.filter((v) => v !== opt) : [...value, opt])
            }
            style={{
              padding: "4px 10px",
              borderRadius: 12,
              border: active
                ? "1px solid #1a1f2e"
                : "1px solid rgba(0,0,0,0.15)",
              background: active ? "#1a1f2e" : "rgba(255,255,255,0.96)",
              color: active ? "white" : "#1a1f2e",
              fontSize: 11,
              fontFamily: monoFont,
              cursor: "pointer",
            }}
          >
            {opt}
          </button>
        );
      })}
    </div>
  );
}

// Concept-based formatters. The slider underneath is continuous in
// raw units (dollars, SCHL codes); the label maps the underlying
// value to a Census-relative concept bucket so users read "poor to
// median" rather than "$25,000 to $112,000."

function fmtAge(n: number): string {
  return `${Math.round(n)}`;
}

// CA median household income is around $95k as of 2023. Buckets are
// chosen relative to that median, not to absolute US dollars.
function fmtIncomeConcept(dollars: number): string {
  if (dollars <= 25_000) return "very poor";
  if (dollars <= 65_000) return "poor";
  if (dollars <= 130_000) return "median";
  if (dollars <= 250_000) return "rich";
  return "very rich";
}

// SCHL bucket boundaries map to common educational milestones. The
// "no high school" bucket covers anyone who did not complete 12th
// grade with diploma or GED.
function fmtSchlConcept(code: number): string {
  if (code <= 15) return "no high school";
  if (code <= 17) return "high school";
  if (code <= 20) return "some college";
  if (code === 21) return "bachelor's";
  return "advanced";
}

function fmtKids(n: number): string {
  return `${n}`;
}

// ---------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------

export default function CohortBuilder({ onCohort, hasCohort }: Props) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DraftState>(DEFAULT_DRAFT);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Restore draft on mount.
  useEffect(() => {
    setDraft(readDraft());
  }, []);

  // Persist draft on change.
  useEffect(() => {
    writeDraft(draft);
  }, [draft]);

  const update = <K extends keyof DraftState>(k: K, v: DraftState[K]) =>
    setDraft((d) => ({ ...d, [k]: v }));

  const vector = buildVector(draft);
  const canSave = draft.title.trim().length > 0 && vector.length > 0;

  const handleSave = async () => {
    if (!canSave || saving) return;
    setSaving(true);
    setError(null);
    try {
      const body = {
        name: draft.title.trim(),
        vibe: draft.vibe.trim() || "user-authored cohort",
        threshold: 0.5,
        tract_marginals: buildMarginals(draft),
        vector,
      };
      const res = await fetch(`${COHORT_API_BASE}/score`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const text = await res.text();
      if (!res.ok) {
        setError(`HTTP ${res.status}: ${text.slice(0, 200)}`);
        return;
      }
      const data = JSON.parse(text);
      onCohort({
        id: data.id,
        name: data.name,
        vibe: draft.vibe.trim() || null,
        tract_scores: data.tract_scores,
        stats: data.stats,
      });
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = () => {
    onCohort(null);
    setDraft(DEFAULT_DRAFT);
    setOpen(false);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        style={{
          background: "rgba(255,255,255,0.85)",
          padding: "4px 8px",
          borderRadius: 4,
          fontSize: 11,
          color: "#1a1f2e",
          fontFamily: monoFont,
          border: "1px solid rgba(0,0,0,0.08)",
          cursor: "pointer",
          textAlign: "left",
          width: 240,
        }}
      >
        {hasCohort ? "edit cohort" : "+ new cohort"}
      </button>

      {open && (
        <div
          onClick={() => !saving && setOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.35)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 420,
              maxHeight: "85vh",
              overflowY: "auto",
              background: "white",
              borderRadius: 6,
              boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
              fontFamily: monoFont,
              fontSize: 11,
              color: "#1a1f2e",
            }}
          >
            <header
              style={{
                padding: "12px 16px",
                borderBottom: "1px solid rgba(0,0,0,0.08)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <span>author a cohort</span>
              <button
                type="button"
                onClick={() => !saving && setOpen(false)}
                disabled={saving}
                style={{
                  background: "transparent",
                  border: "none",
                  cursor: saving ? "default" : "pointer",
                  fontSize: 16,
                  color: "#6a7283",
                  padding: 0,
                  lineHeight: 1,
                }}
                aria-label="close"
              >
                ×
              </button>
            </header>

            <div
              style={{
                padding: 16,
                display: "flex",
                flexDirection: "column",
                gap: 14,
              }}
            >
              <div>
                <Label>title</Label>
                <input
                  type="text"
                  value={draft.title}
                  onChange={(e) => update("title", e.target.value)}
                  placeholder="e.g. wine-mom 2014"
                  style={{
                    width: "100%",
                    padding: "6px 8px",
                    border: "1px solid rgba(0,0,0,0.15)",
                    borderRadius: 3,
                    fontSize: 11,
                    fontFamily: monoFont,
                    boxSizing: "border-box",
                  }}
                />
              </div>

              <div>
                <Label>vibe (optional)</Label>
                <input
                  type="text"
                  value={draft.vibe}
                  onChange={(e) => update("vibe", e.target.value)}
                  placeholder="short editorial flavor"
                  style={{
                    width: "100%",
                    padding: "6px 8px",
                    border: "1px solid rgba(0,0,0,0.15)",
                    borderRadius: 3,
                    fontSize: 11,
                    fontFamily: monoFont,
                    boxSizing: "border-box",
                  }}
                />
              </div>

              <div
                style={{
                  borderTop: "1px solid rgba(0,0,0,0.06)",
                  paddingTop: 12,
                  display: "flex",
                  flexDirection: "column",
                  gap: 12,
                }}
              >
                <Section
                  label="age"
                  isModified={
                    draft.ageRange[0] > AGE_MIN || draft.ageRange[1] < AGE_MAX
                  }
                  onReset={() => update("ageRange", [AGE_MIN, AGE_MAX])}
                >
                  <RangeSlider
                    min={AGE_MIN}
                    max={AGE_MAX}
                    value={draft.ageRange}
                    onChange={(v) => update("ageRange", v)}
                    format={fmtAge}
                  />
                </Section>

                <Section
                  label="income (household)"
                  isModified={
                    draft.incomeRange[0] > INCOME_MIN ||
                    draft.incomeRange[1] < INCOME_MAX
                  }
                  onReset={() =>
                    update("incomeRange", [INCOME_MIN, INCOME_MAX])
                  }
                >
                  <RangeSlider
                    min={INCOME_MIN}
                    max={INCOME_MAX}
                    step={INCOME_STEP}
                    value={draft.incomeRange}
                    onChange={(v) => update("incomeRange", v)}
                    format={fmtIncomeConcept}
                  />
                </Section>

                <Section
                  label="education"
                  isModified={
                    draft.educationRange[0] > SCHL_MIN ||
                    draft.educationRange[1] < SCHL_MAX
                  }
                  onReset={() =>
                    update("educationRange", [SCHL_MIN, SCHL_MAX])
                  }
                >
                  <RangeSlider
                    min={SCHL_MIN}
                    max={SCHL_MAX}
                    value={draft.educationRange}
                    onChange={(v) => update("educationRange", v)}
                    format={fmtSchlConcept}
                  />
                </Section>

                <Section
                  label="children"
                  isModified={
                    draft.kidsRange[0] > KIDS_MIN ||
                    draft.kidsRange[1] < KIDS_MAX
                  }
                  onReset={() => update("kidsRange", [KIDS_MIN, KIDS_MAX])}
                >
                  <RangeSlider
                    min={KIDS_MIN}
                    max={KIDS_MAX}
                    value={draft.kidsRange}
                    onChange={(v) => update("kidsRange", v)}
                    format={fmtKids}
                  />
                </Section>

                <Section
                  label="living arrangement"
                  isModified={draft.living.length > 0}
                  onReset={() => update("living", [])}
                >
                  <PillGroup<Living>
                    options={["single", "family"]}
                    value={draft.living}
                    onChange={(v) => update("living", v)}
                  />
                </Section>

                <Section
                  label="identity"
                  isModified={draft.identity.length > 0}
                  onReset={() => update("identity", [])}
                >
                  <PillGroup<IdentityPill>
                    options={["queer", "married", "divorced", "widowed"]}
                    value={draft.identity}
                    onChange={(v) => update("identity", v)}
                  />
                </Section>

                <Section
                  label="housing"
                  isModified={draft.housing.length > 0}
                  onReset={() => update("housing", [])}
                >
                  <PillGroup<HousingPill>
                    options={["owns", "rents"]}
                    value={draft.housing}
                    onChange={(v) => update("housing", v)}
                  />
                </Section>
              </div>

              {error && (
                <div
                  style={{
                    padding: "6px 8px",
                    background: "rgba(254,242,242,0.95)",
                    border: "1px solid #fecaca",
                    borderRadius: 3,
                    color: "#991b1b",
                    fontSize: 11,
                  }}
                >
                  {error}
                </div>
              )}
            </div>

            <footer
              style={{
                padding: "12px 16px",
                borderTop: "1px solid rgba(0,0,0,0.08)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 8,
              }}
            >
              <button
                type="button"
                onClick={handleDelete}
                disabled={saving || !hasCohort}
                style={{
                  padding: "6px 10px",
                  background: "transparent",
                  border: "1px solid rgba(0,0,0,0.15)",
                  borderRadius: 3,
                  cursor: saving || !hasCohort ? "default" : "pointer",
                  fontSize: 11,
                  fontFamily: monoFont,
                  color: hasCohort ? "#991b1b" : "#9ca3af",
                }}
              >
                delete cohort
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={!canSave || saving}
                style={{
                  padding: "6px 14px",
                  background: canSave && !saving ? "#1a1f2e" : "#9ca3af",
                  border: "none",
                  borderRadius: 3,
                  cursor: canSave && !saving ? "pointer" : "default",
                  fontSize: 11,
                  fontFamily: monoFont,
                  color: "white",
                }}
              >
                {saving ? "scoring…" : "save"}
              </button>
            </footer>
          </div>
        </div>
      )}
    </>
  );
}
