# QC: biip GTIN validation + image URL query-string relaxation

Date: 2026-09-19
Status: approved (design), pending implementation

## Problem

1. `GtinMpn._gs1_checksum` (`backend/app/qc/rules.py`) hand-rolls the GS1
   mod-10 check and calls `str(gtin)`. `gtin` is a REPEATED_SCALAR registry
   field, so a list value becomes `"['...']"` and is wrongly flagged
   `critical`. The hand-rolled check also accepts meaningless lengths
   (9/10/11 digits) as long as the check digit happens to pass.
2. `ImageRequirements` extracts the extension with
   `url.rsplit(".", 1)[-1]`. For `https://host/img.jpg?v=1243` that yields
   `jpg?v=1243`, producing a false `warning: unrecognized image format`.
   Fragments (`#...`) fail the same way.

## Decisions

### A. GTIN validation via `biip`

- Add `biip` (5.0.0, pinned) to `backend/pyproject.toml`.
- Replace `_gs1_checksum` with `biip.parse(str(value).strip())`:
  - `result.gtin is not None` → valid.
  - else → `Finding(rule_id="gtin_mpn", severity="critical", field="gtin",
    message=result.gtin_error or "invalid GTIN")`.
- `gtin` is repeatable: normalize to a list (scalar → single element), drop
  empty/whitespace-only values, validate each; one finding per bad value.
  A fully empty gtin value keeps today's behavior: missing gtin requires
  `mpn` + `brand` (`warning` otherwise).
- biip implements GS1 mod-10 and additionally enforces length ∈ {8, 12, 13,
  14}. This is stricter than the old check; the QC design spec §7 wording is
  updated. `gmc-feed-engine-spec.md` §"GTIN/MPN logic" says "modulo-10
  weighting per the GS1 spec, no special cases" — biip is the same GS1
  weighting, so the spec is not contradicted; length enforcement matches
  `gmc_def.md` ("Max. 14 digits per value: UPC (12), EAN (13), JAN (8/13),
  ISBN (13), ITF-14 (14)").

### B. Image URL relaxation

- Resolve the path with `urllib.parse.urlsplit(url).path`, then take the last
  `/`-segment and only split on `.` within that segment.
- Query strings and fragments are ignored for the format check.
- URLs with no recognizable extension still emit the existing `warning`
  (magic-byte sniffing remains out of scope; listed as a follow-up).

## Files touched

- `backend/pyproject.toml`, `backend/uv.lock` — add `biip`
- `backend/app/qc/rules.py` — `GtinMpn`, `ImageRequirements`
- `backend/tests/test_qc_rules.py` — GTIN + image cases
- `docs/superpowers/specs/2026-08-27-m7-quality-check-design.md` — §7 row
- `backend/docs/decisions.md` — dated entry for the biip dependency

## Tests

- GTIN valid: 8, 12, 13, 14 digits.
- GTIN invalid check digit → critical.
- GTIN invalid length (10 digits) → critical (previously passed if checksum ok).
- GTIN non-numeric → critical.
- GTIN repeated list with one bad value → exactly one critical.
- GTIN empty list / empty string → same as missing.
- Image: `img.jpg?v=1243`, `img.webp#frag`, `img.png?size=large&x=1` → no
  format warning.
- Image: extensionless URL and directory containing a dot (`/v1.2/image`)
  still warn.

## Follow-up suggestions (not in scope)

- Magic-byte format sniffing for extensionless URLs (spec already promises it).
- Use biip GS1 prefix / company prefix for soft data-quality `info` hints.
- Put the accepted GTIN lengths in `app/qc/constants.py` instead of relying on
  biip defaults.
- Record the offending raw value in `Finding.details`.
