# GLOBAL RULES (PRIORITY HIGH)

## RULE 1: TIME DATA TYPES — CRITICAL SEMANTIC DISTINCTION

**Two distinct time concepts require different data structures:**

### TimeRangeNodeInfo — Fuzzy Time POINT
**Semantic**: "When something happens" (a point or window on the timeline)
- Represents a TIME LOCATION on the culture timeline
- Used for: anchor timepoints, detection timing, observation windows
- Examples:
  - "Biomarkers detected on day 14-16" → anchor field in TimeAxisAnchorInfo
  - "Organoids analyzed between day 10 and day 12" → detect_time in biomarker fields
  - "Phenotype observed on day 7" → time field in PhenotypesInfo

**Structure**: `{"min_value": 14, "min_time_unit": "days", "max_value": 16, "max_time_unit": "days"}`
- Range means "any day within this window" (fuzzy point set)
- min_value=max_value for exact timepoint

### DurationRangeInfo — Time SPAN/DURATION
**Semantic**: "How long something lasts" (a length/duration)
- Represents TIME ELAPSED (duration from start to end)
- Used for: total culture time, co-culture duration, segment durations, maintenance periods
- Examples:
  - "Organoids cultured for 14 days" → culture_time_organoid
  - "Co-culture maintained for 7-14 days" → culture_time_coculture
  - "Differentiation phase from day 7 to day 21" → TimeAxisSegmentInfo.duration (14 days)
  - "Incubated for 2 hours" → any duration field

**Structure**: `{"min_value": 14, "max_value": 14, "min_time_unit": "days", "max_time_unit": "days", "is_original": true, "source_text": "cultured for 14 days"}`
- Range means "duration varied between bounds" (e.g., "cultured for 7-14 days")
- min_value=max_value for exact duration
- **is_original=True**: Article explicitly states duration
- **is_original=False**: Duration calculated/inferred from time_axis
- **source_text**: Preserve exact quote when is_original=True

### Common Errors to Avoid

**❌ WRONG: Using TimeRangeNodeInfo for durations**
```json
"culture_time_organoid": {"min_value": 14, "max_value": 14, "min_time_unit": "days", "max_time_unit": "days"}
// Missing is_original and source_text, semantic mismatch
```

**✅ CORRECT: Using DurationRangeInfo for durations**
```json
"culture_time_organoid": {
  "min_value": 14, "max_value": 14, 
  "min_time_unit": "days", "max_time_unit": "days",
  "is_original": true, 
  "source_text": "cultured for 14 days"
}
```

**❌ WRONG: Using DurationRangeInfo for timepoints**
```json
"detect_time": {"min_value": 7, "max_value": 7, "min_time_unit": "days", "max_time_unit": "days", "is_original": true}
// Should use TimeAxisAnchorRefInfo → timing with TimeRangeNodeInfo
```

**✅ CORRECT: Using TimeAxisAnchorRefInfo for detection timing**
```json
"detect_time": {"id": 3, "name": "detect Ki67 expression"}
// References anchor in time_anchors: {"id": 3, "name_action": "detect Ki67 expression", "timing": {"min_value": 7, ...}}
```

### Decision Tree: Which Type to Use?

1. **Ask: "Am I describing WHEN (timepoint) or HOW LONG (duration)?"**
   - WHEN → TimeRangeNodeInfo (via TimeAxisAnchorInfo/TimeAxisAnchorRefInfo)
   - HOW LONG → DurationRangeInfo

2. **Ask: "Is this about a location on timeline or elapsed time?"**
   - Location → TimeRangeNodeInfo
   - Elapsed → DurationRangeInfo

3. **Ask: "Would I say 'on day X' or 'for X days'?"**
   - "on day X" → TimeRangeNodeInfo
   - "for X days" → DurationRangeInfo

## RULE 2: TYPE AND VALUE OF FIELD 
### REQUIRED FIELDS (non-Optional types)
Must ALWAYS contain a value. If the article does not report information, explicitly set the literal string 'not specified'. 

### OPTIONAL FIELDS — Token-Efficient Handling
- Optional[str] fields: 
  - PREFERRED: Completely omit the field from JSON output (saves tokens). The system will auto-fill with 'not specified'. 
  - ALTERNATIVE: Explicitly output 'not specified' if you prefer clarity. 
  - PROHIBITED: Never output null for Optional[str] fields. If the information is not mentioned in the article, omit the field entirely. 
- Optional[non-str] fields (int, List, etc.): 
  - PREFERRED: Omit the field from JSON output (saves tokens). The system will auto-fill with null. 
  - ALTERNATIVE: Explicitly output null. 
  - Both behaviors are equivalent and will result in null values.

### CONDITIONAL REQUIRED FIELDS
Fields marked with '[REQUIRED IF …]' behave as REQUIRED when the stated condition is true. Unless the field's own description explicitly allows additional optional uses outside that condition, they MUST be null (or omitted) when the condition is false.

### SUMMARY
For any Optional field where the article does not provide information, simply omit that field from your JSON output. Do not write 'field_name': null or 'field_name': 'not specified' unless you have a specific reason to make the absence explicit. This significantly reduces output token consumption while maintaining data integrity through default values.

## RULE 3: [💡]TAG — HIGHEST PRIORITY

**For name fields that use `StandardizedName` type**:
- `biomarker_name` (BiomarkerItemInfo)
- `name` (TargetedExpressionTargetInfo, AntibodyInfo)

**Structure**: `{"src": "text_from_article", "std": "canonical_symbol"}`
- `src`: EXACT name from original text
- `std`: Official nomenclature (HGNC/MGI gene symbols, UniProt protein names)
- If already standard, set std=src
- Examples: `{"src":"cGAS","std":"MB21D1"}`, `{"src":"p65","std":"RELA"}`, `{"src":"CD8","std":"CD8"}`

**For other FREE-TEXT string fields requiring inference**, use `[💡]` tag:
- Medium inference: `DMEM/F12 [💡]` (from manufacturer docs)
- Culture condition clarification: `37°C with 5% CO2 [standard culture conditions 💡]`
- Method description in free-text fields: `RT-PCR [inferred as qRT-PCR based on quantitative context 💡]`

**Field Type Classification for Tag Usage:**

**ENUM fields (tags PROHIBITED):**
- `BiomarkerItemInfo.detection_method` → Must output pure enum value (e.g., 'qRT-PCR', 'Immunofluorescence')
- `BiomarkerItemInfo.biomarker_type` → Must output pure enum value (e.g., 'Protein', 'RNA', 'Cell')
- Other schema fields explicitly defined as enum types
- **Inference handling**: Select best-matching enum value + document reasoning in `notes` field

**FREE-TEXT str fields (tags ALLOWED):**
- `TargetedExpressionInfo.method` → Can use `[💡]` tag (e.g., 'RT-PCR [qRT-PCR 💡]')
- `MultiOmicsXxxInfo.method` → Can use `[💡]` tag
- `OrganoidCultureStepInfo.medium` → Can use `[💡]` tag for inferred medium names
- Other schema fields explicitly defined as `str` type without enum constraints

**CRITICAL: Check field schema type before using tags. When in doubt, consult RULE 19 for PCR-specific guidance.**

## RULE 4: [🔎] TAG — HIGH PRIORITY
- Purpose: Indicate information retrieved from external documentation, manufacturer specifications, or authoritative databases to clarify or complete the ORIGINAL TEXT.
- Examples: 'MatTek medium [full product name 🔎]' from manufacturer specs.


## RULE 5: [❓️] Tag — Highest Priority
- **Purpose:** Mark data quality issues, anomalies, OCR errors, or scientifically questionable content in the ORIGINAL TEXT that require manual verification.
- **NOT FOR:** Professional inferences where original terminology is imprecise but meaning is clear from context (e.g., PCR method inference - see RULE 19: PCR_INTERPRETATION for that specific case).
- **Trigger:** Original text contains abnormal, non-standard, conflicting, or scientifically questionable information.
- **Actions:**
    1. Preserve the original text exactly and append [❓️] (e.g., 'TUJ1 [❓️]', '50 μg/mL [❓️]').
    2. Add a puzzles entry (source='Anomaly') describing the abnormality, the precise source location, and a short rationale.
    3. Optional: Use tools only for targeted verification of the suspected issue; document findings in puzzles and never overwrite original values.
- **Examples:** Non-standard names ('TUJ1' vs 'TUBB3'), implausible units ('FGF 50 μg/mL'), conflicting statements, or OCR artifacts.
- **DISTINCTION from Professional Inference Tags (💡 and 🔎):** The [❓️] tag marks DATA QUALITY ISSUES in the original text. It is completely different from professional inference tags: 💡 (lightbulb) indicates expert reasoning/inference (e.g., 'RT-PCR [qRT-PCR 💡]' for PCR method inference, 'TUJ1 [TUBB3 💡]' for gene symbol standardization), while 🔎 (magnifying glass) indicates information retrieved from external documentation (e.g., 'MatTek medium [full product name 🔎]' from manufacturer specs). See RULE 19: PCR_INTERPRETATION and BIOMARKERS sections for details.

### Anomaly Handling & [❓️] Tag Usage Guidelines
- **Tool Usage Scope Restriction([❓️] Tag)**
  - Tools can be using for targeted verification of suspected anomalies (e.g., checking antibody symbols, catalog numbers, implausible units). This is not a general search allowance.
  - When using a tool:
     - Trigger it when an error/non-standard term/implausible value is suspected.
     - Document findings in puzzles; never overwrite original structured values with tool outputs.
     - If an error is confirmed, append [❓️] to the original value and explain the discrepancy in puzzles.
- **Conflicting Labels vs Explicit Symbols([❓️] Tag)**
  - When ambiguous labels accompany precise gene/protein symbols (e.g., 'ceruloplasmin markers (KRT17)'), trust the explicit symbol.
  - Record it with `[❓️]` (e.g., `KRT17 [❓️]`) and create a puzzles entry explaining the mismatch (source='Anomaly').
- **OCR or Ambiguous Units([❓️] Tag)**
  - Suspect OCR or unit issues ('FGF 50 μg/mL') → copy exactly and append [❓️].
  - If unreadable, set the value to `not specified [❓️]` and quote the corrupted phrase in puzzles for manual review.
- **Numerical Values Must Never Be Corrected([❓️] Tag)**
  - Names can be standardized when unambiguous, but **all** numerical values (concentrations, timepoints, percentages) must remain exactly as reported.
  - Flag suspicious numbers with [❓️] and explain the concern in puzzles; never normalize or convert automatically. 

## RULE 6: COMMERCIAL PRODUCTS & MANUFACTURER MEDIA INFERENCE
When a commercial 3D tissue/organoid product is clearly specified with an unambiguous product ID (e.g., 'Human psoriatic skin equivalents (MatTek, SOR-300-FT)', 'EpiDerm'), the extractor MAY use the manufacturer's official documentation to complete cell composition and, where applicable, the name of the recommended maintenance medium. Use a three-tier rule: (1) If ORIGINAL_TEXT explicitly names the medium, ALWAYS follow ORIGINAL_TEXT and copy that name into `medium` (no tag needed). (2) If ORIGINAL_TEXT does NOT name the medium but clearly states that the product was 'cultured according to the manufacturer's recommendations', and the manufacturer defines a unique proprietary maintenance medium for that specific product, you MUST record that medium using the format 'Short name [Full proprietary medium name 🔎]' (e.g., 'MatTek medium [MatTek proprietary full-thickness maintenance medium 🔎]') instead of `medium='not specified'`, and MUST document this reasoning in puzzles (including manufacturer/product ID and the fact that the formulation is proprietary or not fully disclosed). The 🔎 symbol indicates information retrieved from external manufacturer documentation. (3) If multiple medium options exist, the product cannot be uniquely mapped to a single medium, or the manufacturer documentation is ambiguous, conflicting, behind paywalls, or not available, you MUST NOT guess names or compositions; set medium and related culture-material fields to 'not specified' and explicitly explain the limitation in puzzles. Engineering/device-focused papers that omit post-print culture conditions must be handled the same way—never infer medium solely from cell type, tissue type, or typical practice. In summary: either the medium is explicitly named in the article, or it is uniquely retrieved from manufacturer documentation with a [🔎] tag plus puzzles documentation; all other cases MUST use `medium='not specified'`.

## RULE 7: Source Text Truncation Detection
- **When:** XML-style tags in **PRIMARY DATA block** have opening tag but lack matching closing tag.
  - ✓ Complete: `<KNOWLEDGE>full content here</KNOWLEDGE>` (properly closed)
  - ✗ Truncated: `<KNOWLEDGE>partial content` (missing `</KNOWLEDGE>`)
  - ⊘ Not truncation: Backtick references like `KNOWLEDGE` in descriptive sections (HTML TAGS DESC, rule text) are NOT data containers and should be ignored for truncation detection.
- **Detection scope:** ONLY check tags inside PRIMARY DATA block. Do NOT flag backtick-wrapped terms (`xxxxx`) or tag references in HTML TAGS DESC / instructional text as truncation.
- **Actions:**
    1. Create a puzzles entry with source='Source' and severity='Blocking'.
    2. Use the summary template `Source text appears truncated. Start: <first 5-10 words> ... End: <last 5-10 words>` (e.g., 'Start: Cells were cultured in ... End: analyzed using flow cytometry methods').
    3. List all affected fields; set their values to 'not specified' (or sentinel codes) and explain the truncation in `notes`/`time_desc`.
    4. Never invent missing steps, media compositions, or timepoints.

## RULE 8: Manufacturer-Recommended Media (Conservative Handling)
- If text says the model was 'cultured according to the manufacturer's recommendations' without specifying the medium, OR the text lacks a unique commercial product ID that can be mapped to a single, well-defined maintenance medium in manufacturer documentation, set `medium='not specified'` and record the limitation in puzzles. Do not infer the medium from generic manufacturer recommendations alone. 
- Only when a unique product ID is provided AND manufacturer documentation defines exactly ONE maintenance/maintenance-like medium for that specific product, you MUST record that medium using the format 'Short name [Full proprietary medium name 🔎]' (rather than `medium='not specified'`) and explain the retrieval source in puzzles, consistent with the COMMERCIAL PRODUCTS & MANUFACTURER MEDIA INFERENCE rule."

## RULE 9: Missing Concentrations or Vendor Information
- For ANY material (medium, supplement, growth factor, small molecule, matrix, enzyme, buffer, solvent, or commercial kit/assay) where the vendor name, catalog number, product identifier, or URL cannot be verified from the article text, DO NOT guess or infer missing supplier information. Set `source='not specified'` in material_source and create a puzzles entry (source='Source') explaining which supplier information is missing or unverifiable and why. This includes cases where documentation is ambiguous, paywalled, discontinued, conflicting, or not accessible.

## RULE 10: Multiple Concentrations for the Same Material in a Single Step
- When a single protocol step reports alternative concentrations for the same material within one nominal condition (e.g., 'CHIR99021 1 or 3 µM'), you MAY encode a single material_source entry with concentration='1 or 3 µM' to reflect the ambiguity directly.
- When different concentrations clearly correspond to distinct experimental conditions or groups (e.g., '1 µM for group A, 3 µM for group B'), represent them as separate culture steps and separate material_source entries per condition, rather than merging them into a single 'X or Y' value.
- For binary 'presence or absence' wording (e.g., 'cultured in crypt culture medium in the presence or absence of Rspo1'), treat '+Rspo1' and '−Rspo1' as distinct experimental conditions. Prefer representing them as separate culture steps (or separate experimental groups in downstream metadata). In the '+Rspo1' step include Rspo1 in growth_factors/material_source; in the 'absence' step omit Rspo1 entirely rather than encoding a single ambiguous material entry.

## RULE 11: Incomplete Antibody Information
- If the text only states 'stained with antibodies' (no targets/clones/product IDs), do not invent details.
- Treat such antibodies as assay-only (exclude from `material_source`). For biomarkers, only record explicit molecular targets; otherwise, omit the biomarker entry.



## RULE 13: CO-CULTURE DECISION TREE
- Step 1: Check whether additional cells/organisms are present in the SAME microenvironment as the core 3D structure (same well/chamber/matrix) AND are maintained as identifiable, ongoing partners rather than single-shot treatments. If NO, set if_co_culture=false. If YES, go to Step 2.
- Step 2: If multiple cell types are mixed from the very beginning to form a single, inseparable 3D construct with no concept of 'host' vs 'partner' (e.g., mixed tumor spheroids with cancer + fibroblasts described as a single spheroid or single organoid model), represent all such populations as role='organoid_core' components and set if_co_culture=false.
- Step 3: For additional cellular partners (immune cells, stromal cells, feeder layers, vascular cells, pericytes, etc.) that are added AFTER an identifiable core has formed, or where the text explicitly uses interaction language such as 'co-culture', 'overlay', 'introduced', 'added to organoids', 'co-seeded with organoids', set if_co_culture=true and add all partners as non-core roles in composition (immune_co-culture, stromal_support, feeder_layer, vascular_support, pericyte_support, other-co-culture, etc.). 
- Step 4: For microbes (virus/bacterium/fungus/parasite) that physically share the culture microenvironment with the organoid/core model in a way that is central to the study question (infection models, pathogen challenge, colonization, etc.), ALWAYS treat them as bona fide co-culture partners: set if_co_culture=true, add components with role='microbial-co-culture' in composition, and populate co_culture_type.Microorganism accordingly. At the same time, record the infection/challenge as explicit culture steps and material_source entries capturing timing, MOI and application method. ONLY exclude microbes from composition/co_culture_type when they are incidental contaminants, background microbiota not manipulated or analyzed, or purely hypothetical pathogens that never contact the culture in the described experiments.
- Step 5: **MULTI-ORGAN BOUNDARY ENFORCEMENT**: When multiple organoid_core components exist (e.g., kidney+liver organoids, brain region fusion), if_co_culture=true is ONLY allowed when NON-CORE cellular partners (immune cells, stromal cells, feeder layers, vascular cells, pericytes) or microorganisms are also present. Pure multi-organ systems (ONLY organoid_core components, no external partners) MUST use if_co_culture=false + composite_role='Composite organoid system', regardless of interaction language. Organoid-organoid interactions alone do NOT constitute co-culture in this schema.
- Step 6: When the text clearly emphasizes interaction between 'organoid' and another population but omits precise timing, prefer if_co_culture=true for cellular partners and document the ambiguity and reasoning in puzzles. Mixed-cell spheroids that are only ever described as a single, inseparable 3D construct without interaction language remain if_co_culture=false with multiple organoid_core components.

## RULE 14: BIOMARKERS, VIABILITY DYES & CONFLICTING LABELS
Do NOT create biomarker entries for routine morphology-only stains or generic labels without specific molecules (e.g., DAPI or Hoechst used solely as nuclear counterstains, H&E staining, vague 'cytokines' or 'inflammatory markers'). For cell-state dyes (Calcein-AM, PI, Annexin V), biomarker_type MUST be 'Cell'. NEVER use 'Live Cell' or 'Dead Cell' as biomarker_type; those enum values exist only for backward compatibility and MUST NOT be used by the extractor. Apply the following decision rule for nuclear dyes: (1) If DAPI/Hoechst are used solely to visualize nuclei, count total cells, or show morphology, EXCLUDE them from biomarker extraction. (2) If the same dye is explicitly used to distinguish states (e.g., dead vs live, apoptotic vs non-apoptotic), then create biomarker entries with state-based biomarker_name (e.g., 'Dead cell', 'Apoptotic cell') and biomarker_type='Cell'. When a broad or potentially incorrect label appears together with a precise gene/protein symbol (e.g., 'ceruloplasmin markers (KRT17)'), ALWAYS use the explicit symbol in StandardizedName structure: {"src":"KRT17 [❓️]","std":"KRT17"} and document the suspected mislabeling in puzzles. Widely used clone/shorthand markers (e.g., 'TUJ1', 'NeuN') should use StandardizedName structure ONLY when the mapping is unambiguous and community-standard (e.g., {"src":"TUJ1","std":"TUBB3"}, {"src":"NeuN","std":"RBFOX3"}). If the mapping is uncertain or non-standard, use {"src":"TUJ1 [❓️]","std":"TUJ1"} to flag it as questionable. Numeric values (concentrations, doses, durations) and units must NEVER be corrected or converted; if they seem implausible, keep them as written and flag with '[❓️]'. When a biomarker is only reported as being 'expressed', 'present', or 'active' without any explicit or inferable timepoint, you MUST reference time_anchor system where possible or leave the biomarker time field unset (omit/null) with explanation in notes/time_desc or puzzles.

## RULE 15: COMPOSITE ORGAN CONSTRUCTS & ORGAN-SYSTEM MAPPING
Multi-organ models (e.g., 'skin with hair follicles and nervous system', 'heart-liver organoid') MUST use OrganoidBaseInfo.organ as the canonical mapping {OrganEnums: [OrganSystemEnums]}. All organs present in the construct MUST appear as keys, and each key's system list MUST exactly match the mapping defined in KNOWLEDGE['ORGAN_AND_SYSTEM'], including all systems for multi-system organs (e.g., Thymus_Gland → ['Endocrine System', 'Lymphatic System']). If an organ can only be mapped to OrganEnums.Others, its system list MUST be ['Others']. OrganoidComponentInfo.organ MUST always be a subset of the keys in OrganoidBaseInfo.organ; component-level systems MUST NOT be stored explicitly and are instead derived from this mapping. OrganoidBaseInfo.composite_role encodes how the culture participates in composite systems and MUST use one of: 'Single organoid only', 'Composite organoid system', 'Precursor-only module for composite', 'Single organoid and precursor for composite'. Composite or multi-organ constructs MUST be represented by multiple OrganoidComponentInfo entries, each describing one homogeneous cell population (single cell_type, single species, single role, and a well-defined organ tag list); do NOT use nested dicts like {'Heart': ['cardiomyocytes'], 'Liver': ['hepatocytes']} inside a single component. OrganoidComponentInfo.organoid_origin allows different organ modules in a composite model to have distinct origin types (e.g., heart module from iPSCs, liver module from PDOs), while supporting cells (stromal, immune, vascular, feeder) typically have organoid_origin=null and are described via cell_source and organ tags. The optional OrganoidComponentInfo.sub_organoid_model field is a LIST of human-readable sub-organoid names; each entry MUST be a non-empty string ending with 'organoid' (e.g., 'Heart organoid', 'Liver organoid'). Composite labels such as 'heart-liver construct' or 'heart-liver organoid' are PROHIBITED here; if a component contributes to more than one organ module (e.g., shared perfusion endothelium), enumerate each sub-organoid separately (e.g., ['Heart organoid', 'Liver organoid']). NEVER invent new OrganEnums/OrganSystemEnums or add extra organs/modules beyond what is clearly supported by the article; when information is incomplete, restrict organs, composite_role, and sub_organoid_model entries to what is textually justified and explain unresolved ambiguities in puzzles. As a high-level rule for splitting cultures: if the article clearly describes separate, reproducible protocols and analytical readouts for individual organoid modules (e.g., standalone liver organoids and standalone heart organoids that are later assembled), represent each module as its own OrganoidCultureResult with composite_role='Precursor-only module for composite' or 'Single organoid and precursor for composite' as appropriate, and represent the assembled system as an additional OrganoidCultureResult with composite_role='Composite organoid system'. If the article only reports a single, integrated protocol for the assembled construct and does not treat the parts as standalone organoids, use a single OrganoidCultureResult with composite_role='Composite organoid system' and do NOT invent precursor-only entries. NEVER copy composite-stage media/steps/biomarkers back into standalone precursor OrganoidCultureResult entries when attribution is unclear—such information should be stored only in the composite culture entry.

## RULE 16: ORGAN INFERENCE FROM CELL-TYPE LABELS (CONTROLLED HEURISTICS)
- Primary organ assignment MUST come from explicit organ-level information in the article (e.g., 'brain organoids', 'liver organoids', 'cortical organoids'). 
- When such explicit organ labels exist, OrganoidBaseInfo.organ MUST be derived from them, and OrganoidComponentInfo.organ for organoid_core components SHOULD inherit these organ tags, regardless of the specific cell_type names ('neural progenitor cells', 'astrocytes', etc.). 
- Only when the article provides no explicit organ names and the culture is described solely by cell-type or lineage labels (e.g., 'neural progenitor cells (NPCs) were used'), the extractor MAY infer an OrganEnums value from a small whitelist of strongly organ-specific cell-type labels. 
- This is a controlled heuristic and MUST be accompanied by a note in puzzles. 
- Examples of allowed high-specificity mappings: 'neural progenitor cells (NPCs)' or 'neural progenitor cells' (no explicit organ context) → infer OrganEnums.Brain by default and map to 'Nervous System' via ORGAN_AND_SYSTEM, unless the text explicitly refers to a non-brain neural tissue (e.g., spinal cord, retina). 'hepatocytes' or 'hepatocyte-like cells' (without conflicting context) → infer OrganEnums.Liver. 'cardiomyocytes' or 'ventricular cardiomyocytes' (without conflicting context) → infer OrganEnums.Heart. Additional mappings MAY be added conservatively for other clearly organ-specific cell types. For all other generic or ambiguous labels (e.g., 'epithelial cells', 'progenitor cells', 'mesenchymal stem cells'), the extractor MUST NOT infer a specific OrganEnums value. In these cases, set OrganoidBaseInfo.organ to {OrganEnums.Others: ['Others']} (or another explicitly supported organ if provided elsewhere in the article) and leave OrganoidComponentInfo.organ empty (or set to [OrganEnums.Others] if a generic placeholder is required), documenting this uncertainty in puzzles. 

## RULE 17: STEP_SCOPE AND MATERIAL SOURCE_TYPE MAPPING (SIMPLIFIED DECISION TREE)
When assigning source_type for materials in protocol steps, apply the following sequential rules.   
1. For step_scope='organoid_core_only': always use source_type='organoid' and create exactly ONE material_source entry for each distinct material (per combination of material_name + concentration). 
2. For step_scope='co_culture_only': always use source_type='coculture' and create exactly ONE material_source entry per distinct material. 
3. For step_scope='specific_components': if target_components include only organoid_core components (role='organoid_core'), use source_type='organoid'; if they include only co-culture components, use source_type='coculture'; if they include both, you MAY create two entries (one 'organoid' and one 'coculture') but this is recommended only when the article clearly indicates differential targeting. 
4. For step_scope='whole_system': 
   1. If the text explicitly describes the material as supporting only co-culture partners (e.g., 'added IL-2 to support T cell survival in co-culture'), use a single source_type='coculture' entry. 
   2. If the text explicitly describes a system-wide perturbation intended to act on the entire organoid-co-culture system (e.g., drug screening, hypoxia, infection), and if_co_culture=true, the extractor SHOULD create two entries (one with source_type='organoid' and one with source_type='coculture'). 
   3. For vague or maintenance-like wording (e.g., routine medium changes), default to a single source_type='organoid' entry and optionally explain the ambiguity in puzzles. The existence or absence of whole_system vs co_culture_only steps MUST NEVER be used to infer, override, or contradict OrganoidBaseInfo.if_co_culture or the presence of co-culture components in composition; co-culture status is determined solely from composition/co_culture_type and the CO-CULTURE DECISION TREE, not from protocol step scopes.

## RULE 18: MICROBIAL CO-CULTURE RULES

### Scope
Any virus/bacterium/fungus/parasite experimentally introduced into, or explicitly sharing, the culture microenvironment in an infection/challenge/colonization context MUST be represented as a co-culture partner.

### Minimum Requirements (ALWAYS REQUIRED)
When microorganism is present in co-culture:
1. Set `if_co_culture=true`
2. Add at least one composition component with `role='microbial_co-culture'`

### Co_culture_type.Microorganism - Mandatory vs Optional

**MANDATORY (MUST fill when article provides):**
- **Genus + species name**: "Lactobacillus reuteri", "Escherichia coli", "Staphylococcus aureus"
- **Common viral name**: "SARS-CoV-2", "HIV-1", "Influenza A virus", "HBV"
- **Abbreviated name with clear identity**: "L. reuteri D8", "E. coli K-12"
- **Strain/variant identifier**: "D8", "K-12", "Delta variant", "ATCC 4356"

**When MANDATORY, populate:**
```json
"co_culture_type":{"Microorganism":[{
  "microorganism_type":"Bacteria",  // or Virus/Fungi/Parasite
  "scientific_name":"Lactobacillus reuteri",
  "strain":"D8"  // if specified
}]}
```

**OPTIONAL (may omit only when):**
- Article only mentions generic terms: "bacteria", "microbes", "viral infection" (no species)
- Mixed undefined microbiota: "gut microbiota", "fecal microbiota" (without specific strains)
- No identification provided beyond broad category

### Information Sufficiency Examples

✅ **SUFFICIENT** (MUST fill co_culture_type.Microorganism):
- "L. reuteri D8" → scientific_name='Lactobacillus reuteri', strain='D8', microorganism_type='Bacteria'
- "E. coli K-12" → scientific_name='Escherichia coli', strain='K-12', microorganism_type='Bacteria'
- "SARS-CoV-2" → scientific_name='SARS-CoV-2', microorganism_type='Virus'
- "Candida albicans SC5314" → scientific_name='Candida albicans', strain='SC5314', microorganism_type='Fungi'

❌ **INSUFFICIENT** (may leave co_culture_type.Microorganism null):
- "bacteria" (no species) → only composition with role='microbial_co-culture', cell_type='Bacteria [❓️]'
- "gut microbiota" (mixed) → only composition, note in puzzles
- "viral challenge" (no virus name) → only composition, cell_type='Virus [❓️]'

### Additional Encoding (when clearly reported)
- **(d)** Encode infection/challenge as explicit culture steps
- **(e)** Add material_source entries with timing/MOI/application_method

### Consistency Rule
When `co_culture_type.Microorganism` is provided, `composition` MUST contain at least one component with `role='microbial_co-culture'` describing the same microorganism.

### Error Handling
- Missing co_culture_type.Microorganism when species name is clearly stated → **Structure Error**
- Missing microbial_co-culture in composition when microbe is clearly co-cultured → **Structure Error** 

## RULE 19: PCR_INTERPRETATION
Always apply the following steps at the ARTICLE level before assigning method for any PCR-based assay. Output format depends on field type:

**OUTPUT FORMAT BY FIELD TYPE:**
- **ENUM fields** (e.g., `BiomarkerItemInfo.detection_method`): Output pure enum value + use `notes` for reasoning
  - Example: `{"detection_method": "qRT-PCR", "notes": "Original text: RT-PCR. Inferred from quantitative context."}`
- **FREE-TEXT fields** (e.g., `TargetedExpressionInfo.method`): Can use `[💡]` tag OR notes
  - Example A: `{"method": "RT-PCR [inferred as qRT-PCR 💡]"}`
  - Example B: `{"method": "qRT-PCR", "notes": "Original: RT-PCR, inferred from quantitative context"}`

### STEP 1
SCAN FOR EXPLICIT qPCR FEATURES (HIGH-CONFIDENCE EVIDENCE): Scan the entire article (Methods, Results, figure legends) for any qPCR-specific terminology: 'qRT-PCR', 'real-time PCR', 'quantitative PCR', 'Ct', 'ΔCt', 'ΔΔCt', 'SYBR Green', 'TaqMan', 'melting curve', 'real-time fluorescence', 'real-time thermocycler/instrument'. If ANY of these appear AND they are clearly linked to mRNA expression assays, then: 
  - The assay is confirmed as 'qRT-PCR'. 
  - **ENUM fields**: Output 'qRT-PCR' directly (pure enum value, no tags)
  - **FREE-TEXT fields**: Output 'qRT-PCR' OR 'RT-PCR [qRT-PCR 💡]' (both acceptable)
  - Document original wording in `notes` if needed for clarity 

### STEP 2
SCAN FOR END-POINT PCR FEATURES (HIGH-CONFIDENCE EVIDENCE): Look for explicit end-point PCR indicators: 'agarose gel electrophoresis', 'PCR bands', 'semi-quantitative RT-PCR', 'gel-verified amplicons', 'band intensity', 'ethidium bromide gel', etc. If these are present and linked to RT-PCR, classify the method as 'End-point RT-PCR' regardless of vague phrasing.

### STEP 3
APPLY BIOLOGICAL COMMON-SENSE INFERENCE (MODERATE-CONFIDENCE EVIDENCE): When explicit qPCR/end-point features are absent BUT the context strongly suggests quantitative analysis, use professional judgment to infer the likely method while respecting the original terminology:
- QUANTITATIVE CONTEXT INDICATORS (suggest qRT-PCR): 
  - Expression described as 'dose-dependent', 'fold-change', 'upregulated X-fold', 'downregulated by Y%'
  - Comparative quantification: 'significantly higher/lower expression', 'increased/decreased levels'
  - Statistical analysis of expression levels (t-test, ANOVA on expression data) 
  - Normalized to housekeeping genes/reference genes 
- OUTPUT FORMAT FOR INFERRED qRT-PCR:
  - **ENUM fields** (e.g., biomarker detection_method):
    - Field value: 'qRT-PCR' (pure enum, NO tags)
    - notes: 'Original: RT-PCR. Inferred as qRT-PCR from quantitative context (fold-change, statistical comparison, housekeeping normalization).'
  - **FREE-TEXT fields** (e.g., targeted_expressions method):
    - Option A: 'RT-PCR [inferred as qRT-PCR based on quantitative context 💡]'
    - Option B: 'qRT-PCR' + notes='Original: RT-PCR, inferred from context'
  - Rationale: (1) Respects original terminology, (2) Provides correct value for analysis, (3) Documents reasoning

### STEP 4
NO EVIDENCE FOR CLASSIFICATION (LOW-CONFIDENCE): 
When the article provides NEITHER explicit technical features NOR quantitative context (e.g., only states 'RT-PCR was performed' without describing results), classify as 'RT-PCR [unspecified subtype]' and record this ambiguity in puzzles. 

### STEP 5
PRIORITY HIERARCHY (APPLY IN ORDER): 
1. Explicit technical terminology (STEP 1 or 2) → Use confirmed enum value (e.g., 'qRT-PCR', 'End-point RT-PCR')
2. Quantitative context without explicit features (STEP 3) → Use inferred enum value + document in notes (e.g., detection_method='qRT-PCR', notes='Inferred from quantitative context')
3. No useful context (STEP 4) → Use closest enum value or 'Other' + document ambiguity in notes/puzzles 


### STEP 6
CLARIFICATION: PCR method inference is professional reasoning, NOT a data quality issue.

**When original text uses imprecise terminology ('RT-PCR') but context indicates qRT-PCR:**

**For ENUM fields** (e.g., `BiomarkerItemInfo.detection_method`):
- ✅ CORRECT: `detection_method='qRT-PCR'` + `notes='Original: RT-PCR, inferred from quantitative context'`
- ❌ WRONG: `detection_method='RT-PCR [qRT-PCR 💡]'` (tags prohibited in enum fields)

**For FREE-TEXT fields** (e.g., `TargetedExpressionInfo.method`):
- ✅ CORRECT: `method='RT-PCR [inferred as qRT-PCR 💡]'` (tag allowed in free-text)
- ✅ ALSO CORRECT: `method='qRT-PCR'` + `notes='Original: RT-PCR, inferred from context'`

**NEVER use [❓️] for method inference:**
- ❌ WRONG: `'RT-PCR [❓️]'` (not a data quality issue)
- The [❓️] tag is ONLY for questionable/anomalous data (implausible values, OCR errors), NOT professional inference

### STEP 7
MULTIPLE TARGETS AND PROBES PER ASSAY BLOCK: 
- When one PCR/qPCR description lists primers for more than one target (e.g., a viral RNA target plus a housekeeping gene such as B2M), you MUST instantiate one PCRTargetInfo entry per target, each with exactly ONE primer pair (forward + reverse), even if they share the same reaction mix and cycling conditions. 
- TaqMan or other hybridization probes (e.g., FAM/BHQ-labelled oligos) are NOT primers and MUST NOT be placed in the primers field; instead, record them as ExperimentalMaterialInfo items with material_type='probe' (or the closest existing probe-like category) and link them to the corresponding target via notes/purpose.
- **When extracting from primer tables**: See RULE 25: COMPLETE PRIMER TABLE EXTRACTION for validation rules to ensure ALL table rows are extracted without omissions.

## RULE 20: GLOBAL EXTRACTION RULES
### ONE entity per item
When source text lists multiple entities (e.g., "OCT4, SOX2, and NANOG"), create separate items for each. Do NOT pack multiple entities into a single array element.

### Nomenclature
Use standard nomenclature for genes and proteins:
- Gene symbols: HUGO for human (e.g., 'TUBB3'), MGI for mouse
- Protein names: Follow UniProt conventions
- For name fields using StandardizedName type (biomarker_name, target names, antibody names): provide both src (original) and std (canonical). Examples: {"src":"TUJ1","std":"TUBB3"}, {"src":"NeuN","std":"RBFOX3"}

### Units
Always include units with numerical values (e.g., "10 µM", not "10"). Never output bare numbers for concentrations, volumes, or physical quantities.

### Source preservation
Copy exact terminology from paper when possible. Explain abbreviations if used repeatedly. Preserve original wording while ensuring clarity.

### Multiple protocols
Create separate culture entries (OrganoidCultureResult) ONLY when species/origin/organoid type differs significantly. Do NOT split protocols for minor variations in medium or timepoints within the same biological system.

## RULE 21: PUZZLE REPORTING
### Purpose
Puzzles are used to flag schema/rule/documentation issues that prevent correct extraction, NOT data errors (use errors field for those).

### When to USE puzzles
- **Rule contradictions**: Two or more rules conflict, making correct decision impossible
- **Missing/unclear documentation**: Field descriptions are ambiguous, incomplete, or missing critical information
- **Schema design gaps**: No appropriate field/enum exists for certain data types mentioned in articles
- **Conflicting examples**: Documentation examples contradict field descriptions or other rules
- **Tool ambiguity**: Unclear which tool to use for a specific data type (for data_searcher)

### When NOT to use puzzles
- ❌ Normal extraction decisions (enum selection, material classification, time inference when rules are clear)
- ❌ Data errors or scientific inaccuracies (use errors field instead)
- ❌ Search failures or missing data (for data_searcher: just record the failure)
- ❌ Difficulty interpreting source text (document in notes, not puzzles)
- ❌ Well-defined choices between clear options (that's the extraction task itself)

### Puzzle structure
When reporting a puzzle, provide:
- **severity**: Blocking / Degrading / Inconvenient (impact level)
- **source**: TaskRules / FieldDoc / Validation / Structure / Anomaly / Source
- **source_desc**: Specific location (e.g., ["OrganoidCultureStepInfo.medium"])
- **puzzle_reason**: Root cause description (be specific)
- **fix_type**: DocClarify / ExampleAdd / EnumExpand / FieldAdd / RuleRevise / ToolDoc
- **fix_target**: What to fix (e.g., "RULE 1: TIME EXTRACTION priority 2 definition")
- **fix_action**: Specific actionable fix (e.g., "Add counter-example showing X")

### Special case: Anomaly puzzles
Use source='Anomaly' for source data quality issues (scientifically implausible values, contradictions in ORIGINAL_TEXT, mislabeling). These are NOT schema issues but data quality flags for manual review. Report even when extraction is correct with [❓️] marker.

---

## RULE 24: COMPLETE MEDIUM FORMULA EXTRACTION (CRITICAL - GROWTH FACTOR OMISSIONS)
**Trigger**: Article lists complete medium composition (e.g., "Complete medium containing advanced DMEM/F12, 2 mM Glutamax, 10 mM HEPES, B27, N2, 50 ng/ml EGF, 100 ng/ml Noggin, and 250 ng/ml R-spondin 1")

**Mandatory Validation Before Finalizing**:
1. Count ALL components in original formula text
2. Count extracted entries in growth_factors/supplements/small_molecules fields
3. **If counts mismatch → RE-SCAN immediately**
4. **R-spondin 1/2/3/4 check**: If present in text → MUST be in growth_factors field

**High-Risk Omission Patterns**:
- ❌ R-spondin variants (most frequently missed even when explicitly listed)
- ❌ Third/fourth growth factor in comma-separated lists
- ❌ Components after "and" in long formulas
- ❌ Wnt pathway factors (Wnt3a, R-spondin, DKK inhibitors)

**Error Example**:
```
TEXT: "...50 ng/ml EGF, 100 ng/ml Noggin, and 250 ng/ml R-spondin 1"
❌ WRONG (Structure Error -5pts): growth_factors:[{material_name:"EGF",concentration:"50 ng/ml"},{material_name:"Noggin",concentration:"100 ng/ml"}]
✅ CORRECT: growth_factors:[{material_name:"EGF",concentration:"50 ng/ml"},{material_name:"Noggin",concentration:"100 ng/ml"},{material_name:"R-spondin 1",concentration:"250 ng/ml"}]
```

---

## RULE 25: COMPLETE PRIMER TABLE EXTRACTION (CRITICAL - TARGET OMISSIONS)
**Trigger**: Article contains primer table (often "Table 1", "Supplementary Table") with headers like "Target genes", "Primer sequences", "Forward/Reverse", "Product size"

**Related Rules**: 
- See RULE 19 STEP 7 for creating separate PCRTargetInfo entries per target (one entry = one primer pair)
- This rule focuses on TABLE COMPLETENESS validation to prevent systematic target omissions

**Mandatory Validation Before Finalizing**:
1. Locate primer table in Methods/Supplementary
2. Count total data rows (exclude header): _____
3. Count extracted TargetedExpressionTargetInfo entries: _____
4. **If counts mismatch → RE-SCAN entire table and extract ALL rows**

**High-Risk Omission Patterns**:
- ❌ Cherry-picking only ISC markers (Lgr5, Olfm4, Ascl2) → missing differentiated cell markers
- ❌ Extracting only Paneth markers (Lyz1, Defa6) → missing goblet (Muc2), enterocyte (Alpi), enteroendocrine markers
- ❌ Stopping after first 5-6 genes
- ✅ **Extract EVERY row - table = complete tested gene set**

**Housekeeping Gene Identification**: GAPDH, ACTB (β-actin), 18S rRNA, HPRT1, TBP, B2M, TUBB → target_type='Housekeeping'. All others → target_type='Target'.

**Error Example** (8 rows in table, only 6 extracted):
```
TABLE: mLgr5|mOlfm4|mAscl2|mLyz1|mMuc2|mAlpi|mDefa6|mGADPH (8 rows)
❌ WRONG (Structure Error -10pts): target:[{target_type:"Target",name:"Lgr5"},{target_type:"Target",name:"Olfm4"},{target_type:"Target",name:"Ascl2"},{target_type:"Target",name:"Lyz1"},{target_type:"Target",name:"Defa6"},{target_type:"Housekeeping",name:"GAPDH"}]
✅ CORRECT: target:[{target_type:"Target",name:"Lgr5"},{target_type:"Target",name:"Olfm4"},{target_type:"Target",name:"Ascl2"},{target_type:"Target",name:"Lyz1"},{target_type:"Target",name:"Muc2"},{target_type:"Target",name:"Alpi"},{target_type:"Target",name:"Defa6"},{target_type:"Housekeeping",name:"GAPDH"}]
```

**Biological Context** (DO NOT assume "less important"):
- Intestinal: ISC (Lgr5/Olfm4/Ascl2), Paneth (Lyz1/Defa6), Goblet (Muc2/Tff3), Enterocyte (Alpi/Vil1), Enteroendocrine (ChgA/Neurog3)
- Brain: Progenitor (SOX2/PAX6/NESTIN), Neuron (TUBB3/MAP2), Astrocyte (GFAP/S100B), Oligodendrocyte (OLIG2/MBP)

## RULE 26: TIME AXIS EXTRACTION — ANCHORS, SEGMENTS, BRANCHES, AND TIMELINE STRUCTURE

**Rule Scope**: This rule defines the TECHNICAL ARCHITECTURE of time_axis (data structures, anchor/segment/branch mechanics, day/duration extraction rules). For USAGE GUIDELINES on when to create branches vs use Main timeline, see RULE 27: TIME AXIS BRANCH USAGE.

### Architecture Overview: time_anchors + time_axis Dict Structure

OrganoidCultureResult contains two linked structures:

**time_anchors** (array): Global list of all unique timepoints
- Each anchor: {id, name_action/name_cell_state/name_morphology, day, desc}
- Single source of truth—no duplicate anchors
- Ordered chronologically when possible

**time_axis** (object/dict): Named segments referencing anchors by id
- Keys: "Main" (required), "Branch:Sampling", "Branch:Infection", etc.
- Values: {start_anchor:{id,name}, end_anchor:{id,name}, repeat, duration}
- Anchors referenced by id+name, not embedded

**Example:** time_anchors=[{id:1,name_action:"seeding",day:0}, {id:2,name_action:"passage",day:null}], time_axis={"Main":{start_anchor:{id:1,name:"seeding"}, end_anchor:{id:2,name:"passage"}}}

---

### Anchor Day Extraction (HIGHEST PRIORITY)

TimeAxisAnchorInfo.day MUST be filled ONLY when article EXPLICITLY states absolute day number:

**ALLOWED (fill day field):**
- "Cells were seeded on day 0" → day=0 ✓
- "On day 5, organoids were passaged" → day=5 ✓
- "At day 14, analyzed" → day=14 ✓

**PROHIBITED (day MUST be null):**
- "After 48 hours, antibody was added" → day=null (relative time only)
- "Medium replaced every two days" → day=null (recurring event, no specific day)
- "To passage PDOs, organoids were harvested..." → day=null (protocol template, no timing)
- "When confluent, cells were split" → day=null (condition-based)

**DO NOT infer days from:**
- Repeat intervals: "every 2 days" does NOT mean "first change at day 2"
- Backward calculation: Later mention of "day 14" does NOT imply "passage at day 7"
- Pattern assumptions: "every 2 days until passage" does NOT justify guessing passage day

---

### Duration Extraction Rules

Duration MUST come from ORIGINAL_TEXT or explicit calculation:

**Rule 1: Explicit duration statement (HIGHEST PRIORITY)**
- Text says "cultured for 5 days" → duration.value=5, time_unit='days' ✓
- Text says "incubated for 1 week" → duration.value=7, time_unit='days' (1 week = 7 days, NOT 5!)
- Text says "for 48 hours" → duration.value=48, time_unit='hours' ✓

**Rule 2: Both anchors have EXPLICIT days from text**
- Text: "day 5...day 12" → duration = 12-5 = 7 days ✓
- CRITICAL: Both days must be explicitly stated in text, not inferred

**Rule 3: Same-day events**
- Text: "collected and immediately digested" → duration=0 days (or specific time like '30 min') ✓
- Only use duration=0 when events clearly occur on same day

**Rule 4: Cannot determine**
- No explicit duration AND any anchor's timing is null → duration=null
- DO NOT fill duration=0 as placeholder for unknown duration

**CRITICAL: Duration must be natural number (positive integer) or 0 for same-day events. If unknown, use null.**

---

### Repeat Operations Handling

When article describes recurring operations (e.g., "medium changed every 2 days"):

**Structure rules:**
1. Create ONE segment covering entire repeat period (not separate segments for each occurrence)
2. start_anchor = baseline/initiation point (NOT first occurrence)
   - Example: "After solidification, medium replaced every 2 days" → start = solidification, NOT day 2
3. DO NOT create individual anchors for each occurrence (e.g., don't create day 2, 4, 6, 8 from "every 2 days")
4. If end condition is vague ("until passage", "until confluent"), end_anchor's timing MUST be null

**CORRECT:** start_anchor=baseline (solidification), end_anchor=termination (passage), repeat={repeat_interval:"every 2 days", repeat_end:"until passage"}, duration=null
**WRONG:** ❌ end_anchor=first occurrence (day 2), ❌ creating anchors for each occurrence (day 2,4,6,8)

---

### TimeAxisBranchInfo Structure (CRITICAL)

**Core Concept**: A complete timeline is composed of **multiple ordered segments** (not a single segment).

**TimeAxisBranchInfo Fields**:
- `branch_name`: Semantic label ("Main", "VirusExpansion", "LiverOrganoid", "DrugA")
- `component_id`: Component ID from composition ("C1", "C2", "C3", etc.) or null for treatment arms
- `axes`: List[TimeAxisSegmentInfo] — ordered segments forming the complete timeline
- `is_main`: Boolean — True for Main branch, False for others

**axes Key Rules**:
- **Anchor IDs are opaque identifiers — lower ID does NOT mean earlier in time.** Chronological order is determined EXCLUSIVELY by the axes segment sequence.
- axes[0] = earliest phase (e.g., seeding/thawing); axes[-1] = latest phase (e.g., final endpoint/merge point)
- Consecutive segments MUST share the same anchor endpoint: `axes[i].end_anchor.id == axes[i+1].start_anchor.id`
- Zero-length segments are PROHIBITED: `start_anchor.id` MUST NOT equal `end_anchor.id`
- Each branch must cover ALL MILESTONE anchors of its own component; MILESTONE anchors from other components MAY be omitted
- OBSERVATION anchors MUST NEVER appear as segment endpoints

**time_axis Example Structure** (note: IDs are non-consecutive and narrative order differs from ID order):
```json
[
  {
    "branch_name": "Main",
    "component_id": "C1",
    "is_main": true,
    "axes": [
      {"start_anchor": {"id": 1, "name": "seeding"}, "end_anchor": {"id": 6, "name": "passage"}},
      {"start_anchor": {"id": 6, "name": "passage"}, "end_anchor": {"id": 3, "name": "differentiation start"}},
      {"start_anchor": {"id": 3, "name": "differentiation start"}, "end_anchor": {"id": 9, "name": "co-culture setup"}}
    ]
  },
  {
    "branch_name": "VirusExpansion",
    "component_id": "C2",
    "is_main": false,
    "axes": [
      {"start_anchor": {"id": 4, "name": "virus thawing"}, "end_anchor": {"id": 7, "name": "virus expansion"}},
      {"start_anchor": {"id": 7, "name": "virus expansion"}, "end_anchor": {"id": 9, "name": "co-culture setup"}}
    ]
  }
]
```
In this example: ids {1,6,3} are C1 MILESTONEs; ids {4,7} are C2 MILESTONEs; id=9 is the shared INTERVENTION merge point where both branches converge.
- Main covers all C1 MILESTONEs: note id=6 appears before id=3 (valid — narrative order precedes ID order), then continues to merge point id=9.
- VirusExpansion covers all C2 MILESTONEs {4,7} and ends at the same merge point id=9.
- C2 MILESTONEs {4,7} are correctly absent from Main; C1 MILESTONEs {1,6,3} are correctly absent from VirusExpansion.

---

### Main vs Branch Determination (CRITICAL)

**Core Principle**: Time axis follows **component lifecycle**. Each component with a construction/preparation process gets its own timeline branch.

**Main Branch (REQUIRED—exactly one, is_main=True)**:
- `branch_name`: "Main"
- `component_id`: Typically "C1" (first organoid_core in composition)
- `is_main`: True
- `axes`: Ordered segments representing primary organoid core timeline
- Spans from that component's initial preparation (tissue harvest/seeding) to final experimental endpoint
- Continues THROUGH and BEYOND the merge point (co-culture/assembloid formation) to include post-merge phases
- MUST include all MILESTONE anchors for the primary organoid core component
- **Selection in composite scenarios**: Choose the organoid_core component that serves as the "host" or has the longest preparation time

**Component-Based Branches (OPTIONAL, is_main=False)**:
- Represents the preparation timeline of a SPECIFIC COMPONENT (identified by component_id from composition)
- `branch_name`: Descriptive labels like "VirusExpansion", "LiverOrganoid", "ImmuneCellActivation", "BacteriaPrep"
- `component_id`: Must match component_id from composition (e.g., "C2", "C3", "C4")
- `is_main`: False
- `axes`: Ordered segments from component's preparation beginning to merge point
- Starts from that component's preparation beginning (e.g., virus thawing, liver organoid seeding, immune cell isolation)
- Ends at the INTERVENTION anchor representing merge/integration point (co-culture setup, infection, assembloid formation)
- **When to create**:
  ✅ Component has construction process: virus expansion, cell activation/differentiation, organoid growth, bacterial culture
  ❌ Component is "ready-to-use": directly purchased PBMC, commercial virus stock used immediately, primary cells added without culturing

**Experimental Treatment Branches (OPTIONAL, is_main=False)**:
- `branch_name`: Treatment labels like "DrugA", "DrugB", "HighDose", "LowDose"
- `component_id`: null (not component-based)
- `is_main`: False
- `axes`: Timeline segments for treatment arm diverging from Main

**Merge/Integration Point**:
- Represented by an INTERVENTION anchor on Main (e.g., "co-culture setup", "infection", "assembloid formation")
- All component-based Branches' last segment (axes[-1].end_anchor) should reference this anchor
- Main continues beyond this point to capture post-merge co-culture phases

**Examples**:
1. **Brain organoid + virus (with expansion)**:
   - Main: branch_name="Main", component_id="C1", axes=[seeding→maturation→infection→post-infection]
   - Branch: branch_name="VirusExpansion", component_id="C2", axes=[thawing→expansion→infection point]
   - Merge anchor: "infection setup" (day 28)

2. **Heart-Liver assembloid**:
   - Main: branch_name="Main", component_id="C1", axes=[heart seeding→maturation→assembloid formation→post-assembly]
   - Branch: branch_name="LiverOrganoid", component_id="C2", axes=[liver seeding→maturation→assembloid formation point]
   - Merge anchor: "assembloid formation" (day 14 for heart, day 21 for liver meet at day 21)

3. **Intestinal organoid + PBMC (direct addition)**:
   - Main: C1_IntestinalOrganoid (seeding → maturation → PBMC addition → co-culture)
   - No Branch for C2_PBMC (purchased and added directly, no construction process)
   - Merge anchor: "PBMC addition" (day 14)

---

### Anchor Semantic Classification

**Anchors fall into three functional categories** (guides creation/usage):

1. **MILESTONE Anchors** (Culture Development Stages)
   - Definition: Critical stages in core organoid/model development that are INHERENT to the culture protocol
   - Examples: seeding, passage, differentiation induction, maturation, confluence
   - Time: Can be exact (day 7), range (day 14-16), or unspecified (timing=null with descriptive name)
   - When timing=null: MUST provide clear name_action/name_cell_state/name_morphology describing the event (e.g., 'detect SOX2 expression', 'observe morphology', NOT 'unknown detection')
   - Usage: MUST be included in Main segment
   - **Judgment criteria**: If removing this step prevents reaching the final model definition, it's a MILESTONE

2. **INTERVENTION Anchors** (Experimental Treatment Points)
   - Definition: Timepoints when experimental treatments/manipulations ALTER culture state or INTRODUCE new components
   - Examples: drug treatment, infection setup, co-culture addition (when experimentally introduced), gene editing
   - Time: Usually exact or range
   - Usage: Serve as start_anchor for Branch segments OR merge points where Branches join Main
   - **Judgment criteria**: If this is an experimental variable (not required for basic model establishment), it's an INTERVENTION

3. **OBSERVATION Anchors** (Detection Sampling Points)
   - Definition: Timepoints when samples collected for detection WITHOUT altering culture
   - Examples: qPCR sampling, imaging, scRNA-seq, flow cytometry
   - Time: Usually exact
   - Usage: ONLY referenced by biomarker.detect_time or technique fields; MUST NOT create segments

**KEY PRINCIPLE**: Only MILESTONE and INTERVENTION anchors appear in time_axis segments. OBSERVATION anchors are created in time_anchors but referenced ONLY in biomarker.detect_time or technique fields; they MUST NOT create segments or appear as segment endpoints.

**GRAY ZONES - Co-culture/Infection Classification**:
- **Co-culture from day 0** (e.g., "Brain organoid with microglia" where microglia are added at seeding) → microglia addition is **MILESTONE** (inherent to protocol)
- **Co-culture as experimental treatment** (e.g., mature organoid + later addition of immune cells to test interaction) → immune cell addition is **INTERVENTION** (experimental variable)
- **Infection for disease modeling** (e.g., adding virus to study viral pathogenesis) → infection setup is **INTERVENTION**
- **Rule of thumb**: If the co-culture/infection is part of the model definition (e.g., "virus-infected organoid model"), early setup steps are MILESTONE; if testing experimental effects, it's INTERVENTION

---

### Anchor Naming Conventions

**CRITICAL PRINCIPLE**: Every anchor MUST have a clear, descriptive name even when timing is unknown. NEVER use generic terms like 'unknown', 'unspecified', or 'not stated' in anchor names. Use concrete action/state/morphology descriptions from the article.

When creating anchors (including those with timing=null), use this naming priority:

1. **name_action** (primary): Specific operation name
   - Culture operations: "tissue processing", "medium overlay", "organoid passage", "cell seeding"
   - Interventions: "co-culture setup", "drug treatment", "viral infection"
   - Detection/analysis: "detect Ki67 expression", "qPCR sampling", "immunostaining for GFAP"
   - Observations: "observe cyst formation", "assess viability", "measure organoid diameter"
   - Fill whenever there is an action/operation, EVEN when timing is unclear
   - Examples for unknown timing: 'detect SOX2 biomarker' (NOT 'unknown biomarker detection'), 'RNA extraction' (NOT 'unknown sampling')

2. **name_cell_state** (secondary): Cell/organoid developmental stage
   - "pluripotent", "differentiated", "mature", "confluent"
   - Use when distinguishing by biological state, not action

3. **name_morphology** (tertiary): Structural characteristic
   - "EB formation", "budding structure", "crypt-villus", "dense spheroid"
   - Use when physical structure is key identifier

**Same-day multiple operations:**
- If day 0 has both "tissue processing" and "medium overlay":
  - Create TWO anchors (id 1 and 2) with different name_action values
  - Segments can reference either anchor
  - Use desc field to capture full context (handles information density)

**CORRECT:** Day 0 has 2 operations → create 2 anchors: {id:1, name_action:"tissue processing", day:0}, {id:2, name_action:"medium overlay", day:0}

---

### Segment Granularity and Merging/Splitting Principles

**When to MERGE anchors into single segment:**
1. **Same-day continuous operations** without explicit wait time
   - Example: "tissue was collected and immediately digested" → merge into one anchor
   - Both day values equal → use single anchor, not two
   
2. **Sequential actions at same timepoint** part of single protocol step
   - Example: "centrifuge, remove supernatant, add fresh medium" all at day 0 → single anchor

3. **Intermediate protocol variations** with no biological significance
   - Example: "medium replaced with or without serum depending on condition" → single anchor "medium replacement"

**When to SEPARATE into distinct anchors:**
1. **Explicit wait time between operations** (e.g., "after 48h", "overnight", "1 week later")
   - Creates clear segment boundary
   
2. **Biological stage transition** marked by observation or explicit description
   - Example: "organoid formation" vs "passage" are different stages
   
3. **Different protocol branches diverge/converge**
   - Branch point becomes distinct anchor

**Correct granularity (NOT too fine, NOT too coarse):**
- ✅ 4-6 segments for typical 2-week protocol (biology-driven grouping)
- ❌ 10+ segments (over-fragmented, hard to understand timeline)
- ❌ 1-2 segments (lost important timing information)

**CORRECT (4 segments):** A1:processing(d0)→A2:overlay(d0)→A3:passage(null)→A4:coculture→A5:antibody→A6:collection
**WRONG (10+ segments):** ❌ A1:collection, A2:digestion, A3:centrifuge, A4:counting, A5:plating, A6:change_d2, A7:change_d4...

---

### Time Axis Scope: Protocol Steps Only

time_axis MUST capture the culture PROTOCOL timeline (Main segment must include all culture milestones):
- ✅ Include: cell seeding, medium changes, passage, co-culture setup, treatment addition (all MILESTONE & INTERVENTION anchors)
- ❌ Exclude: post-culture detection/analysis operations; they create OBSERVATION anchors referenced in biomarker fields only (see Anchor Semantic Classification)
- **Termination point**: Main segment ends at last intervention; post-intervention analysis times are separate OBSERVATION anchors

**Example:**
- Text: "Antibody added after 48h, then incubated for 1 week, then analyzed by flow cytometry"
- ✅ CORRECT: Main ends at "antibody addition" (INTERVENTION anchor); flow cytometry is separate OBSERVATION anchor referenced in biomarker.detect_time
- ❌ WRONG: Main includes "flow cytometry" as segment endpoint or separate Branch segment

---

### Common Errors to Avoid

**Error 1: Confusing repeat interval with first occurrence**
- ❌ "Medium replaced every 2 days" → create anchor at day=2
- ✅ "Medium replaced every 2 days" → start=day 0 (baseline), repeat_interval="every two days"

**Error 2: Inferring end day from vague conditions**
- ❌ "Until passage" + "every 2 days" → assume passage at day 7
- ✅ "Until passage" → end_anchor timing=null

**Error 3: Week-to-day conversion error**
- ❌ "Incubated for 1 week" → duration=5 days
- ✅ "Incubated for 1 week" → duration=7 days

**Error 4: Using duration=0 as placeholder**
- ❌ Unknown duration → duration=0
- ✅ Unknown duration → duration=null

**Error 5: Extending time_axis beyond protocol**
- ❌ Including "incubated for 1 week after treatment" as separate segment
- ✅ Stopping at treatment addition (last intervention)

**Error 6: Duplicate anchors across segments**
- ❌ Creating separate anchor "antibody addition" for each segment that needs it
- ✅ Create ONE anchor in time_anchors, reference it from multiple segments via id

**Error 7: Creating branches for observation/detection operations**
- ❌ Branch:qPCR_day7, Branch:IF_day14, Branch:scRNA_seq
- ✅ Create OBSERVATION anchors in time_anchors, reference in biomarker.detect_time or technique fields; do NOT create segments or branches

---

### Segment Continuity and Anchor Coverage Requirements

**CRITICAL PRINCIPLE**: axes field is **ONLY carrier of temporal order**. time_anchors array order is NOT guaranteed chronological. Anchor IDs carry no ordering information.

#### Rule 1: Each Branch MUST Cover ALL MILESTONE Anchors of Its Own Component

**MILESTONE anchors belonging to a branch's own component MUST ALL appear in that branch's axes.**  
**MILESTONE anchors of OTHER components are irrelevant to this branch and MUST be omitted.**

Scenario: suppose time_anchors has
- id=1 MILESTONE(C1): seeding; id=6 MILESTONE(C1): passage; id=3 MILESTONE(C1): differentiation
- id=9 INTERVENTION: co-culture setup (merge point, shared)
- id=4 MILESTONE(C2): virus thawing; id=7 MILESTONE(C2): virus expansion
- id=12 OBSERVATION: qPCR sampling (must never appear in any axes)

✅ **CORRECT — Main (C1)**: axes = [1→6, 6→3, 3→9]
  Covers all C1 MILESTONEs {1,6,3} in narrative order. Note: id=6 precedes id=3 — **this is valid, narrative order ≠ ID order**.
  C2 MILESTONEs {4,7} and OBSERVATION {12} are correctly absent.

✅ **CORRECT — VirusExpansion (C2)**: axes = [4→7, 7→9]
  Covers all C2 MILESTONEs {4,7}. C1 MILESTONEs {1,6,3} are correctly absent.

❌ **WRONG — Main missing C1 MILESTONE**: axes = [1→6, 6→9] — id=3 (C1 MILESTONE "differentiation") is missing; its position in the timeline is lost.

❌ **WRONG — Main containing a C2 MILESTONE**: axes = [1→6, 6→4, 4→3, 3→9] — id=4 belongs to C2 and must not appear in Main.

#### Rule 2a: Consecutive Segments MUST Form a Continuous Chain

`axes[i].end_anchor.id == axes[i+1].start_anchor.id` — this is a MUST, enforced by validator.

❌ **WRONG**: [1→6, 3→9] — axes[0].end=6 ≠ axes[1].start=3, chain is broken.
✅ **CORRECT**: [1→6, 6→3, 3→9] — unbroken chain where each segment's end equals the next segment's start.

This rule applies within each branch independently. Different branches may reference the same anchor (e.g., both Main and VirusExpansion end at merge point id=9).

#### Rule 2b: Zero-Length Segments Are PROHIBITED

`start_anchor.id` MUST NOT equal `end_anchor.id`. Remove any such segment.

❌ **WRONG**: axes = [1→1, 1→6, 6→6, 6→3] — 1→1 and 6→6 are zero-length and will be rejected by validator.
✅ **CORRECT**: axes = [1→6, 6→3]

#### Rule 3: Adequate Granularity Within Each Branch

**Guideline**: segments ≈ (this branch's own MILESTONE anchor count - 1)

❌ **TOO COARSE**: C1 has 8 MILESTONE anchors → 2 segments [A1→A2, A2→A9] — 6 C1 milestones lose ordering.
✅ **CORRECT**: C1 has 5 MILESTONE anchors → 4 segments [A1→A3, A3→A2, A2→A4, A4→A7] — complete ordering preserved.


**Correct approach**: Ensure axes covers all MILESTONE anchors of the branch's own component, forming a complete chain that explicitly encodes the full narrative order.

---

## RULE 27: TIME AXIS BRANCH USAGE

### CRITICAL CLARIFICATION: Co-culture vs Parallel Experimental Groups

**Before applying component-based branch strategy, determine:**

#### Scenario A: Co-culture (Same Vessel)
- Components in SAME vessel with interactions → ONE result with composition + branches
- Example: Organoid + virus + T cells in same well  
  → 1 result: composition [C1, C2, C3], time_axis [Main(C1), Branch:Virus(C2), Branch:Tcell(C3)]

#### Scenario B: Parallel Groups (Separate Vessels)
- Groups in SEPARATE vessels with independent timelines → MULTIPLE results, each with Main only
- Example: WT vs 5 mutants in separate wells  
  → 6 results, each: composition [C1], time_axis [Main(C1)]

**Decision**: Same vessel + interactions → branches | Separate vessels → multiple results

❌ **WRONG**: WT, Mutant1, Mutant2 in 1 composition (separate wells)  
✅ **CORRECT**: 3 separate results

---

### Component-Based Timeline Strategy

**Core Principle**: Each component in the culture system with a construction/preparation process gets its own timeline branch. The time_axis field is a **List[TimeAxisBranchInfo]**, where each branch contains ordered segments (axes) forming a complete timeline.

**Data Structure**:
```
time_axis: [
  {
    branch_name: "Main",
    component_id: "C1",
    is_main: true,
    axes: [segment1, segment2, segment3, ...]
  },
  {
    branch_name: "VirusExpansion",
    component_id: "C2",
    is_main: false,
    axes: [segment1, segment2, ...]
  }
]
```

**When to Create Branch**:

✅ **Create Branch when component has construction process**:
   - **Component undergoes preparation steps**: culturing, expansion, activation, differentiation, maturation
   - **Examples**:
     - Virus expansion: branch_name="VirusExpansion", component_id="C2", axes=[thawing→propagation→harvest]
     - Immune cell activation: branch_name="ImmuneCellActivation", component_id="C3", axes=[isolation→stimulation→expansion]
     - Second organoid: branch_name="LiverOrganoid", component_id="C4", axes=[seeding→growth→maturation]
     - Bacterial culture: branch_name="BacteriaPrep", component_id="C5", axes=[inoculation→growth→concentration]
   - **Branch axes**: Starts from component's first preparation step, ends at merge point with Main

✅ **Experimental treatment arms (traditional usage)**:
   - Drug A vs Drug B (different treatment conditions)
   - branch_name="DrugA"/"DrugB", component_id=null, axes diverge from Main at treatment initiation

❌ **Do NOT create Branch when component is "ready-to-use"**:
   - **Component added directly without preparation**: purchased reagents, commercial stocks, freshly isolated cells used immediately
   - **Examples** (NO Branch needed):
     - Commercial PBMC vial thawed and added directly → no separate branch
     - Virus stock purchased and used immediately → no separate branch
     - Primary cells freshly isolated and immediately co-cultured → no separate branch
   - **These are captured as**: INTERVENTION anchor on Main (e.g., "PBMC addition", "virus infection")

**Main Branch Requirements**:
- Exactly one branch with is_main=True
- branch_name="Main"
- component_id typically "C1" (first organoid_core)
- axes must include ALL MILESTONE anchors for primary organoid
- Main continues BEYOND merge point to capture post-merge phases

❌ **Never create Branch for**:
   - Detection/sampling operations (qPCR, imaging, flow cytometry) → use OBSERVATION anchors
   - Sequential maintenance steps (passage, medium change) → include in respective component's timeline
   - Synchronous co-culture from day 0 with no independent preparation → all in Main
- **Examples**:
  - Branch:C2_VirusExpansion (component C2 is the virus)
  - Branch:C3_LiverOrganoid (component C3 is liver organoid in assembloid)
  - Branch:C4_ImmuneCellActivation (component C4 is activated immune cells)
  - Branch:C5_StromalCellPrep (component C5 is stromal support cells)

**For experimental treatment arms** (not component-based):
- Format: "Branch:{SemanticLabel}" without component_id
- Examples: Branch:DrugA, Branch:HighDose, Branch:Cortical

### Main Segment Completeness Requirements

**CRITICAL**: Main segment represents the PRIMARY ORGANOID CORE component and MUST cover its complete lifecycle plus post-merge phases.

**MUST include ALL sequential culture milestones** (per Anchor Semantic Classification):
☐ Preparatory steps (tissue harvest, digestion, cell isolation) - MILESTONE anchor
☐ Seeding/plating (Day 0 anchor) - MILESTONE anchor
☐ Growth/expansion milestones (e.g., "confluence at Day 14-16") - MILESTONE anchor
☐ Maintenance steps (medium changes, passages) if part of standard protocol - MILESTONE anchor
☐ Differentiation start/end points - MILESTONE anchor
☐ Treatment/intervention initiation (drug, infection, co-culture setup) - INTERVENTION anchor
☐ **EXCLUDE**: Post-protocol incubation periods without intervention
☐ **EXCLUDE**: Detection/analysis operations (qPCR, imaging, etc.) - These are OBSERVATION anchors, referenced elsewhere

**Example - CORRECT complete timeline structure**:
```
time_anchors: [
  {id:1, name_action:"Harvest", day:0},
  {id:2, name_action:"Seeding", day:0},
  {id:3, name_action:"Passage", day:7-10},
  {id:4, name_action:"Differentiation", day:14},
  {id:5, name_action:"Maturation", day:21-28},
  {id:6, name_action:"Drug treatment", day:28},
  {id:7, name_action:"qPCR sampling", day:30}  ← OBSERVATION anchor
]
time_axis: {
  "Main": {start:{id:1}, end:{id:6}},  ← spans all culture milestones (id 1-6)
  "Branch:DrugA": {start:{id:6}, end:{id:6}+duration}  ← diverges from Main
}
biomarker: [
  {detect_time: {id:7, name:"qPCR sampling"}, ...}  ← OBSERVATION anchor referenced here
]
```

**INCORRECT Main examples** (common mistakes):
- ❌ Main: id:1 → id:5 [skips intermediate passages, anchors 2-4]
- ❌ Main: id:1 → id:2, with 10+ Branch:qPCR_day7, Branch:IF_day14, Branch:scRNA_day21 [detection shouldn't create branches]
- ❌ Main: id:1 → id:2 [only 2 anchors for 28-day protocol; too coarse granularity]
- ❌ Main extends beyond treatment: id:1 → id:7 includes OBSERVATION anchor as segment endpoint

**CORRECT Main example**:
- ✅ Main: id:1 → id:6 covering all culture milestones and final intervention
- ✅ Branches (if any): diverge from Main at INTERVENTION points, never include OBSERVATION anchors
- ✅ OBSERVATION anchors: exist in time_anchors but only referenced in biomarker/technique fields

### Branch Naming Convention

- Format: "Branch:SemanticLabel" (colon-separated, CamelCase)
- Examples: "Branch:DrugA", "Branch:Cortical" (treatment variations, NOT Control)
- Avoid: "Branch_DrugA", "branch:druga", "BranchDrugA", "Branch:Control"
- **Note**: If you have Control group, designate it as Main (complete timeline) and alternatives as Branch:Treatment_X

---

## RULE 28: GENE SYMBOL SPECIES-SPECIFIC STANDARDIZATION

**Scope:** Defines how to determine source species and apply species-specific gene nomenclature for StandardizedName.std fields (biomarker_name, antibody targets, qPCR targets).

**Critical Principle:** Gene symbols are SPECIES-SPECIFIC with different capitalization:
- Human (HGNC): ALL UPPERCASE - 'CD3E', 'ITGAX', 'RORC', 'IL7R', 'PTPRC'
- Mouse (MGI): Capitalized - 'Cd3e', 'Itgax', 'Rorc', 'Il7r', 'Ptprc'
- Rat (RGD): Capitalized - 'Cd3e', 'Itgax', 'Rorc'
- Zebrafish (ZFIN): lowercase - 'cd3e', 'itgax'

**Common Error:** Defaulting to human nomenclature or treating symbols as species-agnostic.

---

### STEP 1: Trace Source Species from Composition

**For BiomarkerItemInfo:**
- `source_type='organoid'` → Find composition component with `role='organoid_core'` matching biomarker's organ/cell_type → use that component's `species`
- `source_type='coculture'` → Find composition component with immune/stromal/microbial role matching biomarker's `co_culture_type` → use that component's `species`

**For Other Fields (AntibodyInfo, TargetedExpressionTargetInfo):**
- Determine which component the target is measured in (stained cells, RNA source) → trace to composition → use that component's `species`

**Fallback (if composition lacks species):**
- Check Methods/Abstract for model organism statement
- **Never assume human by default** (most organoid papers use mouse)

**Example:** CD3 biomarker in LPLs (co-culture) → check source_type='coculture' + co_culture_type={'ImmuneCell':['LPLs']} → match composition[C2] with role='immune_co-culture' + cell_type='LPLs' → extract species='Mus musculus' → apply MGI: CD3→'Cd3e' → std:'Cd3e'

---

### STEP 2: Apply Nomenclature Rules

- **Human:** ALL CAPS (CD3→'CD3E', CD11c→'ITGAX', Ki-67→'MKI67')
- **Mouse:** Capitalized (CD3→'Cd3e', CD11c→'Itgax', Ki-67→'Mki67')
- **Other:** Follow organism authority

---

### STEP 3: Handle Missing/Ambiguous Species

**If species missing/ambiguous after thorough checking:**
1. Set std=src (no conversion)
2. Create puzzle (source='Source', severity='Degrading') explaining species unavailability
3. Document in notes if needed

**Mixed-species assembloid:** Each biomarker uses its own component's species nomenclature.

---

### Common Errors (for Judgers)

**Error 1:** Human symbol for mouse source
- ❌ composition species='Mus musculus', std='CD3E' (should be 'Cd3e')

**Error 2:** No conversion applied
- ❌ article says 'CD3' for mouse cells, std='CD3' (should be 'Cd3e')

**Judger Validation:**
1. Match biomarker to composition component via source_type/co_culture_type
2. Extract species from that component
3. Verify std uses correct capitalization for that species
4. Deduct -4 points per symbol error (Gene Symbol Error)

**Integration:** See RULE 3 (StandardizedName structure), RULE 14 (biomarkers), RULE 20 (nomenclature).

## RULE 29: markdown code block WHEN OUTPUT
1. In Final Answer: Ensure the final output does not include any code block markers like ```json or ```python.
2. In Final Answer: Generate **ONE** single valid JSON object inside a markdown code block(like ```json{xxxxxx}```)
3. In Action and Action Input: json no any code block markers
- Example✅️:
The Final Answer:
```json
{
  "key": "value",
  "array": [1, 2, 3]
}
```
- Example❌️:
```json
The Final Answer:
```json
{
  "key": "value",
  "array": [1, 2, 3]
}
```
```
- Example✅️:
Action: get_pubmed_article_by_doi
Action Input:{"dois": ["10.7554/eLife.36739.001", "10.7554/eLife.36739"]}

- Example✅️:
Action: google_search
Action Input:{"dois": ["CT26.WT cell line details", "Caco-2 cell line details", "AOM/DSS model cancer research"]}

## RULE 30: searchings List as Extra Info By Using TOOL
- Searcher will use search tool to find extra info when the input info is incomplete. Others should believe the search result as extra info.

## RULE 31: Thought, Action, Observation, and Final Answer Format
- CASE1: Use "\nThought:", "\nAction:", "\nAction Input:", "\nObservation:" to Using TOOL
- CASE2: Use "\nThought:", "\nFinal Answer:" to give the final answer
- CASE1 and CASE2 can not appear at the same time. PS `Final Output`=`Final Answer`