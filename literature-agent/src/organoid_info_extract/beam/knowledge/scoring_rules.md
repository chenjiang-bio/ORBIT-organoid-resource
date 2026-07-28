# JUDGER SCORING RULES

## SCORING SYSTEM (0-100)

### Base Score
- Start with: 100 points

### Deduction Rules
1. **Meta Information Errors**: -10 points per error
   - Examples: Wrong DOI, incorrect title, author mismatch, journal name error, PMID/PMCID errors

2. **Value Errors**: -3 points per error
   - Examples: Wrong culture_day, incorrect concentration values, wrong temperature, inaccurate duration, erroneous biomarker expression timing

3. **Structure Errors**: -5 points per error
   - Examples: Missing required fields, wrong data types, incorrect array usage, field misuse, can be provided but not provided

4. **Value Unit Errors**: -2 points per error
   - Examples: Incorrect units (e.g., "mg/ml" instead of "µg/ml"), wrong date formats, improper numerical formats

5. **Value Format Errors**: 0 points per error
   - Examples: 50 mg/ml vs 50mg/ml (spacing issues)
   - Examples: "ten days" vs "10 days"

6. **GENE SYMBOL Errors**: -4 points per error
   - Examples: Incorrect gene symbols not matching HGNC standards, only for gene type(DNA, RNA), not for protein type. 

### Critical Validation Points
- **Meta Section**: Verify DOI, title, authors, journal against authoritative sources
- **Culture Protocol**: Check day values, concentrations, units against ORIGINAL_TEXT
- **Material References**: Validate material indexing (1-based, not 0-based)
- **Schema Compliance**: Ensure all required fields present and correctly typed


### Special Cases
- **Automatic Zero Score**:
  - Completely fabricated data (not from ORIGINAL_TEXT)
  - Missing entire meta section
  - Wrong organism/tissue type
  - Violates RULE 20: GLOBAL EXTRACTION RULES systematically

### Scoring Process
1. Verify meta information using tools (DOI, gene symbols, catalog numbers, etc.)
2. Compare extracted values against ORIGINAL_TEXT for accuracy
3. Check structural compliance with EXTRACTED_DATA_DESCRIPTION
4. Apply deductions according to error category
5. Provide detailed reasoning for each deduction
6. Correct items (deduction_score=0) do not need to be listed in deductions.
7. Final score = 100 - (sum of all deductions)
