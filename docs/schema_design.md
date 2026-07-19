# Organoid Culture Knowledge Graph — Detailed Schema Design

> Reference: MOF-ChemUnity (JACS 2025) knowledge graph design methodology
> Data source: MySQL `public_general_2026` table (49 columns, 17,546 rows)

---

## 1. Design Philosophy

Three principles adapted from MOF-ChemUnity for the single wide table scenario:

### 1.1 Scalability

- When adding new sample records, only new `Sample` nodes and their associated edges need to be added. Existing `Organoid`, `Organ`, `System`, `Drug`, `Gene`, and other nodes can be reused.
- The Schema allows adding new node types and relationship types without breaking the existing structure.
- In JSON format, `properties` is a free dictionary that can be extended with fields as needed.

### 1.2 Linkability

- Through the unique ID system (e.g., `org_{name_hash}`), the same organoid type shares a single node across multiple samples.
- Entities extracted from JSON columns (drugs, cytokines, genes, etc.) are deduplicated by content hash, enabling cross-sample linking.
- Supports cross-sample entity aggregation (e.g., how many samples use the same cytokine).

### 1.3 Queryability

- Supports precise queries: exact matching by node ID or properties
- Supports graph traversal: starting from a Sample, follow edges to find all associated organoids, drugs, genes, biomarkers, etc.
- Supports keyword search: fuzzy matching across all node property text
- Supports composite queries: e.g., "Human intestinal organoid samples using EGF factor and screened with Cisplatin"

### 1.4 Design Principle: What Should Become an Independent Node

When designing nodes from the `public_general_2026` wide table, the following criteria are used:

| Criterion | Description | Example |
|------|------|------|
| **Reusability** | Does this entity appear in multiple samples? | Same drug, same gene, same cytokine |
| **Independent Queryability** | Would users query by this entity as an entry point? | "What liver organoids are there?" "Phenotype of APC knockout?" |
| **Property Richness** | Does this entity have its own attributes? | Drug has name, target, concentration |
| **Graph Traversal Value** | Would making it a node produce meaningful graph paths? | Sample→Drug→Sample to find different samples with the same drug |

**Columns that do not meet the above criteria → retained as Sample node properties.**

---

## 2. Node Type Definitions

A total of **19 node types**, divided into 6 semantic layers.

### 2.1 Sample — Core Fact Entity

Each row in `public_general_2026` corresponds to one Sample node, the central hub of the entire graph.

```
Sample {
    id:          "smp_{sample_id}"           -- Globally unique ID (sample_id is the table primary key)
    type:        "Sample"
    properties: {
        sample_id:              str           -- Original sample identifier (PK)
        culture_days:           str           -- Culture duration in days
        coculture:              str           -- Co-culture description
        coculture_days:         str           -- Co-culture duration in days
        cultivation_material_sources:  json   -- Culture materials (raw JSON)
        cultivation_protocol:   json          -- Culture protocol steps (raw JSON)
        culture_technique:      json          -- Culture technique (raw JSON)
        culture_condition:      json          -- Culture conditions (raw JSON)
        coculture_cultivation_protocol:   json -- Co-culture protocol steps
        coculture_cultivation_material_sources: json -- Co-culture materials
        coculture_technique:    json          -- Co-culture technique
        coculture_condition:    json          -- Co-culture conditions
        endpoints:              str           -- Culture endpoints
        read_out:               str           -- Co-culture read-out results
        time_anchors:           json          -- Global time anchors
        application_strategy:   str           -- Application decision information
        search_content:         str           -- Search interface content (for full-text search)
        accession:              str           -- Data accession
        is_analyzed:            str           -- Whether analyzed
        platform:               str           -- Platform
    }
}
```

> **Note**: Columns such as culture materials, conditions, steps, and endpoints vary greatly between samples and have low reusability; they are not split into independent nodes and are retained in Sample properties.

### 2.2 Organoid — Organoid Type Identifier

Standardized organoid type, the second core for information aggregation in the graph.

```
Organoid {
    id:          "org_{name_hash}"           -- Content hash deduplication based on organoid name
    type:        "Organoid"
    properties: {
        name:                   str           -- Organoid name (e.g., "Intestinal Organoid")
        canonical_name:         str           -- Organoid canonical name
        characteristics:        str           -- Organoid characteristics
        functions:              str           -- Organoid functions
        maturity:               str           -- Maturity description
        complexity:             str           -- Complexity description
        is_organoid:            str           -- Whether it is an organoid ("yes"/"no")
    }
}
```

> **Note**: The original `system` column is no longer an Organoid attribute but is split into an independent System node (see 2.4), indirectly associated via the Organ → System relationship.

### 2.3 Organ — Tissue/Organ Source

```
Organ {
    id:          "orn_{name_hash}"            -- Hash deduplication based on organ name
    type:        "Organ"
    properties: {
        name:                   str           -- Organ name (e.g., "Small Intestine", "Liver", "Brain", "Colon")
    }
}
```

### 2.4 System — NEW

Physiological system classifications extracted from the `system` JSON column. Multiple organs share the same system, with high reusability and independent query value.

```
System {
    id:          "sys_{name_hash}"            -- Hash deduplication based on system name
    type:        "System"
    properties: {
        name:                   str           -- System name (e.g., "Digestive System", "Nervous System", "Respiratory System")
        organs:                 [str]         -- List of organs included in this system (e.g., ["Small Intestine", "Colon", "Stomach"])
    }
}
```

| Typical System Values | Included Organs |
|---------------|-------------|
| Digestive System | Small Intestine, Colon, Stomach, Liver, Pancreas, Esophagus |
| Nervous System | Brain, Spinal Cord, Retina, Peripheral Nerve |
| Respiratory System | Lung, Nasal Epithelium, Trachea, Bronchus |
| Urinary System | Kidney, Bladder, Ureter |
| Reproductive System | Ovary, Testis, Uterus, Prostate, Mammary Gland |
| Endocrine System | Thyroid, Pituitary, Adrenal Gland |
| Cardiovascular System | Heart, Blood Vessel |
| Integumentary System | Skin, Hair Follicle |
| Immune System | Thymus, Spleen, Lymph Node |
| Musculoskeletal System | Skeletal Muscle, Bone, Cartilage |

> **Query scenarios**: "Which organ organoids are in the digestive system?" "Comparison of nervous system and respiratory system organoids"

### 2.5 Organism — Species

```
Organism {
    id:          "osm_{name_hash}"            -- Hash deduplication based on species name
    type:        "Organism"
    properties: {
        name:                   str           -- Species name (e.g., "Human", "Mouse", "Zebrafish")
    }
}
```

### 2.6 Source — Source

Tissue source, cell line, or iPSC source information of the organoid.

```
Source {
    id:          "src_{name_hash}"            -- Hash deduplication based on source description
    type:        "Source"
    properties: {
        name:                   str           -- Source description (e.g., "Lgr5+ intestinal stem cells")
    }
}
```

### 2.7 CellFactor — Cytokines

Growth factors, cytokines, and small molecules extracted from the `cell_factors` and `coculture_cell_factors` JSON columns.

```
CellFactor {
    id:          "cf_{name_hash}"             -- Hash deduplication based on factor name
    type:        "CellFactor"
    properties: {
        name:                   str           -- Factor name (e.g., "EGF", "R-spondin1", "Noggin", "CHIR99021")
        category:               str           -- Classification: "growth_factor" | "small_molecule" | "cytokine" | "supplement"
        concentration:          str|null      -- Concentration (if included in JSON)
    }
}
```

### 2.8 Technology — Techniques

Culture/analysis techniques extracted from the `techologies` JSON column.

```
Technology {
    id:          "tec_{name_hash}"            -- Hash deduplication based on technique name
    type:        "Technology"
    properties: {
        name:                   str           -- Technique name (e.g., "CRISPR-Cas9", "scRNA-seq", "Immunofluorescence", "Live-cell imaging")
        category:               str           -- Classification: "gene_editing" | "omics" | "imaging" | "culture" | "other"
    }
}
```

### 2.9 Drug — Drugs

Screened drugs extracted from the `drug_screening` JSON column.

```
Drug {
    id:          "drg_{name_hash}"            -- Hash deduplication based on drug name
    type:        "Drug"
    properties: {
        name:                   str           -- Drug name (e.g., "Cisplatin", "5-FU", "Gemcitabine")
        category:               str|null      -- Drug classification (e.g., "Chemotherapy", "Targeted Therapy")
        target:                 str|null      -- Drug target
        concentration_range:    str|null      -- Screening concentration range
    }
}
```

### 2.10 Gene — Gene Editing

Gene editing targets extracted from the `gene_name` and `sgrna` columns.

```
Gene {
    id:          "gen_{name_hash}"            -- Hash deduplication based on gene name
    type:        "Gene"
    properties: {
        name:                   str           -- Gene name (e.g., "APC", "TP53", "KRAS")
        sgrna:                  str|null      -- sgRNA sequence
        editing_method:         str           -- Editing method (e.g., "CRISPR-Cas9", "shRNA", "siRNA")
    }
}
```

### 2.11 DiseaseModel — Disease Models

Disease modeling information extracted from the `disease_modeling` column.

```
DiseaseModel {
    id:          "dm_{name_hash}"             -- Hash deduplication based on disease name
    type:        "DiseaseModel"
    properties: {
        name:                   str           -- Disease name (e.g., "Colorectal Cancer", "Cystic Fibrosis", "IBD")
        category:               str           -- Classification: "Cancer" | "Genetic" | "Inflammatory" | "Infectious" | "Metabolic" | "Other"
        description:            str|null      -- Disease description
    }
}
```

### 2.12 Infection — Infection Challenges

Microbial infection experiment information extracted from the `infection_list` JSON column.

```
Infection {
    id:          "inf_{name_hash}"            -- Hash deduplication based on pathogen name
    type:        "Infection"
    properties: {
        name:                   str           -- Pathogen name (e.g., "Helicobacter pylori", "Salmonella", "SARS-CoV-2")
        category:               str           -- Classification: "Bacteria" | "Virus" | "Fungi" | "Parasite"
        moi:                    str|null      -- Multiplicity of infection (MOI)
    }
}
```

### 2.13 Biomarker — Biomarkers

Biomarker information extracted from the `biomarker` and `biomarker_coculture` JSON columns.

```
Biomarker {
    id:          "bmk_{name_hash}"            -- Hash deduplication based on biomarker name
    type:        "Biomarker"
    properties: {
        name:                   str           -- Biomarker name (e.g., "Lgr5", "Ki67", "Muc2", "Villin")
        category:               str           -- Classification: "Stemness" | "Proliferation" | "Differentiation" | "Apoptosis" | "Other"
        detection_method:       str|null      -- Detection method (e.g., "qPCR", "Immunostaining", "RNA-seq")
    }
}
```

### 2.14 Phenotype — Phenotypes

Phenotype information extracted from the `phenotype_identification` JSON column.

```
Phenotype {
    id:          "phn_{hash}"                 -- Hash deduplication based on phenotype content
    type:        "Phenotype"
    properties: {
        name:                   str           -- Phenotype name (e.g., "Cystic morphology", "Budding organoid", "Crypt-like structure")
        category:               str           -- Classification: "Morphology" | "Growth" | "Differentiation" | "Viability" | "Other"
        description:            str|null      -- Detailed phenotype description
        quantification:         str|null      -- Quantitative metrics (if included in JSON)
    }
}
```

### 2.15 Test — Detection Methods

Experimental detection/analysis methods extracted from the `test` JSON column.

```
Test {
    id:          "tst_{name_hash}"            -- Hash deduplication based on detection method name
    type:        "Test"
    properties: {
        name:                   str           -- Detection method name (e.g., "Immunofluorescence", "Flow Cytometry", "qPCR", "RNA-seq", "Western Blot")
        category:               str           -- Classification: "Imaging" | "Molecular" | "Biochemical" | "Sequencing" | "Functional" | "Other"
        target:                 str|null      -- Detection target
    }
}
```

### 2.16 Omics — Omics

Omics data information extracted from the `omics_id` JSON column and `platform`, `accession` columns.

```
Omics {
    id:          "omc_{name_hash}"            -- Hash deduplication based on omics ID
    type:        "Omics"
    properties: {
        omics_id:               str           -- Omics data ID
        omics_type:             str           -- Omics type (e.g., "scRNA-seq", "Bulk RNA-seq", "ATAC-seq", "Proteomics")
        platform:               str|null      -- Sequencing/detection platform
        accession:              str|null      -- Data accession number
    }
}
```

### 2.17 Composition — Biological Composition — NEW

Organoid cell composition profiles extracted from the `composition` JSON column. Different organoids may share the same cell type combinations, with cross-sample reusability.

```
Composition {
    id:          "cmp_{hash}"                 -- Hash deduplication based on cell type list content hash
    type:        "Composition"
    properties: {
        cell_types:             [str]         -- Cell type list (e.g., ["Enterocytes", "Goblet cells", "Paneth cells", "Lgr5+ stem cells"])
        category:               str           -- Classification: "Epithelial" | "Mesenchymal" | "Neural" | "Immune" | "Mixed" | "Other"
    }
}
```

| Typical Composition | Cell Types |
|-----------------|---------|
| Intestinal Epithelium | Enterocytes, Goblet cells, Paneth cells, Enteroendocrine cells, Tuft cells, Lgr5+ stem cells |
| Gastric Epithelium | Parietal cells, Chief cells, Mucous neck cells, G cells, Pit cells |
| Brain Organoid | Neurons, Astrocytes, Oligodendrocytes, Neural progenitors, Microglia |
| Lung Epithelium | Ciliated cells, Club cells, Goblet cells, Basal cells, AT1 cells, AT2 cells |
| Liver Organoid | Hepatocytes, Cholangiocytes, Hepatic stellate cells, Kupffer cells |
| Kidney Organoid | Podocytes, Proximal tubular cells, Distal tubular cells, Collecting duct cells |

> **Query scenarios**: "Which organoids contain both goblet cells and Paneth cells?" "Which brain organoids have neural progenitors?" "Top 5 samples with the most similar cell composition?"

### 2.18 Application — Application Directions

Application scenarios for organoids.

```
Application {
    id:          "app_{name_hash}"            -- Hash deduplication based on application name
    type:        "Application"
    properties: {
        name:                   str           -- Application name
        category:               str           -- Classification ("Drug Screening", "Disease Modeling", "Regenerative Medicine", "Toxicology", "Personalized Medicine", "Basic Research")
        description:            str           -- Application description
    }
}
```

### 2.19 Publication — Reference Sources

Reference information for experiment records or method sources.

```
Publication {
    id:          "pub_{doi_hash}"             -- Hash deduplication based on DOI
    type:        "Publication"
    properties: {
        reference:              str           -- Reference information
        doi:                    str|null      -- DOI number
        title:                  str|null      -- Publication title (if resolvable)
        year:                   int|null      -- Publication year (if resolvable)
    }
}
```

---

## 3. Relationship Type Definitions

A total of **20 relationship types** (including 2 inferred relationships).

### 3.1 HAS_ORGANOID
```
(Sample) --[:HAS_ORGANOID]--> (Organoid)
Semantics: The organoid type cultured in this sample
Cardinality: One Sample → One Organoid
```

### 3.2 FROM_ORGAN
```
(Organoid) --[:FROM_ORGAN]--> (Organ)
Semantics: Which organ/tissue the organoid is derived from
Cardinality: One Organoid → One or more Organs
```

### 3.3 BELONGS_TO_SYSTEM
```
(Organ) --[:BELONGS_TO_SYSTEM]--> (System)
Semantics: Which physiological system the organ belongs to
Cardinality: One Organ → One System (an organ typically belongs to only one system)
```

### 3.4 FROM_ORGANISM
```
(Sample) --[:FROM_ORGANISM]--> (Organism)
Semantics: The species source of this sample
Cardinality: One Sample → One Organism
```

### 3.5 DERIVED_FROM
```
(Organoid) --[:DERIVED_FROM]--> (Source)
Semantics: Tissue/cell source of the organoid
Cardinality: One Organoid → One or more Sources
```

### 3.6 USES_FACTOR
```
(Sample) --[:USES_FACTOR]--> (CellFactor)
Semantics: Cytokines/growth factors/small molecules used in this sample's culture
Properties:
  - context: str  ("primary" | "coculture")  -- Distinguishes primary culture from co-culture
```

### 3.7 USES_TECHNOLOGY
```
(Sample) --[:USES_TECHNOLOGY]--> (Technology)
Semantics: Techniques used in this sample's culture/analysis
```

### 3.8 SCREENS_DRUG
```
(Sample) --[:SCREENS_DRUG]--> (Drug)
Semantics: Which drug screening was performed on this sample
Properties:
  - concentration: str|null   -- Screening concentration
  - duration: str|null        -- Treatment duration
```

### 3.9 HAS_GENE_EDIT
```
(Sample) --[:HAS_GENE_EDIT]--> (Gene)
Semantics: What gene editing was performed on this sample
```

### 3.10 MODELS_DISEASE
```
(Organoid) --[:MODELS_DISEASE]--> (DiseaseModel)
Semantics: What disease this organoid is used to model
```

### 3.11 HAS_INFECTION
```
(Sample) --[:HAS_INFECTION]--> (Infection)
Semantics: What infection/microbial challenge experiment was conducted on this sample
```

### 3.12 HAS_BIOMARKER
```
(Sample) --[:HAS_BIOMARKER]--> (Biomarker)
Semantics: What biomarkers this sample expressed/detected
Properties:
  - context: str  ("primary" | "coculture")  -- Distinguishes primary culture from co-culture biomarkers
```

### 3.13 HAS_PHENOTYPE
```
(Sample) --[:HAS_PHENOTYPE]--> (Phenotype)
Semantics: What phenotype was observed in this sample
```

### 3.14 HAS_TEST
```
(Sample) --[:HAS_TEST]--> (Test)
Semantics: What detection/analysis method was performed on this sample
```

### 3.15 HAS_OMICS
```
(Sample) --[:HAS_OMICS]--> (Omics)
Semantics: What omics data is associated with this sample
```

### 3.16 HAS_COMPOSITION
```
(Sample) --[:HAS_COMPOSITION]--> (Composition)
Semantics: What cell composition the organoid in this sample contains
```

### 3.17 HAS_APPLICATION
```
(Organoid) --[:HAS_APPLICATION]--> (Application)
Semantics: What directions this organoid can be applied to
Properties:
  - relevance: str  ("primary" | "secondary" | "potential")
```

### 3.18 CITES
```
(Sample) --[:CITES]--> (Publication)
Semantics: Which publication the sample record references
```

### 3.19 TREATS_DISEASE (Inferred Relationship)
```
(Drug) --[:TREATS_DISEASE]--> (DiseaseModel)
Semantics: This drug is used to treat/study this disease
Inference logic: Drug screening + DiseaseModel co-occur in the same sample → infer drug-disease association
Properties:
  - confidence: float  (0.0–1.0, based on co-occurrence frequency)
  - sample_count: int  (co-occurring sample count)
```
> **Query scenarios**: "What drugs treat colorectal cancer?" "Which disease models can Cisplatin be used for?" "Which drugs have been screened in multiple cancer models?"

### 3.20 INDICATES_DISEASE (Inferred Relationship)
```
(Biomarker) --[:INDICATES_DISEASE]--> (DiseaseModel)
Semantics: This biomarker is associated with/indicates this disease
Inference logic: Biomarker detection + DiseaseModel co-occur in the same sample → infer biomarker-disease association
Properties:
  - confidence: float  (0.0–1.0, based on co-occurrence frequency)
  - sample_count: int  (co-occurring sample count)
```
> **Query scenarios**: "What biomarkers are associated with colorectal cancer?" "In which disease models is Lgr5 expressed?" "Which biomarkers are abnormal in multiple diseases?"

---

## 4. Relationship Overview Diagram

```
                         ┌──────────────┐
                         │  Publication │
                         └──────┬───────┘
                                │ CITES
                         ┌──────▼───────┐
                    ┌────│    Sample    │────┐
                    │    └──────┬───────┘    │
                    │           │            │
       ┌────────────┤  HAS_ORGANOID          ├──────────────────┐
       │            │           │            │                  │
       ▼            │           ▼            │                  │
┌──────────┐        │    ┌──────────┐        │                  │
│ Organism │        │    │ Organoid │        │                  │
└──────────┘        │    └────┬─────┘        │                  │
                    │         │              │                  │
       ┌────────────┤    FROM_ORGAN          │                  │
       │            │         │              │                  │
       ▼            │         ▼              │                  │
┌──────────┐        │    ┌──────────┐        │                  │
│  Source  │◄───────┘    │  Organ   │        │                  │
└──────────┘ DERIVED     └────┬─────┘        │                  │
                  _FROM        │ BELONGS_TO   │                  │
                               ▼   _SYSTEM    │                  │
                          ┌──────────┐        │                  │
                          │  System  │        │                  │
                          └──────────┘        │                  │
                                              │                  │
       ┌──────────────────────────────────────┘                  │
       │                                                         │
       ▼         ▼         ▼         ▼         ▼         ▼
┌──────────┐ ┌────────┐ ┌──────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
│CellFactor│ │Technology│ │ Drug │ │  Gene  │ │DiseaseModel│ │Infection │
└──────────┘ └────────┘ └──┬───┘ └────────┘ └────△───△──┘ └──────────┘
 USES_FACTOR USES_TECH SCREENS  HAS_GENE  MODELS   │   │  HAS_INFECTION
                       _DRUG    _EDIT     _DISEASE  │   │
                           │         ┌──────────────┘   │
                           │ TREATS  │  INDICATES_DISEASE│
                           │ _DISEASE│                    │
                           ▼         │                    │
                          ┌──────────┴────────────────────┘
                          │
       ▼         ▼         ▼         ▼         ▼
┌──────────┐ ┌────────┐ ┌──────┐ ┌────────┐ ┌──────────────┐
│Biomarker │ │Phenotype│ │ Test │ │ Omics  │ │ Composition  │
└────┬─────┘ └────────┘ └──────┘ └────────┘ └──────────────┘
 HAS_│BIOMARKER HAS_PHENO HAS_TEST HAS_OMICS  HAS_COMPOSITION
     │           _TYPE
     │ INDICATES
     │ _DISEASE
     └────────────────┘  (already shown above)

       ▼
┌──────────────┐
│ Application  │
└──────────────┘
 HAS_APPLICATION
```

---

## 5. Data Provenance Design

Referencing the paper's design of "storing evidence to improve transparency and interpretability," each node and edge retains data provenance information:

### 5.1 Node Provenance

Each node records its source:

```json
{
  "id": "smp_ABC123",
  "type": "Sample",
  "properties": { ... },
  "_provenance": {
    "source_type": "mysql",
    "source_database": "organoid_db",
    "source_table": "public_general_2026",
    "source_row_id": "ABC123",
    "extracted_at": "2026-07-18T10:00:00"
  }
}
```

For nodes extracted from JSON columns (e.g., Drug, CellFactor, System, Composition), the source column is additionally recorded:

```json
{
  "id": "drg_a1b2c3",
  "type": "Drug",
  "properties": { "name": "Cisplatin" },
  "_provenance": {
    "source_type": "json_extraction",
    "source_column": "drug_screening",
    "parent_sample_ids": ["smp_ABC123", "smp_DEF456"],
    "extracted_at": "2026-07-18T10:00:00"
  }
}
```

### 5.2 Edge Provenance

Each relationship edge also records its source:

```json
{
  "source": "smp_ABC123",
  "target": "drg_a1b2c3",
  "relation": "SCREENS_DRUG",
  "properties": {
    "concentration": "10 µM"
  },
  "_provenance": {
    "derived_from": "json_column",
    "source_column": "drug_screening",
    "confidence": 1.0
  }
}
```

---

## 6. Node ID Generation Rules

| Node Type | ID Prefix | ID Format | Deduplication Basis |
|---------|--------|---------|---------|
| Sample | `smp` | `smp_{sample_id}` | `sample_id` column (PK, naturally unique) |
| Organoid | `org` | `org_{name_hash}` | Content hash of `organoid` column |
| Organ | `orn` | `orn_{name_hash}` | Content hash of `organ` column |
| System | `sys` | `sys_{name_hash}` | Hash of system name from `system` JSON |
| Organism | `osm` | `osm_{name_hash}` | Content hash of `organism` column |
| Source | `src` | `src_{name_hash}` | Content hash of `source` column |
| CellFactor | `cf` | `cf_{name_hash}` | Hash of factor name |
| Technology | `tec` | `tec_{name_hash}` | Hash of technique name |
| Drug | `drg` | `drg_{name_hash}` | Hash of drug name |
| Gene | `gen` | `gen_{name_hash}` | Hash of gene name |
| DiseaseModel | `dm` | `dm_{name_hash}` | Hash of disease name |
| Infection | `inf` | `inf_{name_hash}` | Hash of pathogen name |
| Biomarker | `bmk` | `bmk_{name_hash}` | Hash of biomarker name |
| Phenotype | `phn` | `phn_{content_hash}` | Content hash of phenotype content |
| Test | `tst` | `tst_{name_hash}` | Hash of detection method name |
| Omics | `omc` | `omc_{id_hash}` | Hash of omics ID |
| Composition | `cmp` | `cmp_{content_hash}` | Content hash of cell type list |
| Application | `app` | `app_{name_hash}` | Hash of application name |
| Publication | `pub` | `pub_{doi_hash}` | Hash of DOI (or reference text hash if no DOI) |

> Hash algorithm: First 8 characters of MD5 (or first 12 characters of SHA256), ensuring brevity with extremely low collision probability.

---

## 7. MySQL Column → KG Mapping Master Table

| public_general_2026 Column | Mapping Target | Description |
|------------------------|---------|------|
| `sample_id` | **Sample** node ID | PK, core entity |
| `organoid` | **Organoid** node | Extracted as independent node |
| `organ` | **Organ** node | Extracted as independent node |
| `system` | **System** node | JSON, extract entity; Organ → BELONGS_TO_SYSTEM → System |
| `source` | **Source** node | Extracted as independent node |
| `organism` | **Organism** node | Extracted as independent node |
| `canonical_name` | Organoid property | |
| `characteristics` | Organoid property | |
| `functions` | Organoid property | |
| `maturity` | Organoid property | |
| `complexity` | Organoid property | |
| `is_organoid` | Organoid property | |
| `cell_factors` | **CellFactor** node | JSON, extract entity |
| `coculture_cell_factors` | **CellFactor** node | JSON, extract entity, edge marked `context:coculture` |
| `techologies` | **Technology** node | JSON, extract entity |
| `drug_screening` | **Drug** node | JSON, extract entity |
| `gene_name` | **Gene** node | Extract entity |
| `sgrna` | Gene property | |
| `disease_modeling` | **DiseaseModel** node | Extract entity |
| `infection_list` | **Infection** node | JSON, extract entity |
| `biomarker` | **Biomarker** node | JSON, extract entity |
| `biomarker_coculture` | **Biomarker** node | JSON, extract entity, edge marked `context:coculture` |
| `phenotype_identification` | **Phenotype** node | JSON, extract entity |
| `test` | **Test** node | JSON, extract entity |
| `omics_id` | **Omics** node | JSON, extract entity |
| `platform` | Omics property | |
| `accession` | Omics property | |
| `composition` | **Composition** node | JSON, extract entity |
| `application` | **Application** node | Extract entity |
| `application_strategy` | Sample property | Long text, associated with specific sample |
| `reference` | **Publication** node property | |
| `doi` | **Publication** node ID source | |
| `culture_days` | Sample property | Highly variable between samples |
| `coculture_days` | Sample property | Same as above |
| `coculture` | Sample property | Descriptive text |
| `culture_technique` | Sample property | JSON, different from `techologies` |
| `cultivation_protocol` | Sample property | JSON |
| `cultivation_material_sources` | Sample property | JSON |
| `culture_condition` | Sample property | JSON |
| `coculture_cultivation_protocol` | Sample property | JSON |
| `coculture_cultivation_material_sources` | Sample property | JSON |
| `coculture_technique` | Sample property | JSON |
| `coculture_condition` | Sample property | JSON |
| `endpoints` | Sample property | Long text |
| `read_out` | Sample property | Long text |
| `time_anchors` | Sample property | JSON |
| `search_content` | Sample property | Full-text search index |
| `is_analyzed` | Sample property | |
| `deleted_at` | — | Soft delete marker, not included in KG |

---

## 8. Co-Culture Handling Strategy

Co-culture data does not use independent node types; instead:

1. **Same node types**: Co-culture cytokines and biomarkers still map to `CellFactor` and `Biomarker` nodes
2. **Edge attribute distinction**: The `context` attribute on edges identifies the source:
   - `context: "primary"` — from primary culture columns such as `cell_factors`, `biomarker`
   - `context: "coculture"` — from co-culture columns such as `coculture_cell_factors`, `biomarker_coculture`
3. **Co-culture descriptions**: `coculture`, `coculture_days`, `coculture_condition`, etc. are retained in Sample properties

This avoids doubling the Schema (no need to create a Coculture version for each node type) while preserving query distinction capability.

---

## 9. Comparison with MOF-ChemUnity Schema

| MOF-ChemUnity Node/Relationship | Corresponding in This Schema | Mapping Description |
|------------------------|---------------|---------|
| **MOF** node | **Sample** | The paper's MOF is the core entity; here Sample is the core entity |
| **Name** node | **Organoid** | Standardized entity name |
| **Publication** node | **Publication** | Direct correspondence |
| **Property** node | **Phenotype** + **Biomarker** + **Composition** | The paper's physicochemical properties split into phenotype, biomarker, and cell composition |
| **Synthesis** node | Sample properties (`cultivation_protocol`, etc.) | Synthesis info retained as properties in single wide table scenario |
| **Application** node | **Application** | Direct correspondence |
| **Has Property** relation | HAS_PHENOTYPE + HAS_BIOMARKER + HAS_COMPOSITION | Split into three relationships |
| **Has Synthesis** relation | None (retained in Sample properties) | Not needed for wide table scenario |
| **Has Source** relation | CITES | Corresponds |
| — | **Organ** + **System** + **Organism** | Not in the paper; new biological hierarchy dimension in this Schema |
| — | **BELONGS_TO_SYSTEM** | Newly added Organ→System hierarchy relationship |

---

## 10. JSON Graph File Format Example

```json
{
  "meta": {
    "name": "Organoid Culture Knowledge Graph",
    "version": "2.0",
    "created": "2026-07-18",
    "source_table": "public_general_2026",
    "description": "Knowledge graph of organoid culture samples from public_general_2026",
    "node_types": [
      "Sample", "Organoid", "Organ", "System", "Organism", "Source",
      "CellFactor", "Technology", "Drug", "Gene",
      "DiseaseModel", "Infection", "Biomarker", "Phenotype",
      "Test", "Omics", "Composition", "Application", "Publication"
    ],
    "relationship_types": [
      "HAS_ORGANOID", "FROM_ORGAN", "BELONGS_TO_SYSTEM", "FROM_ORGANISM", "DERIVED_FROM",
      "USES_FACTOR", "USES_TECHNOLOGY", "SCREENS_DRUG", "HAS_GENE_EDIT",
      "MODELS_DISEASE", "HAS_INFECTION", "HAS_BIOMARKER", "HAS_PHENOTYPE",
      "HAS_TEST", "HAS_OMICS", "HAS_COMPOSITION", "HAS_APPLICATION", "CITES",
      "TREATS_DISEASE", "INDICATES_DISEASE"
    ]
  },
  "nodes": [
    {
      "id": "smp_ABC123",
      "type": "Sample",
      "properties": {
        "sample_id": "ABC123",
        "culture_days": "7",
        "culture_condition": {"temperature": "37°C", "co2": "5%"},
        "endpoints": "Organoid formation efficiency > 80%"
      },
      "_provenance": {
        "source_type": "mysql",
        "source_table": "public_general_2026",
        "source_row_id": "ABC123"
      }
    },
    {
      "id": "org_a1b2c3d4",
      "type": "Organoid",
      "properties": {
        "name": "Intestinal Organoid",
        "canonical_name": "Small Intestinal Organoid"
      }
    },
    {
      "id": "orn_small_intestine",
      "type": "Organ",
      "properties": {
        "name": "Small Intestine"
      }
    },
    {
      "id": "sys_digestive",
      "type": "System",
      "properties": {
        "name": "Digestive System",
        "organs": ["Small Intestine", "Colon", "Stomach", "Liver", "Pancreas"]
      }
    },
    {
      "id": "cmp_intestinal_epi",
      "type": "Composition",
      "properties": {
        "cell_types": ["Enterocytes", "Goblet cells", "Paneth cells", "Enteroendocrine cells", "Lgr5+ stem cells"],
        "category": "Epithelial"
      }
    },
    {
      "id": "drg_e5f6g7h8",
      "type": "Drug",
      "properties": {
        "name": "Cisplatin",
        "category": "Chemotherapy",
        "target": "DNA"
      }
    }
  ],
  "edges": [
    {
      "source": "smp_ABC123",
      "target": "org_a1b2c3d4",
      "relation": "HAS_ORGANOID"
    },
    {
      "source": "org_a1b2c3d4",
      "target": "orn_small_intestine",
      "relation": "FROM_ORGAN"
    },
    {
      "source": "orn_small_intestine",
      "target": "sys_digestive",
      "relation": "BELONGS_TO_SYSTEM"
    },
    {
      "source": "smp_ABC123",
      "target": "cmp_intestinal_epi",
      "relation": "HAS_COMPOSITION"
    },
    {
      "source": "smp_ABC123",
      "target": "drg_e5f6g7h8",
      "relation": "SCREENS_DRUG",
      "properties": {
        "concentration": "10 µM"
      },
      "_provenance": {
        "derived_from": "json_column",
        "source_column": "drug_screening"
      }
    },
    {
      "source": "drg_e5f6g7h8",
      "target": "dm_colorectal_cancer",
      "relation": "TREATS_DISEASE",
      "properties": {
        "confidence": 0.85,
        "sample_count": 12
      },
      "_provenance": {
        "derived_from": "co_occurrence_inference",
        "description": "Drug and DiseaseModel co-occur in same sample"
      }
    },
    {
      "source": "bmk_lgr5",
      "target": "dm_colorectal_cancer",
      "relation": "INDICATES_DISEASE",
      "properties": {
        "confidence": 0.92,
        "sample_count": 25
      },
      "_provenance": {
        "derived_from": "co_occurrence_inference",
        "description": "Biomarker and DiseaseModel co-occur in same sample"
      }
    }
  ]
}
```

---

## References

1. Pruyn, T. M. et al. MOF-ChemUnity: Literature-Informed Large Language Models for Metal−Organic Framework Research. *J. Am. Chem. Soc.* **2025**, *147*, 43474−43486.
2. MOF-ChemUnity open-source code: https://github.com/AI4ChemS/MOF_ChemUnity
