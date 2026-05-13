"use client";

// CohortBuilder
//
// Modal form for authoring a single user-defined cohort and rendering
// it on the map. UX shape:
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

import { createContext, useContext, useEffect, useState } from "react";
import type { Cohort } from "@/lib/types";
import { COHORT_API_BASE } from "@/lib/constants";

// Importance tier per active control row. "required" makes every
// emitted condition a hard gate (required: true); the other three map
// to weights 0.5 / 1 / 2 on the soft-similarity score. See
// METHODOLOGY.md "Scoring" for how weights compose with the threshold.
type Tier = "required" | "low" | "med" | "high";
const DEFAULT_TIER: Tier = "med";

function tierToVectorProps(tier: Tier | undefined): { weight: number; required?: boolean } {
  const t = tier ?? DEFAULT_TIER;
  if (t === "required") return { weight: 1, required: true };
  if (t === "low") return { weight: 0.5 };
  if (t === "high") return { weight: 2 };
  return { weight: 1 };
}

// React context so each Section can read its own tier without forcing
// every Section call site to thread tier props explicitly.
const TiersContext = createContext<{
  tiers: Record<string, Tier>;
  setTier: (key: string, tier: Tier) => void;
}>({ tiers: {}, setTier: () => {} });

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

// Pill labels for the pooled-boolean sections. Each label maps to one
// or more underlying PUMS conditions; the buildVector mapping lives in
// the section's loop. Keeping them as enumerated string literal
// unions gives us exhaustiveness checks if a new option is added.
type HouseholdFeaturesPill =
  | "queer"
  | "new parent"
  | "multigen"
  | "elder in home"
  | "unmarried partner"
  | "raising grandchild";
type LanguageFlagsPill = "non-English home" | "limited-English household";
type HouseholdTechPill = "broadband" | "laptop" | "smartphone";
type InsuranceCoveragePill =
  | "insured"
  | "employer"
  | "Medicare"
  | "Medi-Cal"
  | "VA";

// A single rule on a multi-rule field. Each rule carries its own
// value (here a [lo, hi] age range) and its own tier. The frontend
// enforces at most one required rule per field by demoting any
// previously-required rule to "med" when a new one is set to
// "required". See METHODOLOGY notes on the gate vs weight math.
interface RangeRule {
  range: [number, number];
  tier: Tier;
}

interface DraftState {
  title: string;
  vibe: string;
  // Multi-rule list. Empty list = "any age". Each entry contributes
  // one AGEP range condition to the cohort vector with its own tier.
  ageRules: RangeRule[];
  incomeRules: RangeRule[];
  // Education is a range over SCHL codes (1-24). Lets the user express
  // "high school only" or "some college through bachelor's" without
  // being limited to gte. Labels are bucketed concepts not raw codes
  // (see fmtSchlConcept).
  educationRules: RangeRule[];
  kidsRules: RangeRule[];
  livingRules: PillRule<Living>[];
  // Mixed-field pill group. `queer` maps to SAME_SEX = 1. The other
  // three collapse into one MAR in [...] condition at vector-build
  // time so multi-select reads as "married OR divorced OR widowed."
  identityRules: PillRule<IdentityPill>[];
  // TEN tenure pills. Multi-select; collapse into one TEN in [...]
  // condition. Both selected is equivalent to "any tenure" so the
  // condition is omitted.
  housingRules: PillRule<HousingPill>[];

  // Accordion: demographics
  raceRules: PillRule<RacePill>[];
  sexRules: PillRule<SexPill>[];
  citizenshipRules: PillRule<CitizenshipPill>[];
  recentlyMoved: boolean;

  // Accordion: family — pooled household-composition pills, each
  // mapping to a separate boolean PUMS condition. Multi-rule: each
  // rule is one pill selection set + one tier.
  householdFeaturesRules: PillRule<HouseholdFeaturesPill>[];

  // Accordion: language & education
  languageFlagsRules: PillRule<LanguageFlagsPill>[];
  englishRules: RangeRule[];

  // Accordion: money & work
  familyIncomeRules: RangeRule[];
  hoursRules: RangeRule[];
  povertyRules: RangeRule[];
  foodStamps: boolean;
  classOfWorkerRules: PillRule<ClassOfWorkerPill>[];

  // Accordion: disability (subtypes replace single toggle)
  disabilityRules: PillRule<DisabilityPill>[];

  // Accordion: health insurance — pooled coverage pills.
  insuranceCoverageRules: PillRule<InsuranceCoveragePill>[];

  // Accordion: housing detail
  housingTypeRules: PillRule<HousingTypePill>[];
  yearBuiltRules: RangeRule[];
  yearMovedRules: RangeRule[];
  bedroomsRules: RangeRule[];
  vehiclesRules: RangeRule[];
  heatingFuelRules: PillRule<HeatingFuelPill>[];
  propertyValueRules: RangeRule[];
  rentBurdenRules: RangeRule[];
  ownerCostBurdenRules: RangeRule[];

  // Accordion: tech — pooled tech-access pills.
  householdTechRules: PillRule<HouseholdTechPill>[];

  // Accordion: commute
  commuteModeRules: PillRule<CommuteModePill>[];
  commuteTimeRules: RangeRule[];

  // Accordion: military
  veteran: boolean;
  veteranEraRules: PillRule<VeteranEraPill>[];

  // Per-section importance tier. Keyed by Section controlKey
  // (snake_case label). Missing entries default to "med" (weight 1).
  // At least one entry must be "required" before save is enabled, so
  // the API's "at least one required gate" contract is honored.
  tiers: Record<string, Tier>;
}

const DEFAULT_DRAFT: DraftState = {
  title: "",
  vibe: "",
  ageRules: [],
  incomeRules: [],
  educationRules: [],
  kidsRules: [],
  livingRules: [],
  identityRules: [],
  housingRules: [],
  raceRules: [],
  sexRules: [],
  citizenshipRules: [],
  recentlyMoved: false,
  householdFeaturesRules: [],
  languageFlagsRules: [],
  englishRules: [],
  familyIncomeRules: [],
  hoursRules: [],
  povertyRules: [],
  foodStamps: false,
  classOfWorkerRules: [],
  disabilityRules: [],
  insuranceCoverageRules: [],
  housingTypeRules: [],
  yearBuiltRules: [],
  yearMovedRules: [],
  bedroomsRules: [],
  vehiclesRules: [],
  heatingFuelRules: [],
  propertyValueRules: [],
  rentBurdenRules: [],
  ownerCostBurdenRules: [],
  householdTechRules: [],
  commuteModeRules: [],
  commuteTimeRules: [],
  veteran: false,
  veteranEraRules: [],
  tiers: {},
};

const STORAGE_KEY = "cohort_draft_v1";

function readDraft(): DraftState {
  if (typeof window === "undefined") return DEFAULT_DRAFT;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_DRAFT;
    const parsed = JSON.parse(raw);

    // Migrate legacy single-rule age (`ageRange: [lo, hi]` + tier in
    // `tiers.age`) to the multi-rule list (`ageRules: [{range, tier}]`).
    // A draft at the full default range collapses to an empty list
    // since "any age" is no condition.
    if ("ageRange" in parsed && !("ageRules" in parsed)) {
      const [lo, hi] = parsed.ageRange ?? [AGE_MIN, AGE_MAX];
      if (lo > AGE_MIN || hi < AGE_MAX) {
        const legacyTier: Tier = parsed.tiers?.age ?? DEFAULT_TIER;
        parsed.ageRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.ageRules = [];
      }
      delete parsed.ageRange;
    }
    if ("incomeRange" in parsed && !("incomeRules" in parsed)) {
      const [lo, hi] = parsed.incomeRange ?? [INCOME_MIN, INCOME_MAX];
      if (lo > INCOME_MIN || hi < INCOME_MAX) {
        const legacyTier: Tier = parsed.tiers?.income_household ?? DEFAULT_TIER;
        parsed.incomeRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.incomeRules = [];
      }
      delete parsed.incomeRange;
    }
    if ("educationRange" in parsed && !("educationRules" in parsed)) {
      const [lo, hi] = parsed.educationRange ?? [SCHL_MIN, SCHL_MAX];
      if (lo > SCHL_MIN || hi < SCHL_MAX) {
        const legacyTier: Tier = parsed.tiers?.education ?? DEFAULT_TIER;
        parsed.educationRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.educationRules = [];
      }
      delete parsed.educationRange;
    }
    if ("kidsRange" in parsed && !("kidsRules" in parsed)) {
      const [lo, hi] = parsed.kidsRange ?? [KIDS_MIN, KIDS_MAX];
      if (lo > KIDS_MIN || hi < KIDS_MAX) {
        const legacyTier: Tier = parsed.tiers?.children ?? DEFAULT_TIER;
        parsed.kidsRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.kidsRules = [];
      }
      delete parsed.kidsRange;
    }
    if ("familyIncomeRange" in parsed && !("familyIncomeRules" in parsed)) {
      const [lo, hi] = parsed.familyIncomeRange ?? [FAMILY_INCOME_MIN, FAMILY_INCOME_MAX];
      if (lo > FAMILY_INCOME_MIN || hi < FAMILY_INCOME_MAX) {
        const legacyTier: Tier = parsed.tiers?.family_income ?? DEFAULT_TIER;
        parsed.familyIncomeRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.familyIncomeRules = [];
      }
      delete parsed.familyIncomeRange;
    }
    if ("hoursRange" in parsed && !("hoursRules" in parsed)) {
      const [lo, hi] = parsed.hoursRange ?? [WKHP_MIN, WKHP_MAX];
      if (lo > WKHP_MIN || hi < WKHP_MAX) {
        const legacyTier: Tier = parsed.tiers?.hours_per_week ?? DEFAULT_TIER;
        parsed.hoursRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.hoursRules = [];
      }
      delete parsed.hoursRange;
    }
    if ("povertyRange" in parsed && !("povertyRules" in parsed)) {
      const [lo, hi] = parsed.povertyRange ?? [POVPIP_MIN, POVPIP_MAX];
      if (lo > POVPIP_MIN || hi < POVPIP_MAX) {
        const legacyTier: Tier = parsed.tiers?.poverty_status ?? DEFAULT_TIER;
        parsed.povertyRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.povertyRules = [];
      }
      delete parsed.povertyRange;
    }
    if ("englishRange" in parsed && !("englishRules" in parsed)) {
      const [lo, hi] = parsed.englishRange ?? [ENG_MIN, ENG_MAX];
      if (lo > ENG_MIN || hi < ENG_MAX) {
        const legacyTier: Tier = parsed.tiers?.english_fluency ?? DEFAULT_TIER;
        parsed.englishRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.englishRules = [];
      }
      delete parsed.englishRange;
    }
    if ("yearBuiltRange" in parsed && !("yearBuiltRules" in parsed)) {
      const [lo, hi] = parsed.yearBuiltRange ?? [YRBLT_MIN, YRBLT_MAX];
      if (lo > YRBLT_MIN || hi < YRBLT_MAX) {
        const legacyTier: Tier = parsed.tiers?.year_built ?? DEFAULT_TIER;
        parsed.yearBuiltRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.yearBuiltRules = [];
      }
      delete parsed.yearBuiltRange;
    }
    if ("yearMovedRange" in parsed && !("yearMovedRules" in parsed)) {
      const [lo, hi] = parsed.yearMovedRange ?? [MV_MIN, MV_MAX];
      if (lo > MV_MIN || hi < MV_MAX) {
        const legacyTier: Tier = parsed.tiers?.year_moved_in ?? DEFAULT_TIER;
        parsed.yearMovedRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.yearMovedRules = [];
      }
      delete parsed.yearMovedRange;
    }
    if ("bedroomsRange" in parsed && !("bedroomsRules" in parsed)) {
      const [lo, hi] = parsed.bedroomsRange ?? [BDSP_MIN, BDSP_MAX];
      if (lo > BDSP_MIN || hi < BDSP_MAX) {
        const legacyTier: Tier = parsed.tiers?.bedrooms ?? DEFAULT_TIER;
        parsed.bedroomsRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.bedroomsRules = [];
      }
      delete parsed.bedroomsRange;
    }
    if ("vehiclesRange" in parsed && !("vehiclesRules" in parsed)) {
      const [lo, hi] = parsed.vehiclesRange ?? [VEH_MIN, VEH_MAX];
      if (lo > VEH_MIN || hi < VEH_MAX) {
        const legacyTier: Tier = parsed.tiers?.vehicles ?? DEFAULT_TIER;
        parsed.vehiclesRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.vehiclesRules = [];
      }
      delete parsed.vehiclesRange;
    }
    if ("propertyValueRange" in parsed && !("propertyValueRules" in parsed)) {
      const [lo, hi] = parsed.propertyValueRange ?? [VALP_MIN, VALP_MAX];
      if (lo > VALP_MIN || hi < VALP_MAX) {
        const legacyTier: Tier = parsed.tiers?.home_value ?? DEFAULT_TIER;
        parsed.propertyValueRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.propertyValueRules = [];
      }
      delete parsed.propertyValueRange;
    }
    if ("rentBurdenRange" in parsed && !("rentBurdenRules" in parsed)) {
      const [lo, hi] = parsed.rentBurdenRange ?? [GRPIP_MIN, GRPIP_MAX];
      if (lo > GRPIP_MIN || hi < GRPIP_MAX) {
        const legacyTier: Tier = parsed.tiers?.rent_burden ?? DEFAULT_TIER;
        parsed.rentBurdenRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.rentBurdenRules = [];
      }
      delete parsed.rentBurdenRange;
    }
    if ("ownerCostBurdenRange" in parsed && !("ownerCostBurdenRules" in parsed)) {
      const [lo, hi] = parsed.ownerCostBurdenRange ?? [OCPIP_MIN, OCPIP_MAX];
      if (lo > OCPIP_MIN || hi < OCPIP_MAX) {
        const legacyTier: Tier = parsed.tiers?.owner_cost_burden ?? DEFAULT_TIER;
        parsed.ownerCostBurdenRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.ownerCostBurdenRules = [];
      }
      delete parsed.ownerCostBurdenRange;
    }
    if ("commuteTimeRange" in parsed && !("commuteTimeRules" in parsed)) {
      const [lo, hi] = parsed.commuteTimeRange ?? [JWMNP_MIN, JWMNP_MAX];
      if (lo > JWMNP_MIN || hi < JWMNP_MAX) {
        const legacyTier: Tier = parsed.tiers?.commute_time ?? DEFAULT_TIER;
        parsed.commuteTimeRules = [{ range: [lo, hi], tier: legacyTier }];
      } else {
        parsed.commuteTimeRules = [];
      }
      delete parsed.commuteTimeRange;
    }
    if ("race" in parsed && !("raceRules" in parsed)) {
      const arr = parsed.race;
      if (Array.isArray(arr) && arr.length > 0) {
        const legacyTier: Tier = parsed.tiers?.race ?? DEFAULT_TIER;
        parsed.raceRules = [{ pills: arr, tier: legacyTier }];
      } else {
        parsed.raceRules = [];
      }
      delete parsed.race;
    }
    if ("sex" in parsed && !("sexRules" in parsed)) {
      const arr = parsed.sex;
      if (Array.isArray(arr) && arr.length > 0) {
        const legacyTier: Tier = parsed.tiers?.sex ?? DEFAULT_TIER;
        parsed.sexRules = [{ pills: arr, tier: legacyTier }];
      } else {
        parsed.sexRules = [];
      }
      delete parsed.sex;
    }
    if ("citizenship" in parsed && !("citizenshipRules" in parsed)) {
      const arr = parsed.citizenship;
      if (Array.isArray(arr) && arr.length > 0) {
        const legacyTier: Tier = parsed.tiers?.citizenship ?? DEFAULT_TIER;
        parsed.citizenshipRules = [{ pills: arr, tier: legacyTier }];
      } else {
        parsed.citizenshipRules = [];
      }
      delete parsed.citizenship;
    }
    if ("identity" in parsed && !("identityRules" in parsed)) {
      const arr = parsed.identity;
      if (Array.isArray(arr) && arr.length > 0) {
        const legacyTier: Tier = parsed.tiers?.marital_status ?? DEFAULT_TIER;
        parsed.identityRules = [{ pills: arr, tier: legacyTier }];
      } else {
        parsed.identityRules = [];
      }
      delete parsed.identity;
    }
    if ("living" in parsed && !("livingRules" in parsed)) {
      const arr = parsed.living;
      if (Array.isArray(arr) && arr.length > 0) {
        const legacyTier: Tier = parsed.tiers?.living_arrangement ?? DEFAULT_TIER;
        parsed.livingRules = [{ pills: arr, tier: legacyTier }];
      } else {
        parsed.livingRules = [];
      }
      delete parsed.living;
    }
    if ("housing" in parsed && !("housingRules" in parsed)) {
      const arr = parsed.housing;
      if (Array.isArray(arr) && arr.length > 0) {
        const legacyTier: Tier = parsed.tiers?.tenure ?? DEFAULT_TIER;
        parsed.housingRules = [{ pills: arr, tier: legacyTier }];
      } else {
        parsed.housingRules = [];
      }
      delete parsed.housing;
    }
    if ("housingType" in parsed && !("housingTypeRules" in parsed)) {
      const arr = parsed.housingType;
      if (Array.isArray(arr) && arr.length > 0) {
        const legacyTier: Tier = parsed.tiers?.housing_type ?? DEFAULT_TIER;
        parsed.housingTypeRules = [{ pills: arr, tier: legacyTier }];
      } else {
        parsed.housingTypeRules = [];
      }
      delete parsed.housingType;
    }
    if ("heatingFuel" in parsed && !("heatingFuelRules" in parsed)) {
      const arr = parsed.heatingFuel;
      if (Array.isArray(arr) && arr.length > 0) {
        const legacyTier: Tier = parsed.tiers?.heating_fuel ?? DEFAULT_TIER;
        parsed.heatingFuelRules = [{ pills: arr, tier: legacyTier }];
      } else {
        parsed.heatingFuelRules = [];
      }
      delete parsed.heatingFuel;
    }
    if ("classOfWorker" in parsed && !("classOfWorkerRules" in parsed)) {
      const arr = parsed.classOfWorker;
      if (Array.isArray(arr) && arr.length > 0) {
        const legacyTier: Tier = parsed.tiers?.class_of_worker ?? DEFAULT_TIER;
        parsed.classOfWorkerRules = [{ pills: arr, tier: legacyTier }];
      } else {
        parsed.classOfWorkerRules = [];
      }
      delete parsed.classOfWorker;
    }
    if ("disability" in parsed && !("disabilityRules" in parsed)) {
      const arr = parsed.disability;
      if (Array.isArray(arr) && arr.length > 0) {
        const legacyTier: Tier = parsed.tiers?.disability_type ?? DEFAULT_TIER;
        parsed.disabilityRules = [{ pills: arr, tier: legacyTier }];
      } else {
        parsed.disabilityRules = [];
      }
      delete parsed.disability;
    }
    if ("commuteMode" in parsed && !("commuteModeRules" in parsed)) {
      const arr = parsed.commuteMode;
      if (Array.isArray(arr) && arr.length > 0) {
        const legacyTier: Tier = parsed.tiers?.commute_mode ?? DEFAULT_TIER;
        parsed.commuteModeRules = [{ pills: arr, tier: legacyTier }];
      } else {
        parsed.commuteModeRules = [];
      }
      delete parsed.commuteMode;
    }
    if ("veteranEra" in parsed && !("veteranEraRules" in parsed)) {
      const arr = parsed.veteranEra;
      if (Array.isArray(arr) && arr.length > 0) {
        const legacyTier: Tier = parsed.tiers?.era_of_service ?? DEFAULT_TIER;
        parsed.veteranEraRules = [{ pills: arr, tier: legacyTier }];
      } else {
        parsed.veteranEraRules = [];
      }
      delete parsed.veteranEra;
    }

    // Migrate pooled-boolean sections: each section's underlying
    // booleans collapse into a single PillRule with the pills the user
    // had toggled on. Legacy tiers come from `tiers[sectionKey]`.
    if (!("householdFeaturesRules" in parsed)) {
      const legacyTier: Tier = parsed.tiers?.household_features ?? DEFAULT_TIER;
      const pills: HouseholdFeaturesPill[] = [];
      if (parsed.queerHousehold) pills.push("queer");
      if (parsed.fertility) pills.push("new parent");
      if (parsed.multigenerational) pills.push("multigen");
      if (parsed.seniorsInHome) pills.push("elder in home");
      if (parsed.unmarriedPartner) pills.push("unmarried partner");
      if (parsed.grandparentCaretaker) pills.push("raising grandchild");
      parsed.householdFeaturesRules =
        pills.length > 0 ? [{ pills, tier: legacyTier }] : [];
      delete parsed.queerHousehold;
      delete parsed.fertility;
      delete parsed.multigenerational;
      delete parsed.seniorsInHome;
      delete parsed.unmarriedPartner;
      delete parsed.grandparentCaretaker;
    }
    if (!("languageFlagsRules" in parsed)) {
      const legacyTier: Tier = parsed.tiers?.language_flags ?? DEFAULT_TIER;
      const pills: LanguageFlagsPill[] = [];
      if (parsed.speaksNonEnglish) pills.push("non-English home");
      if (parsed.limitedEnglishHousehold) pills.push("limited-English household");
      parsed.languageFlagsRules =
        pills.length > 0 ? [{ pills, tier: legacyTier }] : [];
      delete parsed.speaksNonEnglish;
      delete parsed.limitedEnglishHousehold;
    }
    if (!("householdTechRules" in parsed)) {
      const legacyTier: Tier = parsed.tiers?.household_tech ?? DEFAULT_TIER;
      const pills: HouseholdTechPill[] = [];
      if (parsed.broadband) pills.push("broadband");
      if (parsed.laptop) pills.push("laptop");
      if (parsed.smartphone) pills.push("smartphone");
      parsed.householdTechRules =
        pills.length > 0 ? [{ pills, tier: legacyTier }] : [];
      delete parsed.broadband;
      delete parsed.laptop;
      delete parsed.smartphone;
    }
    if (!("insuranceCoverageRules" in parsed)) {
      const legacyTier: Tier = parsed.tiers?.insurance_coverage ?? DEFAULT_TIER;
      const pills: InsuranceCoveragePill[] = [];
      if (parsed.hasInsurance) pills.push("insured");
      if (parsed.employerInsurance) pills.push("employer");
      if (parsed.medicare) pills.push("Medicare");
      if (parsed.medicaid) pills.push("Medi-Cal");
      if (parsed.vaInsurance) pills.push("VA");
      parsed.insuranceCoverageRules =
        pills.length > 0 ? [{ pills, tier: legacyTier }] : [];
      delete parsed.hasInsurance;
      delete parsed.employerInsurance;
      delete parsed.medicare;
      delete parsed.medicaid;
      delete parsed.vaInsurance;
    }

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

// Apply the tier for the given section key to a partial vector entry.
// Every condition emitted by a section gets the same tier, so a user
// who marks "race" as required has each selected race pill emit a hard
// gate. See METHODOLOGY.md "Scoring" for the gate vs weight math.
function withTier(
  draft: DraftState,
  key: string,
  entry: Omit<VectorEntry, "weight" | "required">,
): VectorEntry {
  return { ...entry, ...tierToVectorProps(draft.tiers[key]) };
}

function buildVector(draft: DraftState): VectorEntry[] {
  const v: VectorEntry[] = [];
  // Multi-rule: emit one AGEP range entry per rule, each with its own
  // tier. Rules at the full default span are skipped (a "doesn't
  // matter" rule should not be in the list, but skipping is defensive).
  for (const rule of draft.ageRules) {
    const [aLo, aHi] = rule.range;
    if (aLo > AGE_MIN || aHi < AGE_MAX) {
      v.push({
        field: "AGEP",
        op: "range",
        value: [aLo, aHi],
        ...tierToVectorProps(rule.tier),
      });
    }
  }
  for (const rule of draft.incomeRules) {
    const [lo, hi] = rule.range;
    if (lo > INCOME_MIN || hi < INCOME_MAX) {
      v.push({ field: "HINCP", op: "range", value: [lo, hi], ...tierToVectorProps(rule.tier) });
    }
  }
  for (const rule of draft.educationRules) {
    const [lo, hi] = rule.range;
    if (lo > SCHL_MIN || hi < SCHL_MAX) {
      v.push({ field: "SCHL", op: "range", value: [lo, hi], ...tierToVectorProps(rule.tier) });
    }
  }
  for (const rule of draft.kidsRules) {
    const [lo, hi] = rule.range;
    if (lo > KIDS_MIN || hi < KIDS_MAX) {
      v.push({ field: "NOP", op: "range", value: [lo, hi], ...tierToVectorProps(rule.tier) });
    }
  }
  for (const rule of draft.livingRules) {
    if (rule.pills.length > 0 && rule.pills.length < 2) {
      const codes = rule.pills[0] === "family" ? HHT_FAMILY : HHT_SINGLE;
      v.push({ field: "HHT", op: "in", value: codes, ...tierToVectorProps(rule.tier) });
    }
  }
  // Identity pills collapse into a single MAR condition. Queer
  // (same-sex household) used to live here too; it moved into the
  // family accordion's "household features" pool as a separate
  // boolean, since living in a same-sex household is a family-
  // composition trait rather than a marital identity.
  for (const rule of draft.identityRules) {
    const identitySet = new Set(rule.pills);
    const marCodes: number[] = [];
    if (identitySet.has("married")) marCodes.push(MAR_MARRIED);
    if (identitySet.has("widowed")) marCodes.push(MAR_WIDOWED);
    if (identitySet.has("divorced")) marCodes.push(MAR_DIVORCED);
    if (marCodes.length > 0) {
      v.push({ field: "MAR", op: "in", value: marCodes, ...tierToVectorProps(rule.tier) });
    }
  }
  // Housing tenure pills. Both selected = "any tenure" = omit.
  for (const rule of draft.housingRules) {
    if (rule.pills.length > 0 && rule.pills.length < 2) {
      const codes = rule.pills[0] === "owns" ? TEN_OWN : TEN_RENT;
      v.push({ field: "TEN", op: "in", value: codes, ...tierToVectorProps(rule.tier) });
    }
  }

  // --- Accordion: race & origin -------------------------------------
  // Each selected race pill becomes its own soft condition. Latino is
  // not a race in Census terms; it's HISP >= 2 (any Hispanic origin).
  for (const rule of draft.raceRules) {
    const tprops = tierToVectorProps(rule.tier);
    for (const r of rule.pills) {
      if (r === "white") v.push({ field: "RACWHT", op: "eq", value: 1, ...tprops });
      else if (r === "Black") v.push({ field: "RACBLK", op: "eq", value: 1, ...tprops });
      else if (r === "Asian") v.push({ field: "RACASN", op: "eq", value: 1, ...tprops });
      else if (r === "Indigenous") v.push({ field: "RACAIAN", op: "eq", value: 1, ...tprops });
      else if (r === "Pacific Islander") v.push({ field: "RACNHPI", op: "eq", value: 1, ...tprops });
      else if (r === "Latino") v.push({ field: "HISP", op: "gte", value: 2, ...tprops });
    }
  }
  // Sex pills. Both selected = "any" = omit.
  for (const rule of draft.sexRules) {
    if (rule.pills.length === 1) {
      const code = rule.pills[0] === "female" ? SEX_FEMALE : SEX_MALE;
      v.push({ field: "SEX", op: "eq", value: code, ...tierToVectorProps(rule.tier) });
    }
  }
  // Citizenship pills collapse into one CIT in [...] condition. All
  // three selected = "any" = omit.
  for (const rule of draft.citizenshipRules) {
    if (rule.pills.length > 0 && rule.pills.length < 3) {
      const codes: number[] = [];
      if (rule.pills.includes("native")) codes.push(...CIT_NATIVE);
      if (rule.pills.includes("naturalized")) codes.push(...CIT_NATURALIZED);
      if (rule.pills.includes("non-citizen")) codes.push(...CIT_NON_CITIZEN);
      if (codes.length > 0) {
        v.push({ field: "CIT", op: "in", value: codes, ...tierToVectorProps(rule.tier) });
      }
    }
  }
  if (draft.recentlyMoved) {
    // MIG = 1 means "same house as 1 year ago" (= didn't move). Anything
    // else means moved. We express "recently moved" as MIG != 1 via
    // gte 2, which covers the moved-from-another-county and
    // moved-from-abroad codes.
    v.push(withTier(draft, "mobility", { field: "MIG", op: "gte", value: 2 }));
  }

  // --- Accordion: family (pooled household-composition pills) -------
  for (const rule of draft.householdFeaturesRules) {
    const tprops = tierToVectorProps(rule.tier);
    for (const p of rule.pills) {
      if (p === "queer") v.push({ field: "SAME_SEX", op: "eq", value: 1, ...tprops });
      else if (p === "new parent") v.push({ field: "FER", op: "eq", value: 1, ...tprops });
      else if (p === "multigen") v.push({ field: "MULTG", op: "eq", value: 1, ...tprops });
      else if (p === "elder in home") v.push({ field: "R65", op: "gte", value: 1, ...tprops });
      else if (p === "unmarried partner") v.push({ field: "PARTNER", op: "gte", value: 1, ...tprops });
      else if (p === "raising grandchild") v.push({ field: "GCL", op: "eq", value: 1, ...tprops });
    }
  }

  // --- Accordion: language & education ------------------------------
  for (const rule of draft.languageFlagsRules) {
    const tprops = tierToVectorProps(rule.tier);
    for (const p of rule.pills) {
      if (p === "non-English home") v.push({ field: "LANX", op: "eq", value: 1, ...tprops });
      else if (p === "limited-English household") v.push({ field: "LNGI", op: "eq", value: 1, ...tprops });
    }
  }
  for (const rule of draft.englishRules) {
    const [lo, hi] = rule.range;
    if (lo > ENG_MIN || hi < ENG_MAX) {
      v.push({
        field: "ENG",
        op: "range",
        value: [lo, hi],
        ...tierToVectorProps(rule.tier),
      });
    }
  }

  // --- Accordion: money & work --------------------------------------
  for (const rule of draft.familyIncomeRules) {
    const [lo, hi] = rule.range;
    if (lo > FAMILY_INCOME_MIN || hi < FAMILY_INCOME_MAX) {
      v.push({
        field: "FINCP",
        op: "range",
        value: [lo, hi],
        ...tierToVectorProps(rule.tier),
      });
    }
  }
  for (const rule of draft.hoursRules) {
    const [lo, hi] = rule.range;
    if (lo > WKHP_MIN || hi < WKHP_MAX) {
      v.push({
        field: "WKHP",
        op: "range",
        value: [lo, hi],
        ...tierToVectorProps(rule.tier),
      });
    }
  }
  for (const rule of draft.povertyRules) {
    const [lo, hi] = rule.range;
    if (lo > POVPIP_MIN || hi < POVPIP_MAX) {
      v.push({
        field: "POVPIP",
        op: "range",
        value: [lo, hi],
        ...tierToVectorProps(rule.tier),
      });
    }
  }
  if (draft.foodStamps) {
    v.push(withTier(draft, "food_stamps", { field: "FS", op: "eq", value: 1 }));
  }
  // Class of worker pills collapse into one COW in [...] condition.
  for (const rule of draft.classOfWorkerRules) {
    if (rule.pills.length > 0 && rule.pills.length < 3) {
      const codes: number[] = [];
      if (rule.pills.includes("private")) codes.push(...COW_PRIVATE);
      if (rule.pills.includes("government")) codes.push(...COW_GOVERNMENT);
      if (rule.pills.includes("self-employed")) codes.push(...COW_SELF_EMPLOYED);
      if (codes.length > 0) {
        v.push({ field: "COW", op: "in", value: codes, ...tierToVectorProps(rule.tier) });
      }
    }
  }

  // --- Accordion: disability ----------------------------------------
  // Subtype pills add soft conditions for each selected difficulty
  // type. Sensory expands to both DEAR and DEYE so a person matching
  // either gets a partial score; "independent" expands to DOUT and
  // DDRS for the same reason.
  for (const rule of draft.disabilityRules) {
    const tprops = tierToVectorProps(rule.tier);
    for (const d of rule.pills) {
      if (d === "physical") v.push({ field: "DPHY", op: "eq", value: 1, ...tprops });
      else if (d === "cognitive") v.push({ field: "DREM", op: "eq", value: 1, ...tprops });
      else if (d === "sensory") {
        v.push({ field: "DEAR", op: "eq", value: 1, ...tprops });
        v.push({ field: "DEYE", op: "eq", value: 1, ...tprops });
      } else if (d === "independent") {
        v.push({ field: "DOUT", op: "eq", value: 1, ...tprops });
        v.push({ field: "DDRS", op: "eq", value: 1, ...tprops });
      }
    }
  }

  // --- Accordion: health insurance ----------------------------------
  for (const rule of draft.insuranceCoverageRules) {
    const tprops = tierToVectorProps(rule.tier);
    for (const p of rule.pills) {
      if (p === "insured") v.push({ field: "HICOV", op: "eq", value: 1, ...tprops });
      else if (p === "employer") v.push({ field: "HINS1", op: "eq", value: 1, ...tprops });
      else if (p === "Medicare") v.push({ field: "HINS3", op: "eq", value: 1, ...tprops });
      else if (p === "Medi-Cal") v.push({ field: "HINS4", op: "eq", value: 1, ...tprops });
      else if (p === "VA") v.push({ field: "HINS6", op: "eq", value: 1, ...tprops });
    }
  }

  // --- Accordion: housing detail ------------------------------------
  // Housing type pills collapse into one BLD in [...] condition.
  for (const rule of draft.housingTypeRules) {
    if (rule.pills.length > 0 && rule.pills.length < 3) {
      const codes: number[] = [];
      if (rule.pills.includes("mobile home")) codes.push(...BLD_MOBILE);
      if (rule.pills.includes("single-family")) codes.push(...BLD_SINGLE_FAMILY);
      if (rule.pills.includes("apartment")) codes.push(...BLD_APARTMENT);
      if (codes.length > 0) {
        v.push({ field: "BLD", op: "in", value: codes, ...tierToVectorProps(rule.tier) });
      }
    }
  }
  for (const rule of draft.yearBuiltRules) {
    const [lo, hi] = rule.range;
    if (lo > YRBLT_MIN || hi < YRBLT_MAX) {
      v.push({
        field: "YRBLT",
        op: "range",
        value: [lo, hi],
        ...tierToVectorProps(rule.tier),
      });
    }
  }
  for (const rule of draft.bedroomsRules) {
    const [lo, hi] = rule.range;
    if (lo > BDSP_MIN || hi < BDSP_MAX) {
      v.push({
        field: "BDSP",
        op: "range",
        value: [lo, hi],
        ...tierToVectorProps(rule.tier),
      });
    }
  }
  for (const rule of draft.vehiclesRules) {
    const [lo, hi] = rule.range;
    if (lo > VEH_MIN || hi < VEH_MAX) {
      v.push({
        field: "VEH",
        op: "range",
        value: [lo, hi],
        ...tierToVectorProps(rule.tier),
      });
    }
  }
  // Heating fuel pills. Each maps to a single HFL code, collapsed
  // into one HFL in [...] condition.
  for (const rule of draft.heatingFuelRules) {
    if (rule.pills.length > 0) {
      const codes = rule.pills.map((f) => {
        switch (f) {
          case "gas": return HFL_GAS;
          case "propane": return HFL_PROPANE;
          case "electric": return HFL_ELECTRIC;
          case "oil": return HFL_OIL;
          case "wood": return HFL_WOOD;
          case "solar": return HFL_SOLAR;
        }
      });
      v.push({ field: "HFL", op: "in", value: codes, ...tierToVectorProps(rule.tier) });
    }
  }
  for (const rule of draft.propertyValueRules) {
    const [lo, hi] = rule.range;
    if (lo > VALP_MIN || hi < VALP_MAX) {
      v.push({
        field: "VALP",
        op: "range",
        value: [lo, hi],
        ...tierToVectorProps(rule.tier),
      });
    }
  }
  for (const rule of draft.yearMovedRules) {
    const [lo, hi] = rule.range;
    if (lo > MV_MIN || hi < MV_MAX) {
      v.push({
        field: "MV",
        op: "range",
        value: [lo, hi],
        ...tierToVectorProps(rule.tier),
      });
    }
  }
  for (const rule of draft.rentBurdenRules) {
    const [lo, hi] = rule.range;
    if (lo > GRPIP_MIN || hi < GRPIP_MAX) {
      v.push({
        field: "GRPIP",
        op: "range",
        value: [lo, hi],
        ...tierToVectorProps(rule.tier),
      });
    }
  }
  for (const rule of draft.ownerCostBurdenRules) {
    const [lo, hi] = rule.range;
    if (lo > OCPIP_MIN || hi < OCPIP_MAX) {
      v.push({
        field: "OCPIP",
        op: "range",
        value: [lo, hi],
        ...tierToVectorProps(rule.tier),
      });
    }
  }

  // --- Accordion: tech ----------------------------------------------
  for (const rule of draft.householdTechRules) {
    const tprops = tierToVectorProps(rule.tier);
    for (const p of rule.pills) {
      if (p === "broadband") v.push({ field: "BROADBND", op: "eq", value: 1, ...tprops });
      else if (p === "laptop") v.push({ field: "LAPTOP", op: "eq", value: 1, ...tprops });
      else if (p === "smartphone") v.push({ field: "SMARTPHONE", op: "eq", value: 1, ...tprops });
    }
  }

  // --- Accordion: commute -------------------------------------------
  for (const rule of draft.commuteModeRules) {
    if (rule.pills.length > 0) {
      const codes: number[] = [];
      for (const mode of rule.pills) {
        switch (mode) {
          case "drove alone": codes.push(...JWTRNS_DROVE_ALONE); break;
          case "carpool": codes.push(...JWTRNS_CARPOOL); break;
          case "transit": codes.push(...JWTRNS_TRANSIT); break;
          case "walked or biked": codes.push(...JWTRNS_WALKED_OR_BIKED); break;
          case "worked from home": codes.push(...JWTRNS_WORKED_FROM_HOME); break;
        }
      }
      v.push({ field: "JWTRNS", op: "in", value: codes, ...tierToVectorProps(rule.tier) });
    }
  }
  for (const rule of draft.commuteTimeRules) {
    const [lo, hi] = rule.range;
    if (lo > JWMNP_MIN || hi < JWMNP_MAX) {
      v.push({
        field: "JWMNP",
        op: "range",
        value: [lo, hi],
        ...tierToVectorProps(rule.tier),
      });
    }
  }

  // --- Accordion: military service ----------------------------------
  if (draft.veteran) {
    // MIL = 1 (active duty now) or 2 (past active duty) = veteran.
    v.push(withTier(draft, "veteran", { field: "MIL", op: "in", value: [1, 2] }));
  }
  for (const rule of draft.veteranEraRules) {
    if (rule.pills.length > 0) {
      const codes: number[] = [];
      for (const era of rule.pills) {
        if (era === "post-9/11") codes.push(...VPS_POST_9_11);
        else if (era === "Gulf") codes.push(...VPS_GULF);
        else if (era === "Vietnam") codes.push(...VPS_VIETNAM);
      }
      v.push({ field: "VPS", op: "in", value: codes, ...tierToVectorProps(rule.tier) });
    }
  }

  // Each cohort needs at least one identity gate. The check is enforced
  // in the save flow (canSave below). No auto-promotion here: a missing
  // required tier should surface as user-facing friction, not be hidden
  // by silently turning the first soft signal into a gate.
  return v;
}

// Marginal tables to pull, picked based on which quick controls are
// active. The /score endpoint accepts up to 8; the five quick controls
// generate at most five, well inside the cap.
function buildMarginals(draft: DraftState): string[] {
  const m: string[] = [];
  // Age uses Sex by Age (population pyramid). One of the densest,
  // most reliably published ACS tables; safe default. Any active rule
  // (regardless of range) opts the marginal in.
  if (draft.ageRules.length > 0) {
    m.push("B01001_002E"); // Total male population
  }
  if (draft.incomeRules.length > 0) {
    m.push("B19001_001E"); // Households with income reported
  }
  if (draft.educationRules.length > 0) {
    m.push("B15003_022E"); // Bachelor's degree count
  }
  if (draft.kidsRules.length > 0) {
    m.push("B11003_001E"); // Family households by presence of children
  }
  if (draft.livingRules.length > 0) {
    m.push("B11001_001E"); // Households by type
  }
  if (draft.identityRules.length > 0 && !m.includes("B11001_001E")) {
    // Identity-gated cohorts benefit from a household-type density
    // signal; add the same marginal we use for living arrangement if
    // not already included.
    m.push("B11001_001E");
  }
  if (draft.housingRules.length > 0) {
    m.push("B25003_001E"); // Total occupied housing units
  }

  // Accordion marginals — added only when the relevant section has
  // been touched. The API caps at 8 marginals so we slice at the end;
  // quick-control marginals (above) are prioritized by being added
  // first.
  if (draft.raceRules.length > 0) {
    m.push("B02001_001E"); // Race - total
  }
  if (draft.sexRules.length > 0) {
    m.push("B01001_001E"); // Sex by age - total
  }
  if (draft.citizenshipRules.length > 0) {
    m.push("B05002_001E"); // Place of birth / citizenship - total
  }
  if (
    draft.languageFlagsRules.length > 0 ||
    draft.englishRules.length > 0
  ) {
    m.push("C16001_001E"); // Language at home - total (collapsed)
  }
  if (
    draft.povertyRules.length > 0
  ) {
    m.push("B17001_001E"); // Poverty status - total
  }
  if (draft.foodStamps) {
    m.push("B22001_001E"); // SNAP - total
  }
  if (draft.disabilityRules.length > 0) {
    m.push("B18101_001E"); // Disability - total
  }
  if (draft.classOfWorkerRules.length > 0) {
    m.push("B24080_001E"); // Class of worker - total
  }
  if (
    draft.familyIncomeRules.length > 0
  ) {
    m.push("B19101_001E"); // Family income - total
  }
  if (
    draft.propertyValueRules.length > 0
  ) {
    m.push("B25075_001E"); // Home value - total
  }
  if (
    draft.rentBurdenRules.length > 0
  ) {
    m.push("B25070_001E"); // Gross rent as % of income - total
  }
  if (
    draft.ownerCostBurdenRules.length > 0
  ) {
    m.push("B25101_001E"); // Owner cost as % of income - total
  }
  if (draft.householdTechRules.length > 0) {
    m.push("B28002_001E"); // Internet subscription - total
  }
  if (
    draft.commuteModeRules.length > 0 ||
    draft.commuteTimeRules.length > 0
  ) {
    m.push("B08006_001E"); // Means of transportation to work - total
  }
  if (draft.insuranceCoverageRules.length > 0) {
    m.push("B27001_001E"); // Health insurance coverage - total
  }
  if (draft.householdFeaturesRules.length > 0) {
    // Family / household-composition signal not already covered by
    // earlier B11001 (added by living/identity/family pills).
    if (!m.includes("B11001_001E")) m.push("B11001_001E");
  }
  if (draft.recentlyMoved) {
    m.push("B07003_001E"); // Geographic mobility - total
  }
  if (draft.housingTypeRules.length > 0) {
    m.push("B25024_001E"); // Units in structure - total
  }
  if (
    draft.yearBuiltRules.length > 0
  ) {
    m.push("B25034_001E"); // Year built - total
  }
  if (
    draft.vehiclesRules.length > 0
  ) {
    m.push("B25044_001E"); // Vehicles - total
  }
  if (draft.heatingFuelRules.length > 0) {
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
          style={{ display: "flex", flexDirection: "column", gap: 22 }}
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

// Section wrapper: single-column layout. The header row carries the
// label on the left and the "any" reset on the right. When the
// section is modified, a compact horizontal ImportancePicker appears
// inline between them so tier-setting lives on the same line as the
// section identity and the reset. The picker is per-section, set
// independently for every Section call site via controlKey.
function Section({
  label,
  controlKey,
  isModified,
  onReset,
  children,
}: {
  label: string;
  controlKey: string;
  isModified: boolean;
  onReset: () => void;
  children: React.ReactNode;
}) {
  const { tiers, setTier } = useContext(TiersContext);
  const tier = tiers[controlKey];
  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 4,
        }}
      >
        <span
          style={{
            fontSize: 11,
            color: "#6a7283",
            fontFamily: monoFont,
            flexShrink: 0,
          }}
        >
          {label}
        </span>
        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexShrink: 0,
          }}
        >
          <ImportancePicker
            value={tier ?? DEFAULT_TIER}
            onChange={(t) => setTier(controlKey, t)}
            disabled={!isModified}
          />
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
              flexShrink: 0,
            }}
          >
            clear
          </button>
        </div>
      </div>
      {children}
    </div>
  );
}

// Compact horizontal four-tier picker. Always rendered in the
// Section header but visually muted when the section is unmodified so
// it teaches the model without dominating the row. Labels collapse to
// numeric weights (½× / 1× / 2×) plus a "▣" for the required hard
// gate; hover tooltips surface the verbal meaning for users who want
// it. "required" stays visually distinct because it runs a logical
// filter under the hood, not a weight multiplier.
function ImportancePicker({
  value,
  onChange,
  disabled,
}: {
  value: Tier;
  onChange: (t: Tier) => void;
  disabled: boolean;
}) {
  const options: { tier: Tier; label: string; title: string }[] = [
    { tier: "low", label: "½×", title: "a little important (weight ×0.5)" },
    { tier: "med", label: "1×", title: "important (weight ×1)" },
    { tier: "high", label: "2×", title: "very important (weight ×2)" },
    { tier: "required", label: "🔒", title: "required (hard gate)" },
  ];
  return (
    <div
      style={{
        display: "inline-flex",
        flexShrink: 0,
        flexWrap: "nowrap",
        gap: 2,
        opacity: disabled ? 0.3 : 1,
        transition: "opacity 120ms",
        verticalAlign: "middle",
      }}
    >
      {options.map((opt) => {
        const active = !disabled && opt.tier === value;
        const isRequired = opt.tier === "required";
        return (
          <button
            key={opt.tier}
            type="button"
            onClick={() => !disabled && onChange(opt.tier)}
            disabled={disabled}
            title={opt.title}
            style={{
              width: 32,
              height: 22,
              padding: 0,
              boxSizing: "border-box",
              flexShrink: 0,
              borderRadius: 6,
              border: active
                ? "1px solid #1a1f2e"
                : "1px solid rgba(0,0,0,0.12)",
              background: active
                ? isRequired
                  ? "#1a1f2e"
                  : "#5468d8"
                : "transparent",
              color: active ? "white" : "#6a7283",
              fontSize: 10,
              fontFamily: monoFont,
              cursor: disabled ? "default" : "pointer",
              lineHeight: 1,
              textAlign: "center",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

// Multi-rule wrapper for range-slider fields. Renders the section
// header (label on the left, "clear" reset on the right), one row per
// active rule (range slider + per-rule importance picker + per-rule
// remove button), and an "+ add another" affordance.
//
// At-most-one-required enforcement: when a rule's tier is set to
// "required", any sibling rule that was already "required" is demoted
// to "med". This keeps the per-field constraint (multiple required
// entries on the same field would intersect rather than union) without
// blocking the user mid-interaction.
function MultiRangeSection({
  label,
  rules,
  onChange,
  min,
  max,
  step,
  format,
  defaultRange,
  addLabel,
}: {
  label: string;
  rules: RangeRule[];
  onChange: (rules: RangeRule[]) => void;
  min: number;
  max: number;
  step?: number;
  format: (n: number) => string;
  defaultRange: [number, number];
  addLabel: string;
}) {
  const isModified = rules.length > 0;
  const setRuleTier = (idx: number, tier: Tier) => {
    onChange(
      rules.map((r, i) => {
        if (i === idx) return { ...r, tier };
        if (tier === "required" && r.tier === "required") {
          return { ...r, tier: DEFAULT_TIER };
        }
        return r;
      }),
    );
  };
  const setRuleRange = (idx: number, range: [number, number]) => {
    onChange(rules.map((r, i) => (i === idx ? { ...r, range } : r)));
  };
  const removeRule = (idx: number) =>
    onChange(rules.filter((_, i) => i !== idx));
  const addRule = () =>
    onChange([...rules, { range: defaultRange, tier: DEFAULT_TIER }]);
  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 4,
        }}
      >
        <span
          style={{
            fontSize: 11,
            color: "#6a7283",
            fontFamily: monoFont,
            flexShrink: 0,
          }}
        >
          {label}
        </span>
        <button
          type="button"
          onClick={() => onChange([])}
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
            marginLeft: "auto",
            flexShrink: 0,
          }}
        >
          clear
        </button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <RangeSlider
              min={min}
              max={max}
              step={step}
              value={rules[0]?.range ?? defaultRange}
              onChange={(v) => {
                if (rules.length === 0) {
                  onChange([{ range: v, tier: DEFAULT_TIER }]);
                } else {
                  setRuleRange(0, v);
                }
              }}
              format={format}
            />
          </div>
          {isModified && (
            <>
              <ImportancePicker
                value={rules[0].tier}
                onChange={(t) => setRuleTier(0, t)}
                disabled={false}
              />
              {rules.length > 1 && (
                <button
                  type="button"
                  onClick={() => removeRule(0)}
                  aria-label="remove rule"
                  style={{
                    background: "transparent",
                    border: "none",
                    cursor: "pointer",
                    fontSize: 14,
                    color: "#9ca3af",
                    padding: "0 4px",
                    lineHeight: 1,
                    flexShrink: 0,
                  }}
                >
                  ×
                </button>
              )}
            </>
          )}
        </div>
        {rules.slice(1).map((rule, i) => {
          const idx = i + 1;
          return (
            <div
              key={idx}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <RangeSlider
                  min={min}
                  max={max}
                  step={step}
                  value={rule.range}
                  onChange={(v) => setRuleRange(idx, v)}
                  format={format}
                />
              </div>
              <ImportancePicker
                value={rule.tier}
                onChange={(t) => setRuleTier(idx, t)}
                disabled={false}
              />
              <button
                type="button"
                onClick={() => removeRule(idx)}
                aria-label="remove rule"
                style={{
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  fontSize: 14,
                  color: "#9ca3af",
                  padding: "0 4px",
                  lineHeight: 1,
                  flexShrink: 0,
                }}
              >
                ×
              </button>
            </div>
          );
        })}
        {isModified && (
          <button
            type="button"
            onClick={addRule}
            style={{
              background: "transparent",
              border: "1px dashed rgba(0,0,0,0.18)",
              borderRadius: 6,
              padding: "4px 10px",
              cursor: "pointer",
              fontSize: 11,
              color: "#6a7283",
              fontFamily: monoFont,
              alignSelf: "flex-start",
            }}
          >
            {addLabel}
          </button>
        )}
      </div>
    </div>
  );
}

// Generic pill-rule shape, used by every pill-based MultiPillSection
// in the builder. Same idea as RangeRule but with a list of selected
// pill names instead of a numeric range.
interface PillRule<T extends string> {
  pills: T[];
  tier: Tier;
}

// Multi-rule wrapper for pill-group fields. First pill group is always
// visible; clicking a pill on the empty state creates rule 0. Each
// rule renders as a pill group with its own importance picker on the
// row below, right-aligned. "+ add another" spawns a fresh empty pill
// group beneath. Mirrors the MultiRangeSection visual rhythm so the
// builder stays internally consistent.
//
// At-most-one-required: setting any rule's tier to "required" demotes
// any sibling rule that was already required to "med", same constraint
// as for ranges.
function MultiPillSection<T extends string>({
  label,
  options,
  rules,
  onChange,
  addLabel,
}: {
  label: string;
  options: T[];
  rules: PillRule<T>[];
  onChange: (r: PillRule<T>[]) => void;
  addLabel: string;
}) {
  const isModified = rules.length > 0;
  const firstHasPills =
    rules.length > 0 && rules[0].pills.length > 0;
  const setRuleTier = (idx: number, tier: Tier) => {
    onChange(
      rules.map((r, i) => {
        if (i === idx) return { ...r, tier };
        if (tier === "required" && r.tier === "required") {
          return { ...r, tier: DEFAULT_TIER };
        }
        return r;
      }),
    );
  };
  const setRulePills = (idx: number, pills: T[]) => {
    onChange(rules.map((r, i) => (i === idx ? { ...r, pills } : r)));
  };
  const removeRule = (idx: number) =>
    onChange(rules.filter((_, i) => i !== idx));
  const addRule = () =>
    onChange([...rules, { pills: [], tier: DEFAULT_TIER }]);

  // First-row pill change handler: creates rule 0 on first selection,
  // collapses back to no rules if user deselects everything in the only
  // rule. Beyond that, defers to setRulePills.
  const handleFirstChange = (newPills: T[]) => {
    if (rules.length === 0) {
      if (newPills.length === 0) return;
      onChange([{ pills: newPills, tier: DEFAULT_TIER }]);
      return;
    }
    if (rules.length === 1 && newPills.length === 0) {
      onChange([]);
      return;
    }
    setRulePills(0, newPills);
  };

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 4,
        }}
      >
        <span
          style={{
            fontSize: 11,
            color: "#6a7283",
            fontFamily: monoFont,
            flexShrink: 0,
          }}
        >
          {label}
        </span>
        <button
          type="button"
          onClick={() => onChange([])}
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
            marginLeft: "auto",
            flexShrink: 0,
          }}
        >
          clear
        </button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 10,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <PillGroup<T>
              options={options}
              value={rules[0]?.pills ?? []}
              onChange={handleFirstChange}
            />
          </div>
          {firstHasPills && (
            <>
              <ImportancePicker
                value={rules[0].tier}
                onChange={(t) => setRuleTier(0, t)}
                disabled={false}
              />
              {rules.length > 1 && (
                <button
                  type="button"
                  onClick={() => removeRule(0)}
                  aria-label="remove rule"
                  style={{
                    background: "transparent",
                    border: "none",
                    cursor: "pointer",
                    fontSize: 14,
                    color: "#9ca3af",
                    padding: "0 4px",
                    lineHeight: 1,
                    flexShrink: 0,
                  }}
                >
                  ×
                </button>
              )}
            </>
          )}
        </div>
        {rules.slice(1).map((rule, i) => {
          const idx = i + 1;
          return (
            <div
              key={idx}
              style={{
                display: "flex",
                alignItems: "center",
                flexWrap: "wrap",
                gap: 10,
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <PillGroup<T>
                  options={options}
                  value={rule.pills}
                  onChange={(v) => setRulePills(idx, v)}
                />
              </div>
              <ImportancePicker
                value={rule.tier}
                onChange={(t) => setRuleTier(idx, t)}
                disabled={false}
              />
              <button
                type="button"
                onClick={() => removeRule(idx)}
                aria-label="remove rule"
                style={{
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  fontSize: 14,
                  color: "#9ca3af",
                  padding: "0 4px",
                  lineHeight: 1,
                  flexShrink: 0,
                }}
              >
                ×
              </button>
            </div>
          );
        })}
        {firstHasPills && (
          <button
            type="button"
            onClick={addRule}
            style={{
              background: "transparent",
              border: "1px dashed rgba(0,0,0,0.18)",
              borderRadius: 6,
              padding: "4px 10px",
              cursor: "pointer",
              fontSize: 11,
              color: "#6a7283",
              fontFamily: monoFont,
              alignSelf: "flex-start",
            }}
          >
            {addLabel}
          </button>
        )}
      </div>
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

  const setTier = (key: string, tier: Tier) =>
    setDraft((d) => ({ ...d, tiers: { ...d.tiers, [key]: tier } }));

  const vector = buildVector(draft);
  // No required-gate constraint: cohorts can be pure soft-signal
  // scoring. Membership is then determined entirely by whether the
  // weighted fit score clears the cohort threshold τ.
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
          <TiersContext.Provider value={{ tiers: draft.tiers, setTier }}>
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 600,
              maxWidth: "94vw",
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
                <MultiRangeSection
                  label="age"
                  rules={draft.ageRules}
                  onChange={(r) => update("ageRules", r)}
                  min={AGE_MIN}
                  max={AGE_MAX}
                  format={fmtAge}
                  defaultRange={[AGE_MIN, AGE_MAX]}
                  addLabel="+ add another age range"
                />
                <MultiPillSection<RacePill>
                  label="race"
                  options={[
                      "white",
                      "Black",
                      "Asian",
                      "Latino",
                      "Indigenous",
                      "Pacific Islander",
                    ]}
                  rules={draft.raceRules}
                  onChange={(r) => update("raceRules", r)}
                  addLabel="+ add another race"
                />
                <MultiPillSection<SexPill>
                  label="sex"
                  options={["female", "male"]}
                  rules={draft.sexRules}
                  onChange={(r) => update("sexRules", r)}
                  addLabel="+ add another sex"
                />
                <MultiPillSection<CitizenshipPill>
                  label="citizenship"
                  options={["native", "naturalized", "non-citizen"]}
                  rules={draft.citizenshipRules}
                  onChange={(r) => update("citizenshipRules", r)}
                  addLabel="+ add another citizenship"
                />
                <Section
                  label="mobility"
                  controlKey="mobility"
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
                <MultiPillSection<IdentityPill>
                  label="marital status"
                  options={["married", "divorced", "widowed"]}
                  rules={draft.identityRules}
                  onChange={(r) => update("identityRules", r)}
                  addLabel="+ add another marital status"
                />
                <MultiRangeSection
                  label="children"
                  rules={draft.kidsRules}
                  onChange={(r) => update("kidsRules", r)}
                  min={KIDS_MIN}
                  max={KIDS_MAX}
                  format={fmtKids}
                  defaultRange={[KIDS_MIN, KIDS_MAX]}
                  addLabel="+ add another children range"
                />
                <MultiPillSection<Living>
                  label="living arrangement"
                  options={["single", "family"]}
                  rules={draft.livingRules}
                  onChange={(r) => update("livingRules", r)}
                  addLabel="+ add another living arrangement"
                />
                <MultiPillSection<HouseholdFeaturesPill>
                  label="household features"
                  options={[
                    "queer",
                    "new parent",
                    "multigen",
                    "elder in home",
                    "unmarried partner",
                    "raising grandchild",
                  ]}
                  rules={draft.householdFeaturesRules}
                  onChange={(r) => update("householdFeaturesRules", r)}
                  addLabel="+ add another household features rule"
                />
              </Accordion>

              <Accordion label="language & education">
                <MultiPillSection<LanguageFlagsPill>
                  label="language flags"
                  options={["non-English home", "limited-English household"]}
                  rules={draft.languageFlagsRules}
                  onChange={(r) => update("languageFlagsRules", r)}
                  addLabel="+ add another language flags rule"
                />
                <MultiRangeSection
                  label="English fluency"
                  rules={draft.englishRules}
                  onChange={(r) => update("englishRules", r)}
                  min={ENG_MIN}
                  max={ENG_MAX}
                  format={fmtEngConcept}
                  defaultRange={[ENG_MIN, ENG_MAX]}
                  addLabel="+ add another English fluency range"
                />
                <MultiRangeSection
                  label="education"
                  rules={draft.educationRules}
                  onChange={(r) => update("educationRules", r)}
                  min={SCHL_MIN}
                  max={SCHL_MAX}
                  format={fmtSchlConcept}
                  defaultRange={[SCHL_MIN, SCHL_MAX]}
                  addLabel="+ add another education tier"
                />
              </Accordion>

              <Accordion label="money & work">
                <MultiRangeSection
                  label="income (household)"
                  rules={draft.incomeRules}
                  onChange={(r) => update("incomeRules", r)}
                  min={INCOME_MIN}
                  max={INCOME_MAX}
                  step={INCOME_STEP}
                  format={fmtIncomeConcept}
                  defaultRange={[INCOME_MIN, INCOME_MAX]}
                  addLabel="+ add another income range"
                />
                <MultiRangeSection
                  label="family income"
                  rules={draft.familyIncomeRules}
                  onChange={(r) => update("familyIncomeRules", r)}
                  min={FAMILY_INCOME_MIN}
                  max={FAMILY_INCOME_MAX}
                  step={FAMILY_INCOME_STEP}
                  format={fmtIncomeConcept}
                  defaultRange={[FAMILY_INCOME_MIN, FAMILY_INCOME_MAX]}
                  addLabel="+ add another family income range"
                />
                <MultiRangeSection
                  label="hours per week"
                  rules={draft.hoursRules}
                  onChange={(r) => update("hoursRules", r)}
                  min={WKHP_MIN}
                  max={WKHP_MAX}
                  format={fmtHours}
                  defaultRange={[WKHP_MIN, WKHP_MAX]}
                  addLabel="+ add another hours range"
                />
                <MultiRangeSection
                  label="poverty status"
                  rules={draft.povertyRules}
                  onChange={(r) => update("povertyRules", r)}
                  min={POVPIP_MIN}
                  max={POVPIP_MAX}
                  format={fmtPovertyConcept}
                  defaultRange={[POVPIP_MIN, POVPIP_MAX]}
                  addLabel="+ add another poverty range"
                />
                <Section
                  label="food stamps"
                  controlKey="food_stamps"
                  isModified={draft.foodStamps}
                  onReset={() => update("foodStamps", false)}
                >
                  <BinaryToggle
                    label="receives SNAP"
                    value={draft.foodStamps}
                    onChange={(v) => update("foodStamps", v)}
                  />
                </Section>
                <MultiPillSection<ClassOfWorkerPill>
                  label="class of worker"
                  options={["private", "government", "self-employed"]}
                  rules={draft.classOfWorkerRules}
                  onChange={(r) => update("classOfWorkerRules", r)}
                  addLabel="+ add another class of worker"
                />
              </Accordion>

              <Accordion label="disability">
                <MultiPillSection<DisabilityPill>
                  label="disability type"
                  options={["physical", "cognitive", "sensory", "independent"]}
                  rules={draft.disabilityRules}
                  onChange={(r) => update("disabilityRules", r)}
                  addLabel="+ add another disability type"
                />
              </Accordion>

              <Accordion label="health insurance">
                <MultiPillSection<InsuranceCoveragePill>
                  label="coverage"
                  options={["insured", "employer", "Medicare", "Medi-Cal", "VA"]}
                  rules={draft.insuranceCoverageRules}
                  onChange={(r) => update("insuranceCoverageRules", r)}
                  addLabel="+ add another coverage rule"
                />
              </Accordion>

              <Accordion label="housing">
                <MultiPillSection<HousingPill>
                  label="tenure"
                  options={["owns", "rents"]}
                  rules={draft.housingRules}
                  onChange={(r) => update("housingRules", r)}
                  addLabel="+ add another tenure"
                />
                <MultiPillSection<HousingTypePill>
                  label="housing type"
                  options={["mobile home", "single-family", "apartment"]}
                  rules={draft.housingTypeRules}
                  onChange={(r) => update("housingTypeRules", r)}
                  addLabel="+ add another housing type"
                />
                <MultiRangeSection
                  label="year built"
                  rules={draft.yearBuiltRules}
                  onChange={(r) => update("yearBuiltRules", r)}
                  min={YRBLT_MIN}
                  max={YRBLT_MAX}
                  format={fmtYear}
                  defaultRange={[YRBLT_MIN, YRBLT_MAX]}
                  addLabel="+ add another year built range"
                />
                <MultiRangeSection
                  label="bedrooms"
                  rules={draft.bedroomsRules}
                  onChange={(r) => update("bedroomsRules", r)}
                  min={BDSP_MIN}
                  max={BDSP_MAX}
                  format={fmtCount}
                  defaultRange={[BDSP_MIN, BDSP_MAX]}
                  addLabel="+ add another bedrooms range"
                />
                <MultiRangeSection
                  label="vehicles"
                  rules={draft.vehiclesRules}
                  onChange={(r) => update("vehiclesRules", r)}
                  min={VEH_MIN}
                  max={VEH_MAX}
                  format={fmtCount}
                  defaultRange={[VEH_MIN, VEH_MAX]}
                  addLabel="+ add another vehicles range"
                />
                <MultiPillSection<HeatingFuelPill>
                  label="heating fuel"
                  options={[
                      "gas",
                      "propane",
                      "electric",
                      "oil",
                      "wood",
                      "solar",
                    ]}
                  rules={draft.heatingFuelRules}
                  onChange={(r) => update("heatingFuelRules", r)}
                  addLabel="+ add another heating fuel"
                />
                <MultiRangeSection
                  label="home value"
                  rules={draft.propertyValueRules}
                  onChange={(r) => update("propertyValueRules", r)}
                  min={VALP_MIN}
                  max={VALP_MAX}
                  step={VALP_STEP}
                  format={fmtValueConcept}
                  defaultRange={[VALP_MIN, VALP_MAX]}
                  addLabel="+ add another home value range"
                />
                <MultiRangeSection
                  label="year moved in"
                  rules={draft.yearMovedRules}
                  onChange={(r) => update("yearMovedRules", r)}
                  min={MV_MIN}
                  max={MV_MAX}
                  format={fmtMovedConcept}
                  defaultRange={[MV_MIN, MV_MAX]}
                  addLabel="+ add another year moved range"
                />
                <MultiRangeSection
                  label="rent burden"
                  rules={draft.rentBurdenRules}
                  onChange={(r) => update("rentBurdenRules", r)}
                  min={GRPIP_MIN}
                  max={GRPIP_MAX}
                  format={fmtBurdenConcept}
                  defaultRange={[GRPIP_MIN, GRPIP_MAX]}
                  addLabel="+ add another rent burden range"
                />
                <MultiRangeSection
                  label="owner cost burden"
                  rules={draft.ownerCostBurdenRules}
                  onChange={(r) => update("ownerCostBurdenRules", r)}
                  min={OCPIP_MIN}
                  max={OCPIP_MAX}
                  format={fmtBurdenConcept}
                  defaultRange={[OCPIP_MIN, OCPIP_MAX]}
                  addLabel="+ add another owner cost burden range"
                />
              </Accordion>

              <Accordion label="tech">
                <MultiPillSection<HouseholdTechPill>
                  label="household tech"
                  options={["broadband", "laptop", "smartphone"]}
                  rules={draft.householdTechRules}
                  onChange={(r) => update("householdTechRules", r)}
                  addLabel="+ add another tech rule"
                />
              </Accordion>

              <Accordion label="commute">
                <MultiPillSection<CommuteModePill>
                  label="commute mode"
                  options={[
                      "drove alone",
                      "carpool",
                      "transit",
                      "walked or biked",
                      "worked from home",
                    ]}
                  rules={draft.commuteModeRules}
                  onChange={(r) => update("commuteModeRules", r)}
                  addLabel="+ add another commute mode"
                />
                <MultiRangeSection
                  label="commute time"
                  rules={draft.commuteTimeRules}
                  onChange={(r) => update("commuteTimeRules", r)}
                  min={JWMNP_MIN}
                  max={JWMNP_MAX}
                  format={fmtMinutes}
                  defaultRange={[JWMNP_MIN, JWMNP_MAX]}
                  addLabel="+ add another commute time range"
                />
              </Accordion>

              <Accordion label="military service">
                <Section
                  label="veteran"
                  controlKey="veteran"
                  isModified={draft.veteran}
                  onReset={() => update("veteran", false)}
                >
                  <BinaryToggle
                    label="is veteran"
                    value={draft.veteran}
                    onChange={(v) => update("veteran", v)}
                  />
                </Section>
                <MultiPillSection<VeteranEraPill>
                  label="era of service"
                  options={["post-9/11", "Gulf", "Vietnam"]}
                  rules={draft.veteranEraRules}
                  onChange={(r) => update("veteranEraRules", r)}
                  addLabel="+ add another era"
                />
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
          </TiersContext.Provider>
        </div>
      )}
    </>
  );
}
