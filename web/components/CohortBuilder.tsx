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

// SEX codes: 1 = male, 2 = female.
const SEX_FEMALE = 2;
const SEX_MALE = 1;

// BLD (Units in Structure) codes grouped into three culturally
// meaningful buckets. Boat/RV/van (10) is omitted as an edge case.
const BLD_MOBILE = [1];
const BLD_SINGLE_FAMILY = [2, 3];
const BLD_APARTMENT = [4, 5, 6, 7, 8, 9];

// HFL (House Heating Fuel) codes mapped to common fuel pill names.
// 5 (coal/coke), 8 (other), and 9 (no fuel) are omitted.
const HFL_GAS = 1;
const HFL_PROPANE = 2;
const HFL_ELECTRIC = 3;
const HFL_OIL = 4;
const HFL_WOOD = 6;
const HFL_SOLAR = 7;

// CIT (Citizenship Status) codes. 1-3 are all "native"; 4 is
// naturalized; 5 is non-citizen.
const CIT_NATIVE = [1, 2, 3];
const CIT_NATURALIZED = [4];
const CIT_NON_CITIZEN = [5];

// COW (Class of Worker) codes grouped by employment sector. 8 (unpaid
// family) and 9 (unemployed) are omitted as edge cases.
const COW_PRIVATE = [1, 2];
const COW_GOVERNMENT = [3, 4, 5];
const COW_SELF_EMPLOYED = [6, 7];

// JWTRNS (Means of Transportation to Work) codes grouped into five
// culturally meaningful buckets. 7 (ferry), 8 (taxi), 9 (motorcycle),
// and 13 (other) are omitted as low-cardinality edge cases.
const JWTRNS_DROVE_ALONE = [1];
const JWTRNS_CARPOOL = [2];
const JWTRNS_TRANSIT = [3, 4, 5, 6];
const JWTRNS_WALKED_OR_BIKED = [10, 11];
const JWTRNS_WORKED_FROM_HOME = [12];

// VPS (Veteran Period of Service) codes for the era pills. Many of
// the intermediate codes are omitted in favor of the three most
// commonly authored eras.
const VPS_POST_9_11 = [1];
const VPS_GULF = [2];
const VPS_VIETNAM = [4];

// Range bounds for accordion sliders.
const WKHP_MIN = 0;
const WKHP_MAX = 60;
const POVPIP_MIN = 0;
const POVPIP_MAX = 500;
const ENG_MIN = 1;
const ENG_MAX = 4;
const YRBLT_MIN = 1939;
const YRBLT_MAX = 2020;
const BDSP_MIN = 0;
const BDSP_MAX = 6;
const VEH_MIN = 0;
const VEH_MAX = 6;
const FAMILY_INCOME_MIN = 0;
const FAMILY_INCOME_MAX = 500_000;
const FAMILY_INCOME_STEP = 5_000;
const VALP_MIN = 0;
const VALP_MAX = 2_000_000;
const VALP_STEP = 25_000;
const GRPIP_MIN = 0;
const GRPIP_MAX = 100;
const OCPIP_MIN = 0;
const OCPIP_MAX = 100;
const MV_MIN = 1;
const MV_MAX = 7;
const JWMNP_MIN = 0;
const JWMNP_MAX = 90;

type Living = "single" | "family";
// "queer" was previously here, but queer-household is more a family-
// composition trait than an identity per se; it moved into the
// family accordion's "household features" pool as queerHousehold.
type IdentityPill = "married" | "divorced" | "widowed";
type HousingPill = "owns" | "rents";
type SexPill = "female" | "male";
type RacePill =
  | "white"
  | "Black"
  | "Asian"
  | "Latino"
  | "Indigenous"
  | "Pacific Islander";
type HousingTypePill = "mobile home" | "single-family" | "apartment";
type HeatingFuelPill =
  | "gas"
  | "propane"
  | "electric"
  | "oil"
  | "wood"
  | "solar";
type CitizenshipPill = "native" | "naturalized" | "non-citizen";
type DisabilityPill = "physical" | "cognitive" | "sensory" | "independent";
type ClassOfWorkerPill = "private" | "government" | "self-employed";
type CommuteModePill =
  | "drove alone"
  | "carpool"
  | "transit"
  | "walked or biked"
  | "worked from home";
type VeteranEraPill = "post-9/11" | "Gulf" | "Vietnam";

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

  // Accordion: demographics
  race: RacePill[];
  sex: SexPill[];
  citizenship: CitizenshipPill[];
  recentlyMoved: boolean;

  // Accordion: family
  queerHousehold: boolean;
  fertility: boolean;
  multigenerational: boolean;
  seniorsInHome: boolean;
  unmarriedPartner: boolean;
  grandparentCaretaker: boolean;

  // Accordion: language & education
  speaksNonEnglish: boolean;
  englishRange: [number, number];
  limitedEnglishHousehold: boolean;

  // Accordion: money & work
  familyIncomeRange: [number, number];
  hoursRange: [number, number];
  povertyRange: [number, number];
  foodStamps: boolean;
  classOfWorker: ClassOfWorkerPill[];

  // Accordion: disability (subtypes replace single toggle)
  disability: DisabilityPill[];

  // Accordion: health insurance
  hasInsurance: boolean;
  employerInsurance: boolean;
  medicare: boolean;
  medicaid: boolean;
  vaInsurance: boolean;

  // Accordion: housing detail
  housingType: HousingTypePill[];
  yearBuiltRange: [number, number];
  yearMovedRange: [number, number];
  bedroomsRange: [number, number];
  vehiclesRange: [number, number];
  heatingFuel: HeatingFuelPill[];
  propertyValueRange: [number, number];
  rentBurdenRange: [number, number];
  ownerCostBurdenRange: [number, number];

  // Accordion: tech
  broadband: boolean;
  laptop: boolean;
  smartphone: boolean;

  // Accordion: commute
  commuteMode: CommuteModePill[];
  commuteTimeRange: [number, number];

  // Accordion: military
  veteran: boolean;
  veteranEra: VeteranEraPill[];
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
  race: [],
  sex: [],
  citizenship: [],
  recentlyMoved: false,
  queerHousehold: false,
  fertility: false,
  multigenerational: false,
  seniorsInHome: false,
  unmarriedPartner: false,
  grandparentCaretaker: false,
  speaksNonEnglish: false,
  englishRange: [ENG_MIN, ENG_MAX],
  limitedEnglishHousehold: false,
  familyIncomeRange: [FAMILY_INCOME_MIN, FAMILY_INCOME_MAX],
  hoursRange: [WKHP_MIN, WKHP_MAX],
  povertyRange: [POVPIP_MIN, POVPIP_MAX],
  foodStamps: false,
  classOfWorker: [],
  disability: [],
  hasInsurance: false,
  employerInsurance: false,
  medicare: false,
  medicaid: false,
  vaInsurance: false,
  housingType: [],
  yearBuiltRange: [YRBLT_MIN, YRBLT_MAX],
  yearMovedRange: [MV_MIN, MV_MAX],
  bedroomsRange: [BDSP_MIN, BDSP_MAX],
  vehiclesRange: [VEH_MIN, VEH_MAX],
  heatingFuel: [],
  propertyValueRange: [VALP_MIN, VALP_MAX],
  rentBurdenRange: [GRPIP_MIN, GRPIP_MAX],
  ownerCostBurdenRange: [OCPIP_MIN, OCPIP_MAX],
  broadband: false,
  laptop: false,
  smartphone: false,
  commuteMode: [],
  commuteTimeRange: [JWMNP_MIN, JWMNP_MAX],
  veteran: false,
  veteranEra: [],
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
  // Identity pills collapse into a single MAR condition. Queer
  // (same-sex household) used to live here too; it moved into the
  // family accordion's "household features" pool as a separate
  // boolean, since living in a same-sex household is a family-
  // composition trait rather than a marital identity.
  const identitySet = new Set(draft.identity);
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

  // --- Accordion: race & origin -------------------------------------
  // Each selected race pill becomes its own soft condition. Latino is
  // not a race in Census terms; it's HISP >= 2 (any Hispanic origin).
  for (const r of draft.race) {
    if (r === "white") {
      v.push({ field: "RACWHT", op: "eq", value: 1, weight: 1 });
    } else if (r === "Black") {
      v.push({ field: "RACBLK", op: "eq", value: 1, weight: 1 });
    } else if (r === "Asian") {
      v.push({ field: "RACASN", op: "eq", value: 1, weight: 1 });
    } else if (r === "Indigenous") {
      v.push({ field: "RACAIAN", op: "eq", value: 1, weight: 1 });
    } else if (r === "Pacific Islander") {
      v.push({ field: "RACNHPI", op: "eq", value: 1, weight: 1 });
    } else if (r === "Latino") {
      v.push({ field: "HISP", op: "gte", value: 2, weight: 1 });
    }
  }
  // Sex pills. Both selected = "any" = omit.
  if (draft.sex.length === 1) {
    const code = draft.sex[0] === "female" ? SEX_FEMALE : SEX_MALE;
    v.push({ field: "SEX", op: "eq", value: code, weight: 1 });
  }
  // Citizenship pills collapse into one CIT in [...] condition. All
  // three selected = "any" = omit.
  if (draft.citizenship.length > 0 && draft.citizenship.length < 3) {
    const codes: number[] = [];
    if (draft.citizenship.includes("native")) codes.push(...CIT_NATIVE);
    if (draft.citizenship.includes("naturalized"))
      codes.push(...CIT_NATURALIZED);
    if (draft.citizenship.includes("non-citizen"))
      codes.push(...CIT_NON_CITIZEN);
    if (codes.length > 0) {
      v.push({ field: "CIT", op: "in", value: codes, weight: 1 });
    }
  }
  if (draft.recentlyMoved) {
    // MIG = 1 means "same house as 1 year ago" (= didn't move). Anything
    // else means moved. We express "recently moved" as MIG != 1 via
    // gte 2, which covers the moved-from-another-county and
    // moved-from-abroad codes.
    v.push({ field: "MIG", op: "gte", value: 2, weight: 1 });
  }

  // --- Accordion: family (toggles for household composition) --------
  if (draft.queerHousehold) {
    v.push({ field: "SAME_SEX", op: "eq", value: 1, weight: 1 });
  }
  if (draft.fertility) {
    v.push({ field: "FER", op: "eq", value: 1, weight: 1 });
  }
  if (draft.multigenerational) {
    v.push({ field: "MULTG", op: "eq", value: 1, weight: 1 });
  }
  if (draft.seniorsInHome) {
    v.push({ field: "R65", op: "gte", value: 1, weight: 1 });
  }
  if (draft.unmarriedPartner) {
    v.push({ field: "PARTNER", op: "gte", value: 1, weight: 1 });
  }
  if (draft.grandparentCaretaker) {
    v.push({ field: "GCL", op: "eq", value: 1, weight: 1 });
  }

  // --- Accordion: language & education ------------------------------
  if (draft.speaksNonEnglish) {
    v.push({ field: "LANX", op: "eq", value: 1, weight: 1 });
  }
  if (
    draft.englishRange[0] > ENG_MIN ||
    draft.englishRange[1] < ENG_MAX
  ) {
    v.push({
      field: "ENG",
      op: "range",
      value: [draft.englishRange[0], draft.englishRange[1]],
      weight: 1,
    });
  }
  if (draft.limitedEnglishHousehold) {
    v.push({ field: "LNGI", op: "eq", value: 1, weight: 1 });
  }

  // --- Accordion: money & work --------------------------------------
  if (
    draft.familyIncomeRange[0] > FAMILY_INCOME_MIN ||
    draft.familyIncomeRange[1] < FAMILY_INCOME_MAX
  ) {
    v.push({
      field: "FINCP",
      op: "range",
      value: [draft.familyIncomeRange[0], draft.familyIncomeRange[1]],
      weight: 1,
    });
  }
  if (
    draft.hoursRange[0] > WKHP_MIN ||
    draft.hoursRange[1] < WKHP_MAX
  ) {
    v.push({
      field: "WKHP",
      op: "range",
      value: [draft.hoursRange[0], draft.hoursRange[1]],
      weight: 1,
    });
  }
  if (
    draft.povertyRange[0] > POVPIP_MIN ||
    draft.povertyRange[1] < POVPIP_MAX
  ) {
    v.push({
      field: "POVPIP",
      op: "range",
      value: [draft.povertyRange[0], draft.povertyRange[1]],
      weight: 1,
    });
  }
  if (draft.foodStamps) {
    v.push({ field: "FS", op: "eq", value: 1, weight: 1 });
  }
  // Class of worker pills collapse into one COW in [...] condition.
  if (draft.classOfWorker.length > 0 && draft.classOfWorker.length < 3) {
    const codes: number[] = [];
    if (draft.classOfWorker.includes("private"))
      codes.push(...COW_PRIVATE);
    if (draft.classOfWorker.includes("government"))
      codes.push(...COW_GOVERNMENT);
    if (draft.classOfWorker.includes("self-employed"))
      codes.push(...COW_SELF_EMPLOYED);
    if (codes.length > 0) {
      v.push({ field: "COW", op: "in", value: codes, weight: 1 });
    }
  }

  // --- Accordion: disability ----------------------------------------
  // Subtype pills add soft conditions for each selected difficulty
  // type. Sensory expands to both DEAR and DEYE so a person matching
  // either gets a partial score; "independent" expands to DOUT and
  // DDRS for the same reason.
  for (const d of draft.disability) {
    if (d === "physical") {
      v.push({ field: "DPHY", op: "eq", value: 1, weight: 1 });
    } else if (d === "cognitive") {
      v.push({ field: "DREM", op: "eq", value: 1, weight: 1 });
    } else if (d === "sensory") {
      v.push({ field: "DEAR", op: "eq", value: 1, weight: 1 });
      v.push({ field: "DEYE", op: "eq", value: 1, weight: 1 });
    } else if (d === "independent") {
      v.push({ field: "DOUT", op: "eq", value: 1, weight: 1 });
      v.push({ field: "DDRS", op: "eq", value: 1, weight: 1 });
    }
  }

  // --- Accordion: health insurance ----------------------------------
  if (draft.hasInsurance) {
    v.push({ field: "HICOV", op: "eq", value: 1, weight: 1 });
  }
  if (draft.employerInsurance) {
    v.push({ field: "HINS1", op: "eq", value: 1, weight: 1 });
  }
  if (draft.medicare) {
    v.push({ field: "HINS3", op: "eq", value: 1, weight: 1 });
  }
  if (draft.medicaid) {
    v.push({ field: "HINS4", op: "eq", value: 1, weight: 1 });
  }
  if (draft.vaInsurance) {
    v.push({ field: "HINS6", op: "eq", value: 1, weight: 1 });
  }

  // --- Accordion: housing detail ------------------------------------
  // Housing type pills collapse into one BLD in [...] condition.
  if (
    draft.housingType.length > 0 &&
    draft.housingType.length < 3
  ) {
    const codes: number[] = [];
    if (draft.housingType.includes("mobile home")) codes.push(...BLD_MOBILE);
    if (draft.housingType.includes("single-family"))
      codes.push(...BLD_SINGLE_FAMILY);
    if (draft.housingType.includes("apartment"))
      codes.push(...BLD_APARTMENT);
    if (codes.length > 0) {
      v.push({ field: "BLD", op: "in", value: codes, weight: 1 });
    }
  }
  if (
    draft.yearBuiltRange[0] > YRBLT_MIN ||
    draft.yearBuiltRange[1] < YRBLT_MAX
  ) {
    v.push({
      field: "YRBLT",
      op: "range",
      value: [draft.yearBuiltRange[0], draft.yearBuiltRange[1]],
      weight: 1,
    });
  }
  if (
    draft.bedroomsRange[0] > BDSP_MIN ||
    draft.bedroomsRange[1] < BDSP_MAX
  ) {
    v.push({
      field: "BDSP",
      op: "range",
      value: [draft.bedroomsRange[0], draft.bedroomsRange[1]],
      weight: 1,
    });
  }
  if (
    draft.vehiclesRange[0] > VEH_MIN ||
    draft.vehiclesRange[1] < VEH_MAX
  ) {
    v.push({
      field: "VEH",
      op: "range",
      value: [draft.vehiclesRange[0], draft.vehiclesRange[1]],
      weight: 1,
    });
  }
  // Heating fuel pills. Each maps to a single HFL code, collapsed
  // into one HFL in [...] condition.
  if (draft.heatingFuel.length > 0) {
    const codes = draft.heatingFuel.map((f) => {
      switch (f) {
        case "gas":
          return HFL_GAS;
        case "propane":
          return HFL_PROPANE;
        case "electric":
          return HFL_ELECTRIC;
        case "oil":
          return HFL_OIL;
        case "wood":
          return HFL_WOOD;
        case "solar":
          return HFL_SOLAR;
      }
    });
    v.push({ field: "HFL", op: "in", value: codes, weight: 1 });
  }
  if (
    draft.propertyValueRange[0] > VALP_MIN ||
    draft.propertyValueRange[1] < VALP_MAX
  ) {
    v.push({
      field: "VALP",
      op: "range",
      value: [draft.propertyValueRange[0], draft.propertyValueRange[1]],
      weight: 1,
    });
  }
  if (
    draft.yearMovedRange[0] > MV_MIN ||
    draft.yearMovedRange[1] < MV_MAX
  ) {
    v.push({
      field: "MV",
      op: "range",
      value: [draft.yearMovedRange[0], draft.yearMovedRange[1]],
      weight: 1,
    });
  }
  if (
    draft.rentBurdenRange[0] > GRPIP_MIN ||
    draft.rentBurdenRange[1] < GRPIP_MAX
  ) {
    v.push({
      field: "GRPIP",
      op: "range",
      value: [draft.rentBurdenRange[0], draft.rentBurdenRange[1]],
      weight: 1,
    });
  }
  if (
    draft.ownerCostBurdenRange[0] > OCPIP_MIN ||
    draft.ownerCostBurdenRange[1] < OCPIP_MAX
  ) {
    v.push({
      field: "OCPIP",
      op: "range",
      value: [draft.ownerCostBurdenRange[0], draft.ownerCostBurdenRange[1]],
      weight: 1,
    });
  }

  // --- Accordion: tech ----------------------------------------------
  if (draft.broadband) {
    v.push({ field: "BROADBND", op: "eq", value: 1, weight: 1 });
  }
  if (draft.laptop) {
    v.push({ field: "LAPTOP", op: "eq", value: 1, weight: 1 });
  }
  if (draft.smartphone) {
    v.push({ field: "SMARTPHONE", op: "eq", value: 1, weight: 1 });
  }

  // --- Accordion: commute -------------------------------------------
  if (draft.commuteMode.length > 0) {
    const codes: number[] = [];
    for (const mode of draft.commuteMode) {
      switch (mode) {
        case "drove alone":
          codes.push(...JWTRNS_DROVE_ALONE);
          break;
        case "carpool":
          codes.push(...JWTRNS_CARPOOL);
          break;
        case "transit":
          codes.push(...JWTRNS_TRANSIT);
          break;
        case "walked or biked":
          codes.push(...JWTRNS_WALKED_OR_BIKED);
          break;
        case "worked from home":
          codes.push(...JWTRNS_WORKED_FROM_HOME);
          break;
      }
    }
    v.push({ field: "JWTRNS", op: "in", value: codes, weight: 1 });
  }
  if (
    draft.commuteTimeRange[0] > JWMNP_MIN ||
    draft.commuteTimeRange[1] < JWMNP_MAX
  ) {
    v.push({
      field: "JWMNP",
      op: "range",
      value: [draft.commuteTimeRange[0], draft.commuteTimeRange[1]],
      weight: 1,
    });
  }

  // --- Accordion: military service ----------------------------------
  if (draft.veteran) {
    // MIL = 1 (active duty now) or 2 (past active duty) = veteran.
    v.push({ field: "MIL", op: "in", value: [1, 2], weight: 1 });
  }
  if (draft.veteranEra.length > 0) {
    const codes: number[] = [];
    for (const era of draft.veteranEra) {
      if (era === "post-9/11") codes.push(...VPS_POST_9_11);
      else if (era === "Gulf") codes.push(...VPS_GULF);
      else if (era === "Vietnam") codes.push(...VPS_VIETNAM);
    }
    v.push({ field: "VPS", op: "in", value: codes, weight: 1 });
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

  // Accordion marginals — added only when the relevant section has
  // been touched. The API caps at 8 marginals so we slice at the end;
  // quick-control marginals (above) are prioritized by being added
  // first.
  if (draft.race.length > 0) {
    m.push("B02001_001E"); // Race - total
  }
  if (draft.sex.length === 1) {
    m.push("B01001_001E"); // Sex by age - total
  }
  if (draft.citizenship.length > 0) {
    m.push("B05002_001E"); // Place of birth / citizenship - total
  }
  if (
    draft.speaksNonEnglish ||
    draft.englishRange[0] > ENG_MIN ||
    draft.englishRange[1] < ENG_MAX
  ) {
    m.push("C16001_001E"); // Language at home - total (collapsed)
  }
  if (
    draft.povertyRange[0] > POVPIP_MIN ||
    draft.povertyRange[1] < POVPIP_MAX
  ) {
    m.push("B17001_001E"); // Poverty status - total
  }
  if (draft.foodStamps) {
    m.push("B22001_001E"); // SNAP - total
  }
  if (draft.disability.length > 0) {
    m.push("B18101_001E"); // Disability - total
  }
  if (draft.classOfWorker.length > 0) {
    m.push("B24080_001E"); // Class of worker - total
  }
  if (
    draft.familyIncomeRange[0] > FAMILY_INCOME_MIN ||
    draft.familyIncomeRange[1] < FAMILY_INCOME_MAX
  ) {
    m.push("B19101_001E"); // Family income - total
  }
  if (
    draft.propertyValueRange[0] > VALP_MIN ||
    draft.propertyValueRange[1] < VALP_MAX
  ) {
    m.push("B25075_001E"); // Home value - total
  }
  if (
    draft.rentBurdenRange[0] > GRPIP_MIN ||
    draft.rentBurdenRange[1] < GRPIP_MAX
  ) {
    m.push("B25070_001E"); // Gross rent as % of income - total
  }
  if (
    draft.ownerCostBurdenRange[0] > OCPIP_MIN ||
    draft.ownerCostBurdenRange[1] < OCPIP_MAX
  ) {
    m.push("B25101_001E"); // Owner cost as % of income - total
  }
  if (draft.broadband || draft.laptop || draft.smartphone) {
    m.push("B28002_001E"); // Internet subscription - total
  }
  if (
    draft.commuteMode.length > 0 ||
    draft.commuteTimeRange[0] > JWMNP_MIN ||
    draft.commuteTimeRange[1] < JWMNP_MAX
  ) {
    m.push("B08006_001E"); // Means of transportation to work - total
  }
  if (
    draft.hasInsurance ||
    draft.employerInsurance ||
    draft.medicare ||
    draft.medicaid ||
    draft.vaInsurance
  ) {
    m.push("B27001_001E"); // Health insurance coverage - total
  }
  if (
    draft.fertility ||
    draft.multigenerational ||
    draft.seniorsInHome ||
    draft.unmarriedPartner ||
    draft.grandparentCaretaker
  ) {
    // Family / household-composition signal not already covered by
    // earlier B11001 (added by living/identity/family pills).
    if (!m.includes("B11001_001E")) m.push("B11001_001E");
  }
  if (draft.recentlyMoved) {
    m.push("B07003_001E"); // Geographic mobility - total
  }
  if (draft.housingType.length > 0) {
    m.push("B25024_001E"); // Units in structure - total
  }
  if (
    draft.yearBuiltRange[0] > YRBLT_MIN ||
    draft.yearBuiltRange[1] < YRBLT_MAX
  ) {
    m.push("B25034_001E"); // Year built - total
  }
  if (
    draft.vehiclesRange[0] > VEH_MIN ||
    draft.vehiclesRange[1] < VEH_MAX
  ) {
    m.push("B25044_001E"); // Vehicles - total
  }
  if (draft.heatingFuel.length > 0) {
    m.push("B25040_001E"); // Heating fuel - total
  }
  if (draft.veteran) {
    m.push("B21001_001E"); // Veteran status - total
  }

  // If the user activated nothing (shouldn't happen because Save is
  // disabled in that case), fall back to a generic baseline.
  if (m.length === 0) {
    m.push("B01001_001E");
  }
  // Dedupe and cap to API's 8-marginal limit.
  return Array.from(new Set(m)).slice(0, 8);
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

// Collapsible group with a header label. Stays closed by default so
// the modal isn't overwhelming on first open; user clicks the header
// to expand and see the controls inside.
function Accordion({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div
      style={{
        borderTop: "1px solid rgba(0,0,0,0.06)",
        paddingTop: 10,
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%",
          background: "transparent",
          border: "none",
          padding: 0,
          fontSize: 11,
          color: "#1a1f2e",
          fontFamily: monoFont,
          cursor: "pointer",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: open ? 10 : 0,
        }}
      >
        <span>{label}</span>
        <span style={{ color: "#9ca3af", fontSize: 10 }}>
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <div
          style={{ display: "flex", flexDirection: "column", gap: 12 }}
        >
          {children}
        </div>
      )}
    </div>
  );
}

// Binary on/off toggle rendered as a single-pill group. Reuses
// PillGroup so the visual matches every other pill in the modal.
function BinaryToggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <PillGroup<string>
      options={[label]}
      value={value ? [label] : []}
      onChange={(v) => onChange(v.includes(label))}
    />
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

// ENG codes: 1 = very well, 2 = well, 3 = not well, 4 = not at all.
function fmtEngConcept(code: number): string {
  if (code === 1) return "very well";
  if (code === 2) return "well";
  if (code === 3) return "not well";
  return "not at all";
}

// WKHP raw integer hours per week — no need for a concept ladder.
function fmtHours(n: number): string {
  return `${Math.round(n)}h`;
}

// POVPIP is income-to-poverty ratio × 100. 100 = at poverty line,
// 500 = 5× poverty line (well-off). Buckets follow the Census
// Bureau's poverty-status convention.
function fmtPovertyConcept(n: number): string {
  if (n <= 100) return "below poverty";
  if (n <= 200) return "near poverty";
  if (n <= 400) return "above poverty";
  return "well above poverty";
}

function fmtYear(n: number): string {
  return `${Math.round(n)}`;
}

function fmtCount(n: number): string {
  return `${n}`;
}

// VALP property value buckets, CA-relative. Median CA home value is
// ~$700k as of 2023; buckets push the boundaries upward to reflect
// the state's housing market.
function fmtValueConcept(dollars: number): string {
  if (dollars <= 300_000) return "affordable";
  if (dollars <= 600_000) return "modest";
  if (dollars <= 1_000_000) return "expensive";
  if (dollars <= 1_500_000) return "very expensive";
  return "ultra";
}

// GRPIP / OCPIP buckets follow HUD definitions: 0-30% = unburdened,
// 30-50% = burdened, 50%+ = severely burdened.
function fmtBurdenConcept(pct: number): string {
  if (pct < 30) return "unburdened";
  if (pct < 50) return "burdened";
  return "severely burdened";
}

// MV (Year Householder Moved Into Unit) codes 1-7, low = recent.
function fmtMovedConcept(code: number): string {
  if (code === 1) return "just moved";
  if (code === 2) return "<2 years";
  if (code === 3) return "<5 years";
  if (code === 4) return "<10 years";
  if (code === 5) return "<20 years";
  if (code === 6) return "<30 years";
  return "30+ years";
}

function fmtMinutes(n: number): string {
  return `${Math.round(n)}m`;
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
              width: 560,
              maxHeight: "85vh",
              // Flex column with overflow:hidden so the rounded corners
              // clip cleanly; only the middle body scrolls, header and
              // footer stay fixed.
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
              background: "white",
              borderRadius: 12,
              boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
              fontFamily: monoFont,
              fontSize: 11,
              color: "#1a1f2e",
            }}
          >
            <header
              style={{
                flexShrink: 0,
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
                flex: 1,
                overflowY: "auto",
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
                    borderRadius: 4,
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
                    borderRadius: 4,
                    fontSize: 11,
                    fontFamily: monoFont,
                    boxSizing: "border-box",
                  }}
                />
              </div>

              <Accordion label="demographics">
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
                  label="race"
                  isModified={draft.race.length > 0}
                  onReset={() => update("race", [])}
                >
                  <PillGroup<RacePill>
                    options={[
                      "white",
                      "Black",
                      "Asian",
                      "Latino",
                      "Indigenous",
                      "Pacific Islander",
                    ]}
                    value={draft.race}
                    onChange={(v) => update("race", v)}
                  />
                </Section>
                <Section
                  label="sex"
                  isModified={draft.sex.length > 0}
                  onReset={() => update("sex", [])}
                >
                  <PillGroup<SexPill>
                    options={["female", "male"]}
                    value={draft.sex}
                    onChange={(v) => update("sex", v)}
                  />
                </Section>
                <Section
                  label="citizenship"
                  isModified={draft.citizenship.length > 0}
                  onReset={() => update("citizenship", [])}
                >
                  <PillGroup<CitizenshipPill>
                    options={["native", "naturalized", "non-citizen"]}
                    value={draft.citizenship}
                    onChange={(v) => update("citizenship", v)}
                  />
                </Section>
                <Section
                  label="mobility"
                  isModified={draft.recentlyMoved}
                  onReset={() => update("recentlyMoved", false)}
                >
                  <BinaryToggle
                    label="recently moved"
                    value={draft.recentlyMoved}
                    onChange={(v) => update("recentlyMoved", v)}
                  />
                </Section>
              </Accordion>

              <Accordion label="family">
                <Section
                  label="marital status"
                  isModified={draft.identity.length > 0}
                  onReset={() => update("identity", [])}
                >
                  <PillGroup<IdentityPill>
                    options={["married", "divorced", "widowed"]}
                    value={draft.identity}
                    onChange={(v) => update("identity", v)}
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
                  label="household features"
                  isModified={
                    draft.queerHousehold ||
                    draft.fertility ||
                    draft.multigenerational ||
                    draft.seniorsInHome ||
                    draft.unmarriedPartner ||
                    draft.grandparentCaretaker
                  }
                  onReset={() =>
                    setDraft((d) => ({
                      ...d,
                      queerHousehold: false,
                      fertility: false,
                      multigenerational: false,
                      seniorsInHome: false,
                      unmarriedPartner: false,
                      grandparentCaretaker: false,
                    }))
                  }
                >
                  <PillGroup<string>
                    options={[
                      "queer",
                      "new parent",
                      "multigen",
                      "elder in home",
                      "unmarried partner",
                      "raising grandchild",
                    ]}
                    value={[
                      draft.queerHousehold && "queer",
                      draft.fertility && "new parent",
                      draft.multigenerational && "multigen",
                      draft.seniorsInHome && "elder in home",
                      draft.unmarriedPartner && "unmarried partner",
                      draft.grandparentCaretaker && "raising grandchild",
                    ].filter((v): v is string => typeof v === "string")}
                    onChange={(active) =>
                      setDraft((d) => ({
                        ...d,
                        queerHousehold: active.includes("queer"),
                        fertility: active.includes("new parent"),
                        multigenerational: active.includes("multigen"),
                        seniorsInHome: active.includes("elder in home"),
                        unmarriedPartner: active.includes("unmarried partner"),
                        grandparentCaretaker: active.includes(
                          "raising grandchild",
                        ),
                      }))
                    }
                  />
                </Section>
              </Accordion>

              <Accordion label="language & education">
                <Section
                  label="language flags"
                  isModified={
                    draft.speaksNonEnglish || draft.limitedEnglishHousehold
                  }
                  onReset={() =>
                    setDraft((d) => ({
                      ...d,
                      speaksNonEnglish: false,
                      limitedEnglishHousehold: false,
                    }))
                  }
                >
                  <PillGroup<string>
                    options={["non-English home", "limited-English household"]}
                    value={[
                      draft.speaksNonEnglish && "non-English home",
                      draft.limitedEnglishHousehold &&
                        "limited-English household",
                    ].filter((v): v is string => typeof v === "string")}
                    onChange={(active) =>
                      setDraft((d) => ({
                        ...d,
                        speaksNonEnglish: active.includes("non-English home"),
                        limitedEnglishHousehold: active.includes(
                          "limited-English household",
                        ),
                      }))
                    }
                  />
                </Section>
                <Section
                  label="English fluency"
                  isModified={
                    draft.englishRange[0] > ENG_MIN ||
                    draft.englishRange[1] < ENG_MAX
                  }
                  onReset={() => update("englishRange", [ENG_MIN, ENG_MAX])}
                >
                  <RangeSlider
                    min={ENG_MIN}
                    max={ENG_MAX}
                    value={draft.englishRange}
                    onChange={(v) => update("englishRange", v)}
                    format={fmtEngConcept}
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
              </Accordion>

              <Accordion label="money & work">
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
                  label="family income"
                  isModified={
                    draft.familyIncomeRange[0] > FAMILY_INCOME_MIN ||
                    draft.familyIncomeRange[1] < FAMILY_INCOME_MAX
                  }
                  onReset={() =>
                    update("familyIncomeRange", [
                      FAMILY_INCOME_MIN,
                      FAMILY_INCOME_MAX,
                    ])
                  }
                >
                  <RangeSlider
                    min={FAMILY_INCOME_MIN}
                    max={FAMILY_INCOME_MAX}
                    step={FAMILY_INCOME_STEP}
                    value={draft.familyIncomeRange}
                    onChange={(v) => update("familyIncomeRange", v)}
                    format={fmtIncomeConcept}
                  />
                </Section>
                <Section
                  label="hours per week"
                  isModified={
                    draft.hoursRange[0] > WKHP_MIN ||
                    draft.hoursRange[1] < WKHP_MAX
                  }
                  onReset={() => update("hoursRange", [WKHP_MIN, WKHP_MAX])}
                >
                  <RangeSlider
                    min={WKHP_MIN}
                    max={WKHP_MAX}
                    value={draft.hoursRange}
                    onChange={(v) => update("hoursRange", v)}
                    format={fmtHours}
                  />
                </Section>
                <Section
                  label="poverty status"
                  isModified={
                    draft.povertyRange[0] > POVPIP_MIN ||
                    draft.povertyRange[1] < POVPIP_MAX
                  }
                  onReset={() =>
                    update("povertyRange", [POVPIP_MIN, POVPIP_MAX])
                  }
                >
                  <RangeSlider
                    min={POVPIP_MIN}
                    max={POVPIP_MAX}
                    value={draft.povertyRange}
                    onChange={(v) => update("povertyRange", v)}
                    format={fmtPovertyConcept}
                  />
                </Section>
                <Section
                  label="food stamps"
                  isModified={draft.foodStamps}
                  onReset={() => update("foodStamps", false)}
                >
                  <BinaryToggle
                    label="receives SNAP"
                    value={draft.foodStamps}
                    onChange={(v) => update("foodStamps", v)}
                  />
                </Section>
                <Section
                  label="class of worker"
                  isModified={draft.classOfWorker.length > 0}
                  onReset={() => update("classOfWorker", [])}
                >
                  <PillGroup<ClassOfWorkerPill>
                    options={["private", "government", "self-employed"]}
                    value={draft.classOfWorker}
                    onChange={(v) => update("classOfWorker", v)}
                  />
                </Section>
              </Accordion>

              <Accordion label="disability">
                <Section
                  label="disability type"
                  isModified={draft.disability.length > 0}
                  onReset={() => update("disability", [])}
                >
                  <PillGroup<DisabilityPill>
                    options={[
                      "physical",
                      "cognitive",
                      "sensory",
                      "independent",
                    ]}
                    value={draft.disability}
                    onChange={(v) => update("disability", v)}
                  />
                </Section>
              </Accordion>

              <Accordion label="health insurance">
                <Section
                  label="coverage"
                  isModified={
                    draft.hasInsurance ||
                    draft.employerInsurance ||
                    draft.medicare ||
                    draft.medicaid ||
                    draft.vaInsurance
                  }
                  onReset={() =>
                    setDraft((d) => ({
                      ...d,
                      hasInsurance: false,
                      employerInsurance: false,
                      medicare: false,
                      medicaid: false,
                      vaInsurance: false,
                    }))
                  }
                >
                  <PillGroup<string>
                    options={[
                      "insured",
                      "employer",
                      "Medicare",
                      "Medi-Cal",
                      "VA",
                    ]}
                    value={[
                      draft.hasInsurance && "insured",
                      draft.employerInsurance && "employer",
                      draft.medicare && "Medicare",
                      draft.medicaid && "Medi-Cal",
                      draft.vaInsurance && "VA",
                    ].filter((v): v is string => typeof v === "string")}
                    onChange={(active) =>
                      setDraft((d) => ({
                        ...d,
                        hasInsurance: active.includes("insured"),
                        employerInsurance: active.includes("employer"),
                        medicare: active.includes("Medicare"),
                        medicaid: active.includes("Medi-Cal"),
                        vaInsurance: active.includes("VA"),
                      }))
                    }
                  />
                </Section>
              </Accordion>

              <Accordion label="housing">
                <Section
                  label="tenure"
                  isModified={draft.housing.length > 0}
                  onReset={() => update("housing", [])}
                >
                  <PillGroup<HousingPill>
                    options={["owns", "rents"]}
                    value={draft.housing}
                    onChange={(v) => update("housing", v)}
                  />
                </Section>
                <Section
                  label="housing type"
                  isModified={draft.housingType.length > 0}
                  onReset={() => update("housingType", [])}
                >
                  <PillGroup<HousingTypePill>
                    options={["mobile home", "single-family", "apartment"]}
                    value={draft.housingType}
                    onChange={(v) => update("housingType", v)}
                  />
                </Section>
                <Section
                  label="year built"
                  isModified={
                    draft.yearBuiltRange[0] > YRBLT_MIN ||
                    draft.yearBuiltRange[1] < YRBLT_MAX
                  }
                  onReset={() =>
                    update("yearBuiltRange", [YRBLT_MIN, YRBLT_MAX])
                  }
                >
                  <RangeSlider
                    min={YRBLT_MIN}
                    max={YRBLT_MAX}
                    value={draft.yearBuiltRange}
                    onChange={(v) => update("yearBuiltRange", v)}
                    format={fmtYear}
                  />
                </Section>
                <Section
                  label="bedrooms"
                  isModified={
                    draft.bedroomsRange[0] > BDSP_MIN ||
                    draft.bedroomsRange[1] < BDSP_MAX
                  }
                  onReset={() =>
                    update("bedroomsRange", [BDSP_MIN, BDSP_MAX])
                  }
                >
                  <RangeSlider
                    min={BDSP_MIN}
                    max={BDSP_MAX}
                    value={draft.bedroomsRange}
                    onChange={(v) => update("bedroomsRange", v)}
                    format={fmtCount}
                  />
                </Section>
                <Section
                  label="vehicles"
                  isModified={
                    draft.vehiclesRange[0] > VEH_MIN ||
                    draft.vehiclesRange[1] < VEH_MAX
                  }
                  onReset={() =>
                    update("vehiclesRange", [VEH_MIN, VEH_MAX])
                  }
                >
                  <RangeSlider
                    min={VEH_MIN}
                    max={VEH_MAX}
                    value={draft.vehiclesRange}
                    onChange={(v) => update("vehiclesRange", v)}
                    format={fmtCount}
                  />
                </Section>
                <Section
                  label="heating fuel"
                  isModified={draft.heatingFuel.length > 0}
                  onReset={() => update("heatingFuel", [])}
                >
                  <PillGroup<HeatingFuelPill>
                    options={[
                      "gas",
                      "electric",
                      "propane",
                      "wood",
                      "oil",
                      "solar",
                    ]}
                    value={draft.heatingFuel}
                    onChange={(v) => update("heatingFuel", v)}
                  />
                </Section>
                <Section
                  label="home value"
                  isModified={
                    draft.propertyValueRange[0] > VALP_MIN ||
                    draft.propertyValueRange[1] < VALP_MAX
                  }
                  onReset={() =>
                    update("propertyValueRange", [VALP_MIN, VALP_MAX])
                  }
                >
                  <RangeSlider
                    min={VALP_MIN}
                    max={VALP_MAX}
                    step={VALP_STEP}
                    value={draft.propertyValueRange}
                    onChange={(v) => update("propertyValueRange", v)}
                    format={fmtValueConcept}
                  />
                </Section>
                <Section
                  label="year moved in"
                  isModified={
                    draft.yearMovedRange[0] > MV_MIN ||
                    draft.yearMovedRange[1] < MV_MAX
                  }
                  onReset={() => update("yearMovedRange", [MV_MIN, MV_MAX])}
                >
                  <RangeSlider
                    min={MV_MIN}
                    max={MV_MAX}
                    value={draft.yearMovedRange}
                    onChange={(v) => update("yearMovedRange", v)}
                    format={fmtMovedConcept}
                  />
                </Section>
                <Section
                  label="rent burden"
                  isModified={
                    draft.rentBurdenRange[0] > GRPIP_MIN ||
                    draft.rentBurdenRange[1] < GRPIP_MAX
                  }
                  onReset={() =>
                    update("rentBurdenRange", [GRPIP_MIN, GRPIP_MAX])
                  }
                >
                  <RangeSlider
                    min={GRPIP_MIN}
                    max={GRPIP_MAX}
                    value={draft.rentBurdenRange}
                    onChange={(v) => update("rentBurdenRange", v)}
                    format={fmtBurdenConcept}
                  />
                </Section>
                <Section
                  label="owner cost burden"
                  isModified={
                    draft.ownerCostBurdenRange[0] > OCPIP_MIN ||
                    draft.ownerCostBurdenRange[1] < OCPIP_MAX
                  }
                  onReset={() =>
                    update("ownerCostBurdenRange", [OCPIP_MIN, OCPIP_MAX])
                  }
                >
                  <RangeSlider
                    min={OCPIP_MIN}
                    max={OCPIP_MAX}
                    value={draft.ownerCostBurdenRange}
                    onChange={(v) => update("ownerCostBurdenRange", v)}
                    format={fmtBurdenConcept}
                  />
                </Section>
              </Accordion>

              <Accordion label="tech">
                <Section
                  label="household tech"
                  isModified={
                    draft.broadband || draft.laptop || draft.smartphone
                  }
                  onReset={() =>
                    setDraft((d) => ({
                      ...d,
                      broadband: false,
                      laptop: false,
                      smartphone: false,
                    }))
                  }
                >
                  <PillGroup<string>
                    options={["broadband", "laptop", "smartphone"]}
                    value={[
                      draft.broadband && "broadband",
                      draft.laptop && "laptop",
                      draft.smartphone && "smartphone",
                    ].filter((v): v is string => typeof v === "string")}
                    onChange={(active) =>
                      setDraft((d) => ({
                        ...d,
                        broadband: active.includes("broadband"),
                        laptop: active.includes("laptop"),
                        smartphone: active.includes("smartphone"),
                      }))
                    }
                  />
                </Section>
              </Accordion>

              <Accordion label="commute">
                <Section
                  label="commute mode"
                  isModified={draft.commuteMode.length > 0}
                  onReset={() => update("commuteMode", [])}
                >
                  <PillGroup<CommuteModePill>
                    options={[
                      "drove alone",
                      "carpool",
                      "transit",
                      "walked or biked",
                      "worked from home",
                    ]}
                    value={draft.commuteMode}
                    onChange={(v) => update("commuteMode", v)}
                  />
                </Section>
                <Section
                  label="commute time"
                  isModified={
                    draft.commuteTimeRange[0] > JWMNP_MIN ||
                    draft.commuteTimeRange[1] < JWMNP_MAX
                  }
                  onReset={() =>
                    update("commuteTimeRange", [JWMNP_MIN, JWMNP_MAX])
                  }
                >
                  <RangeSlider
                    min={JWMNP_MIN}
                    max={JWMNP_MAX}
                    value={draft.commuteTimeRange}
                    onChange={(v) => update("commuteTimeRange", v)}
                    format={fmtMinutes}
                  />
                </Section>
              </Accordion>

              <Accordion label="military service">
                <Section
                  label="veteran"
                  isModified={draft.veteran}
                  onReset={() => update("veteran", false)}
                >
                  <BinaryToggle
                    label="is veteran"
                    value={draft.veteran}
                    onChange={(v) => update("veteran", v)}
                  />
                </Section>
                <Section
                  label="era of service"
                  isModified={draft.veteranEra.length > 0}
                  onReset={() => update("veteranEra", [])}
                >
                  <PillGroup<VeteranEraPill>
                    options={["post-9/11", "Gulf", "Vietnam"]}
                    value={draft.veteranEra}
                    onChange={(v) => update("veteranEra", v)}
                  />
                </Section>
              </Accordion>

              {error && (
                <div
                  style={{
                    padding: "6px 8px",
                    background: "rgba(254,242,242,0.95)",
                    border: "1px solid #fecaca",
                    borderRadius: 4,
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
                flexShrink: 0,
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
                  borderRadius: 4,
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
                  borderRadius: 4,
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
