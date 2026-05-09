# Available demographic fields (ACS PUMS)

Every PUMS variable that can be pulled into the pipeline and used in a subculture vector. Some are already pulled in `pipeline.py`; others are listed for reference and can be added to `PERSON_VARS` or `HOUSING_VARS` when needed. Codes shown are summarized; full code lists are in the official PUMS data dictionary.

---

## Person-level fields

### Identity / demographics

| Field | Description | Useful values |
|---|---|---|
| `AGEP` | Age (years) | 0-99 |
| `SEX` | Sex | 1 male, 2 female |
| `RAC1P` | Race (recoded major) | 1 white, 2 Black, 3-5 AIAN, 6 Asian, 7 NHPI, 8 some other, 9 two+ |
| `RAC2P` / `RAC3P` | Race detailed | finer breakdowns |
| `RACAIAN` / `RACASN` / `RACBLK` / `RACNH` / `RACPI` / `RACSOR` / `RACWHT` | Race-in-combination flags | 1 yes, 0 no |
| `HISP` | Hispanic origin | 1 not Hispanic, 2-24 specific origins |
| `ANC1P` / `ANC2P` | First / second ancestry | code list |
| `NATIVITY` | Birth country | 1 US-born, 2 foreign-born |
| `POBP` | Place of birth | code |
| `CIT` | Citizenship status | 1-4 native, 5 naturalized, 6 not citizen |
| `CITWP` | Year of naturalization | year |
| `DECADE` | Decade of entry to US | 1-7 |
| `YOEP` | Year of entry | year |
| `WAOB` | World area of birth | 1-8 region |

### Family / household role

| Field | Description | Useful values |
|---|---|---|
| `MAR` | Marital status | 1 married, 2 widowed, 3 divorced, 4 separated, 5 never married |
| `MARHT` | Times married | 1-3 |
| `MARHYP` | Year last married | year |
| `MARHM` / `MARHW` / `MARHD` | Married/widowed/divorced in past year flags | 1/2 |
| `RELSHIPP` | Relationship to householder | 20 self, 21-22 opp-sex spouse/partner, 23-24 same-sex spouse/partner, 25-27 child, 28 sibling, 29 parent, 30 grandchild, 33 other relative, 34 roommate, 36 other nonrelative |
| `FER` | Gave birth in last 12 months | 1 yes, 2 no (women 15-50 only) |
| `NOP` | Number of own children | 0+ |
| `NRC` | Number of related children in household | 0+ |
| `PAOC` | Presence/age own children | 1-4 |
| `PARTNER` | Presence of unmarried partner | 0-4 |
| `ESP` | Employment status of parents | 1-8 |

### Education

| Field | Description | Useful values |
|---|---|---|
| `SCHL` | Educational attainment | 1 none, 16 HS diploma, 17 GED, 18-19 some college, 20 associate, 21 BA, 22 master, 23 professional, 24 doctorate |
| `SCH` | School enrollment now | 1 not enrolled, 2 public, 3 private |
| `SCHG` | Grade level enrolled | 1-16 |
| `SCIENGP` | Has BA in science/engineering | 1 yes, 2 no |
| `SCIENGRLP` | Has BA in S&E-related field | 1 yes, 2 no |
| `FOD1P` / `FOD2P` | Field of degree (1st / 2nd) | code list |

### Language

| Field | Description | Useful values |
|---|---|---|
| `LANP` | Specific language at home | 1200 Spanish, 1970 Tagalog, 2050 Vietnamese, 2030 Chinese, etc. |
| `LANX` | Speaks non-English at home | 1 yes, 2 no |
| `ENG` | English ability | 1 very well, 2 well, 3 not well, 4 not at all |

### Disability

| Field | Description | Useful values |
|---|---|---|
| `DIS` | Any disability | 1 with, 2 without |
| `DEAR` | Hearing difficulty | 1 yes, 2 no |
| `DEYE` | Vision difficulty | 1 yes, 2 no |
| `DPHY` | Ambulatory (mobility) difficulty | 1 yes, 2 no |
| `DREM` | Cognitive difficulty | 1 yes, 2 no |
| `DSE` | Self-care difficulty | 1 yes, 2 no |
| `DOUT` | Independent-living difficulty | 1 yes, 2 no |

### Military

| Field | Description | Useful values |
|---|---|---|
| `MIL` | Service status | 1 active, 2 past active, 3 training only, 4 never |
| `VPS` | Veteran period of service | code list |
| `DRAT` | Service-connected disability rating | 1-6 |
| `DRATX` | Any service-connected disability | 1 yes, 2 no |

### Health insurance

| Field | Description | Useful values |
|---|---|---|
| `HICOV` | Any insurance | 1 yes, 2 no |
| `HINS1` | Employer-based | 1 yes, 2 no |
| `HINS2` | Directly purchased | 1 yes, 2 no |
| `HINS3` | Medicare | 1 yes, 2 no |
| `HINS4` | Medicaid / Medi-Cal | 1 yes, 2 no |
| `HINS5` | TRICARE / military | 1 yes, 2 no |
| `HINS6` | VA | 1 yes, 2 no |
| `HINS7` | Indian Health Service | 1 yes, 2 no |
| `PRIVCOV` | Any private | 1 yes, 2 no |
| `PUBCOV` | Any public | 1 yes, 2 no |

### Employment

| Field | Description | Useful values |
|---|---|---|
| `ESR` | Employment status | 1 employed, 2 employed not at work, 3 unemployed, 6 not in labor force |
| `COW` | Class of worker | 1 private for-profit, 2 nonprofit, 3 federal, 4 state, 5 local gov, 6 self-employed unincorp., 7 self-employed incorp., 8 family business |
| `OCCP` | Occupation (mapped to SOC majors via operator) | major groups: 11 mgmt, 13 biz/finance, 15 computer/math, 17 engineering, 19 social science, 21 community/social, 23 legal, 25 education, 27 arts/media, 29 healthcare, 31 healthcare support, 33 protective service, 35 food prep, 37 cleaning, 39 personal care, 41 sales, 43 office, 45 ag, 47 construction, 49 install/repair, 51 production, 53 transport, 55 military |
| `INDP` | Industry (mapped to NAICS sectors via operator) | sectors: 11 ag, 23 construction, 31-33 manufacturing, 44-45 retail, 51 info, 52 finance, 54 prof svcs, 61 education, 62 healthcare, 71 arts/recreation, 72 accommodation/food |
| `NAICSP` | Industry NAICS code | code |
| `SOCP` | Occupation SOC code | code |
| `WKHP` | Hours worked per week | 1-99 |
| `WKW` | Weeks worked in past 12 months | 1 (50-52) – 6 (0) |
| `WKL` | When last worked | 1 last 12 mo, 2 1-5 yrs, 3 5+ yrs ago, 4 never |
| `NWAB` / `NWAV` / `NWLA` / `NWLK` / `NWRE` | Job-search and availability indicators | 1 yes, 2 no |

### Income

| Field | Description | Useful values |
|---|---|---|
| `PINCP` | Total personal income | dollars |
| `PERNP` | Earnings (subset of PINCP) | dollars |
| `WAGP` | Wage and salary income | dollars |
| `SEMP` | Self-employment income | dollars |
| `INTP` | Interest/dividend/royalty income | dollars |
| `RETP` | Retirement income | dollars |
| `SSP` | Social Security income | dollars |
| `SSIP` | Supplemental Security Income | dollars |
| `PAP` | Public assistance income | dollars |
| `OIP` | All other income | dollars |
| `POVPIP` | Income-to-poverty ratio | 0-501 (501 capped, 100 = at poverty line) |

### Commute / work geography

| Field | Description | Useful values |
|---|---|---|
| `JWTRNS` | Means of transportation to work | 1 drove alone, 2 carpool, 3 bus, 4 streetcar, 5 subway, 6 train, 7 light rail, 8 ferry, 9 taxi, 10 motorcycle, 11 bike, 12 walk, 13 other, 14 work from home |
| `JWMNP` | Travel time (minutes) | 0-200 |
| `JWAP` | Arrival time at work | code |
| `JWDP` | Departure time for work | code |
| `POWPUMA` | PUMA where works | code |
| `POWSP` | State where works | code |

### Mobility (year-ago location)

| Field | Description | Useful values |
|---|---|---|
| `MIG` | Lived in same house 1 yr ago | 1 yes, 2 same county diff house, 3 diff county same state, 4 diff state, 5 abroad |
| `MIGPUMA` | PUMA of residence 1 year ago | code |
| `MIGSP` | State of residence 1 year ago | code |

### Grandparenting

| Field | Description | Useful values |
|---|---|---|
| `GCL` | Grandparents living with grandchildren under 18 | 1 yes, 2 no |
| `GCR` | Grandparents responsible for grandchildren | 1 yes, 2 no |
| `GCM` | Months responsible | 1-5 |

### Sample weights

| Field | Description | Useful values |
|---|---|---|
| `PWGTP` | Person weight (count of real people the record represents) | integer |
| `PWGTP1`-`PWGTP80` | Replicate weights for variance estimation | integer |

---

## Household-level fields

### Tenure / household composition

| Field | Description | Useful values |
|---|---|---|
| `TEN` | Tenure | 1 owned w/ mortgage, 2 owned free, 3 rented, 4 occupied w/o payment |
| `HHT` | Household type | 1 married couple, 2 male HoH no spouse, 3 female HoH no spouse, 4 male alone, 5 male not alone, 6 female alone, 7 female not alone |
| `NP` | Number of persons in household | 1+ |
| `HHL` | Household language | code |
| `HUPAC` | Presence of any children under 18 | 1 yes, 2 no |
| `HUPAOC` | Presence of own children | 1 under 6 only, 2 under 6 and 6-17, 3 6-17 only, 4 no own children |
| `HUPARC` | Presence of related children | similar codes |
| `MULTG` | Multigenerational household | 1 yes, 2 no |
| `LNGI` | Limited-English-speaking household | 1 yes, 2 no |

### Structure / lot

| Field | Description | Useful values |
|---|---|---|
| `BLD` | Units in structure | 1 mobile home, 2 detached single-family, 3 attached single-family, 4-9 apartments by size, 10 boat/RV/van |
| `YBL` | Year structure built | 1 1939 or earlier, 2 1940s, 3 1950s, 4 1960s, 5 1970s, 6 1980s, 7 1990s, 8 2000s, 9 2010s, 10 2020+ |
| `ACR` | Lot size | 1 <1 acre, 2 1-9.99 ac, 3 10+ ac |
| `AGS` | Agricultural product sales | 1 none, 2 $1-999, 3-7 increasing brackets |
| `BUS` | Business or medical office on property | 1 yes, 2 no |
| `BDSP` | Bedrooms | 0+ |
| `RMSP` | Total rooms | 1+ |
| `KIT` | Complete kitchen | 1 yes, 2 no |
| `PLM` | Complete plumbing | 1 yes, 2 no |
| `RWAT` | Running water | 1 yes, 2 no |
| `SINK` | Sink with faucet | 1 yes, 2 no |
| `STOV` | Stove or range | 1 yes, 2 no |
| `REFR` | Refrigerator | 1 yes, 2 no |
| `TOIL` | Flush toilet | 1 yes, 2 no |
| `TEL` | Telephone service | 1 yes, 2 no |

### Move / migration of household

| Field | Description | Useful values |
|---|---|---|
| `MV` | When householder moved in | 1 within 12 mo, 2 1-4 yrs, 3 5-9 yrs, 4 10-19 yrs, 5 20-29 yrs, 6 30+ yrs |

### Vehicles

| Field | Description | Useful values |
|---|---|---|
| `VEH` | Vehicles available | 0-6+ |

### Costs / finances

| Field | Description | Useful values |
|---|---|---|
| `HINCP` | Household income | dollars |
| `FINCP` | Family income | dollars |
| `VALP` | Property value (owner only) | dollars |
| `RNTP` | Monthly rent | dollars |
| `MHP` | Mobile home costs | dollars |
| `MRGP` | First mortgage payment | dollars |
| `MRGI` / `MRGT` / `MRGX` | Mortgage detail flags | code |
| `SMOCP` | Selected monthly owner costs | dollars |
| `SMP` | Selected monthly costs | dollars |
| `CONP` | Condominium fee | dollars |
| `INSP` | Hazard insurance | dollars |
| `TAXAMT` | Real estate taxes | dollars |
| `FS` | Food stamps received in last year | 1 yes, 2 no |
| `WIF` | Workers in family | 0-3 |
| `ELEP` / `GASP` / `FULP` / `WATP` | Monthly utility costs | dollars |
| `ELEFP` / `GASFP` / `FULFP` / `WATFP` | Utility cost flags | code |

### Internet / tech

| Field | Description | Useful values |
|---|---|---|
| `ACCESS` | Internet access at home | 1 paid, 2 free, 3 none |
| `BROADBND` | Broadband subscription | 1 yes, 2 no |
| `HISPEED` | Cable / fiber / DSL | 1 yes, 2 no |
| `DIALUP` | Dial-up | 1 yes, 2 no |
| `LAPTOP` | Laptop or desktop in household | 1 yes, 2 no |
| `SMARTPHONE` | Smartphone | 1 yes, 2 no |
| `TABLET` | Tablet | 1 yes, 2 no |
| `COMPOTHX` | Other computing device | 1 yes, 2 no |

### Householder demographics (diagnostic)

| Field | Description | Useful values |
|---|---|---|
| `HHLDRRAC1P` | Householder race | same codes as RAC1P |
| `HHLDRHISP` | Householder Hispanic origin | code |
| `HHLDRAGEP` | Householder age | years |

### Sample weights

| Field | Description | Useful values |
|---|---|---|
| `WGTP` | Housing unit weight | integer |
| `WGTP1`-`WGTP80` | Replicate weights | integer |

---

## Derived fields (computed in pipeline)

| Field | Description | Useful values |
|---|---|---|
| `SAME_SEX` | Household has a same-sex spouse or unmarried partner | 1 yes, 0 no. Derived from RELSHIPP codes 23 (same-sex spouse) and 24 (same-sex unmarried partner). |

---

## Operators usable in subculture YAML

- `eq` — field equals value
- `in` — field is in `[values...]`
- `range` — field is in `[lo, hi]`
- `gte` / `lte` — `≥` / `≤` value
- `industry_naics` — INDP code mapped to NAICS sector(s)
- `occupation_soc_major` — OCCP code mapped to SOC major group(s)
- `occupation_soc_minor` — OCCP code matching specific 4-digit prefix(es)
- `spanish` — LANP equals 1200 (Spanish)
- `percentile_gte` — value is at or above the Nth percentile of the column

`required: true` on a condition makes it a hard gate (record scores 0 if not satisfied). Otherwise everything is a soft weight.

---

## Notes

- Most fields exist on either the person or housing record; values join via `SERIALNO`.
- Some fields are conditional (only populated for a subset). Examples: `FER` (women 15-50 only), `JWTRNS` (people who worked in the past week), `VALP` (owner-occupied only), `RNTP` (renter-occupied only), `ENG` (people who speak non-English at home).
- For full code lists and notes, see the official PUMS Data Dictionary at https://www.census.gov/programs-surveys/acs/microdata/documentation.html.
