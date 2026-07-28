# MATERIALS RECORDING RULES

## [MAT-RULE-01] Four Material Categories (Scope & Architecture)

### Where Materials Appear in Schema:
1. **material_source** (List[CulturePurposeMaterialInfo])  
   - Purpose: Culture-purpose materials with supplier tracking
   - Referenced in steps using [n] suffix (e.g., "Embedded in Matrigel[1]")
   
2. **ExperimentalMaterialInfo** (within ExperimentTechnologyInfo)  
   - Purpose: Experimental-purpose materials (detection, analysis, manipulation)
   - Examples: Antibodies for IF, qPCR kits, drugs for testing, viral vectors
   
3. **drug_list** (List[DrugListInfo])  
   - Purpose: Drug screening compounds
   - Records drug → disease → response (efficacy/toxicity testing)
   
4. **culture_steps.steps** (List[str])  
   - Purpose: Narrative descriptions of culture operations
   - References culture materials via [n] notation linking to material_source
   - Example: "Day 0: Seeded into Matrigel[1] domes"

### Architecture Rules:

**Rule 1 - Steps & Material_Source Relationship**:
- `steps` is a narrative text field describing culture operations
- ANY culture material mentioned in `steps` MUST exist in `material_source`
- Materials in `material_source` are referenced in `steps` using `[n]` notation (e.g., Matrigel[1], PBS[2])

Note (clarification): The requirement above applies to culture-purpose materials (see [MAT-RULE-03] Layer decision tree). Materials that are used only after fixation or only for downstream detection/analysis (see [MAT-RULE-02] exclusion list) are exempt from being placed in `material_source` and do not require `[n]` references in `steps`.

**Rule 2 - Dual Recording for Specific Types**:
- **material_source** is the complete set of all culture materials
- **medium/supplements/growth_factors/small_molecules** are special subsets requiring dual recording:
  - Type 1 (Medium) → `medium` field + `material_source` (type='Medium')
  - Type 2 (Supplement) → `supplements` field + `material_source` (type='Supplement')
  - Type 3 (Growth Factor) → `growth_factors` field + `material_source` (type='Growth Factor')
  - Type 4 (Small Molecule) → `small_molecules` field + `material_source` (type='Small Molecule')
  - Type 5 (Antibiotic) → `supplements` field + `material_source` (type='Antibiotic')
    - Note: Antibiotics use `supplements` field but material_type='Antibiotic' (not 'Supplement')

**Rule 3 - Single Recording for Other Types**:
- Types 6-16 (Matrix, Coating, Enzyme, Buffer, Solvent, Dye, etc.):
  - Mentioned in `steps` text with `[n]` reference
  - Recorded in `material_source` with appropriate material_type
  - NO dedicated field in OrganoidCultureStepInfo (unlike Types 1-5)

**Rule 4 - [n] Reference Notation**:
- Each material in `material_source` gets a sequential number [1], [2], [3]...
- Use `[n]` in `steps` text to link narrative to structured data
- Examples: "Embedded in Matrigel[1]", "Coated with Poly-L-lysine[2]", "Dissociated using TrypLE[3]"

---

## [MAT-RULE-02] MATERIAL_TYPE EXCLUSION CHECKLIST ⚡

### ❌ Category 1: Detection/Analysis Reagents
**DO NOT record in material_source** (use ExperimentalMaterialInfo instead):
- **qPCR/RT-PCR kits**: TaqMan assays, SYBR Green kits, RNA extraction kits
- **Antibodies for analytical assays**: Primary/secondary antibodies for immunostaining, Western blot, flow cytometry, ELISA, IHC/IF. See [MAT-RULE-08] for detailed antibody extraction rules
- **Primers**: PCR primers for gene amplification
- **Probes**: FISH probes, in situ hybridization probes
- **Detection dyes** (post-fixation only): DAPI as counterstain, EdU Click-iT kits for fixed samples

**Temporal rule**: If used AFTER fixation/lysis → NOT culture material

---

### ❌ Category 2: Sample Processing Reagents
**DO NOT record in material_source** (use ExperimentalMaterialInfo instead):
- **Fixatives**: 4% PFA, paraformaldehyde, formaldehyde, glutaraldehyde
- **Permeabilization reagents**: Triton X-100, Tween-20, saponin
- **Blocking reagents**: Normal goat serum, BSA for blocking (in IF protocol)
- **Chromosome prep reagents**: Colcemid, colchicine, Giemsa stain

**Temporal rule**: If used AFTER culture termination → NOT culture material

**SUPPLEMENTARY NOTE**: These "sample processing/detection" reagents may appear directly in natural language form in `protocol.steps` (e.g., "Fixed organoids in 4% PFA for 60 min") without being mandatorily listed in `material_source` or requiring `[n]` references in steps. To minimize modification and annotation burden, this project accepts such natural-language mentions by default and treats them as non-blocking warnings. For stricter traceability requirements, key detection reagents may optionally be recorded in `ExperimentalMaterialInfo` or similar fields in future work iterations.

---

### ❌ Category 3: Drug Screening Compounds
**DO NOT record in material_source** (use drug_list instead):
- **Therapeutic drugs for efficacy testing**: Cisplatin, Paclitaxel, Temozolomide, Doxorubicin
- **Drug screening libraries**: Compound libraries for drug discovery

**Functional rule**: If purpose is to TEST drug efficacy/toxicity → use drug_list  
**Exception**: If drug is used to CREATE culture condition (e.g., antibiotic selection), may record in material_source

---

### ❌ Category 4: Downstream Assays
**DO NOT record in material_source** (use ExperimentalMaterialInfo instead):
- **Viability/proliferation kits**: MTT, CCK-8, WST-1, CellTiter-Glo (endpoint assays)
- **Apoptosis detection kits**: Annexin V kits, Caspase-3 kits (post-fixation)
- **Mycoplasma detection kits**: PCR-based detection kits
- **Protein assays**: BCA assay, Bradford assay reagents

**Functional rule**: If used for ENDPOINT measurement (not culture maintenance) → NOT culture material

---

### ❌ Category 5: Physical Consumables
**DO NOT record in material_source** (most cases):
- **General labware**: Plates, dishes, pipettes, tubes, flasks
- **Filters**: Cell strainers, syringe filters (unless specialized culture membrane)
- **Specialized vessels**: May use material_type='Others' if critical to culture (e.g., transwell inserts, microfluidic chips)

**Rule**: Only record if the physical item is integral to culture structure (e.g., porous membrane in transwell)

**Minimal Exclusions** (culture materials with negligible impact):
- pH indicators: Phenol Red (unless critical to experiment)
- Water: Deionized water, ultrapure water (unless critical formulation component)
- General lab consumables: CO2 gas, liquid nitrogen (unless part of experimental treatment)

---

### ❌ Category 6: Co-culture Biological Components
**DO NOT record in material_source** (use OrganoidComponentInfo instead):
- **Microorganisms as co-culture partners**: Bacteria, fungi, viruses used as living co-culture components for disease modeling, microbiome simulation, or host-pathogen interaction studies
- **Living cells as co-culture partners**: Immune cells, stromal cells, endothelial cells when used as biological co-culture components
- **Tissue explants as co-culture partners**: Tissue slices, organotypic cultures used as biological partners in the culture system

**Decision Rule**:
- If microorganism/cell is a **BIOLOGICAL CO-CULTURE COMPONENT** (part of the experimental culture system, e.g., modeling microbiome, infection, immune interaction) → Record in `OrganoidBaseInfo.composition` as `OrganoidComponentInfo` with appropriate role (e.g., role='microbial_co-culture' for microorganisms, role='immune_co-culture' for immune cells)
- If microorganism/virus is a **FUNCTIONAL TOOL** (gene delivery vector, infection enhancer) → Record in `material_source` with appropriate material_type (Viral_Vector, Infection_Enhancer, Transfection_Reagent)

**Examples**:
| Material | Purpose | Record Location | Notes |
|----------|---------|----------------|-------|
| SARS-CoV-2 | Disease model / pathogen | OrganoidComponentInfo (role='microbial_co-culture') | Used to model COVID-19 infection |
| Bifidobacterium animalis | Gut microbiome model | OrganoidComponentInfo (role='microbial_co-culture') | Used to study host-microbe interaction |
| E. coli K-12 | Bacterial colonization study | OrganoidComponentInfo (role='microbial_co-culture') | Part of microbiome co-culture |
| Lentivirus-Cas9 | Gene editing tool | material_source (material_type='Viral_Vector') | Used only for gene delivery |
| AAV-GFP | Reporter delivery | material_source (material_type='Viral_Vector') | Used only for transgene expression |
| Polybrene | Infection enhancer | material_source (material_type='Infection_Enhancer') | Chemical reagent to enhance viral transduction |
| CD8+ T cells | Immune co-culture | OrganoidComponentInfo (role='immune_co-culture') | Used to study immune response |
| Fibroblasts | Stromal support | OrganoidComponentInfo (role='stromal_support') | Used to provide stromal niche |

**CRITICAL DISTINCTION**: The same microorganism/virus type may appear in BOTH locations depending on context:
- **SARS-CoV-2 as pathogen** (infection model) → OrganoidComponentInfo
- **Lentiviral vector carrying SARS-CoV-2 gene** (tool for gene delivery) → material_source (Viral_Vector)

---

### ✅ INCLUDE in material_source (Culture-Purpose Materials):
- **ECM/Scaffolds**: Matrigel, Collagen, Laminin, PEG hydrogel
- **Coatings**: Poly-L-lysine, Vitronectin
- **Dissociation enzymes**: TrypLE, Accutase, Collagenase (for passaging)
- **Working buffers**: PBS/DPBS for washing/resuspension during culture
- **Solvents**: DMSO as vehicle control in culture medium
- **Live monitoring dyes**: Calcein-AM if added during culture for viability tracking
- **Media/Supplements/Growth factors/Small molecules/Antibiotics**: ALWAYS record (dual recording required)

---

## [MAT-RULE-03] Material_Source Scope (3-Layer Decision Tree)

### Decision Tree for "Should this material be in material_source?"

**Layer 1 - Temporal Boundary**:
- ✅ Material used DURING culture (cells alive, growing)
- ❌ Material used AFTER fixation/lysis/termination

**Layer 2 - Functional Boundary**:
- ✅ Material affects culture microenvironment/growth/differentiation
- ✅ Material monitors culture status (e.g., live imaging dyes)
- ❌ Material only for detection/measurement (post-fixation)

**Layer 3 - Persistence Boundary**:
- ✅ Material remains in culture (≥ hours)
- ✅ Material is transient but essential (e.g., enzyme dissociation)
- ❌ Material used only for endpoint analysis

### Examples:
| Material | Temporal | Functional | Persistence | Include? |
|----------|----------|------------|-------------|----------|
| Matrigel | During culture ✅ | Affects structure ✅ | Remains ✅ | ✅ YES |
| TrypLE | During passage ✅ | Essential for dissociation ✅ | Transient ✅ | ✅ YES |
| Anti-SOX2 (IF) | After fixation ❌ | Detection only ❌ | N/A | ❌ NO → ExperimentalMaterialInfo |
| Cisplatin (screening) | During treatment ✅ | Testing efficacy ❌ | N/A | ❌ NO → drug_list |
| 4% PFA | After culture ❌ | Fixation ❌ | N/A | ❌ NO → ExperimentalMaterialInfo |
| Calcein-AM (live) | During culture ✅ | Monitors viability ✅ | Short-term ✅ | ✅ YES (if tracked) |

---

## [MAT-RULE-04] Medium Decomposition Workflow  


### Base Medium Recording Rules:
- Base culture medium name only: DMEM/F12, Neurobasal, RPMI 1640, mTeSR1, DMEM/F12+Neurobasal(1:1)
- **UNSPECIFIED OR PROPRIETARY MEDIA NAMES**: When the article uses generic labels such as 'complete growth medium', 'organoid induction medium', 'neural maintenance medium', 'NPC medium', or proprietary medium names without listing individual components, record the label verbatim in medium and leave supplements/growth_factors/small_molecules empty.  
- **NO INFERENCE PRINCIPLE**: NEVER infer concentrations or missing additives. NEVER invent, back-fill, or guess individual ingredients from typical practice or manufacturer documentation. Strict non-overlapping boundaries for medium/supplements/matrix/small_molecules/growth_factors.
- PARTIALLY DEFINED NAMED MEDIA: When a generic/proprietary medium name (e.g., 'crypt culture medium') is described as 'containing' specific additives OR as being 'used with', 'supplemented with', or 'in the presence of' specific factors (e.g., 'crypt culture medium containing epithelial growth factor, Noggin and Rspo1', or 'crypt culture medium in the presence or absence of Rspo1') but the base medium itself is not named and the full recipe cannot be reconstructed, you MUST (i) keep the named label verbatim in `medium` and (ii) still record all explicitly listed additives in `supplements` / `growth_factors` / `small_molecules` as appropriate. Do NOT guess the missing base medium or any unreported components; only the known additives should be encoded.
- EXCEPTION — Explicitly Defined Internal Formula (CRITICAL WORKFLOW): When the article explicitly defines the full composition of a medium — even if it is introduced as a proprietary or branded name (e.g., 'crypt culture medium', 'human liver organoid isolation medium', 'human liver EM', 'DM') — you MUST follow this workflow:
  - STEP 1 - IDENTIFY EXPLICIT DEFINITION: Look for phrases like 'X medium consists of...', 'X medium (base + additives)', 'X medium: [list of components]', or similar explicit formula descriptions.  
  - STEP 2 - DECOMPOSE ON FIRST USE: Decompose the named medium into (i) base medium in `medium` field and (ii) all listed additives in `supplements`/`growth_factors`/`small_molecules` according to their type.  
  - STEP 3 - RECORD DECOMPOSITION RULE: Internally note that this named medium has been explicitly defined and decomposed (e.g., 'crypt culture medium = Advanced DMEM/F12 + EGF + R-spondin 1 + Noggin').
  - STEP 4 - APPLY CONSISTENTLY: For ALL subsequent uses of that named medium in the same article, ALWAYS apply the SAME decomposition from STEP 2. Do NOT keep the named label; always expand to components.  
  - EXAMPLE: If 'crypt culture medium (Advanced DMEM/F12 containing 10-50 ng/ml EGF, 500 ng/ml R-spondin 1, and 100 ng/ml Noggin)' is defined in Methods, then EVERY step mentioning 'crypt culture medium' or 'the medium' (when context clearly refers to this medium) should decompose to: medium='Advanced DMEM/F12', growth_factors=[EGF, R-spondin 1, Noggin].  
  - RATIONALE: This decomposition is NOT inference or back-filling because the authors explicitly define the formula. This ensures data consistency and machine-readability across all culture steps.  
- Only labels without an explicit recipe anywhere in the article (e.g., 'complete medium', 'induction medium', 'maintenance medium' with no definition) must remain un-decomposed.
- Also record in material_source with material_type='Medium'.

---

## [MAT-RULE-05] Culture-Purpose Material Types (18 Categories)

Complete catalog of all 18 `CulturePurposeMaterialTypeEnums` values. Each category lists definition, examples, and specific culture-purpose materials.

---

### Type 1: Medium
**Definition**: Base culture medium providing essential nutrients and basal salts.

**Culture-Purpose Materials**:
- DMEM, DMEM/F12, Advanced DMEM/F12
- Neurobasal, Neurobasal-A
- RPMI 1640, RPMI 1640 HEPES Modification
- mTeSR1, mTeSR Plus, Essential 8
- Alpha-MEM, IMDM
- Ham's F-12, Ham's F-10
- MCDB 131, Williams' Medium E
- Custom/proprietary media (e.g., "crypt culture medium", "NPC medium")

---

### Type 2: Supplement
**Definition**: Commercial supplement mixes, serum, and additives that modify medium performance.

**Culture-Purpose Materials**:
- Supplement mixes: B-27 Supplement, B-27 Minus Vitamin A, N-2 Supplement, N-2 MAX, G-5 Supplement
- Serum: FBS (Fetal Bovine Serum), Human Serum, KSR (KnockOut Serum Replacement)
- Amino acids: GlutaMAX, L-Glutamine, MEM NEAA (Non-Essential Amino Acids)
- Metabolites: Sodium Pyruvate, D-Glucose
- Antioxidants: β-mercaptoethanol (2-ME), Ascorbic Acid, N-Acetyl-L-cysteine (NAC)
- Proteins: BSA (Bovine Serum Albumin), HSA (Human Serum Albumin), ITS (Insulin-Transferrin-Selenium), ITS-X
- Buffers: HEPES (when part of medium formulation)
- Lipids: Chemically Defined Lipid Concentrate, AlbuMAX
- Surfactants/Stabilizers: Pluronic F-68 (Poloxamer 188)

---

### Type 3: Growth Factor
**Definition**: Proteinaceous factors (cytokines, morphogens) added to regulate signaling pathways.

**Culture-Purpose Materials**:
- EGF family: EGF (Epidermal Growth Factor), TGF-α
- FGF family: bFGF/FGF2, FGF8, FGF10, FGF7/KGF
- BMP family: BMP4, BMP7, BMP2
- TGF-β family: TGF-β1, Activin A, Activin B, Nodal, GDF11
- Wnt pathway: Wnt3a, Wnt5a, R-spondin 1/2/3/4
- BMP inhibitors: Noggin, Chordin, Follistatin
- Other morphogens: SHH (Sonic Hedgehog), VEGF, HGF, IGF-1, IGF-2, PDGF-AA/BB
- Cytokines: LIF, SCF, IL-6, IL-3
- Neurotrophins: BDNF, GDNF, NGF, NT-3

---

### Type 4: Small Molecule
**Definition**: Low-molecular-weight pathway modulators and chemical inhibitors/activators.

**Culture-Purpose Materials**:
- Wnt activators: CHIR99021 (GSK-3β inhibitor), CHIR98014
- TGF-β inhibitors: SB431542, A83-01, SB505124
- BMP inhibitors: LDN193189, DMH1, Dorsomorphin
- ROCK inhibitors: Y-27632, Thiazovivin, HA-100
- MEK inhibitors: PD0325901, PD98059, U0126
- Notch inhibitors: DAPT, DBZ
- Retinoids: Retinoic acid (RA), ATRA
- Glucocorticoids: Dexamethasone, Hydrocortisone
- Other modulators: Forskolin, SAG, Purmorphamine, IWP-2, XAV939, Nicotinamide, Valproic acid

---

### Type 5: Antibiotic
**Definition**: Antimicrobial agents included in culture medium to control contamination.

**Culture-Purpose Materials**:
- Bacterial control: Penicillin-Streptomycin (Pen-Strep), Gentamicin, Ampicillin, Kanamycin
- Selection antibiotics: Hygromycin B, Puromycin, G418 (Geneticin), Blasticidin S, Zeocin
- Fungal control: Amphotericin B (Fungizone), Normocin
- Mycoplasma control: Plasmocin, Mycoplasma Removal Agent

---

### Type 6: Matrix
**Definition**: 3D ECM or scaffold materials providing mechanical/biochemical support for organoid structure.

**Culture-Purpose Materials**:
- Commercial ECM: Matrigel (Growth Factor Reduced, High Concentration), Cultrex BME, Geltrex
- Purified ECM proteins: Collagen Type I, Collagen Type IV, Laminin-111, Laminin-511, Fibronectin, Vitronectin
- Natural hydrogels: Fibrin gel, Alginate, Agarose, Hyaluronic acid hydrogel, Methylcellulose
- Synthetic hydrogels: PEG hydrogel, PEG-based scaffolds, PuraMatrix
- Engineered matrices: Decellularized ECM, Custom ECM blends

---

### Type 7: Coating
**Definition**: Surface coatings applied to plates or devices to promote or prevent cell adhesion.

**Culture-Purpose Materials**:
- Adhesion-promoting: Poly-L-lysine (PLL), Poly-D-lysine (PDL), Poly-L-ornithine (PLO), Gelatin, Fibronectin, Vitronectin, Laminin, Collagen (as coating)
- Anti-adhesion: Ultra-low attachment coating, Poly-HEMA, Agarose coating

---

### Type 8: Enzyme
**Definition**: Enzymes used for dissociation, passaging, or matrix remodeling during culture.

**Culture-Purpose Materials**:
- Dissociation enzymes: TrypLE Express, Trypsin-EDTA, Accutase, StemPro Accutase, Versene (EDTA solution)
- Matrix digestion: Collagenase (Type I/II/IV), Dispase, Dispase II, Liberase, Neutral Protease
- DNase: DNase I (to prevent clumping during dissociation)

**Note**: Detection enzymes (e.g., HRP for Western blot) → ExperimentalMaterialInfo.

---

### Type 9: Chelating Agent
**Definition**: Metal-ion chelators used for cell detachment or as buffer components.

**Culture-Purpose Materials**:
- EDTA (Ethylenediaminetetraacetic acid)
- EGTA (Ethylene glycol-bis(β-aminoethyl ether)-N,N,N',N'-tetraacetic acid)
- Versene (EDTA solution for cell detachment)

---

### Type 10: Buffer
**Definition**: Washing or working buffers used during live culture operations (not post-fixation processing).

**Culture-Purpose Materials**:
- Saline buffers: PBS (Phosphate-Buffered Saline), DPBS (Dulbecco's PBS), HBSS (Hank's Balanced Salt Solution), Tyrode's solution
- Working buffers: FACS buffer (for live-cell sorting), Cell dissociation buffer
- pH buffers: HEPES buffer (when used for washing/handling)

**Note**: Buffers used ONLY in immunostaining/Western blot → ExperimentalMaterialInfo.

---

### Type 11: Solvent
**Definition**: Solvents/vehicles present in the culture environment (not stock-only solvents).

**Culture-Purpose Materials**:
- DMSO (Dimethyl sulfoxide) - when used as vehicle control in culture medium
- Ethanol - when used for sterilization or as vehicle in culture
- Methanol, Acetone, Isopropanol - when present in culture environment

**Note**: Solvents used ONLY for stock preparation (not added to culture) → do not record.

---

### Type 12: Dye
**Definition**: Vital dyes or live-cell trackers present during active culture (not endpoint-only stains).

**Culture-Purpose Materials**:
- Viability dyes (live monitoring): Calcein-AM (live-cell marker), CFDA-SE/CFSE (cell tracking), CellTracker dyes (Green, Orange, Red)
- Membrane dyes: PKH26, PKH67, DiI, DiO (when used for live tracking)
- Metabolic indicators: Resazurin (Alamar Blue) - when used during culture

**Note**: Endpoint-only stains (DAPI, PI for fixed cells, Hoechst post-fixation) → ExperimentalMaterialInfo.

---

### Type 13: Transfection Reagent
**Definition**: Reagents used to deliver nucleic acids during live culture steps (not for detection).

**Culture-Purpose Materials**:
- Lipid-based: Lipofectamine 2000/3000/RNAiMAX, FuGENE HD, TransIT-X2, JetPRIME
- Polymer-based: PEI (Polyethylenimine), Fugene 6
- Electroporation reagents: Neon Transfection System buffers

**Note**: Transfection reagents used ONLY for experimental endpoint analysis → may go to ExperimentalMaterialInfo.

---

### Type 14: Infection Enhancer
**Definition**: Agents that increase viral transduction efficiency or infection during culture.

**Culture-Purpose Materials**:
- Polybrene (Hexadimethrine bromide)
- Protamine sulfate
- DEAE-Dextran

---

### Type 15: Tissue Equivalent
**Definition**: Commercial tissue/organotypic products used as culture substrates or ready-to-use models.

**Culture-Purpose Materials**:
- Skin models: MatTek EpiDerm, EpiDermFT, EpiOral
- Liver models: InSphero 3D InSight Liver Microtissues
- Commercial organoid products: Pre-fabricated organoids from vendors

---

### Type 16: Others
**Definition**: Any culture-purpose material not covered by the above 15 categories.

**Culture-Purpose Materials**:
- Custom biomaterials (e.g., lab-synthesized hydrogels, engineered scaffolds)
- Specialized device components (e.g., microfluidic chip coatings, transwell membranes)
- Novel culture additives (e.g., exosomes, extracellular vesicles added to culture)

---

### Type 17: Therapeutic Agent
**Definition**: Therapeutic-grade biologics or small-molecule agents intentionally APPLIED to the culture to perturb, treat, or model therapeutic interventions.

**Culture-Purpose Materials**:
- Monoclonal antibodies used as treatments or perturbations (e.g., anti-EGFR antibodies when used to modulate signaling in culture). 
- Small-molecule targeted inhibitors or activators when applied as experimental treatments (e.g., MEK inhibitors used as treatment perturbations rather than as part of a screening library). 
- Recombinant therapeutic proteins or biologics (e.g., therapeutic cytokine blockers, fusion proteins) when applied to cultures.

**Notes & Rules**:
- If the compound's primary role in the protocol is to ACT ON the culture (as a treatment, perturbation, or selection agent), record it in `material_source` with material_type='Therapeutic Agent'.
- If the compound is reported only as part of a drug screening library or as an efficacy/toxicity readout in a screening assay, record it in `drug_list` instead (see [MAT-RULE-02] Category 3). The distinction is PURPOSE-DRIVEN: treatment-of-culture → `material_source`; screening/test compound → `drug_list`.
- Antibiotics used for selection/maintenance remain under material_type='Antibiotic' (Type 5) and should NOT be relabeled as Therapeutic Agent.
- When possible, provide application context (concentration, duration, route of addition) in the same `material_source` entry to distinguish treatment regimens from screening uses.

**Code/Enum mapping:** In the schema this category is represented by the enum member `CulturePurposeMaterialTypeEnums.Therapeutic_Agent` (member name: `Therapeutic_Agent`, string value: 'Therapeutic Agent'). Use this enum value when populating `material_type` for culture-purpose therapeutic agents.

### Type 18: Viral Vector
**Definition**: Biological viral delivery systems (lentivirus, AAV, adenovirus, retrovirus, etc.) intentionally APPLIED to the culture to deliver genetic payloads, establish stable modification, or act as a persistent perturbation to the culture system.

**Culture-Purpose Materials**:
- Lentiviral vectors (pLenti, pLV constructs) used for stable transduction
- AAV vectors used for long-term expression in culture models
- Adenoviral vectors used for sustained expression or persistent perturbation

**CRITICAL DISTINCTION - Viral Vector vs. Viral Co-culture**:
- **Record as Viral_Vector (in material_source)**: When virus is used as a TOOL for gene delivery
  - Purpose: Deliver genetic payload (transgene, shRNA, CRISPR construct), not model infection biology
  - Examples: Lentivirus-shRNA for gene knockdown, AAV-Cre for conditional knockout, Adenovirus-GFP for cell labeling
  - Intent: The virus is a functional reagent; the biological focus is on the genetic modification outcome, not viral infection per se
  - Format material_name with vector details: 'Lentivirus: pLKO.1-shTP53', 'AAV: Serotype 9-CAG-GFP'
  
- **Record as Component (MICROBIAL_CO_CULTURE in OrganoidComponentInfo)**: When virus is used as PATHOGEN MODEL
  - Purpose: Study host-pathogen interaction, viral infection mechanism, disease modeling
  - Examples: SARS-CoV-2 for COVID-19 infection model, Influenza A for respiratory infection, Zika virus for microcephaly model
  - Intent: The virus is a biological co-culture partner; the focus is on infection biology, immune response, or disease phenotype
  - Record in `OrganoidBaseInfo.composition` with role='microbial_co-culture'

**Notes & Rules**:
- Intent matters: record a viral vector in `material_source` when it is used to MODIFY the culture condition (stable expression, long-term perturbation, selection of modified cells, sustained payload delivery). Include metadata where available: vector type, serotype/pseudotype, payload description (promoter/gene), titer (TU/mL or GC/mL), MOI, and application method (e.g., spinoculation, incubation time, day of addition).
- If the viral vector is used only transiently to deliver a reporter or editing reagent for a downstream endpoint assay (i.e., it does not constitute an ongoing culture condition or persistent perturbation), record it in `ExperimentalMaterialInfo` and document the transient usage (e.g., 'transient transduction for luciferase assay, harvested 48 h post-infection').
- The same virus TYPE may appear in BOTH locations depending on experimental context. For example: (1) SARS-CoV-2 as pathogen for infection modeling → OrganoidComponentInfo, (2) Pseudotyped lentivirus with SARS-CoV-2 Spike protein for gene delivery → material_source (Viral_Vector).

**Example material_source entry**:

  * {'material_name':'Lentiviral pLenti-GFP (EF1a)', 'material_type':'Viral Vector', 'concentration':'MOI 5', 'application_method':'spinoculation 800xg 90 min, day 3', 'source':'prepared in-house'}

**Code/Enum mapping:** Use the enum member `CulturePurposeMaterialTypeEnums.Viral_Vector` (member name: `Viral_Vector`, string value: 'Viral Vector') when populating `material_type` for culture-purpose viral vectors.


## [MAT-RULE-06] Reporting Format

### Material_Source Field Specification
**Comprehensive recording of ALL CULTURE materials** (materials that directly participate in cell growth, differentiation, or maintenance during the culture process):
- Each entry requires: material_name, material_type, concentration, application_method, purpose, source
- **material_type**: Select ONE from the types defined in [MAT-RULE-05]. 
- **Examples** (material_type values are from [MAT-RULE-05]):
    * {'material_name':'DMEM/F12', 'material_type':'Medium', 'concentration':'not specified', 'source':'Gibco, 11320033'}
    * {'material_name':'B-27', 'material_type':'Supplement', 'concentration':'1X', 'source':'Gibco, 17504044'}
    * {'material_name':'EGF', 'material_type':'Growth Factor', 'concentration':'50 ng/ml', 'source':'R&D Systems, 236-EG'}
    * {'material_name':'Matrigel', 'material_type':'Matrix', 'concentration':'10 mg/ml', 'application_method':'embedded in', 'source':'Corning, 356231'}
    * {'material_name':'Matrigel', 'material_type':'Matrix', 'concentration':'1% v/v', 'application_method':'added to medium', 'source':'Corning, 356231'}
    * {'material_name':'TrypLE', 'material_type':'Enzyme', 'concentration':'1X', 'source':'Gibco, 12605010'}
    * {'material_name':'PBS', 'material_type':'Buffer', 'concentration':'1X', 'source':'Gibco, 10010023'}
    * {'material_name':'DMSO', 'material_type':'Solvent', 'concentration':'0.1% v/v', 'source':'Sigma-Aldrich, D2650'}
  * {'material_name':'Lentiviral pLenti-GFP (EF1a)', 'material_type':'Viral Vector', 'concentration':'MOI 5', 'application_method':'spinoculation 800xg 90 min, day 3', 'source':'prepared in-house'}
- NOTE: ECM can be used in different ways - distinguish via application_method:  
  'embedded in' (solid 3D matrix), 'added to medium' (liquid supplement), 'coated on plate' (2D coating).

### Minimal Exclusions:
- pH indicators: Phenol Red (unless critical to experiment)
- Water: Deionized water, ultrapure water (unless critical formulation component)
- General lab consumables: CO2 gas, liquid nitrogen (unless part of experimental treatment)

### Implementation Order:
1. Extract base medium name(s) and assign to medium.  
2. Extract serum/antibiotics/buffers/nutrient additives and assign to supplements.  
3. Extract ECM/coatings and assign to Matrix (in material_source).  
4. Extract growth factors.  
5. Extract small molecules.  
6. Extract solvents/vehicles as material_type='Solvent'.  
When an item could fit multiple intuitive categories in prose (e.g., "Matrigel-based medium"), ALWAYS follow these hard boundaries instead of natural-language phrasing.

---

## [MAT-RULE-07] Medium & Supplement Reporting

### MEDIUM & SUPPLEMENT REPORTING RULE
The extractor MUST record medium and supplement information whenever the article explicitly 
(1) names a medium,
(2) specifies a change of medium, or
(3) introduces new supplements, growth factors, or small molecules.  

**NO INFERENCE PRINCIPLE**: When a step continues using a previously defined medium without providing new composition information (e.g., "maintained in the same medium"), DO NOT repeat ingredients and DO NOT invent or back-fill missing components. Structured fields in such steps should remain unchanged. NEVER infer concentrations or missing additives.

If the article does not name the medium at all, or only uses vague labels such as "complete medium" or "growth medium" without listing components, OR only states that cells were "cultured/maintained/transfected as described elsewhere" with citation numbers (e.g., "as described elsewhere31,36") without restating the medium or composition in the current paper, set medium="not specified" (and similarly supplements/growth_factors/small_molecules="not specified") without any inference or cross-article reconstruction.

---

## [MAT-RULE-08] Antibody Extraction for Analytical Assays

### Scope
Antibodies in **analytical techniques** (Western blot, IHC/IF, Flow cytometry, ELISA) → record in experimental technique sections, NOT material_source.

### Recording Location
- **Western blot/ELISA**: `molecular_analysis.targeted_expressions[].target[].antibodies`
- **IHC/IF**: `cellular_imaging.histology_immunostaining[].target_biomarkers[].antibodies`
- **Flow cytometry**: `functional_auxiliary_systems.cytometry_sorting[].target_markers[].antibodies`

### Extraction Fields (5 items)

1. **target_type** (REQUIRED): 'Target' or 'Housekeeping'
   - **'Target'**: Protein of interest (Lgr5, STAT3, pSTAT3, β-catenin, SOX2, Ki-67)
   - **'Housekeeping'**: Loading control/internal reference
     * PCR: GAPDH, ACTB/β-actin, 18S rRNA
     * Western blot: β-actin, GAPDH, TUBB, VINCULIN, HSP90

2. **name** (REQUIRED): Copy exactly from ORIGINAL_TEXT
   - Examples: 'anti-SOX2', 'rabbit anti-Lgr5', 'anti-β-actin (clone AC-15)', 'goat anti-mouse IgG (HRP)'

3. **host_species** (OPTIONAL): Extraction priority:
   1. Direct from naming: "rabbit anti-Lgr5" → 'rabbit'
   2. From secondary: "goat anti-rabbit IgG" → primary host='rabbit' (no [💡] tag, this is logical deduction)
   3. Common patterns: '[host] anti-[target]', '[host] monoclonal'
   4. Use 'not specified' only if all fail

4. **dilution_or_concentration** (OPTIONAL): '1:500', '1:1000', '2 µg/mL'

5. **role** (OPTIONAL): 'primary', 'secondary', 'isotype_control'

### CRITICAL: Separate Entries for Target and Housekeeping

Create one `TargetedExpressionTargetInfo` per target/housekeeping protein.

**Example: Western blot - Lgr5, STAT3 with β-actin control**
```json
{"method":"Western blot","target":[
  {"target_type":"Target","name":"Lgr5","antibodies":[{"name":"rabbit anti-Lgr5","host_species":"rabbit","dilution_or_concentration":"1:1000","role":"primary"}]},
  {"target_type":"Target","name":"STAT3","antibodies":[{"name":"anti-STAT3","host_species":"rabbit","dilution_or_concentration":"1:500","role":"primary"}]},
  {"target_type":"Housekeeping","name":"β-actin","antibodies":[{"name":"mouse anti-β-actin","host_species":"mouse","dilution_or_concentration":"1:5000","role":"primary"}]}
]}
```

### Secondary Antibody Handling

**Scenario 1: Both explicitly named**
```
"probed with rabbit anti-Lgr5 (1:1000), then goat anti-rabbit IgG-HRP (1:5000)"
```
→ Record BOTH:
```json
{"target_type":"Target","name":"Lgr5","antibodies":[
  {"name":"rabbit anti-Lgr5","host_species":"rabbit","dilution_or_concentration":"1:1000","role":"primary"},
  {"name":"goat anti-rabbit IgG-HRP","host_species":"goat","dilution_or_concentration":"1:5000","role":"secondary"}
]}
```

**Scenario 2: Primary host unstated, infer from secondary**
```
"probed with anti-STAT3 (1:500), then goat anti-rabbit IgG (1:5000)"
```
→ Infer primary host (no [💡] tag):
```json
{"target_type":"Target","name":"STAT3","antibodies":[{"name":"anti-STAT3","host_species":"rabbit","dilution_or_concentration":"1:500","role":"primary"}]}
```

### Edge Cases
- **Multiple targets, shared secondary**: Record secondary in each entry if explicit; otherwise omit
- **Isotype control**: role='isotype_control', target_type='Target'
- **Clone info**: Keep in name ('anti-β-actin (clone AC-15)')
- **Conjugated**: Include in name ('goat anti-mouse IgG-HRP', 'anti-CD45-FITC')

---

## [MAT-RULE-09] MATERIAL_SOURCE COMPLETENESS VERIFICATION

### Extraction Completeness Checklist
When extracting material_source, MUST complete ALL steps:

☐ **Step 1 - Read ENTIRE Methods section**
   - Scan 'Materials and Methods', 'Culture conditions', 'Organoid culture', 'Cell culture' sections
   - Include supplementary materials if referenced

☐ **Step 2 - Extract Base Medium Components**
   - Base medium (DMEM, DMEM/F12, Neurobasal, etc.)
   - ALL supplements in recipe (B-27, N-2, L-glutamine, HEPES, NAC, etc.)
   - Even if described as "complete medium" or "standard protocol", extract ALL named components

☐ **Step 3 - Extract Growth Factors & Small Molecules**
   - ALL growth factors (EGF, FGF, WNT3A, R-spondin, Noggin, etc.)
   - ALL pathway modulators (CHIR99021, Y-27632, A83-01, etc.)
   - Do NOT assume "typical concentrations" - only extract what's written

☐ **Step 4 - Extract Matrix & Coating Materials**
   - ECM materials (Matrigel, Collagen, Laminin, etc.)
   - Surface coatings (Poly-L-lysine, Vitronectin, etc.)
   - Include pre-coating materials even if briefly mentioned

☐ **Step 5 - Extract Enzymes & Buffers**
   - Dissociation enzymes (TrypLE, Dispase, Collagenase, DNase)
   - Washing buffers (PBS, DPBS)
   - Only if used DURING culture (not post-fixation)

☐ **Step 6 - Extract Treatment Materials (if culture-stage)**
   - Therapeutic agents added to LIVING cultures (not for endpoint screening)
   - Live-culture dyes (Calcein-AM, not DAPI for fixed samples)
   - Microorganisms (bacteria, viruses with strain info)

☐ **Step 7 - Cross-Reference Protocol Steps**
   - For each [n] reference in protocol.steps, verify material exists in material_source
   - Ensure no "orphan" references (e.g., Material[15] when only 12 items exist)

### Common Extraction Pitfalls
❌ **Mistake 1**: Extracting only "DMEM/F12" but not the supplements added to it
   - Example: Text says "DMEM/F12 containing B-27, N-2, EGF, and FGF" → extract ALL 5 items

❌ **Mistake 2**: Missing enzymes mentioned in digestion/passage steps
   - Example: Text says "Organoids were dissociated with TrypLE" → TrypLE must be in material_source

❌ **Mistake 3**: Forgetting matrix coating materials
   - Example: Text says "Plates were pre-coated with Collagen IV" → Collagen IV must be in material_source

❌ **Mistake 4**: Not extracting individual components from named media
   - Example: Text defines "crypt culture medium (Advanced DMEM/F12 + EGF + Noggin + Rspo1)"
   - → Decompose to: medium='Advanced DMEM/F12', growth_factors=['EGF', 'Noggin', 'Rspo1']

❌ **Mistake 5**: Missing therapeutic agents used IN culture steps
   - Example: Text says "Organoids were treated with siRNA[25] and anlotinib[38] for 24h"
   - → Both siRNA and anlotinib must be in material_source with indices [25] and [38]

---

## [MAT-RULE-10] MATERIAL REFERENCE INDEX VALIDATION

### Mandatory Validation Before Finalizing

**Step 1 - Count total material_source items**
   - Example: If material_source has 15 items → valid indices are [1] through [15]

**Step 2 - Check ALL [n] references in protocol.steps**
   - Scan through every step's `steps` text field
   - Extract all [n] patterns (e.g., Matrigel[1], TrypLE[3], PBS[7])

**Step 3 - Identify indexing errors**:
   - **Out-of-bounds**: [n] where n > total items
     - Example: cisplatin[17] but only 11 items in material_source → **ERROR**
   - **Zero-based**: [0] reference (should be 1-based)
   - **Missing material**: [n] references material not in material_source

**Step 4 - Fix indexing errors**:
   - If material mentioned in step but missing from material_source → ADD to material_source first
   - Re-index all references to ensure sequential [1], [2], [3]...
   - Verify final indices match material_source length

### Example Error Cases
❌ protocol.steps says "treated with cisplatin[7]" but material_source only has 5 items
   → MUST add cisplatin to material_source OR fix index to correct value

❌ protocol.steps says "embedded in Matrigel[0]"
   → MUST change to Matrigel[1] (1-based indexing)

❌ protocol.steps says "added nivolumab[37]" but nivolumab not in material_source
   → MUST add nivolumab to material_source with index [37]
