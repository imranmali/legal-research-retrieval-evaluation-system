# Spec Delta

## Purpose

Finds legal citations in free text and reduces spelling variants to one
canonical form so citations can be matched across queries, documents and judgments.

## ADDED Requirements

### Requirement: Case reporter citations
The system SHALL recognize `volume reporter page` citations for the major US reporters (U.S., S. Ct., L. Ed., L. Ed. 2d, F., F.2d, F.3d, F.4th, F. Supp. 1st–3d, F. App'x and the regional reporters A., N.E., N.W., P., S.E., S.W., So. with their series).

#### Scenario: Supreme Court citation
- **WHEN** text contains `see Roe v. Wade, 410 U.S. 113 (1973)`
- **THEN** a case citation with canonical form `410 U.S. 113` is returned with its character span

#### Scenario: Spacing variants normalize
- **WHEN** text contains `123 F. 3d 456` or `123 F.3d 456`
- **THEN** both normalize to `123 F.3d 456`

### Requirement: Statutory and regulatory citations
The system SHALL recognize U.S. Code citations (`42 U.S.C. § 1983`, `42 USC 1983`, `42 U.S.C. sec. 1983`) and C.F.R. citations (`29 C.F.R. § 1630.2`), normalizing them to `<title> U.S.C. § <section>` and `<title> C.F.R. § <section>`.

#### Scenario: Statute variants
- **WHEN** text contains `42 USC 1983`
- **THEN** the canonical form is `42 U.S.C. § 1983`

### Requirement: UK neutral citations
The system SHALL recognize UK neutral citations such as `[2020] UKSC 5`, `[2019] EWCA Civ 123` and `[2018] EWHC 456 (Ch)`.

#### Scenario: Court of Appeal citation
- **WHEN** text contains `[2019] EWCA Civ 123`
- **THEN** a neutral citation with canonical form `[2019] EWCA Civ 123` is returned

### Requirement: Normalization of single citations
The system SHALL normalize a standalone citation string to its canonical form and SHALL signal when the string is not a recognized citation.

#### Scenario: Unrecognized string
- **WHEN** `hello world` is normalized
- **THEN** the result indicates no citation was recognized
