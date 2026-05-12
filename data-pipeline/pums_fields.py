"""PUMS field catalog.

Lives in its own module because the lists are large and grow over time;
keeping them out of pipeline.py keeps that file focused on logic.

Two lists, one per PUMS CSV file:
    PERSON_VARS   - columns to pull from the person-level CSV
    HOUSING_VARS  - columns to pull from the housing-level CSV

Plus a hardcoded replicate-weight count (PWGTP1..PWGTP{N}) for the
Fay-Herriot variance estimator. Combined into PERSON_VARS_WITH_REPLICATES
for the parquet build.

The catalog is intentionally generous: any field a user might cite in a
POSTed cohort definition belongs here. Adding a field here loads it into
the parquet eagerly so future scoring requests can use it without
forcing a parquet rebuild. The cost per field is roughly 2 MB at
2M PUMS records, so 60-80 fields keeps the parquet near a few hundred MB.

For full definitions and value codes, see docs/fields.md (project root)
and the authoritative Census PUMS data dictionary at
https://www.census.gov/programs-surveys/acs/microdata/documentation.html.
"""

from __future__ import annotations


# PUMS replicate weights (PWGTP1..PWGTP80) for successive-difference
# replication (SDR) variance estimation. Sampling variance of any
# weighted estimate is Var(θ̂) = (4 / 80) · Σ_r (θ̂_r − θ̂)², per the
# Census methodology described in Wolter 2007, *Introduction to Variance
# Estimation*, 2nd ed., Springer. Used by the Fay-Herriot small-area
# model.
N_REPLICATE_WEIGHTS = 80
REPLICATE_WEIGHT_VARS = [f"PWGTP{i}" for i in range(1, N_REPLICATE_WEIGHTS + 1)]


# Person-record variables. Keep grouped by theme for readability; order
# does not matter at runtime. SERIALNO is the join key for the housing
# record.
PERSON_VARS = [
    # ── Plumbing (identifiers and weights) ──
    "PUMA",       # 5-digit PUMA code (2020 vintage)
    "ST",         # state FIPS (always 06 in this project, kept for parity)
    "PWGTP",      # person weight (main estimate; integer count of real people the record represents)
    "SERIALNO",   # household serial, join key to housing record

    # ── Identity / demographics ──
    "AGEP",       # age in years
    "SEX",        # 1 male, 2 female
    "RAC1P",      # race recoded major (1 white, 2 Black, 6 Asian, ...)
    "RAC2P",      # race recoded detailed (sub-groups within RAC1P)
    "HISP",       # Hispanic origin (1 not Hispanic, 2-24 specific origins)
    "ANC1P",      # primary ancestry code
    "NATIVITY",   # 1 US-born, 2 foreign-born
    "POBP",       # place of birth
    "CIT",        # citizenship status (1-4 native, 5 naturalized, 6 not citizen)
    "YOEP",       # year of entry to US (for non-native-born)
    "DECADE",     # decade of entry to US (1-7)

    # ── Education ──
    "SCHL",       # educational attainment (1 none ... 24 doctorate)
    "SCH",        # current school enrollment (1 not enrolled, 2 public, 3 private)
    "SCHG",       # current grade level (1-16)
    "FOD1P",      # primary field of degree

    # ── Language ──
    "LANP",       # specific language at home (1200 Spanish, 2050 Vietnamese, etc.)
    "LANX",       # speaks non-English at home (1 yes, 2 no)
    "ENG",        # English proficiency (1 very well .. 4 not at all)

    # ── Family / household role ──
    "MAR",        # marital status (1 married, 2 widowed, 3 divorced, 4 separated, 5 never married)
    "MARHT",      # times married (1-3)
    "RELSHIPP",   # relationship to householder (used to derive SAME_SEX)
    "FER",        # gave birth in last 12 mo (1 yes, 2 no; women 15-50 only)
    "NOP",        # number of own children
    "NRC",        # number of related children under 18
    "PAOC",       # presence and age of own children (1-4)
    "GCL",        # grandparents living with grandchildren under 18 (1 yes, 2 no)

    # ── Disability ──
    "DIS",        # any disability (1 with, 2 without)
    "DPHY",       # ambulatory difficulty
    "DREM",       # cognitive / mental-health difficulty
    "DEAR",       # hearing difficulty
    "DEYE",       # vision difficulty
    "DOUT",       # independent-living difficulty
    "DDRS",       # self-care difficulty

    # ── Military ──
    "MIL",        # service status (1 active, 2 past active, 3 training only, 4 never)

    # ── Health insurance ──
    "HICOV",      # any insurance (1 yes, 2 no)
    "HINS1",      # employer-based
    "HINS3",      # Medicare
    "HINS4",      # Medicaid / Medi-Cal
    "PUBCOV",     # any public

    # ── Employment ──
    "ESR",        # employment status recode
    "COW",        # class of worker (1 private for-profit, 2 nonprofit, 3-5 gov, 6-7 self-employed)
    "OCCP",       # occupation (SOC-based; use occupation_soc_major operator)
    "INDP",       # industry (NAICS-based; use industry_naics operator)
    "WKHP",       # usual hours worked per week
    "WKW",        # weeks worked in past 12 months (1 = 50-52 ... 6 = 0)
    "WKL",        # when last worked (1 within 12 mo, 2 1-5 yrs, 3 5+ yrs, 4 never)

    # ── Income subtypes ──
    "PINCP",      # total personal income
    "PERNP",      # earnings (wages + self-employment)
    "WAGP",       # wage and salary income
    "SEMP",       # self-employment income
    "RETP",       # retirement income
    "SSP",        # Social Security income
    "SSIP",       # Supplemental Security Income
    "PAP",        # public assistance income
    "POVPIP",     # income-to-poverty ratio (501 max; 100 = at poverty line)

    # ── Commute / mobility ──
    "JWTRNS",     # means of transportation to work
    "JWMNP",      # travel time to work (minutes)
    "MIG",        # lived in same house 1 yr ago
]


# PERSON_VARS plus the 80 replicate-weight columns. Used by the parquet
# build when reading the person CSV. Replicate weights are kept separate
# from PERSON_VARS itself so the catalog stays readable.
PERSON_VARS_WITH_REPLICATES = PERSON_VARS + REPLICATE_WEIGHT_VARS


# Household-record variables.
HOUSING_VARS = [
    # ── Plumbing ──
    "SERIALNO",
    "WGTP",       # housing unit weight

    # ── Tenure / composition ──
    "TEN",        # tenure (1 owned w/ mortgage, 2 owned free, 3 rented, 4 occupied w/o pmt)
    "HHT",        # household type
    "HHL",        # household language
    "NP",         # number of persons in household
    "HUPAC",      # presence of any children under 18
    "HUPAOC",     # presence of own children (categorical with age groups)
    "MULTG",      # multigenerational household
    "LNGI",       # limited-English-speaking household
    "PARTNER",    # presence of unmarried partner (used to derive SAME_SEX)

    # ── Structure / lot ──
    "BLD",        # units in structure (2 = single-family detached)
    "YRBLT",      # year structure built (decade-start year value: 1939 = "1939 or earlier", ..., 2020 = "2020 or later")
    "ACR",        # lot size (1 = <1 acre, 2 = 1-9.99 ac, 3 = 10+ ac)
    "AGS",        # agricultural sales bracket
    "BDSP",       # bedrooms

    # ── Utilities / amenities ──
    "TEL",        # telephone service
    "PLM",        # complete plumbing
    "HFL",        # heating fuel (2 propane, 4 oil, 6 wood = rural signals)

    # ── Vehicles ──
    "VEH",        # vehicles available

    # ── Costs / finances ──
    "HINCP",      # household income
    "FINCP",      # family income
    "VALP",       # property value (owner-occupied only)
    "RNTP",       # monthly rent
    "MRGP",       # first mortgage payment
    "SMOCP",      # selected monthly owner costs
    "FS",         # food stamps received in last year
    "WIF",        # workers in family

    # ── Internet / tech ──
    "ACCESS",     # internet access at home (1 paid, 2 free, 3 none)
    "BROADBND",   # broadband subscription
    "LAPTOP",     # laptop or desktop in household
    "SMARTPHONE", # smartphone in household

    # ── Move / migration of household ──
    "MV",         # when householder moved in

    # ── Householder demographics (diagnostic) ──
    "HHLDRRAC1P", # householder race

    # Same-sex household indicator: derived in pipeline.fetch_pums from
    # RELSHIPP codes 23 (same-sex spouse) and 24 (same-sex unmarried
    # partner). Persisted to the parquet as SAME_SEX with values 1/0.
    #
    # Methodology: projecting a household-level fact onto person
    # records is standard ACS practice (Census, *Understanding and
    # Using ACS Data*; the official poverty rate is the canonical
    # example). Within-household clustering inflates variance and is
    # handled via SDR with replicate weights PWGTP1..PWGTP80 (Wolter
    # 2007, *Introduction to Variance Estimation*, 2nd ed., Springer).
    # Interpretation: SAME_SEX=1 means "lives in a same-sex household,"
    # not "is in a same-sex relationship"; this framing follows the
    # Williams Institute / Gates lineage of LGBT demography on ACS.
    #
    # Policy: SAME_SEX is the project's ONE documented derivation
    # exception. It exists because it propagates a household-level fact
    # (the householder/partner relationship) onto person records, and
    # the current cohort operators can't express that join. If you find
    # yourself wanting to add a second special case, build a generic
    # `household_has` operator instead. Do not extend this pattern.
]
