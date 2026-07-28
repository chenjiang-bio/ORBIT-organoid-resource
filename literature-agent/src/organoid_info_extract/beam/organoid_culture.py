import unicodedata
import os
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field, field_validator, model_validator
from enum import Enum


class EnumValue:
    """Container for enum value with description metadata.
    
    Used to define enum members with associated documentation:
        MY_VALUE = EnumValue("my_value", "Description of what this means")
    
    This allows centralized maintenance of enum values and their descriptions
    in a single location, avoiding duplication across Field descriptions.
    """
    
    def __init__(self, value: str, description: str = ""):
        self.value = value
        self.description = description
    
    def __repr__(self):
        return f"EnumValue({self.value!r}, {self.description!r})"


PROMPT_VERSION = "v1.4.0-2025-12-19"


THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# Load knowledge files and flatten concatenate
_knowledge_files = [
    "knowledge/domain_knowledge.md",
    "knowledge/organ_system_map.md",
    "knowledge/cultivation_stage.md",
    "knowledge/materials_rules.md",
    "knowledge/core_rules.md",
    "knowledge/scoring_rules.md",
]

_knowledge_sections = []
for file_path in _knowledge_files:
    content = open(os.path.join(THIS_DIR, file_path), "r", encoding="utf-8").read()
    _knowledge_sections.append(content)

OUTPUT_INFOS = ("\n\n" + "="*5 + "\n\n").join(_knowledge_sections)

_UNICODE_REPLACEMENTS = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u2032": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u2033": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    "\u2212": "-",
    "\u00ad": "-",
    "\u200b": "",  # zero-width space
    "\u00a0": " ",
    "\u00b0C":"°C",
    "\u03bc":"μ",
    "\u03b1":"α",
    "\u03b2":"β",
    "\u03b3":"γ",
    "\u03b4":"δ",
    "\u03ba":"κ",
    "\u03c3":"σ",
    "\u03a3":"Σ",
}


def _normalize_string(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    if not normalized:
        return normalized
    # Replace common typography characters with ASCII equivalents
    return "".join(_UNICODE_REPLACEMENTS.get(ch, ch) for ch in normalized)


def _normalize_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        return _normalize_string(payload)
    if isinstance(payload, list):
        return [_normalize_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(_normalize_payload(item) for item in payload)
    if isinstance(payload, dict):
        return {
            (_normalize_string(key) if isinstance(key, str) else key): _normalize_payload(value)
            for key, value in payload.items()
        }
    return payload



class BaseModel(PydanticBaseModel):
    """Pydantic BaseModel that normalizes strings before validation."""

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, data: Any):
        return _normalize_payload(data)

class StandardizedName(BaseModel):
    """Structured name with original source text and standardized nomenclature."""
    
    src: str = Field(
        description=(
            "The EXACT name as it appears in the original article text. "
            "This replaces the old [💡] tag pattern (e.g., 'cGAS [MB21D1 💡]' → src='cGAS', std='MB21D1'). "
            "**CRITICAL: Preserve original terminology exactly:** "
            "- Keep capitalization, spaces, hyphens as written in Methods/Results "
            "- Include modification states if mentioned (e.g., 'phospho-ERK', 'cleaved CASP3') "
            "- Use the term the authors used, not what you think is 'more standard' "
            "**Examples:** "
            "- Article says 'cGAS' → src='cGAS' (NOT 'CGAS' or 'MB21D1') "
            "- Article says 'p65' → src='p65' (NOT 'RELA' or 'NF-κB p65') "
            "- Article says 'PD-L1' → src='PD-L1' (NOT 'CD274' or 'PD-L1/CD274') "
            "- Article says 'NF-kB p65 phospho S276' → src='NF-kB p65 phospho S276' "
            "- Article says 'anti-Ki-67' → src='Ki-67' (target name)"
        )
    )
    
    std: str = Field(
        description=(
            "The standardized/canonical name using official nomenclature systems. "
            "**STANDARDIZATION STRATEGY (context-dependent):** "
            "The standardization rules depend on WHAT is being detected/measured in the parent field's context: "
            "**STRATEGY A: Gene/Transcript Detection (DNA/RNA/mRNA targets)** "
            "- Use SPECIES-SPECIFIC gene symbols (see RULE 28 in core_rules.md) "
            "- Human: ALL UPPERCASE (HGNC) - 'PTPRC', 'MKI67', 'CD3E', 'ITGAX' "
            "- Mouse: Capitalized (MGI) - 'Ptprc', 'Mki67', 'Cd3e', 'Itgax' "
            "- Rat/Zebrafish: Follow RGD/ZFIN nomenclature "
            "- Examples: CD45 mRNA→'PTPRC'(human)/'Ptprc'(mouse), Ki-67 mRNA→'MKI67'/'Mki67' "
            "**STRATEGY B: Protein Detection (antibody targets, Western blot, IHC/IF, flow cytometry)** "
            "- Use standardized PROTEIN names, NOT gene symbols "
            "- CD nomenclature proteins: CD45→'CD45', CD3→'CD3', Ki-67→'Ki-67' "
            "- Non-CD proteins: Use common protein name or gene symbol as fallback "
            "- Examples: anti-CD45→'CD45' (NOT 'PTPRC'), anti-Ki-67→'Ki-67' (NOT 'MKI67') "
            "**STRATEGY C: Metabolites/Small Molecules** "
            "- Use standard chemical names (IUPAC, ChEBI) "
            "**STRATEGY D: Cellular States** "
            "- Use descriptive state names: 'Live cell', 'S-phase cell', 'Apoptotic cell' "
            "**Token optimization:** When src is already standard, set std='' (empty string) and system will auto-copy src to std."
        )
    )
    
    @model_validator(mode="after")
    def _auto_fill_std(self) -> "StandardizedName":
        """Auto-fill std from src when std is empty string (token-saving feature)."""
        if self.std == "":
            self.std = self.src
        return self

class StrEnumBase(str, Enum):
    """Enhanced string enum base class with automatic description support.
    
    Supports two definition styles:
    1. Simple: VALUE = "value"
    2. With description: VALUE = EnumValue("value", "Description text")
    
    Provides get_field_description() class method to auto-generate Field descriptions.
    """
    
    def __new__(cls, value):
        """Handle both plain strings and EnumValue objects."""
        if isinstance(value, EnumValue):
            # Extract actual value from EnumValue
            obj = str.__new__(cls, value.value)
            obj._value_ = value.value
            obj._description_ = value.description
        else:
            # Plain string value
            obj = str.__new__(cls, value)
            obj._value_ = value
            obj._description_ = ""
        return obj
    
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.__name__ = "Enum[str]"  # 🔥 All subclasses auto-set
    
    @classmethod
    def get_field_description(cls, main_desc: str = "") -> str:
        """Generate standardized Field description for this enum.
        
        Args:
            main_desc: Main description or additional rules for this enum field
        
        Returns:
            Formatted description string for Field()
        
        Example:
            end_status: MyEnum = Field(
                description=MyEnum.get_field_description(
                    main_desc="Must be consistent with end_time field."
                )
            )
        """
        # Get actual class name (not the overridden "Enum[str]")
        # enum_class_name = cls.__qualname__
        
        # Count and format values
        values_list = [f"'{e._value_}'" for e in cls]
        values_str = " | ".join(values_list)
        values_count = len(values_list)
        
        # Value definitions as bullet list
        v_descs = "**VALUES DESC**:"
        for enum_member in cls:
            if hasattr(enum_member, '_description_') and enum_member._description_:
                v_descs += f"- '{enum_member._value_}': {enum_member._description_}"
        if v_descs == "**VALUES DESC**:":
            v_descs = ""

        if main_desc is not None and main_desc != "":
            main_desc = f"**MAIN INFO**: {main_desc}"
        else:
            main_desc = ""
        
        doc_str = ""

        if cls.__doc__ is not None:
            doc_str = f"**ENUM DESC**:{''.join([line.lstrip() for line in cls.__doc__.strip().splitlines()])}."
            
        return f"{main_desc} {doc_str} **ENUMS VALUES[{values_count}]**: {values_str} {v_descs}"

class CultureModelCategoryEnums(StrEnumBase):
    ORGANOID = "Organoid" 
    SPHEROID = "Spheroid"  
    EMBRYOID_BODY = "EmbryoidBody"  
    AGGREGATE = "Aggregate"   
    ORGANO_TYPIC = "Organotypic"
    TISSUE_ENGINEERED = "Tissue Engineered"
    OTHER_3D = "Other3D"               
    TWO_D = "2D"                
    OTHERS = "Others"                     

class OrganoidOriginEnums(StrEnumBase):
    """
    Organoid-origin category for this component.
    Use this ONLY for populations that are part of a bona fide organoid module (typically role='organoid_core' or closely related developmental progenitors). 
    This allows composite or multi-organ constructs to have different organoid-source types at the component level (e.g., cardiomyocytes from iPSCs vs hepatocytes from PDOs). 
    **EXTRACTION RULES:** 
    1. EXPLICIT mention: If article clearly states origin type (e.g., 'iPSC-derived', 'patient-derived organoid', 'ESC-based'), use that category directly. 
    2. REASONABLE INFERENCE: When article provides sufficient context for confident scientific inference, apply appropriate category: 
    2.1 Adult tissue + stem cells (e.g., 'Lgr5+ stem cells from adult mouse intestine', 'adult tissue-derived organoids') → ASCs 
    2.2 Patient tumor/disease tissue (e.g., 'patient-derived glioblastoma', 'primary colorectal cancer tissue') → PDOs 
    2.3 Pluripotent stem cell differentiation from ESCs (e.g., 'differentiated from H9 cell line') → ESCs 
    2.4 Pluripotent stem cell differentiation from iPSCs (e.g., 'iPSC-based protocol') → iPSCs 
    2.5 Pluripotent stem cell differentiation from being able to distinguish ESCs vs iPSCs → PSCs
    2.6 Fetal/embryonic tissue (e.g., 'E14.5 mouse cortex', 'fetal brain tissue') → Fetal-Tissue-Derived 
    3. GENETIC MODIFICATION SYSTEMS DO NOT ALTER ORGANOID_ORIGIN: Tools for genetic manipulation (Cre-lox systems like Villin-CreERT2/Ah-Cre, floxed alleles like Lgr4fx/fx, reporter alleles like R26R-LacZ, CRISPR/Cas9 modifications) are NOT sources of cells—they are experimental tools. Origin is determined by WHERE cells came from (adult tissue → ASCs, patient tumor → PDOs, PSC differentiation → iPSCs/ESCs), NOT by what genetic tools were applied. Example: 'Lgr5+ crypts from Lgr4fx/fx Lgr5fl/fl Villin-CreERT2 mice' → ASCs (adult intestinal stem cells with genetic tools for conditional knockout). 
    **AVOID over-caution:** Do NOT leave null solely because the exact phrase 'ASCs' or 'iPSCs' is absent—use scientific reasoning based on tissue source, developmental stage, and culture context.
    null: When origin cannot be determined even after reasonable inference based on article context, developmental stage, and culture details.
    """
    TDCs = EnumValue("TDCs", "Tissue-Derived Cells (from primary tissues, not stem cell-derived). ")
    PSCs = EnumValue("PSCs", "Pluripotent Stem Cells")
    iPSCs = EnumValue("iPSCs", "Induced Pluripotent Stem Cells")
    ESCs = EnumValue("ESCs", "Embryonic Stem Cells")
    ASCs = EnumValue("ASCs", "Adult Stem Cells")
    PDOs = EnumValue("PDOs", "Patient-Derived Organoids")
    Fetal_Tissue_Derived = EnumValue("Fetal_Tissue_Derived", "Fetal or Embryonic Tissue-Derived Cells")
    MSCs = EnumValue("MSCs", "Mesenchymal Stem/Stromal Cells")
    HSCs = EnumValue("HSCs", "Hematopoietic Stem Cells")
    HSPCs = EnumValue("HSPCs", "Hematopoietic Stem/Progenitor Cells")
    NSCs = EnumValue("NSCs", "Neural Stem Cells")
    TSCs = EnumValue("TSCs", "Trophoblast Stem Cells")
    PCs = EnumValue("PCs", "Progenitor Cells")
    Primary_Cells = EnumValue("Primary_Cells", "[AVOID over-caution] Primary Cells (unexpanded, non-stem cells directly from tissue). ")
    Stem_Cells = EnumValue("Stem_Cells", "[AVOID over-caution] Established Stem Cell Line (e.g., P19, F9 embryonic carcinoma stem cells, or other pluripotent/multipotent stem cell lines maintained as stable lines). ")
    Somatic_Cell_Lines = EnumValue("Somatic_Cell_Lines", "[AVOID over-caution] Immortalized somatic (non-stem, differentiated) cell lines from cell repositories or established lab stocks (e.g., HEK293T, DLD1, Caco-2, HeLa, Pan02, C2C12, Jurkat, A549). EXCLUDE stem cell lines (use Stem_Cells/iPSCs/ESCs instead). Distinct from Primary_Cells (limited passage, <10 generations) and PDOs (patient-derived, early passages). Use ONLY for well-characterized somatic cell lines with unlimited proliferation capacity and stable phenotype across passages.")
    Component = EnumValue("Component", "[AVOID over-caution] The component is a co-culture element (immune cells, stromal support, vascular cells, pericytes, microbial) not forming the organoid core.")
    Others = EnumValue("Others", "[AVOID over-caution] Others not covered above. Add notes in puzzles. ")


class OrganEnums(StrEnumBase):
    """
    Organ or tissue type category.
    """
    Mouth = "Mouth"
    Pharynx = "Pharynx"
    Esophagus = "Esophagus"
    Stomach = "Stomach"
    Mesentery = "Mesentery"
    Small_Intestine = "Small Intestine"
    Large_Intestine = "Large Intestine"
    Intestine = "Intestine"
    Liver = "Liver"
    Biliary_Tract = "Biliary Tract"
    Gall_Bladder = "Gall Bladder"
    Pancreas = "Pancreas"
    Anus = "Anus"
    Colon = "Colon"
    Tooth = "Tooth"
    Rectum = "Rectum"
    Caecum = "Caecum"
    Ampulla = "Ampulla"
    Vermiform_Appendix = "Vermiform Appendix"
    Peritoneum = "Peritoneum"
    Respiratory_Airway = "Respiratory Airway"
    Nose = "Nose"
    Larynx = "Larynx"
    Trachea = "Trachea"
    Bronchi = "Bronchi"
    Lung = "Lung"
    Pleura = "Pleura"
    Heart = "Heart"
    Artery = "Artery"
    Vein = "Vein"
    Capillary = "Capillary"
    Blood_Vessel = "Blood Vessel"
    Brain = "Brain"
    Brainstem = "Brainstem"
    Spinal_Cord = "Spinal Cord"
    Nerve = "Nerve"
    Hypothalamus = "Hypothalamus"
    Cerebellum = "Cerebellum"
    Pineal_Gland = "Pineal Gland"
    Pituitary_Gland = "Pituitary Gland"
    Hippocampus = "Hippocampus"
    Thyroid = "Thyroid"
    Adrenal_Gland = "Adrenal Gland"
    Parathyroid_Gland = "Parathyroid Gland"
    Thymus_Gland = "Thymus Gland"
    Kidney = "Kidney"
    Ureter = "Ureter"
    Bladder = "Bladder"
    Urethra = "Urethra"
    Testis = "Testis"
    Ovary = "Ovary"
    Uterus = "Uterus"
    Penis = "Penis"
    Vagina = "Vagina"
    Prostate = "Prostate"
    Seminal_Vesicle = "Seminal Vesicle"
    Fallopian_Tube = "Fallopian Tube"
    Genital = "Genital"
    Vulva = "Vulva"
    Clitoris = "Clitoris"
    Cervix = "Cervix"
    Skeletal_Muscle = "Skeletal Muscle"
    Ligament = "Ligament"
    Tendon = "Tendon"
    Diaphragm = "Diaphragm"
    Muscle = "Muscle"
    Bone = "Bone"
    Bone_Marrow = "Bone Marrow"
    Joint = "Joint"
    Interstitium = "Interstitium"
    Skin = "Skin"
    Hair_Follicle = "Hair Follicle"
    Nails = "Nails"
    Subcutaneous_Tissue = "Subcutaneous Tissue"
    Adipose_Tissue = "Adipose Tissue"
    Connective_Tissue = "Connective Tissue"
    Spleen = "Spleen"
    Lymph_Node = "Lymph Node"
    Tonsil = "Tonsil"
    Lymphatic_Vessel = "Lymphatic Vessel"
    Eye = "Eye"
    Ear = "Ear"
    Tongue = "Tongue"
    Salivary_Gland = "Salivary Gland"
    Mammary_Gland = "Mammary Gland"
    Placenta = "Placenta"
    Others = "Others"

class OrganSystemEnums(StrEnumBase):
    Digestive_System = "Digestive System"
    Respiratory_System = "Respiratory System"
    Cardiovascular_System = "Cardiovascular System"
    Nervous_System = "Nervous System"
    Endocrine_System = "Endocrine System"
    Urinary_System = "Urinary System"
    Reproductive_System = "Reproductive System"
    Muscular_System = "Muscular System"
    Skeletal_System = "Skeletal System"
    Integumentary_System = "Integumentary System"
    Lymphatic_System = "Lymphatic System"
    Sense_Organs = "Sense Organs"
    Accessory_Organs = "Accessory Organs"
    Others = "Others"


class CompositeRoleEnums(StrEnumBase):
    SINGLE = "Single organoid only"
    COMPOSITE = "Composite organoid system"
    PRECURSOR = "Precursor-only module for composite"
    BOTH = "Single organoid and precursor for composite"

class ComponentRoleEnums(StrEnumBase):
    """Component role category in the organoid system"""
    ORGANOID_CORE = "organoid_core"
    STROMAL_SUPPORT = "stromal_support"
    IMMUNE_CO_CULTURE = "immune_co-culture"
    MICROBIAL_CO_CULTURE = "microbial_co-culture"
    VASCULAR_SUPPORT = "vascular_support"
    PERICYTE_SUPPORT = "pericyte_support"
    FEEDER_LAYER = "feeder_layer"
    OTHER_CO_CULTURE = "other-co-culture"


class MicroorganismEnums(StrEnumBase):
    """Type of microorganism"""
    VIRUS = "Virus"
    BACTERIA = "Bacteria"
    FUNGI = "Fungi"
    PARASITE = "Parasite"
    OTHER = "Others"

class TimeUnitEnum(str, Enum):
    DAYS = 'days'
    HOURS = 'hours'
    WEEKS = 'weeks'
    MONTHS = 'months'
    MINUTES = 'minutes'
    SECONDS = 'seconds'


def _time_value_to_days(v: float, unit: TimeUnitEnum) -> float:
    if unit == TimeUnitEnum.DAYS:
        return v
    if unit == TimeUnitEnum.WEEKS:
        return v * 7.0
    if unit == TimeUnitEnum.HOURS:
        return v / 24.0
    if unit == TimeUnitEnum.MINUTES:
        return v / (24.0 * 60.0)
    if unit == TimeUnitEnum.SECONDS:
        return v / (24.0 * 3600.0)
    if unit == TimeUnitEnum.MONTHS:
        return v * 30.0
    return v

# class TimePointNodeInfo(BaseModel):
#     value: int = Field(description="The specific time point value. Examples: '5', '10', '15'.")
#     time_unit: TimeUnitEnum = Field(description=f"The time unit of this time point. from {[e.value for e in TimeUnitEnum]}")
#     value_in_days: Optional[float] = Field(
#         default=None,
#         description=(
#             "Normalized duration in DAYS for downstream calculations. "
#             "If not provided, it will be computed automatically. "
#             "Conversion: days=v; weeks=v*7; hours=v/24; minutes=v/(24*60); seconds=v/(24*3600); months=v*30."
#         ),
#     )

#     @model_validator(mode="after")
#     def _fill_value_in_days(self) -> "TimePointNodeInfo":
#         if self.value_in_days is None:
#             self.value_in_days = _time_value_to_days(float(self.value), self.time_unit)
#         return self

class TimeRangeNodeInfo(BaseModel):
    min_value: int = Field(description="Lower bound of the fuzzy observation window in original text.")
    min_time_unit: TimeUnitEnum = Field(description=f"Unit for min_value. Must be one of {[e.value for e in TimeUnitEnum]}.")

    max_value: int = Field(description="Upper bound of the fuzzy observation window in original text.")
    max_time_unit: TimeUnitEnum = Field(description=f"Unit for max_value. Must be one of {[e.value for e in TimeUnitEnum]}.")

    min_value_in_days: Optional[float] = Field(
        default=None,
        description="Normalized lower bound in days. If not provided, computed from (min_value, min_time_unit)."
    )
    max_value_in_days: Optional[float] = Field(
        default=None,
        description="Normalized upper bound in days. If not provided, computed from (max_value, max_time_unit)."
    )

    @model_validator(mode="after")
    def _validate_range(self) -> "TimeRangeNodeInfo":
        # Fill normalized values
        if self.min_value_in_days is None:
            self.min_value_in_days = _time_value_to_days(float(self.min_value), self.min_time_unit)
        if self.max_value_in_days is None:
            self.max_value_in_days = _time_value_to_days(float(self.max_value), self.max_time_unit)

        # Validate ordering using normalized DAYS (works even if units differ)
        if self.max_value_in_days < self.min_value_in_days:
            raise ValueError("TimeRangeNodeInfo: max must be >= min after normalization to days.")

        return self

class DurationRangeInfo(BaseModel):
    """Represents a time duration/span (how long something lasts) with provenance tracking.
    
    SEMANTIC DISTINCTION (CRITICAL - see RULE 1 in KNOWLEDGE):
    - TimeRangeNodeInfo: FUZZY TIME POINT on timeline (when something happens, e.g., 'detected on day 14-16')
    - DurationRangeInfo: TIME SPAN/DURATION (how long something lasts, e.g., 'cultured for 7-14 days')
    
    Example contrast:
    - 'Organoids detected at day 14-16' → TimeRangeNodeInfo (time point)
    - 'Organoids cultured for 14-16 days' → DurationRangeInfo (duration)
    """
    
    min_value: int = Field(
        description=(
            "Minimum duration value. For exact durations (e.g., 'cultured for 10 days'), "
            "set min_value=max_value. For range durations (e.g., '7-14 days'), set actual bounds."
        )
    )
    min_time_unit: TimeUnitEnum = Field(
        description=f"Time unit for min_value. Must be one of {[e.value for e in TimeUnitEnum]}."
    )
    
    max_value: int = Field(
        description=(
            "Maximum duration value. For exact durations (e.g., 'cultured for 10 days'), "
            "set min_value=max_value. For range durations (e.g., '7-14 days'), set actual bounds."
        )
    )
    max_time_unit: TimeUnitEnum = Field(
        description=f"Time unit for max_value. Must be one of {[e.value for e in TimeUnitEnum]}."
    )
    
    is_original: bool = Field(
        description=(
            "Data provenance flag: whether this duration is explicitly stated in ORIGINAL_TEXT (True) "
            "or inferred/calculated by LLM from context (False). "
            "**Examples of is_original=True:** "
            "- Article states 'cultured for 7-14 days', '10 day culture period', 'maintained for 2 weeks' "
            "- Article states 'from day 0 to day 10' (explicit start-end implies 10-day duration) "
            "- Article states 'total culture time was 21 days' "
            "**Examples of is_original=False:** "
            "- Duration calculated from time_axis anchor endpoints when article doesn't state total time "
            "- Inferred from protocol steps without explicit duration statement "
            "- Computed from 'seeded on day 0, analyzed on day 10' when article doesn't say '10 days' "
            "**CRITICAL RULE:** If article ANYWHERE explicitly mentions the total culture/co-culture duration "
            "(even if phrased as start-to-end timepoints like 'day 0 to day 14'), set is_original=True. "
            "Only use is_original=False when duration MUST be computed from time_axis without explicit source text support."
        )
    )
    
    source_text: Optional[str] = Field(
        default=None,
        description=(
            "Optional: Original text phrase describing this duration. Highly recommended when is_original=True. "
            "Examples: 'cultured for 7-14 days', 'maintained for 10 days', '2-week culture period', "
            "'from day 0 to day 14', 'total co-culture time: 48 hours'. "
            "**Usage rules:** "
            "- When is_original=True: SHOULD provide source_text to preserve exact wording for verification. "
            "- When is_original=False: omit source_text (duration is computed, not quoted). "
            "**Purpose:** Enables validation, quality control, and disambiguation when multiple duration statements exist."
        )
    )
    
    # Normalized values for downstream calculations
    min_value_in_days: Optional[float] = Field(
        default=None,
        description="Normalized minimum duration in days. Auto-computed if not provided."
    )
    max_value_in_days: Optional[float] = Field(
        default=None,
        description="Normalized maximum duration in days. Auto-computed if not provided."
    )
    
    @model_validator(mode="after")
    def _fill_and_validate(self) -> "DurationRangeInfo":
        """Auto-fill normalized day values and validate range ordering."""
        
        # Auto-compute normalized days
        if self.min_value_in_days is None:
            self.min_value_in_days = _time_value_to_days(float(self.min_value), self.min_time_unit)
        if self.max_value_in_days is None:
            self.max_value_in_days = _time_value_to_days(float(self.max_value), self.max_time_unit)
        
        # Validate ordering
        if self.max_value_in_days < self.min_value_in_days:
            raise ValueError(
                f"DurationRangeInfo: max duration ({self.max_value_in_days} days) "
                f"must be >= min duration ({self.min_value_in_days} days)"
            )
        
        # Validate source_text usage
        if self.is_original and self.source_text is None:
            # Warning: should provide source_text when is_original=True, but not blocking
            pass
        
        return self

class OperatorRepeatInfo(BaseModel):
    repeat_num: Optional[int] = Field(default=None, description="The number of repetitions for this operation. should match with `repeat_end` field. Examples: 3, 5, 10, null(when No specific repetition count).")
    repeat_interval: str = Field(default=None, description="The condition for loop/repeat. Examples: 'every 3 days', 'weekly', 'twice per week', 'passaged weekly'.")
    repeat_end: Optional[str] = Field(default=None, description="The end time point of this repeat operation. Examples: 'when dense/when confluent”', 'passaged 20 times', 'passage 12', 'until certain phenotypes appeared','A certain marker has been detected.','Sufficient quantity for transplantation/sequencing/infection experiments'.")

class TimeAxisAnchorInfo(BaseModel):
    id: int = Field(description="The id of Time point anchor. Examples: 1, 2, 3, ...")
    
    name_action: Optional[str] = Field(
        default=None,
        description=(
            "Name this time point based on the action/step/operation. "
            "CRITICAL: Even when exact timing (day/hour) is unknown, ALWAYS use descriptive action names rather than 'unknown' or generic placeholders. "
            "Action categories include: "
            "- Culture operations: 'cell seeding', 'medium change', 'passage 3', 'add Matrigel', 'remove medium' "
            "- Experimental interventions: 'drug treatment', 'viral infection', 'co-culture addition' "
            "- Detection/analysis: 'detect Ki67 expression', 'qPCR sampling', 'RNA extraction', 'immunostaining', 'biomarker detection' "
            "- Observations: 'observe crypt formation', 'assess viability', 'measure diameter', 'phenotype observation' "
            "Examples: 'detect SOX2 biomarker' (NOT 'unknown biomarker detection'), 'observe organoid morphology' (NOT 'unknown observation'), 'passage cells' (NOT 'unknown passage')."
        )
    )
    name_cell_state: Optional[str] = Field(
        default=None,
        description="Name this time point based on the state/stage of cells. Examples: 'pluripotent', 'differentiated', 'mature'."
    )
    name_morphology: Optional[str] = Field(
        default=None,
        description="Name this time point based on structural morphology. Examples: 'EB formation', 'budding structure', 'crypt-villus'."
    )

    timing: Optional[TimeRangeNodeInfo] = Field(
        default=None,
        description=(
            "Represents a fuzzy time point or observation window (discrete set of possible days), not a continuous interval. "
            "Absolute time index since Day 0 in unified range format (TimeRangeNodeInfo). "
            "For day-based timepoints, BOTH bounds should use days: "
            "single day => min_value=max_value, min_time_unit=max_time_unit; "
            "range day => min_value<max_value, min_time_unit=max_time_unit (e.g., day 14-16). "
            "Examples: "
            "- '14-16 days'  -> min_value=14, min_time_unit='days'; max_value=16, max_time_unit='days' "
            "- '30 min to 2 hours' -> min_value=30, min_time_unit='minutes'; max_value=2, max_time_unit='hours' "
            "- '2 h to 1 day' -> min_value=2, min_time_unit='hours'; max_value=1, max_time_unit='days' "
            "Indicates the phenotype may be observed on any of days 14, 15, or 16 (fuzzy point set). "
            "**When timing is unknown**: Set timing=null BUT ensure name_action/name_cell_state/name_morphology provides clear descriptive name. "
            "Example: timing=null + name_action='detect GFAP expression' (clear what happened, just timing unclear). "
            "**CRITICAL**: Even when timing=null, the event's relative temporal order is determined by its position in time_axis.axes segments."
        )
    )

    @field_validator("timing", mode="before")
    @classmethod
    def _coerce_anchor_day(cls, v):
        if v is None:
            return None
        # legacy int day -> range(day)
        if isinstance(v, int):
            return {
                "min_value": v, "min_time_unit": "days",
                "max_value": v, "max_time_unit": "days",
            }
        # legacy old-range dict with shared time_unit -> convert
        if isinstance(v, dict) and "min_value" in v and "max_value" in v and "time_unit" in v:
            u = v["time_unit"]
            return {
                "min_value": v["min_value"], "min_time_unit": u,
                "max_value": v["max_value"], "max_time_unit": u,
            }
        # legacy timepoint-like dict: {"value":2,"time_unit":"hours"}
        if isinstance(v, dict) and "value" in v and "time_unit" in v and "min_value" not in v:
            u = v["time_unit"]
            return {
                "min_value": v["value"], "min_time_unit": u,
                "max_value": v["value"], "max_time_unit": u,
            }
        # already new-format dict -> keep
        return v
    
    desc: str = Field(description="The detailed description of this time point in ORIGINAL_TEXT.")

    @model_validator(mode="after")
    def at_least_one_anchor(self) -> "TimeAxisAnchorInfo":
        if not any([self.name_action, self.name_cell_state, self.name_morphology]):
            raise ValueError("At least one of 'name_action', 'name_cell_state', 'name_morphology' must be provided.")
        return self

class TimeAxisAnchorRefInfo(BaseModel):
    id: int = Field(
        description=(
            "The id of Time point anchor. It must match with one of TimeAxisAnchorInfo.id in time_anchors list. Examples: 1, 2, 3, ... "
            "**CRITICAL**: The referenced anchor may have timing=null (unknown timing), in which case the event's relative temporal order is determined by its position in time_axis.axes segment sequence, not by absolute day values."
            "Not nullable. The referenced anchor MUST exist in time_anchors list."
        )
    )
    name: str = Field(
        description="The name of time point anchor. It must match with one of TimeAxisAnchorInfo.name_action/name_cell_state/name_morphology in time_anchors list."
    )

class TimeAxisSegmentInfo(BaseModel):
    start_anchor: TimeAxisAnchorRefInfo = Field(
        description=(
            "Reference to the start time point anchor by id. "
            "Must match an anchor id from the time_anchors list in OrganoidCultureResult."
        )
    )
    end_anchor: TimeAxisAnchorRefInfo = Field(
        description=(
            "Reference to the end time point anchor by id. "
            "Must match an anchor id from the time_anchors list in OrganoidCultureResult."
        )
    )
    repeat: Optional[OperatorRepeatInfo] = Field(
        default=None, 
        description=(
            "Repeat/recurring operation information. Use when article describes recurring actions (e.g., 'medium changed every 2 days'). "
            "CRITICAL: The segment with repeat represents the ENTIRE repeat period. "
            "start_anchor should be the baseline/initiation point (NOT the first occurrence). "
            "Example: 'After solidification, medium replaced every 2 days' → start_anchor = solidification, NOT first medium change. "
            "DO NOT create separate anchors for each occurrence (e.g., don't create day 2, 4, 6, 8 from 'every 2 days'). "
            "If end condition is vague ('until passage'), end_anchor's timing MUST be null."
        )
    )

    duration: Optional[DurationRangeInfo] = Field(
        default=None,
        description=(
            "Duration/time span between start_anchor and end_anchor (DurationRangeInfo). See RULE 1. "
            "SEMANTIC: This is a DURATION (how long the segment lasts), NOT a time point. "
            "Single duration: set min_value=max_value (e.g., exactly 2 hours). "
            "Range duration: set different min/max values (e.g., 7-14 days). "
            "Provenance: Typically is_original=False (computed from anchors), unless article explicitly states segment duration. "
            "Examples: "
            "- Article says 'seeded on day 0, passaged on day 7' → duration with min_value=7, max_value=7, is_original=False (computed). "
            "- Article says 'differentiation phase lasted 10-14 days' → duration with min_value=10, max_value=14, is_original=True, source_text='differentiation phase lasted 10-14 days'. "
            "If cannot determine, set null (DO NOT default to 0)."
        ),
    )

    @field_validator("duration", mode="before")
    @classmethod
    def _coerce_duration(cls, v):
        if v is None:
            return None

        # Already DurationRangeInfo -> keep as-is
        if isinstance(v, DurationRangeInfo):
            return v

        # BACKWARD COMPATIBILITY: Old data using TimeRangeNodeInfo
        # Convert TimeRangeNodeInfo → DurationRangeInfo (set is_original=False since migrated)
        if isinstance(v, TimeRangeNodeInfo):
            return {
                "min_value": v.min_value,
                "min_time_unit": v.min_time_unit,
                "max_value": v.max_value,
                "max_time_unit": v.max_time_unit,
                "is_original": False,  # Migrated data, provenance unknown
            }

        # Legacy int -> days, is_original=False (computed/inferred)
        if isinstance(v, int):
            return {
                "min_value": v, "min_time_unit": "days",
                "max_value": v, "max_time_unit": "days",
                "is_original": False,
            }

        if isinstance(v, dict):
            # NEW DurationRangeInfo format with is_original
            if all(k in v for k in ("min_value", "min_time_unit", "max_value", "max_time_unit", "is_original")):
                return v

            # NEW format without is_original -> default False
            if all(k in v for k in ("min_value", "min_time_unit", "max_value", "max_time_unit")):
                return {**v, "is_original": False}

            # Legacy OLD shared unit format: {"min_value":14,"max_value":16,"time_unit":"days"}
            if all(k in v for k in ("min_value", "max_value", "time_unit")):
                u = v["time_unit"]
                return {
                    "min_value": v["min_value"], "min_time_unit": u,
                    "max_value": v["max_value"], "max_time_unit": u,
                    "is_original": False,
                }

            # Dict has min/max but no unit -> default days, is_original=False
            if "min_value" in v and "max_value" in v:
                return {
                    "min_value": v["min_value"], "min_time_unit": "days",
                "max_value": v["max_value"], "max_time_unit": "days",
                    "is_original": False,
                }

        return v


class TimeAxisBranchInfo(BaseModel):
    """A complete timeline branch composed of ordered time segments"""
    
    branch_name: str = Field(
        description=(
            "Descriptive name for this timeline branch. "
        )
    )
    
    component_id: Optional[str] = Field(
        default=None,
        description=(
            "Component ID from composition list (e.g., 'C1', 'C2', 'C3'). "
            "REQUIRED for component-based branches (organoid cores, virus, microorganisms, immune cells, auxiliary cells). "
            "NULL for experimental treatment branches (drug arms, experimental variations). "
            "Main branch (primary organoid core) should have component_id='C1' (or the first organoid_core component_id)."
        )
    )
    
    axes: List[TimeAxisSegmentInfo] = Field(
        min_length=1,
        description=(
            "Ordered list of time segments forming this branch's complete timeline. "
            ""
            "**CRITICAL PRINCIPLE 1 — axes is the SOLE carrier of temporal order.** "
            "The time_anchors array order is arbitrary and carries NO chronological meaning. "
            "**Anchor IDs are opaque unique identifiers only — a lower ID does NOT mean earlier in time.** "
            "Chronological order is determined exclusively by the sequence of axes segments. "
            "IDs may be non-consecutive, and the narrative order may even be 'reverse' relative to ID numbers "
            "(e.g., axes [id=8→id=3, id=3→id=11, id=11→id=5] is valid if that matches the paper's narrative order). "
            ""
            "**CRITICAL PRINCIPLE 2 — MUST Strict chain continuity.** "
            "Consecutive segments MUST share the same anchor endpoint: `axes[i].end_anchor.id == axes[i+1].start_anchor.id`. "
            "This forms an unbroken chain A→B→C→D. "
            "❌ INVALID: [8→3, 11→5] — gap between 3 and 11 breaks the chain. "
            "✅ VALID:   [8→3, 3→11, 11→5] — each segment's end equals the next segment's start. "
            ""
            "**CRITICAL PRINCIPLE 3 — MUST No zero-length segments.** "
            "start_anchor.id MUST NOT equal end_anchor.id. A segment from an anchor to itself is meaningless and will be rejected. Remove any such segment entirely. "
            "❌ INVALID: axes = [1→1, 1→3, 3→3, 3→5] — segments 1→1 and 3→3 are zero-length. "
            "✅ VALID:   axes = [1→3, 3→5]. "
            ""
            "**CRITICAL PRINCIPLE 4 — Coverage rule per branch.** "
            "Each branch must include ALL MILESTONE anchors that belong to that branch's own component. "
            "MILESTONE anchors of OTHER components may be omitted (they appear in their own branch). "
            "OBSERVATION anchors MUST NEVER appear as segment endpoints in any branch. "
            "INTERVENTION anchors (merge points, treatments) appear naturally where the narrative requires. "
            ""
            "Coverage rules by branch type: "
            "• Main branch (C1): MUST include every MILESTONE anchor belonging to the primary organoid core (C1). May omit MILESTONE anchors that belong to other components (C2, C3, …). "
            "• Component branch (C2/C3/…): MUST include every MILESTONE anchor belonging to that component. May omit all C1 and other components' MILESTONE anchors. Last segment MUST end at the shared INTERVENTION merge-point anchor. "
            ""
            "**Example, Suppose time_anchors contains: "
            "id=1 MILESTONE(C1): seeding, id=6 MILESTONE(C1): passage, id=3 MILESTONE(C1): differentiation, id=9 INTERVENTION: co-culture setup (merge point), id=4 MILESTONE(C2): virus thawing, id=7 MILESTONE(C2): virus expansion, id=12 OBSERVATION: qPCR sampling. "
            "Main branch axes (C1): [1→6, 6→3, 3→9]  — covers C1 milestones {1,6,3} in narrative order; skips C2 milestones {4,7} and OBSERVATION {12}; ends at merge point 9. "
            "VirusExpansion branch axes (C2): [4→7, 7→9]  — covers C2 milestones {4,7}; ends at merge point 9. "
            "Both branches reference id=9 (merge point) but 4 and 7 do NOT appear in Main — that is correct. "
        )
    )
    
    is_main: bool = Field(
        default=False,
        description=(
            "True if this is the Main timeline (primary organoid core component, typically C1). "
            "Exactly one branch in time_axis list must have is_main=True."
        )
    )


class MicroorganismInfo(BaseModel):
    """Detailed information about a co-cultured microorganism"""
    microorganism_type: MicroorganismEnums = Field(
        description=f"Type of microorganism. Select ONE from: {[e.value for e in MicroorganismEnums]}"
    )
    scientific_name: str = Field(
        description=(
            "Scientific name or standardized identifier of the microorganism. "
            "NAMING CONVENTIONS BY ORGANISM TYPE: "
            "For viruses: use the form appearing in the article. Virus nomenclature does not follow binomial convention; "
            "both ICTV-approved descriptive names (e.g., 'Severe acute respiratory syndrome coronavirus 2', 'Influenza A virus') "
            "and widely accepted abbreviations (e.g., 'SARS-CoV-2', 'HIV-1', 'HBV', 'HCV') are scientifically valid. "
            "Preserve the article's terminology to ensure consistency, searchability, and traceability to the original source. "
            "For bacteria: use binomial name (e.g., 'Escherichia coli', 'Staphylococcus aureus'). "
            "For fungi: use binomial name (e.g., 'Candida albicans', 'Aspergillus fumigatus'). "
            "If specific name not mentioned, use generic category name that matches the enum value selected in the microorganism_type field. "
            "GENERALIZED NAMES WITH [❓️] TAG: If the article confirms microbial co-culture but does not specify the exact species, "
            "use a generalized name with [❓️] tag (e.g., 'Virus [❓️]', 'Bacteria [❓️]', 'Fungi [❓️]'). "
            "This satisfies the co-culture requirement while flagging the lack of specificity."
        )
    )
    strain: Optional[str] = Field(default='not specified',
        description=(
            "Strain or variant identifier if specified. Examples: 'Delta variant', 'Omicron BA.1', "
            "'E. coli K-12', 'C. albicans SC5314'. "
        )
    )


class CocultureObjs(BaseModel):
    """Co-culture organisms information"""
    Microorganism: Optional[List[MicroorganismInfo]] = Field(
        default=None,
        description="List of co-cultured microorganisms with detailed information (type, scientific name, strain)."
    )
    ImmuneCell: Optional[List[str]] = Field(
        default=None,
        description=(
            "List of cell_type names from composition components with role='immune_co-culture'. "
            "CRITICAL FORMAT MATCHING RULES: "
            "1. The strings in this list MUST exactly match (character-by-character, case-sensitive) the cell_type values from composition components with role='immune_co-culture'. "
            "2. Examples: If composition has cell_type='T cells' and 'Dendritic cells' with role='immune_co-culture',  then ImmuneCell MUST be ['T cells', 'Dendritic cells'] (NOT 'T cell', 'Dendritic cell', 'T-cells', or 'ImmuneCell'). "
            "3. Single vs plural: If composition uses 'T cells' (plural), this field must use 'T cells' (plural), not 'T cell' (singular). "
            "4. Special characters: Preserve hyphens, spaces, and special characters exactly as in composition (e.g., 'CD4+ T cells' in composition → 'CD4+ T cells' here). "
            "5. Preferably include all immune cell components from composition, but this field may be a subset when only specific populations are detected by biomarkers or analyzed in experiments. "
            "6. GENERALIZED NAMES WITH [❓️] TAG: If the article confirms co-culture with immune cells but does not specify exact cell types, use a generalized name with [❓️] tag (e.g., ['Immune cells [❓️]']). This satisfies the co-culture requirement while flagging the lack of specificity."
        )
    )
    StromalCell: Optional[List[str]] = Field(
        default=None,
        description=(
            "List of cell_type names from composition components with role='stromal_support' or role='feeder_layer'. "
            "CRITICAL FORMAT MATCHING RULES: "
            "1. The strings in this list MUST exactly match (character-by-character, case-sensitive) the cell_type values from composition components with role='stromal_support' or role='feeder_layer'. "
            "2. Feeder layer cells (e.g., MEFs, STO cells) are accepted here because they functionally provide stromal support. "
            "3. Examples: If composition has cell_type='Fibroblasts' with role='stromal_support' or cell_type='STO cells' with role='feeder_layer', then StromalCell can be ['Fibroblasts'] or ['STO cells'] or both. "
            "4. Single vs plural: If composition uses 'Fibroblasts' (plural), this field must use 'Fibroblasts' (plural), not 'Fibroblast' (singular). "
            "5. Special characters: Preserve hyphens, spaces, and special characters exactly as in composition. "
            "6. Preferably include all stromal/feeder cell components from composition, but this field may be a subset when only specific populations are detected by biomarkers or analyzed in experiments. "
            "7. GENERALIZED NAMES WITH [❓️] TAG: If the article confirms co-culture with stromal cells but does not specify exact cell types, use a generalized name with [❓️] tag (e.g., ['Stromal cells [❓️]']). This satisfies the co-culture requirement while flagging the lack of specificity."
        )
    )
    VascularCell: Optional[List[str]] = Field(
        default=None,
        description=(
            "List of cell_type names from composition components with role='vascular_support'. "
            "CRITICAL FORMAT MATCHING RULES: "
            "1. The strings in this list MUST exactly match (character-by-character, case-sensitive) the cell_type values from composition components with role='vascular_support'. "
            "2. Examples: If composition has cell_type='Endothelial cells' with role='vascular_support',  then VascularCell MUST be ['Endothelial cells'] (NOT 'Endothelial cell', 'endothelial cells', 'HUVEC', or 'VascularCell'). "
            "3. Single vs plural: If composition uses 'Endothelial cells' (plural), this field must use 'Endothelial cells' (plural), not 'Endothelial cell' (singular). "
            "4. Special characters: Preserve hyphens, spaces, and special characters exactly as in composition (e.g., 'HUVECs' in composition → 'HUVECs' here). "
            "5. Preferably include all vascular cell components from composition, but this field may be a subset when only specific populations are detected by biomarkers or analyzed in experiments. "
            "6. GENERALIZED NAMES WITH [❓️] TAG: If the article confirms co-culture with vascular cells but does not specify exact cell types, use a generalized name with [❓️] tag (e.g., ['Vascular cells [❓️]']). This satisfies the co-culture requirement while flagging the lack of specificity."
        )
    )
    Pericytes: Optional[List[str]] = Field(
        default=None,
        description=(
            "List of pericyte cell_type names from composition components with role='pericyte_support'. "
            "CRITICAL FORMAT MATCHING RULES: "
            "1. The strings in this list MUST exactly match (character-by-character, case-sensitive) the cell_type values from composition components with role='pericyte_support'. "
            "2. Examples: If composition has cell_type='Pericytes' with role='pericyte_support',  then Pericytes MUST be ['Pericytes'] (NOT 'Pericyte', 'pericytes', or 'PericyteCell'). "
            "3. Single vs plural: If composition uses 'Pericytes' (plural), this field must use 'Pericytes' (plural), not 'Pericyte' (singular). "
            "4. Special characters: Preserve hyphens, spaces, and special characters exactly as in composition. "
            "5. USE THIS FIELD FOR PERICYTES: When the article explicitly identifies pericytes as co-culture partners, use role='pericyte_support' in composition and list them here. This acknowledges their dual biological role in vascular support and stromal function without forcing a binary classification. "
            "6. GENERALIZED NAMES WITH [❓️] TAG: If the article confirms co-culture with pericytes but does not specify exact naming, use ['Pericytes [❓️]']. "
            "7. BIOLOGICAL NOTE: Pericytes are vascular mural cells that stabilize blood vessels and provide stromal support. This dedicated field avoids classification conflicts between VascularCell and StromalCell."
        )
    )
    # Verify at least one is not empty
    @model_validator(mode='after')
    def validate_at_least_one(self):
        if not any([self.Microorganism, self.ImmuneCell, self.StromalCell, self.VascularCell, self.Pericytes]):
            raise ValueError("At least one of Microorganism, ImmuneCell, StromalCell, VascularCell, or Pericytes must be provided")
        return self

class OrganoidComponentInfo(BaseModel):
    """One biological component/population in the organoid system.

    Design principle:
    - The `composition` field in OrganoidBaseInfo is a FLAT LIST of OrganoidComponentInfo entries.
    - Each OrganoidComponentInfo represents a group of cells that share the same species, role,
      origin (if known), cell_source, and organ assignment, and carries a single cell-type / lineage label.
    - Composite or multi-organ models are represented by MULTIPLE OrganoidComponentInfo entries,
      not by nested dicts. Different organs and lineages are captured by separate rows in `composition`
      (e.g., separate entries for heart cardiomyocytes vs liver hepatocytes), optionally tagged with
      `sub_organoid_model` for human-readable module names.
    """

    component_id: str = Field(
        description=(
            "Unique identifier for this component. Format: 'C1', 'C2', 'C3', etc. "
            "Must be unique within the composition list. "
            "ALLOCATION ORDER: Assign component_ids in the following priority: "
            "1. First, assign C1, C2, ... to all components with role='organoid_core' in the order they appear in the Methods section (or by organ if multiple organs are described simultaneously). "
            "2. Then, assign subsequent IDs to co-culture components (role='immune_co-culture', 'stromal_support', 'microbial_co-culture', etc.) in the order they are introduced in the Methods section. "
            "If the Methods section does not provide a clear order, use logical grouping (e.g., all organoid_core components first, then all co-culture components by role category). "
            "The numbering must be sequential with no gaps (C1, C2, C3, not C1, C3, C5)."
        )
    )

    cell_type: str = Field(
        description=(
            "ONE cell-type / lineage label for this component (one homogeneous population per component). "
            "1.FOR CELLULAR COMPONENTS (role='organoid_core', 'immune_co-culture', 'stromal_support', etc.): "
            "- Examples: 'neural progenitor cells', 'basal keratinocytes', 'suprabasal keratinocytes', 'microglia', 'fibroblasts', 'T cells'. "
            "2. FOR MICROBIAL COMPONENTS (role='microbial_co-culture'): "
            "- This field serves as the organism identifier/descriptor, NOT literally a 'cell type'. Use the microorganism name/strain as it appears in the article. "
            "- Examples: 'HIV-1', 'SARS-CoV-2', 'NL4.3 HIV-1 EGFP BaL reporter virus', 'E. coli K-12', 'Candida albicans SC5314'. "
            "- **Note**: The field is named 'cell_type' for schema consistency across all composition components, but for microorganisms it functions as the organism descriptor. "
            "3. If the article describes multiple distinct cell types within the same compartment (e.g., 'keratinocytes and fibroblasts'), encode them as separate OrganoidComponentInfo entries with different cell_type values rather than packing multiple labels into one field. "
            "- In multi-organ models, organ-cell-type mapping is expressed by creating separate OrganoidComponentInfo entries for different organs and assigning the appropriate `organ` tag(s), rather than using dicts such as {'Heart': ['cardiomyocytes'], 'Liver': ['hepatocytes']} inside a single component."
            "NAMING GUIDELINES:"
            "1. NEVER use iPSC, ESC, or PSC as composition.cell_type."
            "2. These terms describe cell origin, not biological identity."
            "3. Encode them ONLY in composition.organoid_origin and/or composition.cell_source."
        )
    )

    species: str = Field(
        description=(
            "Scientific name (Latin binomial) for CELLULAR components, or organism identifier for MICROBIAL components. "
            "1. FOR CELLULAR COMPONENTS (role='organoid_core', 'immune_co-culture', 'stromal_support', etc.): "
            "- Use Latin binomial nomenclature, e.g., 'Homo sapiens', 'Mus musculus', 'Rattus norvegicus'. "
            "2. FOR MICROBIAL COMPONENTS (role='microbial_co-culture'): "
            "- This field serves as the scientific name/identifier, though 'species' is technically imprecise for viruses. "
            "- Use the standardized scientific name for the microorganism, mirroring the naming conventions of `MicroorganismInfo.scientific_name` (including serotype, strain, or variant if specified in the article). "
            "- Examples: 'HIV-1', 'SARS-CoV-2', 'E. coli K-12', 'Candida albicans SC5314'. "
            "- **Note**: The field is named 'species' for schema consistency, but for viruses it represents the virus taxon name rather than a biological species in the Linnaean sense. "
            "- This approach ensures consistency with `co_culture_type.Microorganism.scientific_name` and preserves experimental specificity."
        )
    )
    
    role: ComponentRoleEnums = Field(
        description=(
            f"Component role category. Must select ONE from: {[e.value for e in ComponentRoleEnums]}. Role info: "
            "- organoid_core: Cells forming the 3D organoid structure and defining its organ identity (e.g., neural progenitors, intestinal stem cells). "
            "- stromal_support: Stromal/mesenchymal cells providing structural or paracrine support (e.g., fibroblasts, MSCs, stellate cells). "
            "- immune_co-culture: Immune cells co-cultured with the organoid (e.g., microglia, macrophages, T cells, PBMCs). "
            "- microbial_co-culture: Microorganisms co-cultured with the organoid (bacteria, viruses, fungi, parasites; e.g., E. coli, SARS-CoV-2, Candida). "
            "- vascular_support: Endothelial or vascular cells supporting vasculature formation (e.g., HUVECs, endothelial progenitors). "
            "- feeder_layer: Feeder cells providing 2D substrate or trophic support (e.g., MEFs, STO cells). **IMPORTANT: Feeder layers are functionally a form of stromal support. When using role='feeder_layer', MUST also list the cell_type in co_culture_type.StromalCell (e.g., STO cells → StromalCell=['STO cells']).** "
            "- other-co-culture: Any other co-cultured component not covered above (e.g., undefined glial mixtures, undefined stromal cells). "
            "The species of components with role='organoid_core' determines the organoid core species."
        )
    )
    cell_source: Optional[str] = Field(default='not specified',
        description=(
            "Origin of this component at the sample level, "
            "e.g. 'human iPSC line WTC11', 'primary PBMCs from healthy donors', "
            "'patient-derived GBM tissue', 'C57BL/6 mouse bone marrow'."
        )
    )
    organ: List[OrganEnums] = Field(description=OrganEnums.get_field_description(
        main_desc=(
            "Organ membership tags for this component. This field records WHICH organ(s) this cell population structurally or functionally belongs to. "
            "CRITICAL: The meaning of 'organ' depends on component role. "
            "Rules for ORGANOID_CORE components: "
            "1. For single-organ models, this list MUST contain exactly ONE organ key that is also present in OrganoidBaseInfo.organ (e.g., ['Liver'] for a liver-only model where OrganoidBaseInfo.organ = {'Liver': ['Digestive System']}). "
            "2. For composite multi-organ models (e.g., heart-liver), use one or more organs drawn from the KEYS of OrganoidBaseInfo.organ to tag which organ(s) each cell population supports. The set of organs for organoid_core components MUST be a subset of the organ keys defined in OrganoidBaseInfo.organ. "
            "3. In most cases a single organ per organoid_core component is expected (e.g., cardiomyocytes → ['Heart'], hepatocytes → ['Liver']). "
            "Rules for MICROBIAL_CO-CULTURE components (viruses, bacteria, fungi, parasites): "
            "4. For microbial_co-culture components, 'organ' represents the HOST ORGAN(S) that the microorganism infects/colonizes/interacts with, NOT the microorganism's own organ (microorganisms have no organs). "
            "   Examples: "
            "   - SARS-CoV-2 infecting brain organoid → organ=['Brain'] (the infected organ) "
            "   - E. coli colonizing intestinal organoid → organ=['Intestine'] (the colonized organ) "
            "   - Candida albicans infecting skin organoid → organ=['Skin'] (the infected organ) "
            "   - Virus infecting multi-organ heart-liver model, localizing only in liver → organ=['Liver'] "
            "5. In single-organ models, microbial organ typically matches the organoid_core organ(s). "
            "6. In multi-organ models, microbial organ indicates which organ module(s) the microorganism targets. "
            "6a. HOW TO EXTRACT INFECTED ORGANS FROM ARTICLE: Search the article for DIRECT EVIDENCE of infection in specific organs or cell types: "
            "   - Statements like 'virus infected [cell type] in [organ]', 'virus was detected in [organ] cells', 'infection of [organ]' "
            "   - Biomarker detection: if biomarker entries show viral proteins/RNA detected in specific cell types (e.g., 'SARS-CoV-2 detected in KRT17+ hair follicle cells'), include the corresponding organ "
            "   - Pathological changes: if article describes organ-specific damage, cell death, or dysfunction after infection (e.g., 'DNA damage in epidermal cells', 'neuron death'), include that organ "
            "   - Include ALL organs with evidence of infection, even if some are infected more heavily than others "
            "   - Example extraction: Article says 'SARS-CoV-2 infected hair follicle cells' + 'epidermal cell damage' + 'neuron infection' → organ=['Skin', 'Hair Follicle', 'Nerve'] "
            "7. If infection/colonization is non-specific or affects all organs equally, use all organ keys from base_info.organ. "
            "8. Use empty list [] ONLY if infection target is genuinely unknown or if microorganism is added but not yet introduced to organoid. "
            "Rules for OTHER CO-CULTURE components (immune_co-culture, stromal_support, vascular_support, feeder_layer, other-co-culture): "
            "9. These components MAY specify organ(s) to indicate organ-specific localization (e.g., brain-resident microglia → ['Brain'], liver Kupffer cells → ['Liver']). "
            "10. For systemically circulating or non-organ-specific support cells (e.g., peripheral blood T cells, general fibroblast feeders), use empty list []. "
            "11. Co-culture component organs are NOT strictly validated against base_info.organ keys, allowing flexibility for support cells. "
        )
    ))

    organoid_origin: Optional[OrganoidOriginEnums] = Field(
        default=None,
        description=(
            OrganoidOriginEnums.get_field_description(main_desc=(
            " **CRITICAL:** 'Cell_Line' is NOT valid - NEVER use it. "
            "For established cell lines (Pan02, C2C12, HEK293T, DLD1, Caco-2), use 'Somatic_Cell_Lines'. "
            "For 2D primary cell cultures, set null or 'Primary_Cells'. "
            "For cell lines in organoid protocols: iPSC-derived→'iPSCs', ESC-derived→'ESCs', stem cell lines→'Stem_Cells'. "
            "For co-culture components (immune/microbial/stromal/vascular/pericyte), typically null or 'Component'. "
            "Applies mainly to organoid_core in true organoids (model_category='Organoid'), but also applicable to 2D/Spheroid core components."
            ))
        )
    )


    sub_organoid_model: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional LIST of sub-organoid labels that this component belongs to. Each entry MUST be a non-empty human-readable string, typically describing an organoid module (e.g., 'Heart organoid', 'Liver organoid', 'Brain-spinal assembloid'). This field is purely descriptive and MUST NOT be used to infer organ membership (which is encoded in `organ`) or origin type (encoded in `organoid_origin`). When the article only provides composite names (e.g., 'heart–liver organoid'), the extractor MAY either split them into separate single-organ labels when it is unambiguous, or keep the composite label as-is. The validator MUST NOT reject outputs solely because sub_organoid_model entries are composite or do not end with the word 'organoid'."
        )
    )

    @field_validator('sub_organoid_model')
    @classmethod
    def validate_sub_organoid_model(cls, v):
        if v is None:
            return v
        if not isinstance(v, list) or len(v) == 0:
            raise ValueError("sub_organoid_model, when provided, must be a non-empty list of strings.")
        cleaned = []
        for s in v:
            if not isinstance(s, str) or not s.strip():
                raise ValueError("Each sub_organoid_model entry must be a non-empty string.")
            cleaned.append(s.strip())
        return cleaned

    @field_validator('component_id')
    @classmethod
    def validate_component_id(cls, v):
        """Validate component_id format: C1, C2, C3, etc."""
        import re
        if not isinstance(v, str):
            raise ValueError("component_id must be a string")
        v = v.strip()
        if not re.match(r'^C\d+$', v):
            raise ValueError("component_id must be in format 'C1', 'C2', 'C3', etc. (e.g., 'C1', 'C2')")
        return v

class CultureCategoryEnums(StrEnumBase):
    Scaffold_based = EnumValue("Scaffold-based Systems", "A cultivation system that utilizes external scaffold materials to provide three-dimensional adhesion sites and a physical framework for cells.")
    Suspension_based = EnumValue("Suspension-based Systems", "A cultivation system where cells are maintained in a non-adherent state within a liquid environment, spontaneously forming three-dimensional structures without scaffolds or attachment surfaces.")
    Interface_based = EnumValue("Interface-based Systems", "A cultivation architecture that utilizes physical films or fluid boundaries to partition the growth environment, encompassing the driving of isotropic development and asymmetric induction polarization.")
    Engineered_Microenvironments = EnumValue("Engineered Microenvironments", "A cultivation system that utilizes micro-nano fabrication technology to regulate biochemical gradients and physical mechanics at the microscale.")
    Bioprinting_Assembly = EnumValue("Bioprinting & Assembly", "A cultivation system that uses 3D printing or precise arrangement to position cells, bioink, and support materials according to predefined spatial coordinates.")
    Bioreactor = EnumValue("Bioreactor Systems"," A cultivation system that utilizes mechanical power devices (such as stirring, rotating, and pumping) to provide a dynamic physical environment for organoids.")
    Others = EnumValue("Others", "Others not specifically enumerated.")

class CultureSubcategoryEnums(StrEnumBase):
    MatrigelEmbedding = EnumValue("Matrigel embedding", "A natural gel extracted from mouse tumors (Engelbreth-Holm-Swarm sarcoma), in which cells are typically embedded for cultivation. BOUNDARY: Matrigel is exclusively classified here — do NOT classify Matrigel under 'Hydrogel' even though it is biologically derived, because it has a dedicated subcategory.")
    SyntheticECM = EnumValue("Synthetic ECM", "Fully synthetic, chemically defined biomimetic scaffold whose polymer backbone is synthesized from scratch (not biologically derived), offering precise and batch-consistent composition. Examples: PEG, PEGDA, PEG-RGD. BOUNDARY: Use this for fully synthetic backbones only. For biologically-derived polymers (even if chemically modified after extraction, e.g., GelMA), use 'Hydrogel'. For Matrigel, use 'Matrigel embedding'.")
    Hydrogel = EnumValue("Hydrogel", "Three-dimensional network material with high water content formed from biologically-derived (natural) polymer backbones, even if subsequently chemically modified. Examples: Collagen, Fibrin, Alginate, Hyaluronic acid, GelMA (gelatin methacryloyl — natural gelatin backbone with a synthetic cross-linkable modification). BOUNDARY: Classification is based on backbone origin — biologically derived → Hydrogel; chemically synthesized from scratch → Synthetic ECM. For hybrid materials (e.g., Alginate-PEG), classify by the dominant structural component. EXCLUSION: Matrigel is NOT classified here — use 'Matrigel embedding' instead.")
    ScaffoldTechniques = EnumValue("Scaffold Techniques", "Solid, porous, pre-formed structures with mechanical rigidity that provide three-dimensional structural support and adhesion sites for cells. Examples: PLGA foam, electrospun fiber scaffolds, decellularized ECM scaffolds, ceramic scaffolds. BOUNDARY: The defining feature is a solid/rigid pre-fabricated physical framework — distinguished from 'Synthetic ECM', which is a soft, injectable or crosslinkable gel-phase material; and from 'Hydrogel', which is a soft water-swollen network. If the material is rigid and porous (can hold shape without a mold) → ScaffoldTechniques; if it is a soft gel that conforms to its container → SyntheticECM or Hydrogel.")
    SyntheticBasementMembraneAnalogs = EnumValue("Synthetic basement membrane analogs", "Basement membrane extract preparations or reduced-growth-factor / defined-composition alternatives designed as replacements for standard Matrigel, offering reduced lot-to-lot variability or improved composition control. Despite the word 'Synthetic' in the category name, many products in this group are still biologically derived (e.g., extracted from EHS tumors or other biological sources) but are explicitly marketed and used as Matrigel alternatives. Examples: Cultrex BME (Basement Membrane Extract, Trevigen/R&D Systems), Cultrex Reduced Growth Factor BME, GrowDex (plant-derived). BOUNDARY: Classify here rather than 'Matrigel embedding' ONLY when the article explicitly uses these products as Matrigel alternatives/replacements or describes them by their brand name (Cultrex, BME, GrowDex). If the article uses standard Corning Matrigel or BD Matrigel without qualification, use 'Matrigel embedding'.")
    LowAdherentCulture = EnumValue("Low-adherent culture", "Using hydrophilic, non-ionic coatings (such as ultra-low attachment (ULA) surfaces, PEG, or poly-HEMA) to inhibit cell-surface adhesion, thereby promoting spontaneous cell aggregation in the liquid phase to form three-dimensional structures.")
    HangingDrop = EnumValue("Hanging drop", "A technique that utilizes gravity to aggregate cells at the apex of a hanging liquid droplet.")
    MagneticLevitation = EnumValue("Magnetic levitation", "Using magnetic fields to spatially suspend and assemble labeled cells.")
    RotatingWallVesselSpinnerFlask = EnumValue("Rotating wall vessel or Spinner flask", "Utilize motorized mechanical rotation of the container to generate dynamic flow fields that maintain organoids in suspension. Examples: NASA rotating wall vessel (RWV), spinner flask bioreactors. BOUNDARY: The defining feature is mechanical rotation/stirring of the vessel itself. Distinguished from 'Perfusion Bioreactors', where a pump drives directional medium flow through the system while the vessel remains stationary. If a system combines rotation with perfusion, classify by the primary driving mechanism described in the article.")
    AcousticLevitation = EnumValue("Acoustic levitation", "Using acoustic wave pressure to non-contact suspend and assemble cells in culture medium into three-dimensional structures.")
    AirLiquidInterface = EnumValue("Air-Liquid Interface", "By establishing a gas-liquid interface, asymmetric environmental signals (such as oxygen gradients and physical exposure) are utilized to drive specialized differentiation and cell polarization.")
    SubmergedCulture = EnumValue("Submerged culture", "Cells are fully immersed in culture medium from all sides, receiving isotropic (uniform) biochemical and physical signals that drive symmetric development. Contrast with 'Air-Liquid Interface', where one surface is exposed to air creating asymmetric signals. BOUNDARY: Distinguished from 'Low-adherent culture' — submerged culture does not require anti-adhesion coatings and does not specifically aim to drive 3D aggregation; it describes the bulk liquid immersion condition regardless of whether cells are adherent or in suspension.")
    OrganOnChip = EnumValue("Organ-on-chip", "A multi-compartment microfluidic device that recapitulates organ-level physiological functions by co-culturing distinct cell types in spatially separated chambers (e.g., vascular channel and tissue compartment) connected by a porous membrane, enabling dynamic perfusion and tissue-vascular crosstalk. BOUNDARY: Distinguished from 'Microfluidics', which provides general microscale flow environments (gradients, shear stress) without the multi-compartment organ-mimicry architecture.")
    Microfluidics = EnumValue("Microfluidics", "Utilize microscale fluid control to establish a continuous concentration gradient or shear stress environment. The microfluidic channels are fabricated by conventional methods such as soft lithography (PDMS molding), photolithography, or etching. BOUNDARY: If the microfluidic chip channels are fabricated specifically by 3D printing technology, use '3D printed microfluidic chips' instead. If the device has multi-compartment organ-mimicry architecture with a porous membrane separating cell types, use 'Organ-on-chip' instead.")
    DropletMicrofluidics = EnumValue("Droplet microfluidics", "Generating tens of thousands of tiny discrete droplets on a microchip to encapsulate individual cells or organoids, enabling high-throughput single-cell/single-organoid assays. PRIORITY RULE: Classify by functional purpose (droplet encapsulation) rather than chip fabrication method — use this subcategory whenever the article's core technique is droplet generation for cell encapsulation, regardless of whether the chip was fabricated by soft lithography or 3D printing. BOUNDARY: Distinguished from 'Microfluidics' (continuous flow, gradient/shear stress environment without droplet encapsulation) and '3D printed microfluidic chips' (empty channel fabrication by 3D printing without droplet generation as the primary function).")
    ThreeDPrintedMicrofluidicChips = EnumValue("3D printed microfluidic chips", "Fabricate micron-scale fluidic channels using 3D printing technology (e.g., stereolithography, inkjet printing, extrusion-based printing) to provide microfluidic culture environments for organoids. BOUNDARY: The key distinguishing feature is the channel fabrication method — 3D printing → this subcategory; conventional soft lithography/photolithography → 'Microfluidics'. Distinguished from '3D Bioprinting', which spatially deposits living cells and bioink to build tissue structures rather than fabricating empty fluidic channels.")
    Bioprinting3D = EnumValue("3D Bioprinting", "Precisely stack living cells, bio-ink, and growth factors layer by layer according to pre-designed three-dimensional spatial coordinates.")
    ReSeedingInMicrowells=EnumValue("Re-seeding in Microwells", "Seeding cells, single-cell suspensions, or organoid fragments into structured microwell arrays to achieve size-controlled, uniform organoid formation through geometric confinement. Includes both primary seeding (e.g., directly seeding iPSCs or dissociated cells into AggreWell or PDMS microwells to form EBs or uniform aggregates) and secondary re-seeding (e.g., seeding organoid fragments into microwells for size normalization). The defining feature is geometric confinement by microwell architecture to control organoid size and uniformity.")
    ReSeedingInMicrogrooves=EnumValue("Re-seeding in Microgrooves", "Seeding cells or organoid fragments into structured microgroove arrays to provide anisotropic topographical guidance, inducing cells to align and elongate along groove axes into oriented 3D structures (e.g., nerve bundles or muscle fibers). The defining feature is anisotropic topographical constraint by microgroove geometry to impose directional alignment, regardless of whether it is a primary or secondary seeding step.")
    PerfusionBioreactors=EnumValue("Perfusion Bioreactors", "A pump-driven system that continuously or intermittently drives directional medium flow through the culture chamber, supplying fresh nutrients and removing waste. BOUNDARY: The defining feature is a pump driving directional flow while the vessel remains stationary. Distinguished from 'Rotating wall vessel or Spinner flask', where the vessel itself rotates/stirs to suspend organoids. If a system combines both, classify by the primary driving mechanism described in the article.")
    Others = EnumValue("Others", "Others not specifically enumerated. ONLY use when no other subcategory applies with reasonable confidence. Do NOT use as a default when uncertain — review all subcategory descriptions carefully before choosing this option.")

class CultureFormationStrategyEnums(StrEnumBase):
    DirectedDifferentiation = EnumValue("Directed differentiation", "By adding defined, lineage-specific growth factor cocktails or small molecules, guide iPSC/ESC stem cells along a predetermined differentiation trajectory to yield specific cell types. BOUNDARY: ONLY use for iPSC- or ESC-derived protocols that employ stage-specific, lineage-switching signaling factors (e.g., sequential Wnt/BMP/FGF combinations designed to convert pluripotent cells toward a target lineage such as intestinal, hepatic, or neural). DO NOT use for adult stem cell (ASC)-derived organoids (Lgr5+ intestinal, PDOs, primary tissue): even if their medium contains Wnt, R-Spondin, Noggin, or EGF, those factors maintain the niche and support self-renewal rather than switching lineage identity — these protocols are SelfAssembling. Distinguished from 'Differentiation induction', which uses non-specific or broadly permissive stimuli without defined lineage targeting. PRIORITY RULE for iPSC protocols with downstream self-assembly: When an iPSC/ESC protocol applies stage-specific lineage-switching factors (e.g., sequential BMP4/Wnt/FGF/SHH steps designed to convert pluripotent cells toward a target identity) AND the resulting cells subsequently self-assemble into a 3D structure, classify as 'DirectedDifferentiation' — the lineage-switching intervention is the primary engineering decision; the downstream self-assembly is a natural biological consequence of successful differentiation, not the defining mechanistic feature. Record the self-assembly step in culture_steps, not in formation_strategy.")
    SelfAssembling = EnumValue("Self-assembling", "Cells spontaneously form ordered three-dimensional structures by virtue of their intrinsic biological properties (such as cell migration and adhesion). DEFAULT for: ASC-derived organoids (Lgr5+ intestinal crypts, colonic, gastric, etc.), patient-derived organoids (PDOs from tumor/biopsy), and primary tissue-derived organoids — regardless of whether standard niche-maintenance factors (Wnt3a, R-Spondin, Noggin, EGF) are present in medium, because those factors support self-renewal rather than directing a new lineage identity. PRIORITY RULE (ASC/primary-only): When an ASC-derived or primary-tissue-derived protocol includes an early non-specific differentiation step (e.g., serum withdrawal, retinoic acid) FOLLOWED BY spontaneous 3D self-assembly, classify as 'SelfAssembling' — the 3D structure formation mechanism is the primary descriptor; the prior induction step should be recorded in culture_steps, not reflected in formation_strategy. NOTE: This rule does NOT apply to iPSC/ESC-derived protocols — for iPSC/ESC, use 'DirectedDifferentiation' (stage-specific lineage-switching factors) or 'DifferentiationInduction' (non-specific stimuli before 3D formation) as appropriate.")
    DifferentiationInduction = EnumValue("Differentiation induction", "Induces cells to transition from an immature or progenitor state toward a more lineage-committed state using non-specific or broadly permissive stimuli (e.g., serum withdrawal, conditioned media, retinoic acid, general differentiation cocktails) without precise stage-by-stage lineage targeting. BOUNDARY: Use this when lineage-switching stimuli are applied BEFORE a stable 3D organoid structure is established (i.e., during the transition from 2D/suspension culture to early 3D). Distinguished from 'Directed differentiation', which uses specific, stage-defined growth factor cocktails to achieve a predetermined cell identity. Distinguished from 'Tissue maturation', which applies maturation stimuli AFTER the 3D organoid structure is already formed. APPLICABILITY TO ASC/PRIMARY CELLS: This category CAN apply to ASC-derived or primary cell protocols when non-specific differentiation stimuli are applied BEFORE 3D structure formation AND the article does not describe subsequent spontaneous self-assembly as the defining outcome (e.g., a progenitor cell population treated with retinoic acid to commit to a lineage before being embedded in matrix). If non-specific stimuli are followed by spontaneous 3D self-assembly as the primary outcome, use 'SelfAssembling' instead per its PRIORITY RULE.")
    HighThroughputConstruction = EnumValue("High-throughput organoid construction", "Utilize automated platforms to achieve large-scale, standardized construction of organoids without adding engineered spatial or mechanical microenvironmental cues. POSITIVE CRITERIA: Use this when the article's primary technical contribution is automation of organoid production — e.g., robotic liquid handling, standardized multi-well plate seeding, automated passaging or imaging pipelines — where organoids form by natural self-assembly in uniform conditions across many wells. BOUNDARY: Distinguished from 'High-throughput and structural control', which additionally integrates defined spatial patterning, matrix stiffness gradients, or geometric confinement as deliberate variables. Decision rule: if the article reports automation/throughput WITHOUT explicitly engineering the microenvironment (no matrix mechanics, no patterned substrates, no geometric molds beyond standard well plates) → HighThroughputConstruction; if spatial/mechanical cues are deliberately designed as experimental variables alongside throughput → HighThroughputStructuralControl.")
    HighThroughputStructuralControl = EnumValue("High-throughput and structural control", "Combining high-throughput automation with precise microenvironmental control (such as matrix stiffness, geometry, or spatial patterning) to guide the formation of three-dimensional organoid structures. Distinct from 'High-throughput organoid construction' in that it adds defined spatial/mechanical cues to direct organoid architecture. BOUNDARY: The primary purpose is high-throughput scale/standardization with engineered microenvironment. If the primary purpose is precise spatial positioning of a small number of samples (not throughput-driven), use 'Directed spatial organization' instead.")
    DirectedSpatialOrganization = EnumValue("Directed spatial organization", "By external physical or chemical means (such as microfluidics, 3D printing, magnetic beads, patterned culture substrates), cells are forcibly placed in predetermined spatial positions. BOUNDARY: The primary purpose is precise spatial control of cell positioning, regardless of sample number. Distinguished from 'High-throughput and structural control', where high-throughput scale/batch production is the primary goal and spatial control is a secondary feature. Decision rule: if the article emphasizes spatial precision or pattern fidelity (even for a single sample) → DirectedSpatialOrganization; if the article emphasizes throughput, automation, or batch uniformity → HighThroughputStructuralControl.")
    TissueMaturation = EnumValue("Tissue maturation", "Apply specialized biochemical, physical, or temporal protocols to promote already-formed 3D organoid structures in acquiring the functional and physiological hallmarks of adult tissues. BOUNDARY: Use this when maturation stimuli (e.g., electrical stimulation, mechanical stretch, prolonged culture, metabolic switching) are applied AFTER the 3D organoid structure is established. Distinguished from 'Differentiation induction', which applies broadly permissive stimuli BEFORE or DURING initial 3D structure formation. PRIORITY RULE for multi-phase iPSC protocols: Many iPSC protocols contain both a lineage-switching phase AND a subsequent maturation phase. In such cases, classify as 'DirectedDifferentiation' — the lineage-switching intervention is the primary engineering decision that defines the protocol. Only use 'TissueMaturation' when the article's core contribution or primary experimental focus is specifically on the maturation of already-formed organoids (e.g., the study is evaluating maturation conditions, not differentiation protocols), and the lineage-switching step is treated as standard background.")
    Others = EnumValue("Others", "Others not specifically enumerated. ONLY use when no other formation strategy applies with reasonable confidence. Do NOT use as a default when uncertain — review all strategy descriptions carefully before choosing this option.")

# Fixed mapping: subcategory → category (deterministic, not extracted by LLM)
_SUBCATEGORY_TO_CATEGORY: Dict[CultureSubcategoryEnums, CultureCategoryEnums] = {
    CultureSubcategoryEnums.MatrigelEmbedding:              CultureCategoryEnums.Scaffold_based,
    CultureSubcategoryEnums.SyntheticECM:                   CultureCategoryEnums.Scaffold_based,
    CultureSubcategoryEnums.Hydrogel:                       CultureCategoryEnums.Scaffold_based,
    CultureSubcategoryEnums.ScaffoldTechniques:             CultureCategoryEnums.Scaffold_based,
    CultureSubcategoryEnums.SyntheticBasementMembraneAnalogs: CultureCategoryEnums.Scaffold_based,
    CultureSubcategoryEnums.LowAdherentCulture:             CultureCategoryEnums.Suspension_based,
    CultureSubcategoryEnums.HangingDrop:                    CultureCategoryEnums.Suspension_based,
    CultureSubcategoryEnums.MagneticLevitation:             CultureCategoryEnums.Suspension_based,
    CultureSubcategoryEnums.AcousticLevitation:             CultureCategoryEnums.Suspension_based,
    CultureSubcategoryEnums.RotatingWallVesselSpinnerFlask: CultureCategoryEnums.Bioreactor,
    CultureSubcategoryEnums.AirLiquidInterface:             CultureCategoryEnums.Interface_based,
    CultureSubcategoryEnums.SubmergedCulture:               CultureCategoryEnums.Interface_based,
    CultureSubcategoryEnums.OrganOnChip:                    CultureCategoryEnums.Engineered_Microenvironments,
    CultureSubcategoryEnums.Microfluidics:                  CultureCategoryEnums.Engineered_Microenvironments,
    CultureSubcategoryEnums.DropletMicrofluidics:           CultureCategoryEnums.Engineered_Microenvironments,
    CultureSubcategoryEnums.ThreeDPrintedMicrofluidicChips: CultureCategoryEnums.Engineered_Microenvironments,
    CultureSubcategoryEnums.ReSeedingInMicrowells:          CultureCategoryEnums.Engineered_Microenvironments,
    CultureSubcategoryEnums.ReSeedingInMicrogrooves:        CultureCategoryEnums.Engineered_Microenvironments,
    CultureSubcategoryEnums.Bioprinting3D:                  CultureCategoryEnums.Bioprinting_Assembly,
    CultureSubcategoryEnums.PerfusionBioreactors:           CultureCategoryEnums.Bioreactor,
    CultureSubcategoryEnums.Others:                         CultureCategoryEnums.Others,
}


class CultureTechniqueInfo(BaseModel):
    """Culture technique classification"""
    category: Optional[CultureCategoryEnums] = Field(
        default=None,
        description="Placeholder field. Set to null."
    )
    subcategory: CultureSubcategoryEnums = Field(
        description=CultureSubcategoryEnums.get_field_description(main_desc="The specific technical implementation plan for the organoid culture system.")
    )
    formation_strategy: CultureFormationStrategyEnums = Field(
        description=CultureFormationStrategyEnums.get_field_description(main_desc="Driving and regulating specific biological processes or engineered methods for converting cells into functional three-dimensional tissues.")
    )

    @model_validator(mode='after')
    def _infer_category_from_subcategory(self) -> 'CultureTechniqueInfo':
        self.category = _SUBCATEGORY_TO_CATEGORY.get(self.subcategory, CultureCategoryEnums.Others)
        return self


class OrganoidBaseInfo(BaseModel):
    """Core organoid identification information (historically named; applies to all core 3D culture models)."""

    model_category: CultureModelCategoryEnums = Field(
        description=(
            "High-level culture model category for this entry. "
            "Organoid: true organoids that meet organoid criteria (self-organization, multicellularity, tissue identity). "
            "Spheroid: multicellular or tumor spheroids (e.g., GBM spheroids, cell line spheroids). "
            "EmbryoidBody: embryoid bodies (EBs) ONLY when the EB itself is the final model studied (no downstream organoid). "
            "Aggregate: non-structured 3D aggregates. "
            "Organotypic: organotypic explant/slice cultures (e.g., OPAB, brain slice cultures, retina explants). "
            "Tissue Engineered: commercial pre-fabricated 3D tissue models and engineered tissue constructs (e.g., MatTek skin equivalents, EpiDerm, reconstructed human epidermis kits). "
            "Use this category for products that are: (a) commercially manufactured as ready-to-use 3D tissue systems, (b) not derived through organoid self-organization protocols in the study, "
            "(c) designed to mimic native tissue architecture through tissue engineering approaches. "
            "Other3D: other 3D cultures not fitting the above categories. "
            "2D: classic monolayer or traditional 2D cell cultures (cell lines or primary cells) used as the CORE experimental model or a key comparator; "
            "these still use the same OrganoidCultureResult schema but lack 3D architecture. "
            "**CRITICAL: For established cell lines (e.g., DLD1, Caco-2, HEK293T, HeLa), MUST use '2D' category, NOT 'Cell_Line' (which is NOT a valid enum value).** "
            "Others: ambiguous or mixed culture models that cannot be clearly assigned to the above types. "
            "Consistency rule: model_category='Organoid' ↔ if_organoid=true; all other categories (Spheroid, EmbryoidBody, Aggregate, Organotypic, Tissue Engineered, Other3D, 2D, Others) ↔ if_organoid=false. "
            "When the article does NOT describe a bona fide organoid protocol (e.g., only intestinal crypt cultures, 2D HEK293T/Ls174T assays, or generic tissue cultures used as comparators), the extractor MUST NOT force-fit organoid-specific developmental stages, patterning, self-organization, or biomarker timelines. In such cases, choose the most appropriate non-organoid model_category and only encode the culture_steps that are explicitly reported for that model."
        )
    )


    organoid_model: str = Field(
        description=(
            "Name of the FINAL core culture model used as the main experimental system in this culture protocol. "
            "For organoid-based protocols, organoid_model MUST reflect the terminal organoid or 3D model that the study claims to generate and analyze (e.g., 'Cerebral Organoid', 'Small Intestinal Organoid', 'Glioblastoma Organoid'). "
            "Intermediate developmental stages such as 'embryoid body', 'spheroid', 'neurosphere', or early aggregates "
            "MUST NOT be used as organoid_model when a downstream organoid is present; these stages MUST be encoded only as culture steps within the SAME OrganoidCultureResult (e.g., in culture_steps), not as separate models or separate cultures. "
            "For non-organoid or 2D cultures (if_organoid=false; model_category in ['Spheroid', 'EmbryoidBody', 'Aggregate', 'Organotypic', 'Other3D', '2D', 'Others']), organoid_model may take corresponding names such as 'Glioblastoma Tumor Spheroid', 'Organotypic human brain explant (OPAB)', '2D Neural Monolayer', '3D Neural Aggregate', etc. "
            "For composite multi-organ models, organoid_model MAY use a hyphenated or composite name (e.g., 'Heart-Liver Organoid'), while the structured organ list captures each organ explicitly."
        )
    )

    composite_role: CompositeRoleEnums = Field(
        description=(
            "How this culture participates in composite/multi-organ systems. Must select ONE from: "
            f"{[e.value for e in CompositeRoleEnums]}. "
            "CRITICAL DEFINITIONS: "
            "- Clarification: Coculture does not equal Composite organoid system. Composite organoid system refers to systems with multiple distinct organs (e.g., heart + liver), not coculture with a single organ (e.g., enteroid + immune cells/stromal cells/vascular cells/pericytes/bacteria)."
            "- 'Composite organoid system' refers ONLY to physically integrated multi-module organoid constructs (e.g., multi-organ or multi-region assembloids) formed in the SAME well/device as a single construct. "
            "- Co-culture with immune/stromal/vascular/pericyte cells or microorganisms (including viral/bacterial infection) is NOT 'Composite'. Those cases should be captured by if_co_culture/co_culture_type and non-core components in composition, while composite_role remains 'Single organoid only'. "
            "HARD RULE (structure-based): "
            "- If composition contains only ONE organoid_core component (or multiple organoid_core components but all map to the SAME organ), composite_role MUST NOT be 'Composite organoid system' unless the paper explicitly states assembloid/fusion/multi-organ integration. "
            "DECISION CRITERIA: "
            "1. 'Single organoid only': Use when this OrganoidCultureResult represents ONE organoid module/type. Separate independent culture lines (different regions/subtypes/patients) into separate OrganoidCultureResult entries, each with 'Single organoid only'. "
            "2. 'Composite organoid system': Use ONLY when there are ≥2 distinct organoid_core modules with different organ identities physically integrated in the same culture system (e.g., heart-liver assembloid; skin + hair follicle + nerve grown together). "
            "3. 'Precursor-only module for composite': A single-organ module grown solely as a building block for downstream composite assembly. "
            "4. 'Single organoid and precursor for composite': The module is both independently studied AND used for composite assembly. "
            "DO NOT use 'Composite' just because the study contains multiple subtypes, co-cultures, infections, or parallel assays."
        )
    )


    organ: Dict[OrganEnums, List[OrganSystemEnums]] = Field(
        description=(
            f"Mapping from organ(s) represented by organoid_model to their organ system category(ies). "
            f"Keys MUST be OrganEnums values (selected from: {[e.value for e in OrganEnums]}), and values MUST be non-empty Lists of OrganSystemEnums "
            f"(selected from: {[e.value for e in OrganSystemEnums]}). "
            "This field encodes the organ→system relationships explicitly for the culture model. "
            "Rules: "
            "1. For simple single-organ models, provide a single key-value pair, e.g., {'Liver': ['Digestive System']}. "
            "2. For composite multi-organ constructs (e.g., 'heart-liver model', 'skin with hair follicles and nervous system innervation'), include one entry per organ, each mapped to one or more organ systems strictly according to the ORGAN→SYSTEM mapping in KNOWLEDGE. "
            "Do NOT invent additional organ system labels beyond those defined in ORGAN→SYSTEM for the corresponding organ. "
            "   Examples: "
            "     - {'Heart': ['Cardiovascular System'], 'Liver': ['Digestive System']} "
            "     - {'Skin': ['Integumentary System'], 'Hair Follicle': ['Integumentary System'], 'Nerve': ['Nervous System']} "
            "3. Organs that participate in multiple systems in ORGAN→SYSTEM (e.g., 'Thymus Gland') MUST list all relevant systems for that organ, "
            "   e.g., {'Thymus Gland': ['Endocrine System', 'Lymphatic System']}. "
            "4. Do NOT invent new organ or system names; keys must come from OrganEnums and values must come from OrganSystemEnums. "
            "5. If an organ is 'Others' or cannot be mapped, use OrganEnums.Others as key and map to ['Others']. "
            "6. This mapping replaces the previous separate organ/organ_system fields and serves as the canonical source for both organ-level and system-level summaries. "
            "Per-component organ assignment remains encoded in OrganoidComponentInfo.organ and MUST be a subset of the keys of this mapping."
        )
    )

    if_co_culture: bool = Field(
        description=(
            "Set true if the core 3D structure is co-cultured with additional cells/organisms in the same microenvironment to study interactions. "
            "MUST be true when composition contains ANY co-culture role: stromal_support, feeder_layer, immune_co-culture, microbial_co-culture, vascular_support, pericyte_support, other-co-culture. "
            "Example: composition with roles ['organoid_core', 'feeder_layer'] → if_co_culture=true. "
            "EXCLUSIONS: (1) Parallel assays in separate wells; (2) Mixed-cell spheroids (multiple organoid_core, no distinct partner); (3) Pure multi-organ systems without external partners; (4) In vivo xenograft hosts. "
            "See composition field for role definitions and co_culture_type field for mapping rules."
        )
    )


    co_culture_type: Optional[CocultureObjs] = Field(
        default=None,
        description=(
            "This field applies exclusively to in vitro co-culture partners. In vivo hosts used in xenograft/transplantation models are excluded. "
            "MUST BE PROVIDED IF if_co_culture is true, Otherwise, it will is an invalid action. "
            "**CRITICAL MAPPING RULES (composition role → co_culture_type field):** "
            "- role='immune_co-culture' → co_culture_type.ImmuneCell (list of cell_type values) "
            "- role='stromal_support' → co_culture_type.StromalCell (list of cell_type values) "
            "- role='feeder_layer' → co_culture_type.StromalCell (feeder layers ARE stromal support, e.g., MEFs, STO cells) "
            "- role='vascular_support' → co_culture_type.VascularCell (list of cell_type values) "
            "- role='pericyte_support' → co_culture_type.Pericytes (list of cell_type values) "
            "- role='microbial_co-culture' → co_culture_type.Microorganism (list of MicroorganismInfo objects) "
            "Categories or scientific names of co-cultured organisms/cell populations that are NOT part of the core 3D structure "
            "(e.g., immune cells, stromal cells, feeder layers, vascular cells, pericytes, microbes) and that share the same microenvironment with the organoid/core model. "
            "Do NOT use this field for separate, parallel assays that do not directly interact with the 3D culture."
        )
    )
    if_organoid: bool = Field(
        description=(
            "Set true if this culture model is a true organoid (model_category='Organoid'). "
            "Set false for all other model categories (model_category in ['Spheroid', 'EmbryoidBody', 'Aggregate', 'Organotypic', 'Other3D', '2D', 'Others']), "
            "including spheroids, embryoid bodies used as final models, organotypic explants, other 3D systems, and classic 2D monolayer cultures."
        )
    )

    composition: List[OrganoidComponentInfo] = Field(
        description=(
            "This composition describes ONLY the biological components that co-exist within the in vitro culture system. Organisms serving as in vivo hosts for xenograft/transplantation MUST NOT appear in this list. "
            "Full multi-component composition of this culture system. "
            ""
            "**CRITICAL SEMANTIC RULE: Co-culture (Same Vessel) vs Parallel Groups (Separate Vessels)** "
            "- ✅ USE composition: Components in SAME vessel with interactions → ONE result with multi-component composition "
            "  Example: Organoid + T cells + virus in same well → [C1:organoid, C2:virus, C3:T_cells] "
            "- ❌ DO NOT use composition: Groups in SEPARATE vessels → MULTIPLE results, each with own composition "
            "  Example: WT vs 5 mutants in separate wells → 6 results, each with [C1:single_variant] "
            ""
            "CRITICAL RULES: "
            "1. MUST include at least one component with role='organoid_core' representing the core 3D structure. "
            "2. ⚠️ MANDATORY FOR MICROBIAL CO-CULTURE: If co_culture_type.Microorganism is populated (viruses, bacteria, fungi, parasites), "
            "   you MUST add a corresponding component to this composition list with role='microbial_co-culture'. "
            "   Example: If co_culture_type.Microorganism contains HIV-1, composition MUST include component C6 with role='microbial_co-culture'. "
            "   This is NOT optional - validation will fail if microorganisms are only in co_culture_type but missing from composition. "
            "3. For CELLULAR co-culture (immune cells, stromal cells, vascular cells, pericytes, feeder layers): "
            "  - MUST be added to composition with appropriate role ('immune_co-culture', 'stromal_support', 'vascular_support', 'pericyte_support', 'feeder_layer', etc.) "
            "  - Each component gets a unique component_id (C1, C2, etc.) "
            "  - These component_ids can be referenced in protocol.target_components "
            "  **CRITICAL VALIDATION RULES (role → co_culture_type mapping):** "
            "  - co_culture_type.ImmuneCell MUST list ALL cell_type values from composition components with role='immune_co-culture'. "
            "  - co_culture_type.StromalCell MUST list ALL cell_type values from composition components with role='stromal_support' OR role='feeder_layer'. (Feeder layers like MEFs/STO cells ARE stromal support and MUST be listed in StromalCell field.) "
            "  - co_culture_type.VascularCell MUST list ALL cell_type values from composition components with role='vascular_support'. "
            "  - co_culture_type.Pericytes MUST list ALL cell_type values from composition components with role='pericyte_support'. "
            "  - Format must match composition cell_type exactly (case-sensitive, character-by-character)."
            "4. DETAILED MICROBIAL co-culture REQUIREMENTS (viruses, bacteria, fungi, parasites): "
            "  - MANDATORY: MUST be added to composition as a SEPARATE component with role='microbial_co-culture' "
            "  - Assign unique component_id (e.g., if organoid_core components are C1-C5, microbe is C6) "
            "  - Use cell_type to describe the microorganism (e.g., 'HIV-1', 'SARS-CoV-2', 'E. coli') "
            "  - Set species to the microorganism scientific name (e.g., 'HIV-1', 'Escherichia coli') "
            "  - Set organ to the HOST ORGAN(S) that the microorganism infects/colonizes (e.g., HIV infecting brain organoid → organ=['Brain']) "
            "  - MUST ALSO record in co_culture_type.Microorganism with detailed info (microorganism_type, scientific_name, strain) "
            "  - Example: HIV-1 co-culture requires BOTH: "
            "    * composition entry: {component_id:'C6', cell_type:'HIV-1', species:'HIV-1', role:'microbial_co-culture', organ:['Brain']} "
            "    * co_culture_type.Microorganism entry: {microorganism_type:'Virus', scientific_name:'HIV-1', strain:'...'} "
            "5. In cross-species or multi-organ systems, all components (cellular and microbial) are represented at the component level via OrganoidComponentInfo.species, OrganoidComponentInfo.organ, and OrganoidComponentInfo.organoid_origin. "
            "6. Composite or multi-organ models MUST be represented by multiple OrganoidComponentInfo entries, each encoding one homogeneous context (shared species/role/source/organ with a single cell_type label)."
        )
    )

    @model_validator(mode='after')
    def validate_coculture_and_composition(self):
        # 1) co_culture_type consistency with if_co_culture
        if self.if_co_culture and (self.co_culture_type is None):
            raise ValueError("co_culture_type must be provided when if_co_culture is true")
        if not self.if_co_culture and self.co_culture_type is not None:
            self.co_culture_type = None

        # 2) composition must not be empty
        if not self.composition or len(self.composition) == 0:
            raise ValueError("composition must contain at least one component for the 3D culture system")

        # 3) At least one organoid_core required
        core_components = [c for c in self.composition if c.role == ComponentRoleEnums.ORGANOID_CORE]
        if len(core_components) == 0:
            raise ValueError(
                "composition must include at least one component with role='organoid_core' "
                "to represent the core 3D structure."
            )

        # 4) Co-culture but without viral component case
        roles_requiring_component = {
            ComponentRoleEnums.STROMAL_SUPPORT,
            ComponentRoleEnums.IMMUNE_CO_CULTURE,
            ComponentRoleEnums.VASCULAR_SUPPORT,
            ComponentRoleEnums.FEEDER_LAYER,
            ComponentRoleEnums.OTHER_CO_CULTURE,
            ComponentRoleEnums.MICROBIAL_CO_CULTURE,
        }

        has_component_level_co = any(c.role in roles_requiring_component for c in self.composition)
        if has_component_level_co and not self.if_co_culture:
            raise ValueError(f"if_co_culture must be true when composition contains component-level co-culture roles (roles in composition: {[c.role.value for c in self.composition]}).")

        # 5) if_co_culture=True but composition only contains core - provide detailed diagnosis
        non_core_components = [c for c in self.composition if c.role != ComponentRoleEnums.ORGANOID_CORE]

        if self.if_co_culture and not non_core_components:
            # First check co_culture_type to provide more precise error information
            error_details = []
            if self.co_culture_type is not None:
                if self.co_culture_type.Microorganism is not None:
                    error_details.append(
                        f"co_culture_type.Microorganism has {len(self.co_culture_type.Microorganism)} entries "
                        f"but no components with role='microbial_co-culture' in composition"
                    )
                if self.co_culture_type.ImmuneCell is not None:
                    error_details.append(
                        f"co_culture_type.ImmuneCell has {len(self.co_culture_type.ImmuneCell)} entries "
                        f"but no components with role='immune_co-culture' in composition"
                    )
                if self.co_culture_type.StromalCell is not None:
                    error_details.append(
                        f"co_culture_type.StromalCell has {len(self.co_culture_type.StromalCell)} entries "
                        f"but no components with role='stromal_support' in composition"
                    )
            
            if error_details:
                raise ValueError(
                    "if_co_culture is true but no co-cultured components found in composition. "
                    "ALL co-culture components (cellular and microbial) MUST be added to composition with appropriate roles.\n"
                    "Specific issues:\n- " + "\n- ".join(error_details)
                )
            else:
                raise ValueError(
                    "if_co_culture is true but no co-cultured components found in composition. "
                    "ALL co-culture components (cellular and microbial) MUST be added to composition with appropriate roles."
                )
        
        # 6) If microorganism co-culture exists, must have microbial_co-culture role in composition
        if self.co_culture_type is not None and self.co_culture_type.Microorganism is not None:
            microbial_components = [c for c in self.composition if c.role == ComponentRoleEnums.MICROBIAL_CO_CULTURE]
            if not microbial_components:
                microorganism_names = [m.scientific_name for m in self.co_culture_type.Microorganism]
                raise ValueError(
                    f"co_culture_type.Microorganism specifies {len(self.co_culture_type.Microorganism)} microorganism(s) "
                    f"({', '.join(microorganism_names)}) but no components with role='microbial_co-culture' found in composition. "
                    "ALL microorganisms MUST be added to composition with role='microbial_co-culture'. "
                    f"Example: add component with role='microbial_co-culture', cell_type='{microorganism_names[0]}', "
                    f"species='{microorganism_names[0]}', organ=['Brain'] (or appropriate host organ)."
                )
        
        # 7) co_culture_type.ImmuneCell/StromalCell subset-only check: cannot invent labels, but subset is allowed
        if self.co_culture_type is not None:
            if self.co_culture_type.ImmuneCell is not None:
                immune_in_composition = [c.cell_type for c in self.composition if c.role == ComponentRoleEnums.IMMUNE_CO_CULTURE]
                extra_immune = set(self.co_culture_type.ImmuneCell) - set(immune_in_composition)
                if extra_immune:
                    raise ValueError(
                        f"co_culture_type.ImmuneCell contains values not present in composition components with role='immune_co-culture': {sorted(extra_immune)}. "
                        f"Valid immune_co-culture cell_type values are: {sorted(set(immune_in_composition))}."
                    )
            if self.co_culture_type.StromalCell is not None:
                # Accept both stromal_support and feeder_layer roles for StromalCell validation
                # Feeder layers functionally provide stromal support
                stromal_in_composition = [c.cell_type for c in self.composition 
                                         if c.role in (ComponentRoleEnums.STROMAL_SUPPORT, ComponentRoleEnums.FEEDER_LAYER)]
                extra_stromal = set(self.co_culture_type.StromalCell) - set(stromal_in_composition)
                if extra_stromal:
                    raise ValueError(
                        f"co_culture_type.StromalCell contains values not present in composition components with role='stromal_support' or 'feeder_layer': {sorted(extra_stromal)}. "
                        f"Valid stromal_support/feeder_layer cell_type values are: {sorted(set(stromal_in_composition))}."
                    )

        # 8) model_category (including 2D/non-organoid) consistency with if_organoid
        if self.model_category == CultureModelCategoryEnums.ORGANOID and not self.if_organoid:
            raise ValueError(
                "model_category='Organoid' requires if_organoid=true."
            )
        if self.model_category != CultureModelCategoryEnums.ORGANOID and self.if_organoid:
            raise ValueError(
                "if_organoid=true requires model_category='Organoid'."
            )

        # 9) Verify component organ must be subset of base_info.organ (organoid_core only)
        base_organ_keys = set(self.organ.keys())
        for component in self.composition:
            # Only verify organoid_core component organ assignment
            # Co-culture components (microorganisms, immune cells, stromal cells, etc.) are not restricted, can use empty list
            if component.role == ComponentRoleEnums.ORGANOID_CORE and component.organ:
                component_organs = set(component.organ)
                invalid_organs = component_organs - base_organ_keys
                if invalid_organs:
                    raise ValueError(
                        f"Organoid core component '{component.component_id}' has organ(s) {sorted(invalid_organs)} "
                        f"that are not present in OrganoidBaseInfo.organ keys: {sorted(base_organ_keys)}. "
                        f"All organoid_core component organs must be a subset of base_info.organ keys."
                    )

        return self

class BiomarkerTypeEnums(StrEnumBase):
    """Standardized biomarker molecular types"""
    DNA = EnumValue("DNA", "Genomic locus or gene symbol (e.g., TP53, BRCA1). ")
    RNA = EnumValue("RNA", "Transcript-level entities (mRNA, lncRNA, miRNA, viral RNA) (e.g., HOTAIR, miR-21, SARS-CoV-2 viral RNA). ")
    Protein = EnumValue("Protein", "Protein products (e.g., p53, β-catenin, EGFR, KRT17). If a dye/antibody targets a specific protein, use 'Protein' and set biomarker_name.std to the protein target. ")
    Metabolite = EnumValue("Metabolite", "Small molecules from metabolism (e.g., lactate, ATP, glucose). ")
    Lipid = EnumValue("Lipid", "Lipid species (e.g., cholesterol, sphingomyelin, PIP2). ")
    DNA_Mutation = EnumValue("DNA Mutation", "Specific mutation (e.g., KRAS G12D, BRAF V600E). ")
    DNA_Copy_Number_Variation = EnumValue("DNA CNV", "Gene-level or chromosomal CNVs (e.g., HER2 amplification, 1p36 deletion). ")
    Epigenetic_Modification = EnumValue("Epigenetic Modification", "Methylation/acetylation marks (e.g., H3K27me3, 5mC).")
    Cell = EnumValue("Cell", description=(
            "Use for ALL cellular states or structural features detected by dyes/probes/assays (NOT for the dye itself). Specific state is encoded in biomarker_name.std. Common examples: "
            "  * Cell cycle phases: 'S-phase cell' (EdU/BrdU), 'Mitotic cell' (phospho-H3), 'G1-phase cell', 'G2/M-phase cell', 'Proliferating cell' (Ki67) "
            "  * Viability: 'Live cell' (Calcein-AM, FDA), 'Dead cell' (PI, 7-AAD, Trypan Blue) "
            "  * Apoptosis stages: 'Early apoptotic cell' (Annexin V+/PI-), 'Late apoptotic cell' (Annexin V+/PI+), 'Apoptotic cell' (Cleaved Caspase-3, TUNEL), 'Necrotic cell' "
            "  * Structural features: 'Synaptic structure' (SynaptoRed), 'Actin filament' (phalloidin), 'Lipid droplet' (Oil Red O) "
            "  * Other states: 'Senescent cell', 'Quiescent cell', 'Activated cell', 'Differentiated cell' "
            )
        )
    TISSUE_STRUCTURE = EnumValue("Tissue Structure", "Tissue-, histology-, or structure-level features without a specific molecular target. Use ONLY when the assay reports morphology, spatial organization, or pathological structure (e.g., H&E morphology, fibrosis, collagen deposition, myelinated regions, epithelial architecture) and does NOT explicitly target a gene, RNA, protein, or defined molecular entity.")
    Others = EnumValue("Others", "Other biomolecular entities not covered above (e.g., carbohydrates, extracellular matrix components). ")

class BiomarkerSourceTypeEnums(StrEnumBase):
    """
    Source type for biomarker detection, DECISION FLOWCHART: 
    1. Functional dye/probe without specific target? → 'experimental' 
    2. Organoid core cells/secreted products? → 'organoid' 
    3. Experimental co-culture components? → 'coculture' 
    4. Pathological infiltration? → 'pathological' 
    5. Both core and co-culture? → 'shared' 
    6. Separate primary cell/cell line assay? → 'primary cell'/'cell line'
    """
    ORGANOID = EnumValue("organoid", "Detected in organoid core components (role='organoid_core'). ")           
    COCULTURE = EnumValue("coculture", "Detected in experimentally designed co-culture components (role='immune_co-culture', 'stromal_support', 'microbial_co-culture'). ")
    SHARED = EnumValue("shared", "Detected in both organoid core AND experimental co-culture components. ")
    PATHOLOGICAL = EnumValue("pathological", "Detected in pathological or tissue-resident infiltrating components (NOT experimentally added). ")
    PRIMARY_CELL = EnumValue("primary cell", "Detected in separate primary cell assays (e.g., PBMCs, primary fibroblasts) outside organoid culture. ")
    CELL_LINE = EnumValue("cell line", "Detected in separate cell line assays (e.g., HEK293T, HeLa) outside organoid culture. ")
    EXPERIMENTAL = EnumValue("experimental", "Experimental tools, tracers, or functional probes (e.g., dyes like Fluo-4, viability dyes like PI).")

class BiomarkerItemInfo(BaseModel):
    """Unified biomarker detection record for organoid and co-culture systems"""
    
    source_type: BiomarkerSourceTypeEnums = Field(description=BiomarkerSourceTypeEnums.get_field_description())
    
    co_culture_type: Optional[CocultureObjs] = Field(
        default=None,
        description=(
            "[REQUIRED IF source_type='coculture' or 'shared'] Co-culture type information for this biomarker. "
            "Uses the same CocultureObjs data structure as OrganoidBaseInfo.co_culture_type, but values represent only the subset of components detected by this specific biomarker. "
            "WHEN TO PROVIDE THIS FIELD:"
            "• source_type='coculture' or 'shared': MUST provide co_culture_type to specify which experimental co-culture components are detected."
            "• source_type='organoid': MUST be null (organoid core components don't use this field)."
            "• source_type='pathological': SHOULD be null (pathological infiltrating cells are typically NOT in experimental composition)."
            "• source_type='experimental': MUST be null (experimental tools are not biological co-culture components)."
            "FIELD CONTENT (when source_type='coculture' or 'shared'): "
            "This field should contain ONLY the co-culture components that are ACTUALLY detected by this biomarker, "
            "NOT necessarily all components from base_info.co_culture_type."
            "• Microorganism: List of MicroorganismInfo objects with microorganism_type (Virus/Bacteria/Fungi/Parasite/Others), "
            "  scientific_name, and optional strain. Include only microorganisms detected by this biomarker."
            "• ImmuneCell and StromalCell: List of cell_type names (strings) from composition that are detected. "
            "  Format must match composition cell_type exactly (e.g., if composition has 'T cells', use 'T cells' not 'T cell')."
            "VALIDATION RULES:"
            "• CRITICAL: All cell_type values listed here MUST exist in composition components with the corresponding role "
            "  (role='immune_co-culture' for ImmuneCell entries, role='stromal_support' for StromalCell entries)."
            "• If a biomarker detects a component that is NOT in composition at all, this is an error—do NOT create such entries. "
            "  Instead, use source_type='pathological' for pathological infiltration."
            "• If you suspect a detected component is missing from base_info.co_culture_type but IS in composition, "
            "  you may still record it here (it will be a subset of composition), but document the discrepancy in puzzles."
        )
    )

    detect_time: TimeAxisAnchorRefInfo = Field(
        description=(
            "Detection timepoint on the same global timeline. The Time should correspond to the timing of biomarker measurement/assay within the overall culture protocol. "
            "References an anchor in time_anchors; the anchor may have timing=null (unknown timing), "
            "in which case relative temporal order is determined by the anchor's position in time_axis.axes segment sequence."
        )
    )

    biomarker_name: StandardizedName = Field(
        description=(
            "Structured name with original article term (src) and standardized nomenclature (std). "
            "This replaces the old [💡] tag pattern for better programmatic access. "
            "MUST Extract FROM ORIGINAL_TEXT, Examples: If there is 'Ki67' and no 'MKi67' in ORIGINAL_TEXT, so the name should be 'Ki67'(Protein) rather than 'MKi67'(Gene)'. "
            "**STANDARDIZATION STRATEGY SELECTION (based on biomarker_type):** "
            "- biomarker_type='DNA'/'RNA' → Use StandardizedName STRATEGY A (gene symbols): Human 'PTPRC'/'MKI67', Mouse 'Ptprc'/'Mki67'. Determine species from composition via source_type. "
            "- biomarker_type='Protein' → Use StandardizedName STRATEGY B (protein names): CD45→'CD45', Ki-67→'Ki-67' (NOT gene symbols). "
            "- biomarker_type='Metabolite'/'Lipid' → Use StandardizedName STRATEGY C (chemical names). "
            "- biomarker_type='Cell' → Use StandardizedName STRATEGY D (state descriptions): EdU→'S-phase cell'. "
            "CRITICAL EXTRACTION RULES (apply in order): "
            "1. SPECIFIC MOLECULAR ENTITIES (highest priority): Use specific gene/protein names, NOT generic type words. "
            "   Acceptable: 'TP53', 'KRT17', 'SARS-CoV-2 viral RNA', 'cleaved CASP3', 'Spike protein of SARS-CoV-2'. "
            "   Unacceptable: 'DNA', 'RNA', 'protein', 'enzyme', 'antibody', 'marker', 'stain'. "
            "2. ANTIBODY/DYE TARGETS: For antibodies/dyes targeting a defined molecule, use the target molecule name. "
            "   Examples: anti-ceruloplasmin → src='ceruloplasmin', std='CP'; anti-CD45 → src='CD45', std='CD45' (protein); anti-Ki-67 → src='Ki-67', std='Ki-67' (protein antigen). "
            "3. CELLULAR STATES (when no specific molecular target): If dye/probe reports a cellular state, "
            "   use the MOST PRECISE state description. Set biomarker_target_type='Cell'. Both src and std use same state description. "
            "   Examples: EdU → src='S-phase cell', std='S-phase cell'; Calcein-AM → src='Live cell', std='Live cell'. "
            "4. EXCLUDE ROUTINE COUNTERSTAINS: DAPI/Hoechst as nuclear counterstain only, H&E for morphology only → DO NOT create biomarker entry. "
            "5. CONFLICT RESOLUTION: When text has conflicting labels, use explicit gene/protein symbol in src, append '[❓️]', document in puzzles. "
            "6. VIRUS-SPECIFIC: Include virus name in src (e.g., src='Spike protein of SARS-CoV-2', std='S protein'). "
            "7. STANDARDIZATION: Apply StandardizedName STRATEGY A/B/C/D based on biomarker_type (see field description above). "
            "   Refer to StandardizedName.std for detailed strategy definitions and examples."
        )
    )

    pathway: Optional[str] = Field(
        None,
        description=(
            "Optional: Biological pathway or functional grouping to which the biomarker belongs. "
            "Examples: 'pERK1/2' → 'MAPK pathway'; 'pAKT S473' → 'AKT/mTOR pathway'; 'pS6' → 'mTOR pathway'; "
            "also valid: 'Apoptosis', 'Cell Proliferation', 'Inflammation'. "
            "CRITICAL: Only populate this field when the pathway is explicitly mentioned in the source text. "
            "If the original text does NOT mention a pathway, leave this field NULL. Do NOT infer or guess pathways from marker names unless the source clearly states the pathway relationship. "
            "When a pathway is provided, include the exact supporting phrase from the source in the record's notes or evidence field to preserve provenance. "
            "Prefer standardized pathway names (KEGG/Reactome) when available for interoperability, but free-text names are acceptable if taken verbatim from the source."
        )
    )

    biomarker_type: BiomarkerTypeEnums = Field(
        description= BiomarkerTypeEnums.get_field_description(
            main_desc="CRITICAL: 'Dye' is NOT a valid biomarker_type. When a dye/probe is used for detection, classify by WHAT IS BEING DETECTED, not the detection tool. "
        )
    )


    biomarker_application: str = Field(
        description=(
            "**REQUIRED FIELD** The primary research objective or scientific context for detecting this biomarker. "
            "This field captures WHY the biomarker was measured in the experimental design. "
            "From a biological perspective, specify the overarching research goal: mechanistic pathway investigation, disease phenotype characterization, "
            "therapeutic efficacy evaluation, developmental stage identification, cell fate determination, functional validation, or biomarker discovery. "
            "Common categories: 'immunotherapy response prediction', 'signaling pathway analysis', 'cell proliferation monitoring', "
            "'apoptosis detection', 'differentiation status assessment', 'disease modeling', 'drug screening', 'developmental biology', 'regenerative medicine', "
            "'metabolic profiling', 'stem cell characterization', 'loading control', 'quality control'. "
            "**CRITICAL**: This field MUST NOT be omitted. If the specific application is not explicitly stated in the text, "
            "infer from the experimental context (e.g., Western blots for pathway proteins → 'signaling pathway analysis'; "
            "proliferation markers in drug treatment → 'drug screening'). Only use 'not specified' as a last resort when absolutely no context is available."
        )
    )
    biomarker_characterization: str = Field(
        description=(
            "**REQUIRED FIELD** A concise biological description (1-2 sentences) of the biomarker's role, functional significance, and/or experimental interpretation in this specific study context. "
            "This field should capture the BIOLOGICAL MEANING: what does the presence, absence, or change in this biomarker indicate about the cellular or tissue state? "
            "Include key aspects such as: (1) Temporal dynamics - when is it detected/expressed (e.g., 'Upregulated at day 7 post-differentiation'); "
            "(2) Functional role - what biological process it represents (e.g., 'Marker of activated STING pathway', 'Indicates cell cycle S-phase entry'); "
            "(3) Regulatory relationships - upstream/downstream connections if mentioned (e.g., 'Activated by F. nucleatum to regulate PD-L1 transcription'); "
            "(4) Phenotypic indication - what cellular phenotype/state it reflects (e.g., 'Indicates mature hepatocyte-like identity', 'Reflects apoptotic cell population'). "
            "**CRITICAL**: This field MUST NOT be omitted. Extract from Results/Discussion sections describing what the biomarker measurement reveals. "
            "Examples: 'Expressed at day 3 to indicate neural differentiation status'; 'Phosphorylated form indicates activation of NF-κB pathway upon bacterial stimulation'; "
            "'Used as loading control for Western blot normalization'; 'Elevated levels correlate with enhanced immunotherapy response'."
        )
    )

    detection_method: str = Field(
        description=(
            "**REQUIRED FIELD** The experimental technique/assay used to detect or measure this biomarker. "
            "This field captures HOW the biomarker was detected at the methodological level. "
            "**EXTRACTION STRATEGY:** Extract from Methods section. Look for phrases like 'detected by...', 'measured using...', 'analyzed via...'. "
            "Multiple biomarkers measured in the same assay/panel SHOULD share the same detection_method (e.g., if 25 proteins are all detected by Mass Cytometry, all 25 biomarkers should have detection_method='Mass Cytometry'). "
            "**SYNONYM STANDARDIZATION:** Recognize and standardize equivalent method names: "
            "- Mass Cytometry = CyTOF = Cytometry by Time-of-Flight → use 'Mass Cytometry' "
            "- Immunofluorescence = IF = Immunofluorescent staining → use 'Immunofluorescence' "
            "- Western Blot = Western blotting = Immunoblot → use 'Western Blot' "
            "- Flow Cytometry = FACS = Fluorescence-Activated Cell Sorting → use 'Flow Cytometry' "
            "- For PCR methods: Follow RULE 19 PCR_INTERPRETATION in KNOWLEDGE (handles qRT-PCR/RT-PCR distinction) "
            "**COMMON METHODS:** Protein: 'Immunofluorescence', 'Confocal Microscopy', 'Western Blot', 'ELISA', 'Mass Cytometry', 'Flow Cytometry', 'Mass Spectrometry', 'Immunohistochemistry'. "
            "Nucleic acid: 'qRT-PCR', 'RT-PCR', 'RNA-seq', 'scRNA-seq', 'In Situ Hybridization', 'FISH'. "
            "Metabolite: 'Mass Spectrometry', 'LC-MS', 'GC-MS', 'NMR Spectroscopy'. "
            "Cellular state: 'Flow Cytometry', 'Mass Cytometry', 'Live-Cell Imaging', 'Time-Lapse Microscopy'. "
            "**CRITICAL:** This field MUST NOT be omitted. If the specific method is not explicitly stated in the text, "
            "infer from experimental context: reagents mentioned (e.g., 'fluorescent antibodies' → Immunofluorescence/Flow Cytometry), "
            "equipment mentioned (e.g., 'confocal microscope' → Confocal Microscopy; 'Helios' → Mass Cytometry), "
            "or analysis approach (e.g., 'single-cell protein quantification' → Flow/Mass Cytometry). "
            "Only use 'not specified' as a last resort when absolutely no methodological clues are available."
        )
    )
    
    @field_validator('biomarker_name')
    @classmethod
    def validate_biomarker_name(cls, v):
        """Validate biomarker_name which is now a StandardizedName.

        Requirements:
        - Accepts either a StandardizedName instance or a dict that can be validated into one.
        - Both `src` and `std` must be present and must not be empty or meaningless values
          such as 'not specified', 'unknown', 'n/a', or the empty string.
        """
        # Accept dicts (raw payload) by trying to build a StandardizedName
        if isinstance(v, dict):
            try:
                v = StandardizedName.model_validate(v)
            except Exception as e:
                raise ValueError(f"biomarker_name has invalid structure: {e}")

        # At this point we expect a StandardizedName (or compatible object)
        if not isinstance(v, StandardizedName):
            raise ValueError('biomarker_name must be a StandardizedName or mapping convertible to it')

        def _is_meaningless(s: Optional[str]) -> bool:
            if s is None:
                return True
            ss = str(s).strip()
            return ss == '' or ss.lower() in {'not specified', 'unknown', 'n/a'}

        if _is_meaningless(v.src) or _is_meaningless(v.std):
            raise ValueError("biomarker_name.src and biomarker_name.std must be meaningful and not empty/'not specified'/unknown")

        return v
    
    @model_validator(mode='after')
    def validate_coculture_type(self):
        """Validate co_culture_type consistency with source_type"""
        # MUST provide co_culture_type for 'coculture' and 'shared'
        if self.source_type in [BiomarkerSourceTypeEnums.COCULTURE, BiomarkerSourceTypeEnums.SHARED]:
            if not self.co_culture_type:
                raise ValueError(f"co_culture_type is required when source_type='{self.source_type.value}'")
        
        # MUST NOT provide co_culture_type for 'organoid', 'pathological', and 'experimental'
        if self.source_type in [BiomarkerSourceTypeEnums.ORGANOID, BiomarkerSourceTypeEnums.PATHOLOGICAL, BiomarkerSourceTypeEnums.PRIMARY_CELL, BiomarkerSourceTypeEnums.CELL_LINE, BiomarkerSourceTypeEnums.EXPERIMENTAL]:
            if self.co_culture_type:
                raise ValueError(f"co_culture_type should not be provided when source_type='{self.source_type.value}'")
        
        return self

# Backward compatibility aliases (deprecated, use BiomarkerItemInfo instead)
# OrganoidBiomarkerItemInfo = BiomarkerItemInfo
# CocultureBiomarkerItemInfo = BiomarkerItemInfo

class CultureStepTimeInfo(BaseModel):
    """Time range for a culture step"""
    start_time: TimeAxisAnchorRefInfo = Field(
        description=(
            "The starting point for undertaking this step on the same global timeline(time_axis). "
            "For same-day operations (e.g., 'Day 7: passaged organoids'), start_time and end_time MAY reference the same anchor. "
            "The referenced anchor may have timing=null, in which case relative order is from time_axis.axes position."
            "TimeAxisAnchorRefInfo.id MUST NOT be null."
        )
    )
    end_time: TimeAxisAnchorRefInfo = Field(
        description=(
            "The ending point for undertaking this step on the same global timeline(time_axis). "
            "For same-day operations (e.g., 'Day 7: passaged organoids'), start_time and end_time MAY reference the same anchor. "
            "For multi-day phases (e.g., 'Day 0-7: expansion'), must reference different anchors."
            "TimeAxisAnchorRefInfo.id MUST NOT be null."
        )
    )
    time_src: str = Field(
        description="Source of time information. Select ONE from 5 categories: "
                    "1. 'THIS' = time explicitly stated in current article's original text (Methods/Results section). "
                    " - Examples: 'day 3', 'after 7 days', '72 hours post-seeding' when directly quoted. "
                    "2. 'THIS (inferred): [reasoning]' = time inferred from current article's context using mathematical calculation or logical sequence. "
                    " - Use this when: (a) text gives relative time ('after 3 days') but you calculate absolute day from context, (b) text describes sequence ('seeded on day 0, then changed medium 3 days later') and you infer day 3, (c) text gives hours that you convert to days based on explicit day transitions in the article. "
                    " - Examples: 'THIS (inferred): calculated from seeding on day 0 and analysis 72h later → day 3', 'THIS (inferred): step sequence implies medium change between passage (day 2) and embedding (day 5) → day 3-4'. "
                    " - Do NOT use 'inferred' for simple unit conversions (hours to days) when the day is already explicit. "
                    "3. '[First author surname] et al., [Year]' OR 'DOI: [doi]' = time explicitly stated in cited reference (prefer DOI if available). "
                    " - Example: 'Smith et al., 2020' or 'DOI: 10.1234/example'. "
                    "4. '[Citation] (inferred): [reasoning]' = time inferred from cited reference's context. "
                    " - Example: 'Smith et al., 2020 (inferred): protocol describes seeding followed by 7-day culture, inferred as day 0-7'. "
                    "5. 'not specified' = NO time information found AND cannot be inferred from any source. "
                    " - Use this when: (a) text mentions a step but gives no timing, (b) timing is completely ambiguous, (c) only vague phrases like 'later' or 'subsequently' without any numeric reference. "
                    "NOTE: For inferred cases (2 or 4), MUST include brief reasoning after colon explaining the calculation or logic."
    )
    time_desc: Optional[str] = Field(
        default=None,
        description=(
            "OPTIONAL time-related description copied from original text or cited references. Use this field to preserve context that clarifies or supplements start_day/end_day. "
            "**USAGE RULES:** "
            "1. EXPLICIT TIME IN CURRENT ARTICLE: Copy exact original phrase when informative. "
            " - Examples: 'day 3-7', 'after 72 hours', '2 weeks post-seeding', 'until confluent', 'overnight incubation'. "
            "2. CITED REFERENCE TIME: If current article references another paper for timing without details: "
            " - If you can search and obtain the specific timing from the reference: copy that timing description. Example: '7-day differentiation protocol as described in the reference' "
            " - If reference is inaccessible: copy the original vague phrase. Example: 'step info from Smith et al., 2020' "
            "3. INFERENCE FROM CONTEXT: When time must be inferred, copy the relevant original phrase that enables inference (NOT the inference reasoning—that goes in time_src). "
            " - Examples: 'after passage 3 expansion' (when inferring day from known passage timing), "
            " - 'following medium change' (when inferring relative to prior step). "
            "4. PERIODIC OPERATIONS (TIME_EXTRACTION_RULES STEP 6): Copy original phrasing including periodicity. "
            " - Example: 'medium change every 2 days from day 0 to day 10' "
            " - Note: time_src can add '(first occurrence only; subsequent cycles omitted per TIME_EXTRACTION_RULES STEP 6)' if needed. "
            "5. WITHIN-DAY HOURS (TIME_EXTRACTION_RULES STEP 4): Copy hour-level details from original text. "
            " - Examples: '12h after seeding', '6h post-EGF addition', '36h after plating'. "
            "6. TIMING-UNCLEAR STEPS: When exact timing is unspecified, describe the action/event and use time_anchor system for contextual placement. "
            " - Examples: 'organoids were digested for 5 min' (timing relative to other steps unclear), 'samples were collected for RNA extraction' (absolute day not stated), 'biomarkers detected via immunofluorescence' (detection timepoint not explicit). "
            " - CRITICAL: Describe WHAT happened, not just 'timing unknown'. Use action verbs and material names from original text. "
            "**WHEN TO OMIT:** Omit this field when start_day/end_day + time_src provide sufficient clarity (e.g., simple 'day 3' cases). "
            "Do NOT duplicate inference reasoning from time_src. Do NOT use placeholders like 'not specified'—simply omit the field. "
            "**PURPOSE:** Preserve original text context for transparency and enable future re-interpretation, while start_day/end_day provide standardized integers."
        )
    )


class CultureMaterialInfo(BaseModel):
    """Culture additive (supplement, growth factor, or small molecule) with concentration"""
    name: str = Field(
        description="ONE specific material name. for culture use only (not experimental use). Examples: 'B-27 Supplement', 'EGF', 'CHIR99021', 'FBS', 'Penicillin-Streptomycin'"
    )
    concentration: str = Field(
        description="Concentration or amount used. COPY FROM ORIGINAL_TEXT Format: "
                    "1. For concentrations: include value + unit (e.g., '10 ng/ml', '5 µM', '0.1% w/v', '1X'). "
                    "2. For volumes: state volume + concentration if both given (e.g., '25 µl of 6 mg/ml stock'). "
                    "3. For dilutions: use ratio notation (e.g., '1:100 dilution'). "
                    "4. For percentages: specify type (e.g., '2% v/v', '5% w/w', '10% FBS')."
                    "5. IF the orginal data maybe wrong or inconsistent, keep original text and do not correct it with [❓️]: e.g. `50 ng/ul [❓️]`"
                    "6. Default to 'not specified' if not mentioned and can not reason."
    )
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not v or v.strip() == '':
            raise ValueError("Material name cannot be empty")
        return v.strip()
    

class CultureStageEnums(StrEnumBase):
    """Standardized culture stages"""
    Seeding = EnumValue("Seeding", "Initial placement of cells or aggregates into culture system (e.g., embedding in ECM, plating in low-adherent plates). ")
    Expansion = EnumValue("Expansion", "Proliferation and growth of cells or organoids to increase their number or size.")
    Patterning = EnumValue("Patterning", "Induction of spatial organization and differentiation patterns within the organoid.")
    Maturation = EnumValue("Maturation", "Development of functional and structural characteristics of mature tissue.")
    Self_Organization = EnumValue("Self-Organization", "Spontaneous organization of cells into structured organoids without external patterning cues.")
    Differentiation = EnumValue("Differentiation", "Process by which cells become specialized into specific cell types within the organoid.")
    Maintenance = EnumValue("Maintenance", "Sustaining the health and viability of the organoid culture over time.")
    Manufacturer_Maintenance = EnumValue("Manufacturer Maintenance", "Maintenance procedures recommended or performed by the manufacturer.")
    Others = EnumValue("Others", "Other culture stages not specifically categorized.")

# StepScopeEnums enum inserted immediately after CultureStageEnums
class StepScopeEnums(StrEnumBase):
    """Scope of a culture step within the combined culture system. Scope MUST be interpreted together with target_components according to `RULE 17: STEP_SCOPE AND MATERIAL SOURCE_TYPE MAPPING` in KNOWLEDGE."""
    WHOLE_SYSTEM = "whole_system"
    ORGANOID_CORE_ONLY = "organoid_core_only"
    CO_CULTURE_ONLY = "co_culture_only"
    SPECIFIC_COMPONENTS = "specific_components"


# REPLACEMENT: OrganoidCultureStepInfo with unified organoid/co-culture step structure
class OrganoidCultureStepInfo(BaseModel):
    """Single culture step within one organoid/co-culture system.

    This class encodes BOTH steps applied to the organoid core and steps applied to
    co-cultured components, using `step_scope` and optional `target_component(s)`
    to indicate which parts of the culture system are affected.
    """

    during: CultureStepTimeInfo = Field(
        description="Time range when operating this step. Includes start_time and end_time on the global timeline(time_axis). Min Split items unit is DAY, So multiple steps within one day should be combined into one step with same start_time and end_time."
    )

    steps: List[str] = Field(
        min_length=1,
        description=(
            "# Basic Rules: "
            "List of actions taken. Each item=ONE COMPLETE ACTION. "
            "Base text on verbatim or near-verbatim extraction from the original text whenever possible. "
            "Extract from Methods section first; supplement with Results section and figure legends as needed (all are valid sources). "

            "# SELF-CONTAINED COMPLETENESS (highest priority): "
            "Each step MUST be independently understandable without relying on surrounding context. "
            "A complete step captures: WHO/WHAT is being acted upon (object/target), WHAT is done (action verb), "
            "KEY PARAMETERS (concentration, duration, temperature, dose, MOI, cell density, etc.), "
            "and any essential contextual identifiers needed for the sentence to stand alone. "
            "To achieve this, unlike other fields where inference is restricted, this field ALLOWS (and when necessary REQUIRES) "
            "reading comprehension across the full article text (Methods, Results, and figure legends). "
            "When a sentence is incomplete in isolation (missing subject, object, or key identifier), "
            "MUST synthesize the missing element from other sentences in the article. "
            "This is not speculation; it is faithful reading comprehension within the source text scope. "
            "Do NOT infer parameters not present anywhere in the article (e.g., do not guess MOI if not stated). "
            "❌ Bad (incomplete fragment; do NOT truncate a sentence): 'Analyzed 6 days after infection' → missing what was analyzed, what agent was used, what was infected. "
            "✅ Good (full sentence from source): 'Infected human 2D corticogenesis (D32) with pLenti-CIG-MYC-CROCCP2 at D25; analyzed by immunofluorescence 6 days after infection'. "
            "❌ Bad (missing subject and material): 'Added to the culture'. "
            "✅ Good: 'Added 10 ng/ml EGF to intestinal organoid culture'. "

            "# MATERIAL CITATION [n]: "
            "When mentioning culture-purpose materials listed in material_source, MUST append [n] suffix (1-based index: material_source[0] → [1], material_source[1] → [2], etc.). "
            "Same material used multiple times → same [n]. Include concentration/application method inline (NOT in material_source). "
            "If concentration not mentioned in original text, use prefix '`unknown concentration` of {material}[n]'. "
            "Which materials use [n]: ECM/scaffolds (Matrigel, Collagen), Enzymes (TrypLE, Accutase), Coatings (Poly-L-lysine), Buffers (PBS if tracked), Solvents (DMSO if tracked), Therapeutic agents applied to culture. "
            "Which do NOT use [n]: supplements/growth_factors/small_molecules (already structured in separate fields); post-fixation reagents, staining antibodies, assay kits (recorded in ExperimentalMaterialInfo, reference by name only). "
            "Example: material_source = [Matrigel(Corning,356231), TrypLE(Gibco,12605010)] → 'Embedded cells in 6 mg/ml Matrigel[1] domes'; 'Dissociated using 0.05% TrypLE[2]'. "

            "# FIELD ASSIGNMENT: "
            "Do NOT place ECM/enzyme/coating/buffer/therapeutic-agent materials into medium/supplements/growth_factors/small_molecules fields; record them ONLY in material_source and cite with [n] in steps text. "

            "# EXAMPLES: "
            "['Seeded dissociated cerebral organoid cells into 6 mg/ml Matrigel[1] domes at 500 cells/µl'] | "
            "['Changed intestinal organoid medium to differentiation medium', 'Incubated intestinal organoids at 37°C with 5% CO2 for 7 days'] | "
            "['Infected intestinal organoids with SARS-CoV-2[3] at MOI 0.1 for 2 h, then washed with PBS[4]'] | "
            "['Dissociated intestinal organoids using 0.05% TrypLE[2] for 10 min at 37°C', 'Replated dissociated intestinal organoid cells into fresh `unknown concentration` of Matrigel[1] domes']"
        )
    )


    stage: CultureStageEnums = Field(
        description=CultureStageEnums.get_field_description(main_desc=(
            "Culture stage: Choose based on: (1) the unified stage definitions, OR (2) the specific definitions matching your culture technique category (Scaffold-based/Suspension-based/Interface-based/Engineered Microenvironments/Bioprinting & Assembly). "
            "For organoids or 3D tissue equivalents purchased as commercial products and handled strictly according to the manufacturer's instructions (e.g., MatTek skin equivalents, pre-fabricated liver organoids) without in-house derivation, use stage='manufacturer_maintenance' for steps that only maintain, feed, or prepare the product according to the kit protocol."
            "Do NOT re-label these steps as 'seeding' or 'patterning' unless the article clearly describes additional user-defined manipulations beyond the manufacturer's baseline maintenance protocol. "
            "Refer to `CULTIVATION_STAGE_DEFINITIONS` in KNOWLEDGE for detailed guidance on each stage across different cultivation systems, including when to apply 'manufacturer_maintenance'."
        ))
    )

    step_scope: StepScopeEnums = Field(
        description=(
            f"Scope of this step within the culture system. Select ONE from: {[e.value for e in StepScopeEnums]}. Rules: "
            "1. 'whole_system': operations that affect all components in the combined culture (organoid core + any co-cultured partners), "
            "such as global medium changes, incubation, or common washes. target_components must be null. "
            "2. 'organoid_core_only': steps applied only to components with role='organoid_core' (e.g., early differentiation, "
            "patterning before immune/microbial cells are added). "
            " - target_components: can be null (all organoid core components) or ['C1', 'C2'] (specific core components by component_id) "
            " - Use null when the step applies to all core organoids without distinction "
            " - Use specific component_ids when the step targets only certain core organoid components "
            " - Only list component_ids with role='organoid_core' "
            " - Examples: pre-differentiation of all organoid types (null), passaging only tumoroids (['C2']). "
            "3. 'co_culture_only': steps applied only to non-core co-culture populations. "
            " - target_components: can be null (all co-culture components) or ['C2', 'C3'] (specific components by component_id) "
            " - All co-culture components (cellular and microbial) are in composition with component_id, so can be targeted "
            " - Use null when step affects all co-culture components; use specific component_ids when step targets only certain components "
            " - Examples: pre-activation of T cells, viral infection, microbial pre-culture. "
            "4. 'specific_components': the step targets only a subset of components explicitly listed in `target_components` "
            "(identified by OrganoidComponentInfo.component_id from composition, format: 'C1', 'C2', etc.). "
            "target_components is REQUIRED and must contain at least one valid component_id. "
            "Use this when you need to target specific components (e.g., only heart module, or only immune cells). "
            "When the article description is ambiguous, prefer 'whole_system'."
        )
    )

    target_components: Optional[List[str]] = Field(
        default=None,
        description=(
            "LIST of component_id values targeted by this step. **ONLY used for co-culture systems with multiple components in composition.** "
            "For parallel experimental groups (separate vessels, separate OrganoidCultureResult entries), do NOT use this field. "
            "Rules: "
            "1. When step_scope='specific_components': REQUIRED, must contain at least one component_id from composition. "
            "   Format: ['C1'] for single component, ['C1', 'C2'] for multiple components. "
            "   Examples: "
            "   - ['C1']: step targets only heart organoid module (e.g., 'Added growth factors to heart organoid only') "
            "   - ['C1', 'C2']: step targets both heart and liver modules (e.g., 'Changed medium for both organ modules') "
            "   - ['C3']: step targets only immune cells component (e.g., 'Pre-activated T cells before adding to organoid') "
            "   - ['C4']: step targets only microorganism component (e.g., 'Pre-cultured SARS-CoV-2 virus before infection') "
            "2. When step_scope='organoid_core_only': "
            "   - null: affects ALL organoid core components (default semantic) "
            "   - ['C1', 'C2', ...]: affects ONLY specified organoid core components (only list component_ids with role='organoid_core') "
            "   - Use null when the step applies to all core organoids without distinction "
            "   - Use specific component_ids when the step targets only certain core organoid components "
            "   - Examples: "
            "     • null: 'Passaged all organoid lineages' (affects C1 healthy organoids and C2 tumoroids simultaneously) "
            "     • ['C2']: 'Dissociated tumoroids only' (only affects C2 tumoroids, not C1 healthy organoids) "
            "     • ['C1', 'C2']: explicit listing when you want to make it clear both are targeted "
            "3. When step_scope='co_culture_only': "
            "   - null: affects all co-culture components "
            "   - ['C2', 'C3', ...]: affects only specified co-culture components (only list component_ids with role!='organoid_core') "
            "   - All co-culture components (cellular and microbial) are in composition with component_id, so can be targeted "
            "4. When step_scope='whole_system': target_components MUST be null (affects entire system including support cells) "
            "**NOTE**: Contrast with time_axis.branch.component_id (single str for one component's timeline). "
            "target_components (List[str]) is for protocol steps affecting multiple components within ONE co-culture system."
        )
    )

    medium: str = Field(
        description=(
            "Base culture medium name(s) used in this step (exclude supplements, growth factors, and small molecules). "
            "1. See [MAT-RULE-04] in KNOWLEDGE for medium decomposition workflow and [MAT-RULE-07] for reporting rules. Rules: "
            " - Use specific base medium product names (e.g., 'DMEM/F12', 'Neurobasal', 'RPMI 1640', 'mTeSR1'). "
            " - If text uses pronouns ('the medium', 'this medium'), resolve to the actual name mentioned earlier when possible. "
            " - If a commercial product name contains 'Medium' (e.g., 'Neurobasal Medium'), keep it. "
            " - Do NOT add the word 'medium' if not in the original name (wrong: 'RPMI medium', correct: 'RPMI 1640'). "
            " - If multiple base media are mixed, list all with ratio (e.g., 'DMEM/F12 + Neurobasal (1:1)'). "
            " - For custom media, use the descriptive name from the paper (e.g., 'basal differentiation medium', 'WENR medium'). "
            " - Do NOT include supplements (B-27, N-2, GlutaMax, FBS), growth factors (EGF, bFGF), or small molecules (CHIR99021) here — those go in separate fields. "
            " - If the article only states that cultures were handled 'according to the manufacturer's recommendations' without naming a specific medium for this step, and the exact commercial product ID is ambiguous or multiple media are possible, set the value to 'not specified'. ONLY when the kit/product ID is uniquely specified and the manufacturer's documentation clearly defines a single recommended base medium for this product MAY you fill in that medium name and append [💡] tag to indicate inference from external documentation (e.g., 'DMEM/F12 [💡]' when inferred from MatTek product specification sheet)."
            " - For any culture step where cells, spheroids, organoids, printed constructs, or explants are clearly maintained in a culture environment (including but not limited to bioprinting, microfluidic devices, suspension culture, bioreactors, or interface-based systems), but the article never names the base medium for this phase anywhere in the text, set medium='not specified' for this step and DO NOT guess from cell type, tissue type, journal habits, or 'typical practice'. If this missing information critically affects interpretation of the protocol, you MAY record this limitation as a puzzles entry with source='Source'."
            "2. See [MAT-RULE-06] in KNOWLEDGE for reporting format and the material_source field specification (how to list and reference culture-purpose materials)."
        )
    )

    supplements: Optional[List[CultureMaterialInfo]] = Field(
        default=None,
        description=(
            "Commercial supplements, serum, antibiotics, and medium additives used in this step. "
            "See [MAT-RULE-05] Type 2 (Supplement) and Type 5 (Antibiotic) in KNOWLEDGE for complete lists. See [MAT-RULE-06] in KNOWLEDGE for reporting format and examples. Examples: "
            "B-27 Supplement, N-2 Supplement, GlutaMax, FBS (Fetal Bovine Serum), KSR (KnockOut Serum Replacement), "
            "Penicillin-Streptomycin, Normocin, ITS (Insulin-Transferrin-Selenium), NEAA (Non-Essential Amino Acids), "
            "Sodium Pyruvate, β-mercaptoethanol, Ascorbic acid, BSA (Bovine Serum Albumin), HEPES (when part of medium formulation). "
            "MUST use array format even for a single item: [{'name':'B-27 Supplement','concentration':'1X'}]. "
            "ONE specific supplement per item. Omit this field if none."
        )
    )

    growth_factors: Optional[List[CultureMaterialInfo]] = Field(
        default=None,
        description=(
            "Protein-based growth factors, cytokines, and morphogens added separately to the medium. "
            "See [MAT-RULE-05] Type 3 (Growth Factor) in KNOWLEDGE for complete lists. See [MAT-RULE-06] in KNOWLEDGE for reporting format and examples. "
            "Examples: EGF, bFGF/FGF2, Wnt3a, Noggin, BMP4, Activin A, FGF8, IGF-1, VEGF, HGF, TGF-β, R-spondin. "
            "MUST use array format even for a single item: [{'name':'EGF','concentration':'50 ng/ml'}]. "
            "ONE specific factor per item. Omit this field if none."
        )
    )

    small_molecules: Optional[List[CultureMaterialInfo]] = Field(
        default=None,
        description=(
            "Small molecule inhibitors, activators, and chemical pathway modulators added separately. "
            "See [MAT-RULE-05] Type 4 (Small Molecule) in KNOWLEDGE for complete lists. See [MAT-RULE-06] in KNOWLEDGE for reporting format and examples. "
            "Examples: CHIR99021 (Wnt activator), SB431542 (TGF-β inhibitor), LDN193189 (BMP inhibitor), "
            "Y-27632 (ROCK inhibitor), A83-01 (TGF-β inhibitor), PD0325901 (MEK inhibitor), Forskolin, "
            "Retinoic acid, Dexamethasone, Dorsomorphin, Purmorphamine, SAG (Smoothened Agonist). "
            "MUST use array format even for a single item: [{'name':'CHIR99021','concentration':'3 µM'}]. "
            "ONE specific compound per item. Omit this field if none."
        )
    )

    @model_validator(mode="after")
    def validate_step_targets(self):
        """Basic consistency between step_scope and target component fields."""
        if self.step_scope == StepScopeEnums.SPECIFIC_COMPONENTS:
            if not self.target_components or len(self.target_components) == 0:
                raise ValueError(
                    "For step_scope='specific_components', target_components is REQUIRED and must contain at least one component_id."
                )
            # Validate component_id format
            import re
            for comp_id in self.target_components:
                if not isinstance(comp_id, str) or not re.match(r'^C\d+$', comp_id.strip()):
                    raise ValueError(
                        f"target_components entries must be in format 'C1', 'C2', etc. Found: {comp_id}"
                    )
        elif self.step_scope == StepScopeEnums.WHOLE_SYSTEM:
            if self.target_components is not None:
                raise ValueError(
                    f"target_components must be null when step_scope is 'whole_system'. "
                    f"This scope affects the entire system including all components and support cells."
                )
        # For organoid_core_only and co_culture_only, target_components can be null or a list
        # null means all components of that category, list means specific components
        return self
        # For co_culture_only, target_components can be null (all co-culture) or list (specific components)
        # All co-culture components (cellular and microbial) are in composition, so can be targeted
        return self


class DrugResponseEnums(StrEnumBase):
    """Drug testing response types"""
    Efficacy_Testing = "Drug efficacy testing"
    Toxicity_Testing = "Drug toxicity testing"
    Resistance_Testing = "Drug resistance testing"
    Pharmacokinetics = "Pharmacokinetics"
    Others = "Others"

class DrugListInfo(BaseModel):
    """Drug testing information"""
    drug: str = Field(
        description="Drug name. Example: 'Paclitaxel', 'Cisplatin', 'Temozolomide'"
    )
    disease: str = Field(
        description="Disease tested against. Example: 'Glioblastoma', 'Colorectal cancer', 'Alzheimer disease'"
    )
    drug_response: DrugResponseEnums = Field(description=DrugResponseEnums.get_field_description())

class InfectionRoleEnums(StrEnumBase):
    """High-level experimental role of an infection or microbial challenge"""
    DISEASE_MODEL = "Disease model"
    CHALLENGE = "Challenge / stimulation"
    CONTROL = "Control infection"
    TOOL_VECTOR = "Tool or delivery vector"
    OTHERS = "Others"

class PhenotypeEndStatusEnums(StrEnumBase):
    """Phenotype lifecycle status enumeration.
    All semantic guidance MUST be in PhenotypeTimeInfo.end_status Field description.
    """
    PERSISTING = EnumValue(
        "Persisting",
        description=(
            "Phenotype continues to exist at last observation/study endpoint. No disappearance mentioned. "
            "Use when phenotype is still observable at study end with no indication of decline or transformation."
        )
    )
    DISAPPEARED_TIMING_UNKNOWN = EnumValue(
        "DisappearedTimingUnknown",
        description=(
            "Phenotype disappeared but exact timing unknown. "
            "Use when later observations show phenotype is absent but article doesn't specify when it disappeared. "
            "May have transitioned or been lost between observation timepoints."
        )
    )
    TRANSITIONED = EnumValue(
        "Transitioned",
        description=(
            "Phenotype evolved into different state/morphology. "
            "Use when article explicitly describes transformation (e.g., 'cysts → flat epithelium', 'dense spheroids → loose networks')."
        )
    )
    EXPLICIT_END = EnumValue(
        "ExplicitEnd",
        description=(
            "Phenotype ended with known timing (end_time has value). "
            "This status confirms end_time is NOT null. Use when article states specific time of phenotype disappearance."
        )
    )


class InfectionListInfo(BaseModel):
    """Infection / microbial challenge information (experiment-level summary)"""

    agent_name: str = Field(
        description=(
            "Scientific or common name of the infectious agent, e.g., 'SARS-CoV-2', 'Zika virus', "
            "'Escherichia coli'. This SHOULD match the scientific_name of a MicroorganismInfo entry "
            "in co_culture_type.Microorganism when possible."
        )
    )

    microorganism_type: MicroorganismEnums = Field(
        description=(
            f"Type of microorganism. Select ONE from: {[e.value for e in MicroorganismEnums]}. "
            "Must be consistent with agent_name."
        )
    )

    disease_or_model: Optional[str] = Field(default='not specified',
        description=(
            "Disease, syndrome, or infection model being studied, e.g., 'COVID-19', "
            "'Zika virus-induced microcephaly', 'bacterial colonization'. "
            "Use the literal string 'not specified' only if the article gives no disease-level description."
        )
    )

    infection_role: InfectionRoleEnums = Field(
        description=(
            f"High-level experimental role of this infection. Select ONE from: {[e.value for e in InfectionRoleEnums]}. "
            "Examples: 'Disease model' for primary pathogenic models, 'Challenge / stimulation' for secondary "
            "stimulation of an established culture, 'Control infection' for control strains, and "
            "'Tool or delivery vector' when the microbe is used primarily as a gene-delivery or labeling tool."
        )
    )

    host_system: Optional[str] = Field(default='not specified',
        description=(
            "Text description of what is infected, e.g., 'brain organoid core', "
            "'tumor organoid + T cell co-culture', 'whole culture system'. "
            "This is a free-text summary and MUST NOT invent new components beyond those defined "
            "in OrganoidBaseInfo.composition."
        )
    )

class PhenotypeTimeInfo(BaseModel):
    """Time window when a phenotype appears/persists, with explicit lifecycle status tracking.
    Do NOT confuse this with TimeAxisAnchorInfo - this is for PHENOTYPE APPEARANCE, not culture operations.
    """
    
    start_time: TimeAxisAnchorRefInfo = Field(
        description=(
            "Start timepoint of phenotype appearance. [REQUIRED] Must reference an anchor from time_anchors "
            "(e.g., 'observe cyst formation at day 7'). If timing is unknown but phenotype is described, "
            "create anchor with timing=null and descriptive name."
        )
    )
    end_time: Optional[TimeAxisAnchorRefInfo] = Field(
        default=None,
        description=(
            "[CRITICAL: Read RULE 1 before setting this field] End timepoint if phenotype explicitly disappears or transitions. "
            "Use null (omit) when end_status is PERSISTING or DISAPPEARED_TIMING_UNKNOWN. "
            "When creating end_time anchor with timing=null, use name_action like 'phenotype no longer observed' "
            "or name_cell_state like 'transitioned to X state', NEVER use generic terms like 'unknown'."
        )
    )
    end_status: PhenotypeEndStatusEnums = Field(
        description=PhenotypeEndStatusEnums.get_field_description(
            main_desc=(
                "CONSISTENCY RULE: If end_time has value, end_status MUST be 'ExplicitEnd'. "
                "If end_time is null, end_status MUST be one of 'Persisting' | 'DisappearedTimingUnknown' | 'Transitioned'."
            )
        )
    )
    
    @model_validator(mode="after")
    def validate_end_status_consistency(self) -> "PhenotypeTimeInfo":
        """Ensure end_status is consistent with end_time field."""
        if self.end_time is not None and self.end_status != PhenotypeEndStatusEnums.EXPLICIT_END:
            raise ValueError(
                f"When end_time has a value, end_status must be EXPLICIT_END (got {self.end_status})"
            )
        if self.end_time is None and self.end_status == PhenotypeEndStatusEnums.EXPLICIT_END:
            raise ValueError(
                "When end_status is EXPLICIT_END, end_time must have a value (cannot be null)"
            )
        return self
    
class PhenotypesInfo(BaseModel):
    """Organoid phenotype description"""
    phenotype: str = Field(
        description="Morphological description. Include size, shape, surface features. Example: 'Spherical structures 200-300 µm diameter with clear lumen formation'"
    )
    appear_time: PhenotypeTimeInfo = Field(
        description="Time range when phenotype appears."
    )
    identification_method: str = Field(
        description="Identification technique. Example: 'Brightfield microscopy', 'Immunofluorescence', 'Confocal imaging'"
    )
    application: str = Field(
        description="Biological/clinical importance and applications. Example: 'Indicates mature intestinal epithelium for drug absorption studies'"
    )

class ApplicationStrategy(BaseModel):
    """Complete description of one research application with experimental context, model details, methods, and outcomes.
    
    Captures how the organoid/culture system is used (application type), what is being investigated (factor/model),
    how it's analyzed (methods), and what was discovered (results). One ApplicationStrategy per distinct research objective.
    """
    application: str = Field(
        description=(
            "**REQUIRED** The primary research application type for this organoid/culture system. "
            "From a biological research perspective, specify how this culture model is being used or intended to be used in the study. "
            "Common application categories: "
            "- 'disease modeling' - recapitulating disease pathophysiology, studying disease mechanisms "
            "- 'drug screening' - testing therapeutic compounds, dose-response studies, efficacy evaluation "
            "- 'toxicity testing' - assessing drug/chemical safety, hepatotoxicity, nephrotoxicity studies "
            "- 'developmental biology' - studying organogenesis, cell fate determination, lineage tracing "
            "- 'regenerative medicine' - tissue engineering, transplantation research, stem cell therapy "
            "- 'immune response research' - studying host-pathogen interactions, immunotherapy, immune cell recruitment "
            "- 'mechanistic pathway investigation' - signaling pathway analysis, molecular mechanism studies "
            "- 'biomarker discovery' - identifying diagnostic/prognostic markers, therapeutic response predictors "
            "- 'personalized medicine' - patient-derived models for precision therapy selection "
            "CRITICAL: Even for preparatory cultures (e.g., TILs expansion for co-culture experiments), "
            "specify the ultimate experimental application (e.g., 'immune response research' for TILs used in immunotherapy studies). "
            "Do NOT leave this field empty or use vague terms like 'culture' or 'preparation'."
        )
    )
    factor: str = Field(
        description="Research factors investigated. Example: 'EGFR mutation', 'Zika virus infection', 'chemotherapy response'"
    )
    model: str = Field(
        description="Disease/condition modeled. Example: 'Alzheimer disease', 'Colorectal cancer', 'SARS-CoV-2 infection'"
    )
    detect_method: List[str] = Field(
        description="List of Detection/analysis methods. Examples: ['Immunofluorescence', 'RNA-seq', 'qRT-PCR', 'Western blot', 'Mass spectrometry']"
    )
    result_description: str = Field(
        description="Key experimental outcomes for this application. Extract: "
                    "1. Quantitative results with values when available (e.g., 'IC50 = 10 µM', '3-fold increase', '60% cell death'). "
                    "2. Qualitative findings if no numbers given (e.g., 'significant upregulation of inflammatory markers', 'restored barrier function'). "
                    "3. Statistical significance if mentioned (e.g., 'p < 0.05'). "
                    "4. Comparison to controls if relevant (e.g., 'compared to wild-type organoids'). Combine multiple related findings in one sentence if they address same question. Extract from Results section; avoid restating methods."
    )



class MaterialSourceTypeEnums(StrEnumBase):
    """Material source type classification for culture-purpose materials. 
    If the SAME material (same material_name) is used for BOTH organoid core AND co-culture components in the SAME culture system, you MUST create TWO separate entries: one with source_type='organoid' and one with source_type='coculture'. 
    """
    ORGANOID = EnumValue(
        "organoid",
        "Materials for organoid core components (role='organoid_core')."
    )
    COCULTURE = EnumValue(
        "coculture",
        "Materials for co-culture components (immune/stromal/vascular/pericyte/microbial)."
    )
class TechniqueAppliesToEnums(StrEnumBase):
    """
    Decision priority:
    1. Medium/supernatant/sensor/chip readout → whole culture system 
    2. In vivo/mouse/xenograft/host outcomes → in vivo host 
    3. [Default] Organoid assays (sections, lysate, whole-mount) → organoid 
    4. Isolated/sorted co-culture populations → co-culture components 
    5. External assays → primary cell / cell line / tissue slice / explant 
    """
    ORGANOID = EnumValue("organoid", description="Whole organoid, including all core components(organoid core, co-culture components, primary cell, cell line) for one organoid")
    ORGANOID_CORE = EnumValue("organoid core", description="Core components of the organoid excluding co-culture components")
    COCULTURE_COMPONENT = EnumValue("co-culture components", description="Only co-culture components excluding organoid core")
    WHOLE_CULTURE_SYSTEM = EnumValue("whole culture system", description="Entire culture system including multi organoids, for one organoid system using `organoid`.")
    PRIMARY_CELL = EnumValue("primary cell", description="Primary cell component")
    CELL_LINE = EnumValue("cell line", description="Cell line component")
    TISSUE_SLICE_OR_EXPLANT = EnumValue("tissue slice / explant", description="Tissue slice or explant component")
    IN_VIVO_HOST = EnumValue("in vivo host", description="In vivo host e.g., mouse, zebrafish")
    OTHER = EnumValue("Others", description="Others not listed above")

class TechniqueTargetInfo(BaseModel):
    """Standardized target descriptor for any experimental technique entry"""

    scope: TechniqueAppliesToEnums = Field(
        description=(
            TechniqueAppliesToEnums.get_field_description(
                main_desc=("What this technique is applied to. `target_desc` and `target_components` are OPTIONAL and should be provided ONLY when `applies_to` alone is insufficient to avoid ambiguity.")
            )
        )
    )

    target_components: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional component_id(s) from OrganoidBaseInfo.composition, e.g. ['C1'], ['C2','C3']. "
            "Use null when not component-specific or when outside composition."
        )
    )

    target_desc: Optional[str] = Field(
        default='not specified',
        description=(
            "Free-text clarification, e.g. 'tumor core', 'conditioned medium', "
            "'dissociated organoid cells', 'immune compartment'."
        )
    )

class CulturePurposeMaterialTypeEnums(StrEnumBase):
    """Culture-purpose material categories.

    Add/Detele types need to update MAT-RULE-05.
    """
    Medium = "Medium"
    Supplement = "Supplement"
    Growth_Factor = "Growth Factor"
    Small_Molecule = "Small Molecule"
    Antibiotic = "Antibiotic"
    Matrix = "Matrix"
    Coating = "Coating"
    Enzyme = "Enzyme"
    Chelating_Agent = "Chelating Agent"
    Buffer = "Buffer"
    Solvent = "Solvent"
    Dye = "Dye"
    Transfection_Reagent = "Transfection Reagent"
    Infection_Enhancer = "Infection Enhancer"
    Viral_Vector = "Viral Vector"
    Tissue_Equivalent = "Tissue Equivalent"
    Therapeutic_Agent = "Therapeutic Agent"
    Reagent_Kit="Reagent Kit"
    Others = "Others"

class CulturePurposeMaterialInfo(BaseModel):
    source_type: MaterialSourceTypeEnums = Field(
        description=(
            MaterialSourceTypeEnums.get_field_description(
                main_desc=(
                    "Judgment criteria for 'same material': "
                    "1. Same material_name (e.g., 'DMEM/F12', 'EGF', 'B-27 Supplement') "
                    "2. Used in the same culture system (same OrganoidCultureResult) "
                    "3. Even if concentration or purpose differs, create two entries if the material is clearly used for both organoid core and co-culture components "
                    "4. For each entry, record the specific concentration and purpose details relevant to that source_type (organoid or coculture) in the corresponding fields "
                    "Examples: "
                    "- 'organoid': material used for organoid core components only, or primarily for organoid core. "
                    "- 'coculture': material used for co-cultured components only, or primarily for co-culture. "
                    "- If DMEM/F12 is used for both organoid and immune cells in same system: create two entries (one 'organoid', one 'coculture'). "
                    "- If DMEM/F12 is used for organoid core and vascular cells: create two entries (one 'organoid', one 'coculture'). "
                    "- If DMEM/F12 is used for organoid core and pericytes: create two entries (one 'organoid', one 'coculture'). "
                    "IMPORTANT: Do NOT use the literal value 'shared' 'whole culture system' for material `source_type`. The value 'shared' is reserved and allowed for biomarker source types (see `BiomarkerSourceTypeEnums`). "
                    "- If an extractor or post-processing step currently emits a single material record with source_type='shared', canonicalize it by splitting into two records (one with source_type='organoid' and one with source_type='coculture'), copying other fields as appropriate and recording any differing concentration/purpose per entry. "
                    "- This preserves provenance and enables unambiguous indexing of materials in protocol steps."
                )
            )
        )
    )
    
    material_name: str = Field(
        description="ONE specific material name. See [MAT-RULE-05] in KNOWLEDGE for culture-purpose materials by type. "
                    "Examples: 'Matrigel', 'TrypLE', 'Poly-L-lysine', 'Collagen Type I', 'B-27 Supplement', 'EGF'. "
                    "Use exact product name without concentration/batch info. "
                    "SPECIAL FORMAT FOR VIRAL VECTORS: When recording viral vectors with strain/serotype information, "
                    "use format 'Vector_type: Strain/Serotype'. "
                    "Examples: 'Lentivirus: pLKO.1', 'AAV: Serotype 9', 'Adenovirus: Ad5'. "
                    "NOTE: Living microorganisms used as co-culture components (bacteria, fungi, non-vector viruses for disease modeling) "
                    "should NOT be recorded in material_source - record them in OrganoidComponentInfo with appropriate role "
                    "(e.g., role='microbial_co-culture' for pathogen models, microbiome studies). "
                    "See [MAT-RULE-06] in KNOWLEDGE for reporting format (how to format material entries, examples, and indexing rules)."
    )
    material_type: CulturePurposeMaterialTypeEnums = Field(
        description=CulturePurposeMaterialTypeEnums.get_field_description(
            main_desc=(
                "Define: Culture-purpose material category."
                "Common excluded materials (DO NOT record in material_source): "
                "- qPCR/RNA extraction kits, antibodies(antibody), primers → record in ExperimentalMaterialInfo instead. "
                "- Fixatives (PFA, formaldehyde), permeabilization reagents → record in ExperimentalMaterialInfo instead. "
                "- General labware (plates, pipettes) → do not record anywhere. "

                "MICROORGANISMS - CRITICAL DISTINCTION: "
                "- Microorganisms as CO-CULTURE COMPONENTS (living biological partners in the culture system, "
                "  e.g., bacteria for gut microbiome modeling, viruses for infection models, fungi for host-pathogen interaction) → "
                "  DO NOT record in material_source. Record in OrganoidBaseInfo.composition as OrganoidComponentInfo "
                "  with role='microbial_co-culture'. Examples: SARS-CoV-2 for COVID-19 model, Bifidobacterium for microbiome study. "
                "- Microorganisms as FUNCTIONAL TOOLS (gene delivery vectors, infection enhancers) → "
                "  Record in material_source using existing types: material_type='Viral_Vector' (lentivirus, AAV, adenovirus), "
                "  material_type='Infection_Enhancer' (polybrene for enhancing viral transduction), "
                "  material_type='Transfection_Reagent', etc. Examples: Lentivirus-Cas9 vector, AAV-GFP reporter. "

                "THERAPEUTIC AGENTS (explicit handling): "
                "- Therapeutic agents (e.g., monoclonal antibodies, recombinant proteins, small-molecule compounds) that are intentionally APPLIED to the culture as treatments or experimental perturbations SHOULD be recorded in `material_source` with material_type='Therapeutic Agent'. "
                "- When the same compound is also reported as part of a drug screen or test set, it MAY additionally appear in `drug_list`. This is an operational exception to the 'drug screening compounds' exclusion above when the compound's role in the protocol is to act as a culture treatment. "

                "EXPERIMENTAL / POST-PROCESSING REAGENTS: "
                "- Reagents used strictly for downstream assays or post-fixation processing (antibodies for staining, nucleic-acid extraction kits, viability/apoptosis assay reagents, fixatives, permeabilization reagents, barcoding reagents, etc.) are EXCLUDED from `material_source` and MUST be recorded in `ExperimentalMaterialInfo`. "

                "REFERENCE GUIDANCE: "
                "- Culture-purpose materials listed in `material_source` are intended to be referenced from `protocol.steps` using the [n] 1-based indexing convention. Experimental/post-processing reagents recorded in `ExperimentalMaterialInfo` should be referenced in `protocol.steps` by name (no [n]); full details must appear in the ExperimentalMaterialInfo entries. "

                "RULES: "
                "→ See [MAT-RULE-05] in KNOWLEDGE for all type definitions and lists. "
                "→ See [MAT-RULE-02] in KNOWLEDGE for the exclusion checklist. "
                "→ See [MAT-RULE-03] in KNOWLEDGE for the 3-layer decision tree (Temporal/Functional/Persistence boundaries). "
                "→ See [MAT-RULE-01] in KNOWLEDGE for material category definitions and dual vs single recording rules. "
                "→ See [MAT-RULE-06] in KNOWLEDGE for reporting format (field specification, implementation order, and examples). "
            )
        )
    )
    source: str = Field(
        description=(
            "Supplier or preparation source of the material. "
            "Use company or lab name ONLY. "
            "Examples: 'Corning', 'Gibco', 'Sigma-Aldrich', 'R&D Systems', 'prepared in-house'. "
            "Do NOT include catalog or lot numbers here. "
            "Default 'not specified' if not mentioned."
        )
    )

    cat_number: Optional[str] = Field(
        default=None,
        description=(
            "Catalog number (Cat#) of the material provided by the supplier. "
            "Identifies the product model and is stable across batches. "
            "Examples: '356231', '12605010', 'P4707', '236-EG'. "
            "Use None if not reported."
        )
    )

    lot_number: Optional[str] = Field(
        default=None,
        description=(
            "Batch/Lot number of the specific production batch used. "
            "Especially important for materials with batch variability "
            "(e.g., Matrigel, FBS, growth factors). "
            "Examples: 'Lot 8234019', 'Batch 2023-05-15'. "
            "Use None if not reported."
        )
    )
    
    @field_validator('material_name')
    @classmethod
    def validate_name(cls, v):
        if not v or v.strip() == '':
            raise ValueError("material_name cannot be empty")
        return v.strip()

class ExperimentalMaterialInfo(BaseModel):
    material_name: str = Field(
        description=(
            "ONE specific name of the material used in this experimental technique. "
            "CRITICAL DISTINCTION FROM CultureMaterialSourceInfo: "
            "ExperimentalMaterialInfo records materials used EXCLUSIVELY for experimental analysis, detection, or manipulation (e.g., antibodies for immunostaining, dyes for viability assays, drugs for testing, plasmids for transfection). "
            "CultureMaterialSourceInfo records materials that are part of the CULTURE ENVIRONMENT (media, supplements, growth factors, ECM, etc.). "
            "If a material serves BOTH purposes (culture structure AND experimental detection), use this decision rule: "
            "(1) If the material is primarily used to maintain/grow the culture and detection is secondary → record in CultureMaterialSourceInfo. "
            "(2) If the material is primarily used for experimental readout/analysis and culture maintenance is secondary → record in ExperimentalMaterialInfo. "
            "(3) If both purposes are equally important, prefer CultureMaterialSourceInfo if it's part of the culture medium/environment, "
            "otherwise prefer ExperimentalMaterialInfo. "
            "Examples of ExperimentalMaterialInfo: anti-GFAP antibody (for IF), Calcein-AM (for viability), Paclitaxel (for drug testing), "
            "lentivirus vector (for gene delivery), CRISPR sgRNA (for editing)."
        )
    )
    purpose: Optional[str] = Field(default='not specified', description="The purpose and usage of the material. You did your best to extract and search for these pieces of information. ")
    type: Optional[str] = Field(
        default='not specified', 
        description=(
            "Type/category of the experimental material. Provide a clear, specific category label using standard terminology. "
            "COMMON CATEGORIES (use these when applicable, but not limited to): "
            "'Antibody' (detection antibodies for IF/WB/ELISA/flow cytometry), "
            "'Dye' (fluorescent dyes, viability dyes, trackers), "
            "'Drug' (therapeutic compounds for drug testing/screening), "
            "'Chemical Reagent' (chemical compounds, small molecules for experimental treatment), "
            "'Reagent Kit' (commercial assay/extraction/purification kits), "
            "'Plasmid' (plasmid vectors for transfection/expression), "
            "'Viral Vector' (lentivirus, AAV, adenovirus, retrovirus for gene delivery), "
            "'Probe' (nucleic acid probes for FISH/in situ hybridization), "
            "'Primer' (PCR primers for amplification), "
            "'Enzyme' (enzymes for experimental assays, NOT for culture dissociation), "
            "'Nanoparticle' (nanoparticles for delivery/imaging), "
            "'Bead' (magnetic beads, microspheres for separation/assays), "
            "'Resin/Column' (chromatography resin, separation columns), "
            "'Filter/Membrane' (filtration membranes, separation filters). "
            "GUIDELINES: "
            "1. Use specific, standardized category names (capitalize first letter). "
            "2. If a material fits multiple categories, choose the primary experimental function. "
            "3. For novel or specialized materials not listed above, create a concise, descriptive category name (e.g., 'CRISPR Tool', 'Optical Sensor'). "
            "4. Avoid vague terms like 'reagent' alone; be specific (e.g., 'Chemical Reagent' not just 'Reagent'). "
            "5. Default to 'not specified' only if type cannot be determined from the article."
        )
    )

    source: Optional[str] = Field(default='not specified', description="The source of the material, including company name, catalog number, or lab name (e.g., 'MatTek, catalog SOR-300-FT', 'Sigma-Aldrich', 'prepared in-house'). ")

class PrimerPairInfo(BaseModel):
    fwd: str = Field(description="The nucleotide sequence of the forward primer used in PCR amplification. If there is 5' and 3' directionality in original article, please specify. Examples: '5'-AGCTTGACCT...-3'', 'ATCGTAGCTA...'.")
    rev: str = Field(description="The nucleotide sequence of the reverse primer used in PCR amplification. If there is 5' and 3' directionality in original article, please specify. Examples: '5'-TCGATCGTAC...-3'', 'TAGCTAGCTA...'.")

class AntibodyInfo(BaseModel):
    """Minimal antibody info attached to a target (no duplication with materials)."""

    name: StandardizedName = Field(
        description=(
            "Structured antibody name with original article term and standardized target. "
            "src: Copy EXACT antibody name from article (preserve clone, conjugate, host info, punctuation). "
            "std: ALWAYS use StandardizedName STRATEGY B (protein names). "
            "EXTRACTION RULES FOR src: "
            "- Copy exactly as written: 'anti-SOX2', 'anti-pERK1/2 (Thr202/Tyr204)', 'goat anti-mouse IgG (HRP)' "
            "- If ambiguous, mark with '[❓️]' "
            "EXTRACTION RULES FOR std: "
            "- Extract target PROTEIN name (NOT gene symbols). See StandardizedName STRATEGY B for protein naming rules. "
            "- SPECIAL CASE: Secondary antibodies with no specific target → set std=src (e.g., 'goat anti-rabbit IgG (HRP)') "
        )
    )

    host_species: Optional[str] = Field(
        default=None,
        description=(
            "Host species in which the antibody was raised. "
            "EXTRACTION RULES (in priority order): "
            "1. **Direct mention in antibody name**: 'rabbit anti-Lgr5' → host_species='rabbit', 'mouse anti-β-actin' → host_species='mouse' "
            "2. **Inference from secondary antibody**: If primary antibody host not specified but text mentions 'goat anti-rabbit secondary antibody', "
            "   then the primary host is 'rabbit'. Similarly, 'anti-mouse IgG (HRP)' as secondary → primary host is 'mouse' "
            "3. **Common naming patterns**: '[host] anti-[target]', '[host] monoclonal', '[host] polyclonal' "
            "4. **Only use 'not specified'** if none of the above methods can determine the host species "
            "Host species in common name format. Examples: 'rabbit', 'mouse', 'goat', 'rat', 'chicken', 'donkey', 'sheep', 'human' (if humanized)."
        )
    )

    dilution_or_concentration: Optional[str] = Field(
        default=None,
        description="Dilution or concentration used, e.g., '1:500', '1:1000', '2 µg/mL'."
    )

    role: Optional[str] = Field(
        default=None,
        description="Optional: 'primary', 'secondary', 'isotype_control' if explicitly stated."
    )

class SGRNAInfo(BaseModel):
    sequence: str = Field(description="The specific sgRNA sequence used for CRISPR-based editing or modulation. Examples: 'ACCGACGTCA...', 'TCCGATCGAT...'.")
    primers: Optional[List[PrimerPairInfo]] = Field(default=None, description="Primers for sgRNA amplification/cloning. Array format: [{'fwd':'...','rev':'...'}]. Often not reported for standard vector cloning. CRITICAL: If article provides primer sequences, MUST extract them - this is valuable reproducibility information.")

# MolecularModificationInfo
class GeneEditingInfo(BaseModel):
    method: str = Field(description="Name of the editing technique. Examples: CRISPR-Cas9, CRISPR-Cpf1 (Cas12a), Prime Editing, TALEN, ZFN, ABE, CBE, Homologous Recombination.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="What biological entity/system this molecular modification is applied to.")
    genetic_modification: Optional[str] = Field(default='not specified', description="Editing outcome/type. Examples: knockout, knockin, base_edit, correction.")
    gene: str = Field(description="Genes edited by the method. ONlY one gene. Examples: 'TP53' ")
    sgrnas: Optional[List[SGRNAInfo]] = Field(default=None, description="Specific sgRNA sequences or identifiers used for CRISPR-based editing. MUST use array format even for single item: [{'sequence':'...',...}].")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for gene editing delivery. MUST use array format even for single item: [{'material_name':'...',...}].")

# MolecularModificationInfo
class GeneExpressionModulationInfo(BaseModel):
    modulation: str = Field(description="Modulation method. Examples: shRNA, siRNA, miRNA, CRISPRi, CRISPRa, cDNA overexpression, Antisense Oligonucleotides (ASO), CRISPR/Cas9 Knockout,  Viral Transduction.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="What biological entity/system this molecular modification is applied to.")
    delivery: str = Field(description="Delivery method. Examples: Lentivirus, AAV, Retrovirus, Adenovirus, Plasmid Transfection, Lipofection, Electroporation, Direct Treatment.")
    modulation_type: Optional[str] = Field(default='not specified', description="Direction/type of regulation. Examples: overexpression, knockdown, inhibition, activation.")
    gene: str = Field(description="Genes edited by the method. ONlY one gene. Examples: 'TP53' ")
    sgrnas: Optional[List[SGRNAInfo]] = Field(default=None, description="Specific sgRNA sequences or identifiers used for CRISPR-based editing. MUST use array format even for single item: [{'sequence':'...',...}].")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for gene expression modulation delivery. MUST use array format even for single item: [{'material_name':'...',...}].")

class MolecularModificationInfo(BaseModel):
    gene_editings: Optional[List[GeneEditingInfo]] = Field(default=None, description=" List of genome editing entries. MUST use array format even for single item: [{'method':'CRISPR-Cas9',...}].")
    gene_expression_modulations: Optional[List[GeneExpressionModulationInfo]] = Field(default=None, description=" List of expression modulation entries. MUST use array format even for single item: [{'modulation':'shRNA',...}].")

# MultiOmicsInfo    
class TranscriptomicsInfo(BaseModel):
    method: str = Field(description="Transcriptome profiling method. From Enums: [RNA-seq, scRNA-seq, snRNA-seq, Ribo-seq, CITE-seq, Microarray, Other Transcriptomics Methods(Specific Methods)]. No general terms like 'transcriptomics' or 'RNA profiling'.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this molecular analysis (organoid, primary cell, co-culture, etc.).")
    platform: Optional[str] = Field(default='not specified', description="Sequencing/measurement platform or kit. Examples: Illumina NovaSeq, 10x Genomics, BD Rhapsody, NanoString nCounter.")
    target: Optional[str] = Field(default='not specified', description="Biological scope measured. Examples: transcriptome, single-cell transcriptome, nucleus transcriptome.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for transcriptomic profiling. MUST use array format even for single item: [{'material_name':'...',...}].")

# MultiOmicsInfo
class EpigenomicsInfo(BaseModel):
    method: str = Field(description="Epigenome method. Examples: ATAC-seq, scATAC-seq, CUT&RUN, CUT&Tag, ChIP-seq, WGBS, Hi-C, scHi-C.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this molecular analysis (organoid, primary cell, co-culture, etc.).")
    target: Optional[str] = Field(default='not specified', description="Epigenetic layer readout. Examples: chromatin accessibility, histone modification, methylome, 3D chromatin conformation.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for epigenomic profiling. MUST use array format even for single item: [{'material_name':'...',...}].")

# MultiOmicsInfo
class ProteomicsInfo(BaseModel):
    method: str = Field(description="Proteomics method. Examples: LC-MS/MS, AP-MS, DIA, SWATH-MS, TMT labeling, SILAC, phospho-proteomics.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this molecular analysis (organoid, primary cell, co-culture, etc.).")
    target: Optional[str] = Field(default='not specified', description="Protein-level scope. Examples: proteome, phosphoproteome, interactome.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for proteomic profiling. MUST use array format even for single item: [{'material_name':'...',...}].")

# MultiOmicsInfo
class MetabolomicsInfo(BaseModel):
    method: str = Field(description="Metabolomics method. Examples: LC-MS, GC-MS, UPLC-MS, CE-MS, NMR, Mass Spectrometry Imaging (MSI).")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this molecular analysis (organoid, primary cell, co-culture, etc.).")
    target: Optional[str] = Field(default='not specified', description="Metabolite scope/readout. Examples: metabolites, lipid profile, metabolic flux.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for metabolomic profiling. MUST use array format even for single item: [{'material_name':'...',...}].")

# MultiOmicsInfo
class SpatialOmicsInfo(BaseModel):
    method: str = Field(description="Spatial omics method. Examples: Spatial Transcriptomics, 10x Visium, Stereo-seq, MERFISH, seqFISH, CosMx SMI, MALDI-MSI, Slide-seq.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this molecular analysis (organoid, primary cell, co-culture, etc.).")
    platform: Optional[str] = Field(default='not specified', description="Instrument/commercial platform. Examples: BGI Stereo-seq, NanoString GeoMx, Vizgen MERFISH.")
    target: Optional[str] = Field(default='not specified', description="Spatial molecular layer. Examples: spatial transcriptome, spatial proteome, spatial metabolome.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for spatial omics profiling. MUST use array format even for single item: [{'material_name':'...',...}].")

# MultiOmicsInfo
class GenomicsInfo(BaseModel):
    method: str = Field(description="Genomic assay. Examples: WGS, WES, Amplicon-seq, Targeted panel sequencing, Nanopore long-read, SNP array, CNV profiling, mutation analysis.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this molecular analysis (organoid, primary cell, co-culture, etc.).")
    target: Optional[str] = Field(default='not specified', description="Genomic region/variant class. Examples: genome, exome, SNP, CNV, somatic mutations.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for genomic profiling. MUST use array format even for single item: [{'material_name':'...',...}].")

# MultiOmicsInfo
class OtherOmicsInfo(BaseModel):
    method: str = Field(description="Other omics method. Examples: lipidomics, glycomics, acetylomics, ubiquitinomics, interactomics.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this molecular analysis (organoid, primary cell, co-culture, etc.).")
    target: Optional[str] = Field(default='not specified', description="Molecular class analyzed. Examples: lipidome, glycome, acetylome, ubiquitinome, interactome.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for other omics profiling. MUST use array format even for single item: [{'material_name':'...',...}].")


class MultiOmicsInfo(BaseModel):
    transcriptomics: Optional[List[TranscriptomicsInfo]] = Field(default=None, description="List of transcriptomics entries. MUST use array format even for single item: [{'method':'RNA-seq',...}].")
    epigenomics: Optional[List[EpigenomicsInfo]] = Field(default=None, description="List of epigenomics entries. MUST use array format even for single item: [{'method':'ATAC-seq',...}].")
    proteomics: Optional[List[ProteomicsInfo]] = Field(default=None, description="List of proteomics entries. MUST use array format even for single item: [{'method':'LC-MS/MS',...}].")
    metabolomics: Optional[List[MetabolomicsInfo]] = Field(default=None, description="List of metabolomics entries. MUST use array format even for single item: [{'method':'LC-MS',...}].")
    spatial_omics: Optional[List[SpatialOmicsInfo]] = Field(default=None, description="List of spatial omics entries. MUST use array format even for single item: [{'method':'10x Visium',...}].")
    genomics: Optional[List[GenomicsInfo]] = Field(default=None, description="List of genomics entries. MUST use array format even for single item: [{'method':'WGS',...}].")
    others: Optional[List[OtherOmicsInfo]] = Field(default=None, description="List of other omics entries. MUST use array format even for single item: [{'method':'lipidomics',...}].")

class TargetedExpressionTargetInfo(BaseModel):
    target_type: str = Field(
        description=(
            "Role of this target in the assay. Must be ONE of: "
            "- 'Target': Primary analyte of interest (e.g., TP53, Lgr5, STAT3) "
            "- 'Housekeeping': Internal reference/control for normalization. "
            "  * For PCR: housekeeping genes (e.g., GAPDH, ACTB/β-actin, 18S rRNA) "
            "  * For Western blot/immunoassays: loading controls (e.g., β-actin, GAPDH, tubulin, VINCULIN) "
            "EXTRACTION RULE: Create separate TargetedExpressionTargetInfo entries for each target and each housekeeping control. "
            "Do NOT mix them in a single entry."
        )
    )
    name: StandardizedName = Field(
        description=(
            "Structured name of ONE gene/protein quantified. "
            "src: Use EXACT term from article Methods/Results. "
            "std: STRATEGY SELECTION based on detection method: "
            "  - DNA/RNA detection (PCR, qRT-PCR, RNA-seq) → StandardizedName STRATEGY A (gene symbols, species-specific) "
            "  - Protein detection (Western blot, ELISA) → StandardizedName STRATEGY B (protein names) "
            "EXAMPLES (demonstrating method-based selection): "
            "- 'p53' in qRT-PCR → src='p53', std='TP53' (gene, use STRATEGY A) "
            "- 'p53' in Western blot → src='p53', std='p53' (protein, use STRATEGY B) "
            "- 'Gapdh' in qRT-PCR (mouse) → src='Gapdh', std='Gapdh' (mouse gene, STRATEGY A) "
            "- 'GAPDH' in Western blot → src='GAPDH', std='GAPDH' (protein, STRATEGY B) "
        )
    )
    primers: Optional[List[PrimerPairInfo]] = Field(
        default=None,
        description=(
            "Primer sequences for PCR-based amplification of this target. Rules: "
            "1. Include ONLY if method is PCR-based (PCR, qPCR, RT-PCR, qRT-PCR, etc.) AND target is nucleic acid (DNA/RNA). "
            "2. For standard PCR: one pair (forward + reverse). "
            "3. For Nested PCR: two pairs (outer pair + inner pair), create two separate PrimerInfo entries. "
            "4. Copy sequences exactly as written, preserve 5'→3' directionality notation if given. "
            "5. Omit this field if: method is non-PCR (Western blot, ELISA, etc.), OR primers not reported, OR target is protein. "
            "Note: For RT-PCR of RNA targets, DO include primers (they amplify cDNA). "
            "Housekeeping/reference genes follow the same rules as other DNA/RNA targets."
            "CRITICAL: Never put antibodies into primers. "
            "For Western blot / IHC / IF / Flow cytometry / ELISA, primers MUST be null and antibodies should be used instead (if explicitly reported)."
        )
    )
    antibodies: Optional[List[AntibodyInfo]] = Field(
        default=None,
        description=(
            "Antibodies used for antibody-based assays within targeted_expressions "
            "(e.g., Western blot, IHC/IF, Flow cytometry, ELISA). "
            "Use this field instead of primers for protein-level antibody assays. "
            "record dilution_or_concentration when reported (e.g., '1:500'). "
            "Extract ONLY if the article explicitly states antibody names/details; do NOT hallucinate."
        )
    )
    probes: Optional[List[str]] = Field(
        default=None,
        description=(
            "Probe sequence(s) used for this PCR target (e.g., TaqMan or hydrolysis probes) when explicitly reported. "
            "MUST use array format even for a single item: ['probe_seq1', 'probe_seq2']. "
            "Record each nucleotide sequence exactly as written in the article, including any 5'/3' labels or dyes if present "
            "(e.g., \"5'-FAM-ACCTGCTGCTG-3'-BHQ1\"). "
            "At most one PCR assay configuration (set of probes) should be represented in each TargetedExpressionTargetInfo entry; "
            "if the article reports clearly distinct probe sets for different assays or channels, represent them as separate "
            "TargetedExpressionTargetInfo entries. If no probe is used or reported for this target, omit this field."
        )
    )

# MolecularAnalysisInfo
class TargetedExpressionInfo(BaseModel):
    method: str = Field(description="Targeted detection method. Examples: PCR series(Specify the exact type), Western blot, Immunoblot, Dot blot, ELISA, NanoString nCounter, qPCR array, Flow cytometry.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this molecular analysis (organoid, primary cell, co-culture, etc.).")
    target: Optional[List[TargetedExpressionTargetInfo]] = Field(
        default=None,
        description=(
            "Targets quantified (genes/proteins). MUST use array format even for single item. "
            "Choose fields based on `method`: "
            "1) PCR-series (PCR/qPCR/RT-PCR/qRT-PCR): use `primers` and optionally `probes` when explicitly reported. "
            "   Example: [{'target_type':'Target','name':'TP53','primers':[{'fwd':'...','rev':'...'}],'probes':[\"5'-FAM-...-3'-BHQ1\"]}] "
            "2) Antibody-based protein assays (Western blot / IHC/IF / Flow cytometry / ELISA): use `antibodies` and keep `primers`/`probes` null. "
            "   Example: [{'target_type':'Target','name':'SOX2','antibodies':[{'name':'anti-SOX2','dilution_or_concentration':'1:500','role':'primary'}]}] "
            "CRITICAL: Do NOT put antibodies into `primers` or `probes`."
        )
    )
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for targeted expression analysis. MUST use array format even for single item: [{'material_name':'...',...}].")

class MolecularAnalysisInfo(BaseModel):
    multi_omics: Optional[MultiOmicsInfo] = Field(default=None, description="Omics profiling across transcriptomic, epigenomic, proteomic, metabolomic, spatial, genomic, and others.")
    targeted_expressions: Optional[List[TargetedExpressionInfo]] = Field(default=None, description="List of targeted validation entries. MUST use array format even for single item: [{'method':'qRT-PCR',...}].")


# CellularImagingInfo
class MicroscopyInfo(BaseModel):
    method: str = Field(description="Microscopy technique. Examples: Bright-field, Fluorescence, Confocal, Two-photon, Light-sheet, SIM, STED, SEM, TEM.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this imaging assay.")
    target: Optional[str] = Field(default='not specified', description="Structure/feature imaged. Examples: neuronal morphology, synapses, cilia, lumen, organoid polarity.")
    equipment_type: Optional[str] = Field(default='not specified', description="Imaging device class. Examples: confocal microscope, light-sheet microscope, super-resolution microscope, electron microscope.")
    device: Optional[str] = Field(default='not specified', description="Specific instrument/device brand/model. Examples: Zeiss LSM 980, Leica TCS SP8, Nikon A1R, Olympus FV3000.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for microscopy imaging. MUST use array format even for single item: [{'material_name':'...',...}].")

# CellularImagingInfo
class LiveCellTimeLapseInfo(BaseModel):
    method: str = Field(description="Live-cell/time-lapse technique. Examples: Ca2+ imaging (Fluo-4, GCaMP), Voltage imaging, FUCCI tracking, CellTracker, Time-lapse fluorescence.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this imaging assay.")
    duration: Optional[str] = Field(default='not specified', description="Imaging duration/frequency. Examples: '48h', '1 frame/5min'.")
    equipment_type: Optional[str] = Field(default='not specified', description="Imaging device class. Examples: inverted fluorescence microscope, spinning-disk confocal microscope.")
    device: Optional[str] = Field(default='not specified', description="Specific instrument/device brand/model. Examples: Nikon Ti2-E, Olympus IX83, Zeiss LSM 880, Leica DMi8.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for live-cell/time-lapse imaging. MUST use array format even for single item: [{'material_name':'...',...}].")

# CellularImagingInfo
class HistologyImmunostainingInfo(BaseModel):
    method: str = Field(description="Staining method. Examples: Immunofluorescence (IF), IHC, FISH, RNAscope, HCR, Multiplex IF (mIF), H&E.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this imaging assay.")
    antibodies: Optional[List[AntibodyInfo]] = Field(
        default=None,
        description=(
            "Antibodies used in this staining method. "
            "Record dilution_or_concentration and role when explicitly reported. "
            "If the paper only says 'incubated with antibodies' without names → omit. "
            "Do NOT hallucinate antibody identities."
        )
    )
    probes: Optional[List[str]] = Field(default=None, description="Probes other than antibodies used. MUST use array format even for single item: ['ProbeName1','ProbeName2']. No use 'ProbeName' as value, it just an example.")
    equipment_type: Optional[str] = Field(default='not specified', description="Imaging device class. Examples: slide scanner, fluorescence microscope, multiphoton microscope.")
    device: Optional[str] = Field(default='not specified', description="Specific instrument/device brand/model. Examples: Hamamatsu NanoZoomer S360, Leica DM6 B, Zeiss Axioscan, Olympus VS200.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for histology/immunostaining imaging. MUST use array format even for single item: [{'material_name':'...',...}].")

class CellularImagingInfo(BaseModel):
    microscopies: Optional[List[MicroscopyInfo]] = Field(default=None, description="List of microscopy entries. MUST use array format even for single item: [{'method':'Confocal',...}].")
    live_cell_or_time_lapses: Optional[List[LiveCellTimeLapseInfo]] = Field(default=None, description="List of live-cell imaging entries. MUST use array format even for single item: [{'method':'Ca2+ imaging',...}].")
    histology_immunostainings: Optional[List[HistologyImmunostainingInfo]] = Field(default=None, description="List of histology/immunostaining entries. MUST use array format even for single item: [{'method':'IF',...}].")

# BiophysicalChemicalAnalysisInfo
class SpectroscopyInfo(BaseModel):
    method: str = Field(description="Spectroscopic method. Examples: FRET, SPR, DLS, Raman spectroscopy, ITC, Circular Dichroism (CD), UV-Vis, FLIM.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this biophysical/chemical analysis.")
    target: Optional[str] = Field(default='not specified', description="Property measured. Examples: protein-protein interaction, ligand binding kinetics, particle size, folding stability.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for spectroscopy analysis. MUST use array format even for single item: [{'material_name':'...',...}].")

# BiophysicalChemicalAnalysisInfo
class StructuralBiologyInfo(BaseModel):
    method: str = Field(description="Structure determination method. Examples: Cryo-EM, Cryo-ET, X-ray Crystallography, NMR spectroscopy, AFM, SAXS.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this biophysical/chemical analysis.")
    target: Optional[str] = Field(default='not specified', description="Structural entity analyzed. Examples: protein complex, enzyme structure, supramolecular assembly.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for structural biology analysis. MUST use array format even for single item: [{'material_name':'...',...}].")

class BiophysicalChemicalAnalysisInfo(BaseModel):
    spectroscopies: Optional[List[SpectroscopyInfo]] = Field(default=None, description="List of spectroscopy entries. MUST use array format even for single item: [{'method':'FRET',...}].")
    structural_biologies: Optional[List[StructuralBiologyInfo]] = Field(default=None, description="List of structural biology entries. MUST use array format even for single item: [{'method':'Cryo-EM',...}].")

# InVivoModelsInfo
class XenograftInfo(BaseModel):
    model_type: str = Field(description="Xenograft class. Examples: PDX, PDOX, ODX, Subrenal capsule, Humanized mouse, Zebrafish xenograft, CAM (chorioallantoic membrane).")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="What is being implanted or assessed (organoid, cells, or host-level readout).")
    host_species: Optional[str] = Field(default='not specified', description="Host species in scientific (Latin) name. Examples: Mus musculus, Rattus norvegicus, Danio rerio, Gallus gallus, Homo sapiens (if humanized).")
    implantation_site: Optional[str] = Field(default='not specified', description="Anatomical site of implantation. Examples: subcutaneous, orthotopic (brain), renal capsule, liver, CAM.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for xenograft model establishment. MUST use array format even for single item: [{'material_name':'...',...}].")

# InVivoModelsInfo
class TransplantationImplantationInfo(BaseModel):
    method: str = Field(description="Transplantation/implantation procedure. Examples: intracerebral transplantation, subcutaneous implantation, intrahepatic, intraperitoneal, orthotopic.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="What is being implanted or assessed (organoid, cells, or host-level readout).")
    recipient: Optional[str] = Field(default='not specified', description="Anatomical target/organ of transplantation. Examples: cortex, kidney capsule, liver.")
    recipient_species: Optional[str] = Field(default='not specified', description="Host species receiving the graft (Latin name). Examples: Mus musculus, Rattus norvegicus, Danio rerio, Gallus gallus.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for transplantation/implantation procedure. MUST use array format even for single item: [{'material_name':'...',...}].")

class InVivoModelsInfo(BaseModel):
    xenografts: Optional[List[XenograftInfo]] = Field(default=None, description="List of xenograft entries. MUST use array format even for single item: [{'model_type':'PDX',...}].")
    transplantation_or_implantations: Optional[List[TransplantationImplantationInfo]] = Field(default=None, description="List of transplantation entries. MUST use array format even for single item: [{'method':'intracerebral transplantation',...}].")

# FunctionalAuxiliarySystemsInfo
class FunctionalElectrophysiologyInfo(BaseModel):
    method: str = Field(description="Electrophysiology assay. Examples: Patch-clamp, Multi-electrode array (MEA), Field potential recording, Whole-cell recording.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this functional or auxiliary assay.")
    equipment_type: Optional[str] = Field(default='not specified', description="Instrument/Device class used. Examples: patch amplifier, MEA system, microelectrode setup.")
    device: Optional[str] = Field(default='not specified', description="Instrument/Device brand/model. Examples: Axon MultiClamp 700B, HEKA EPC10, Axion Maestro Pro, MCS MEA2100.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for electrophysiology analysis. MUST use array format even for single item: [{'material_name':'...',...}].")

# FunctionalAuxiliarySystemsInfo
class CytometrySortingInfo(BaseModel):
    method: str = Field(description="Cytometry/sorting technique. Examples: Flow cytometry, Spectral cytometry, CyTOF, FACS, MACS.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this functional or auxiliary assay.")
    panels: Optional[List[str]] = Field(default=None, description="Antibody/marker panel used. MUST use array format: ['CD45','EpCAM','CD133'].")
    equipment_type: Optional[str] = Field(default='not specified', description="Instrument/Device class. Examples: flow cytometer, mass cytometer, cell sorter.")
    device: Optional[str] = Field(default='not specified', description="Instrument/Device model. Examples: BD FACSymphony, Cytek Aurora, Sony MA900, Fluidigm Helios.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for cytometry/sorting analysis. MUST use array format even for single item: [{'material_name':'...',...}].")

# FunctionalAuxiliarySystemsInfo
class LineageTracingBarcodingInfo(BaseModel):
    method: str = Field(description="Tracing/barcoding approach. Examples: scGESTALT, LINNAEUS, Viral barcoding, Mitochondrial lineage tracing.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this functional or auxiliary assay.")
    barcode_strategy: Optional[str] = Field(default='not specified', description="Barcode encoding mechanism. Examples: CRISPR editing barcode, lentiviral barcode, Cre-lox recombination.")
    readout: Optional[str] = Field(default='not specified', description="Detection/decoding readout. Examples: scRNA-seq integration, amplicon-seq, whole-genome sequencing.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for lineage tracing/barcoding analysis. MUST use array format even for single item: [{'material_name':'...',...}].")

# FunctionalAuxiliarySystemsInfo
class ScreeningInfo(BaseModel):
    method: str = Field(description="Screen type. Examples: CRISPR screen, RNAi screen, Small-molecule screen, Epigenetic screen.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this functional or auxiliary assay.")
    library: Optional[str] = Field(default='not specified', description="Library/panel used. Examples: GeCKO, Brunello, drug panel (N=500).")
    readout: Optional[str] = Field(default='not specified', description="Primary readout. Examples: viability, imaging HCA, sequencing readout.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for screening analysis. MUST use array format even for single item: [{'material_name':'...',...}].")

# FunctionalAuxiliarySystemsInfo
class QualityControlAuthenticationInfo(BaseModel):
    method: str = Field(description="QC/authentication test. Examples: Mycoplasma test, Karyotyping (G-banding), STR profiling, Array CGH.")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description="Target system for this functional or auxiliary assay.")
    result: Optional[str] = Field(default='not specified', description="Reported result/outcome. Examples: negative, normal karyotype, chromosomal gain.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for QC/authentication analysis. MUST use array format even for single item: [{'material_name':'...',...}].")

class FunctionalAuxiliarySystemsInfo(BaseModel):
    functional_electrophysiologies: Optional[List[FunctionalElectrophysiologyInfo]] = Field(default=None, description="List of electrophysiology entries. MUST use array format even for single item: [{'method':'Patch-clamp',...}].")
    cytometry_and_sortings: Optional[List[CytometrySortingInfo]] = Field(default=None, description="List of cytometry/sorting entries. MUST use array format even for single item: [{'method':'Flow cytometry',...}].")
    lineage_tracing_and_barcodings: Optional[List[LineageTracingBarcodingInfo]] = Field(default=None, description="List of lineage/barcoding entries. MUST use array format even for single item: [{'method':'scGESTALT',...}].")
    screenings: Optional[List[ScreeningInfo]] = Field(default=None, description="List of screening entries. MUST use array format even for single item: [{'method':'CRISPR screen',...}].")
    quality_control_and_authentications: Optional[List[QualityControlAuthenticationInfo]] = Field(default=None, description="List of QC entries. MUST use array format even for single item: [{'method':'Mycoplasma test',...}].")

class OtherTechniqueInfo(BaseModel):
    method: str = Field(description="Technique name. Examples: Click chemistry, ATP assay, Organoid-on-chip, Microfluidics perfusion, Co-culture system, Reporter assay, Optogenetics, Chemogenetics (DREADDs).")
    applies_to: Optional[TechniqueTargetInfo] = Field(default=None, description=("What biological entity/system this cross-domain technique is applied to. Required for chip systems, perfusion, sensors, organoid engineering, etc."))
    category: Optional[str] = Field(default='not specified', description="Optional subcategory label for organization. Examples: chemical_labeling, metabolic_activity_assay, opto_chemo_modulation, organoid_engineering.")
    application: Optional[str] = Field(default='not specified', description="Experimental purpose/readout. Examples: metabolic labeling, cell viability, luminescence quantification, high-content imaging (HCA), luciferase reporter, light/ligand-induced activation.")
    materials: Optional[List[ExperimentalMaterialInfo]] = Field(default=None, description="[List of ExperimentalMaterialInfo Object] Materials used for Others technique. MUST use array format even for single item: [{'material_name':'...',...}].")

    
class OmicsIdInfo(BaseModel):
    """Omics data repository information"""
    omics_type: str = Field(
        description="Omics type. Examples: 'Transcriptomics', 'Genomics', 'Proteomics', 'Metabolomics', 'Epigenomics', 'Spatial Omics', 'Other Omics'"
    )
    omics_subtype: Optional[str] = Field(default='not specified', description="Provide ONLY the technology/method type, no additional info. This information can usually be found in the summary, overall design, and Platforms description sections of the data record. Examples: "
                    "Transcriptomics from: [Microarray, RNA-seq, scRNA-seq]; "
                    "Genomics from: [WES, WGS]; "
                    "Proteomics from: [Shotgun Proteomics, Quantitative Proteomics, Top-down Proteomics, LC-MS]; "
                    "Metabolomics from: [Targeted Metabolomics, Untargeted Metabolomics, NMR, LC-MS, GC-MS]; "
                    "Epigenomics from: [ChIP-seq, ATAC-seq, WGBS, RRBS, Histone modification]; "
                    "Spatial Omics from: [Spatial Transcriptomics, Spatial Proteomics, 10x Visium, MERFISH, Imaging Mass Cytometry (IMC)]"
                    "Lipidomics, Glycomics, Interactomics and so on from: [Specific Methods in original data record]"
    )
    omics_id: str = Field(
        description="Database accession ID. Examples: 'GSE123456', 'SRR123456', 'E-MTAB-1234'."
    )
    db: str = Field(
        description="Database name. Must be real. Examples: 'GEO', 'SRA', 'ArrayExpress', 'MetaboLights', 'PRIDE', dbGaP', 'EMBL-EBI', 'NCBI'"
    )
    

class OrganoidCultureInfo(BaseModel):
    #  === UNIFIED CULTURE DATA (REQUIRED) ===
    biomarker: Optional[List[BiomarkerItemInfo]] = Field(
        default_factory=list,
        description=(
            "All detected biomarkers for organoid and co-culture systems. ONE molecule per item. "
            f"Use source_type field to distinguish: {[e.value for e in BiomarkerSourceTypeEnums]}. "
            "Split lists. Sort by detect_time ascending. Cannot be empty. "
            "For co-culture biomarkers (source_type='coculture' or 'shared'), co_culture_type is required."
        )
    )

    culture_time_organoid: Optional[DurationRangeInfo] = Field(
        default=None,
        description=(
            "Total organoid culture duration (time span) in DurationRangeInfo format. See RULE 1 for semantic distinction between time points vs durations. "
            "Represents HOW LONG the culture lasted, NOT when it started/ended. "
            "**Exact durations:** set min_value=max_value (e.g., '10 days' → min=max=10, unit='days'). "
            "**Range durations:** set bounds (e.g., 'cultured for 7-14 days' → min=7, max=14, unit='days'). "
            "**Provenance tracking:** "
            "- is_original=True: Article explicitly states duration (e.g., 'cultured for 10 days', 'from day 0 to day 10'). "
            "  Provide source_text with exact quote. "
            "- is_original=False: Duration calculated from time_axis anchor endpoints or inferred from protocol context. "
            "  Omit source_text. "
            "**RELATIONSHIP WITH time_axis**: This duration serves as ground truth when explicitly stated (is_original=True). "
            "It may differ from sum of Main branch segment durations due to incomplete protocol descriptions or implicit steps. "
            "Validators may warn about discrepancies but should NOT fail validation. "
            "**null (field omitted):** Total duration unknown AND cannot be reliably inferred from time_axis. "
            "Document reasoning in puzzles when setting null despite having time_axis data."
        )
    )

    @field_validator("culture_time_organoid", mode="before")
    @classmethod
    def _coerce_culture_time_organoid(cls, v):
        """Backward-compatible validator for culture_time_organoid.
        
        Supports legacy formats:
        - int (old format) → DurationRangeInfo with is_original=False
        - TimeRangeNodeInfo (mistakenly used) → convert to DurationRangeInfo with is_original=False
        - dict without is_original → add is_original=False
        - dict with is_original → keep as-is
        """
        # Handle null
        if v is None:
            return None
        
        # Already DurationRangeInfo instance
        if isinstance(v, DurationRangeInfo):
            return v
        
        # Legacy TimeRangeNodeInfo (semantic error, but support migration)
        if isinstance(v, TimeRangeNodeInfo):
            return {
                "min_value": v.min_value,
                "min_time_unit": v.min_time_unit,
                "max_value": v.max_value,
                "max_time_unit": v.max_time_unit,
                "is_original": False,  # legacy = inferred
                "source_text": None
            }
        
        # Legacy int → assume inferred duration in days
        if isinstance(v, int):
            return {
                "min_value": v,
                "min_time_unit": "days",
                "max_value": v,
                "max_time_unit": "days",
                "is_original": False,
                "source_text": None
            }
        
        if isinstance(v, dict):
            # New format with is_original → use as-is
            if "is_original" in v:
                return v
            
            # Legacy format: has min/max/units but no is_original
            # Add is_original=False (old data = inferred)
            if all(k in v for k in ("min_value", "min_time_unit", "max_value", "max_time_unit")):
                return {**v, "is_original": False, "source_text": None}
            
            # Legacy OLD shared unit: {"min_value":14,"max_value":16,"time_unit":"days"}
            if all(k in v for k in ("min_value", "max_value", "time_unit")):
                u = v["time_unit"]
                return {
                    "min_value": v["min_value"],
                    "min_time_unit": u,
                    "max_value": v["max_value"],
                    "max_time_unit": u,
                    "is_original": False,
                    "source_text": None
                }
            
            # dict has min/max but no unit → default days
            if "min_value" in v and "max_value" in v:
                return {
                    "min_value": v["min_value"],
                    "min_time_unit": "days",
                    "max_value": v["max_value"],
                    "max_time_unit": "days",
                    "is_original": False,
                    "source_text": None
                }
        
        return v


    culture_time_coculture: Optional[DurationRangeInfo] = Field(
        default=None,  # null if not co-culture
        description=(
            "[REQUIRED IF co-culture] Total co-culture duration (time span) across all active co-culture period(s). See RULE 1 for semantic distinction between time points vs durations. "
            "Represents HOW LONG the co-culture lasted, NOT when it started/ended. "
            "Sub-day durations allowed (e.g., '2 hours' → min=max=2, min_time_unit=max_time_unit='hours'). "
            "**Provenance tracking:** "
            "- is_original=True: Article explicitly states co-culture duration (e.g., 'co-cultured for 48 hours', 'immune cells added on day 7 and maintained until day 14'). "
            "  Provide source_text with exact quote. "
            "- is_original=False: Duration calculated from time_axis branch merge/split anchor timepoints. "
            "  Omit source_text. "
            "**RELATIONSHIP WITH time_axis**: This duration serves as ground truth when explicitly stated. "
            "May differ from calculated co-culture branch duration due to protocol ambiguities. "
            "**null (field omitted):** ONLY when system is NOT co-culture (if_co_culture=False). "
            "If co-culture exists but duration unknown, compute from time_axis or document limitation in puzzles."
        )
    )

    @field_validator("culture_time_coculture", mode="before")
    @classmethod
    def _coerce_culture_time_coculture(cls, v):
        """Backward-compatible validator for culture_time_coculture.
        
        Same logic as culture_time_organoid validator.
        """
        # Handle null (not co-culture)
        if v is None:
            return None
        
        # Already DurationRangeInfo instance
        if isinstance(v, DurationRangeInfo):
            return v
        
        # Legacy TimeRangeNodeInfo (semantic error, but support migration)
        if isinstance(v, TimeRangeNodeInfo):
            return {
                "min_value": v.min_value,
                "min_time_unit": v.min_time_unit,
                "max_value": v.max_value,
                "max_time_unit": v.max_time_unit,
                "is_original": False,
                "source_text": None
            }
        
        # Legacy int → assume inferred duration
        if isinstance(v, int):
            return {
                "min_value": v,
                "min_time_unit": "days",
                "max_value": v,
                "max_time_unit": "days",
                "is_original": False,
                "source_text": None
            }
        
        if isinstance(v, dict):
            # New format with is_original
            if "is_original" in v:
                return v
            
            # Legacy format: add is_original=False
            if all(k in v for k in ("min_value", "min_time_unit", "max_value", "max_time_unit")):
                return {**v, "is_original": False, "source_text": None}
            
            # Legacy shared unit format
            if all(k in v for k in ("min_value", "max_value", "time_unit")):
                u = v["time_unit"]
                return {
                    "min_value": v["min_value"],
                    "min_time_unit": u,
                    "max_value": v["max_value"],
                    "max_time_unit": u,
                    "is_original": False,
                    "source_text": None
                }
            
            # dict with min/max but no unit
            if "min_value" in v and "max_value" in v:
                return {
                    "min_value": v["min_value"],
                    "min_time_unit": "days",
                    "max_value": v["max_value"],
                    "max_time_unit": "days",
                    "is_original": False,
                    "source_text": None
                }
        
        return v
    
    culture_technique: Optional[CultureTechniqueInfo] = Field(default=None, description="Culture technique classification.")

    #  === CO-CULTURE SPECIFIC DATA (CONDITIONAL) ===
    culture_technique_coculture: Optional[str] = Field(
        default=None,  # null if not co-culture
        description=(
            "[REQUIRED IF co-culture] Co-culture technique name. If not co-culture, leave as null. IF co-culture, provide specific technique used. "
            "Examples: 'Direct co-culture', 'Transwell System', 'Microfluidic co-culture', 'Organoid-on-chip', '3D bioprinting-based co-culture'. "
            "If co-culture but technique not specified, use 'not specified'. "
        )
    )
    
    # === MATERIALS & SOURCES (References - Define BEFORE protocol steps) ===
    material_source: List[CulturePurposeMaterialInfo] = Field(
        default_factory=list,
        description=(
            "Culture materials -> material_source: List[CulturePurposeMaterialInfo]."
            "Experimental/detection materials → ExperimentalMaterialInfo Object. "
            "Drug screening → drug_list. "
            
            "CRITICAL WORKFLOW (Reference Mechanism): "
            "List ALL culture materials HERE FIRST, THEN reference in protocol steps using [n]. "
            "material_source[0] → [1], material_source[1] → [2] (1-based index, NOT 0-based). "
            "Example: material_source has 3 items → PBS at index 0 is [1], Matrigel at index 1 is [2], TrypLE at index 2 is [3]. "
            "In steps write: 'Washed with PBS[1]', 'Embedded in Matrigel[2]', 'Dissociated using TrypLE[3]'. "
            
            "⚠️ SCOPE: Only materials used DURING culture (before fixation/lysis). "
            "→ See [MAT-RULE-05] in KNOWLEDGE for all type definitions with complete culture-purpose materials lists. "
            "→ See [MAT-RULE-02] in KNOWLEDGE for complete 5-category exclusion checklist. "
            "→ See [MAT-RULE-03] in KNOWLEDGE for 3-layer decision tree (Temporal/Functional/Persistence boundaries). "
            "→ See [MAT-RULE-01] in KNOWLEDGE for material category definitions and dual vs single recording rules. "
            "→ See [MAT-RULE-06] in KNOWLEDGE for reporting format (field specification, implementation order, and examples). "
            
            "Quick check: "
            "- Before fixation + affects microenvironment + remains in culture ✅ "
            "- Post-fixation reagents (antibodies, fixatives) ❌ "
            "- Drug screening compounds ❌ → record in drug_list instead "
            "- Detection kits (qPCR, MTT) ❌ → record in ExperimentalMaterialInfo Object instead "
            
            "Concentration/application_method are recorded in steps text, NOT here. "
            "If concentration not mentioned in text, use prefix '`unknown concentration` of {material}[n]' in steps."

            f"If type of material Not in {[e.value for e in CulturePurposeMaterialTypeEnums]}, omit the entry entirely."
        )
    )
    
    protocol: List[OrganoidCultureStepInfo] = Field(
        min_length=1,
        description=(
            "All culture steps (organoid and co-culture). Use step_scope field to distinguish: "
            "'whole_system' (affects all components), 'organoid_core_only' (organoid only), 'co_culture_only' (co-culture only), 'specific_components' (targeted components). "
            "DO NOT force non-medium/supplements/growth_factors/small_molecules culture-purpose materials into the OrganoidCultureStepInfo (medium, supplements, growth_factors, small_molecules) fields. "
            "CONTINUITY RULES:  "
            "- If the article describes them that way. Do NOT force continuity by merging or splitting steps. "
            "- If the article describes a continuous process but only provides start and end points, create a single step spanning the entire period. "
            "Sorting rules (apply in order): "
            "- 1. Primary sort: by protocol[].during.start_time (ascending) "
            "- 2. If protocol[].during.start_time same: by protocol[].during.end_time (ascending) "
            "- 3. If both same: maintain natural step sequence from article (order of appearance in Methods section, or logical sequence if described in Results) "
        )
    )

    application_strategies: List[ApplicationStrategy] = Field(
        min_length=1,
        description=(
            "**REQUIRED - CANNOT BE EMPTY (min_length=1)** "
            "List of research applications for which this organoid/culture system is utilized in the study. "
            "Every culture system described in a research article MUST have at least one identifiable research application. "
            "**Extraction strategy:** "
            "1. PRIMARY APPLICATION: Identify the main research objective from Introduction/Abstract (e.g., if paper studies immunotherapy, application is 'immune response research'). "
            "2. EXPLICIT APPLICATIONS: Extract applications directly stated in Results/Discussion (e.g., 'used for drug screening', 'disease model for...'). "
            "3. IMPLICIT APPLICATIONS: For preparatory/intermediate cultures, infer from downstream usage: "
            "   - TILs cultured for co-culture experiments → 'immune response research' "
            "   - Organoids used to test drugs → 'drug screening' "
            "   - Patient-derived organoids for therapy selection → 'personalized medicine' "
            "4. MULTIPLE APPLICATIONS: If culture serves multiple purposes, create multiple ApplicationStrategy entries. "
            "**CRITICAL**: This field MUST contain at least one entry. If no explicit application is stated, "
            "infer from the overall study context (paper's main research question). "
            "Common scenarios: mechanistic studies → 'mechanistic pathway investigation'; "
            "disease models → 'disease modeling'; therapy testing → 'drug screening' or 'immunotherapy efficacy evaluation'."
        )
    )
    
    
    # === OPTIONAL METADATA ===
    omics_ids: Optional[List[OmicsIdInfo]] = Field(
        default=None,
        description="Omics data IDs. MUST use array format even for single item: [{'omics_type':'RNA-seq',...}]. GEO IDs MUST be included here if available."
    )
    readout: Optional[str] = Field(default='not specified', description="Experimental results summary. ")

    final_judgement: Optional[str] = Field(default='not specified', description="Success criteria (e.g., '3D structure formation'). ")

    maturity: Optional[str] = Field(default='not specified', description="Maturity indicators. ")

    characteristics: Optional[str] = Field(default='not specified', description="Morphological characteristics emphasizing 3D structure. ")

    functions: Optional[str] = Field(default='not specified', description="Functional characteristics. ")

    disease_model: Optional[str] = Field(default='not specified', description="Disease modeled (full name). ")

    drug_list: Optional[List[DrugListInfo]] = Field(
        default=None,
        description="Drugs tested. MUST use array format even for single item: [{'drug':'Paclitaxel',...}]. "
    )
    infection_list: Optional[List[InfectionListInfo]] = Field(
        default=None,
        description="Experiment-level list of infection or microbial challenge conditions used in this culture."
    )
    phenotypes: Optional[List[PhenotypesInfo]] = Field(
        default=None,
        description="Organoid phenotypes. MUST use array format even for single item: [{'phenotype':'...',...}]. "
    )

    model_config = ConfigDict(extra='forbid')

    # Validate that [REQUIRED IF co-culture] fields are either all null or all filled
    @model_validator(mode='after')
    def check_coculture_fields(self):
        """Validate that co-culture fields are either all filled or all omitted"""
        coculture_fields = {
            'culture_technique_coculture': self.culture_technique_coculture,
            # 'culture_time_coculture': self.culture_time_coculture   # Co-culture time may be empty, meaning time unknown
        }
        all_none = all(field is None for field in coculture_fields.values())
        all_filled = all(field is not None for field in coculture_fields.values())
        if not (all_none or all_filled):
            field_names = ', '.join(coculture_fields.keys())
            raise ValueError(f"All co-culture fields [{field_names}] must be either completely filled or completely omitted in OrganoidCultureInfo.")
        
        # Check biomarker source_type consistency
        has_coculture_biomarker = any(
            b.source_type in [BiomarkerSourceTypeEnums.COCULTURE, BiomarkerSourceTypeEnums.SHARED]
            for b in self.biomarker
        )
        if has_coculture_biomarker and not all_filled:
            raise ValueError(
                "Co-culture biomarkers detected but co-culture fields are not fully filled. "
                "If co-culture biomarkers exist, all co-culture fields must be provided."
            )
        
        # Check material_source source_type consistency
        has_coculture_material = any(
            m.source_type == MaterialSourceTypeEnums.COCULTURE
            for m in self.material_source
        )
        if has_coculture_material and not all_filled:
            raise ValueError(
                "Co-culture materials detected but co-culture fields are not fully filled. "
                "If co-culture materials exist, all co-culture fields must be provided."
            )
        
        # Check protocol step_scope consistency
        # NOTE: Only check co_culture_only steps, NOT whole_system steps
        # whole_system steps can exist even without co-culture (e.g., global medium changes for organoid-only systems)
        # Co-culture status is determined by base_info.if_co_culture, not by step_scope
        has_coculture_step = any(
            step.step_scope == StepScopeEnums.CO_CULTURE_ONLY
            for step in self.protocol
        )
        if has_coculture_step and not all_filled:
            raise ValueError(
                "Co-culture-only steps detected but co-culture fields are not fully filled. "
                "If co_culture_only steps exist, all co-culture fields must be provided."
            )
        
        return self
    
class OrganoidUsedTechnologiesInfo(BaseModel):
    molecular_modification: Optional[MolecularModificationInfo] = Field(default=None, description=f"Technologies that directly modify or regulate genetic/molecular content in cells or organoids. ")
    molecular_analysis: Optional[MolecularAnalysisInfo] = Field(default=None, description=f"Analytical assays at molecular/omics scale to quantify molecules, states, or processes. ")
    cellular_imaging: Optional[CellularImagingInfo] = Field(default=None, description=f"Imaging-based visualization/measurement of cellular, tissue, or organoid morphology and dynamics. ")
    biophysical_or_chemical_analysis: Optional[BiophysicalChemicalAnalysisInfo] = Field(default=None, description=f"Measurements of biophysical, chemical, or structural properties of biomolecules and complexes. ")
    in_vivo_models: Optional[InVivoModelsInfo] = Field(default=None, description=f"Experimental models involving live animal hosts for in vivo assessment of organoids. ")
    functional_and_auxiliary_systems: Optional[FunctionalAuxiliarySystemsInfo] = Field(default=None, description=f"Functional assays and support systems for activity characterization, lineage tracking, screening, and QC (non-omics, non-imaging, non-in vivo). ")
    other_techniques: Optional[List[OtherTechniqueInfo]] = Field(default=None, description=f"Cross-domain/hybrid techniques not reasonably classifiable under any other top-level module. Use ONLY when a technique cannot fit any other module. ")
    model_config = ConfigDict(extra='forbid')
    
class OrganoidCultureResult(BaseModel):
    """Single organoid culture protocol result"""
    base_info: OrganoidBaseInfo = Field(
        description=(
        "Core metadata: model classification, organ mapping, co-culture status. 9 required fields grouped in 3 categories. "
        "SYSTEM CLASSIFICATION: model_category ↔ if_organoid; organoid_model (final model name); composite_role (multi-organ participation). "
        "ORGAN MAPPING: organ (Dict[OrganEnums, List[OrganSystemEnums]]). "
        "CO-CULTURE: if_co_culture ↔ co_culture_type ↔ composition roles. See individual field descriptions for mapping rules. "
        "VALIDATION: if_co_culture=true requires co_culture_type with ≥1 component; co_culture_type fields must match composition cell_type exactly."
        )
    )

    time_anchors: List[TimeAxisAnchorInfo] = Field(
        min_length=1,
        description=(
            "Global list of all timepoint anchors in this culture protocol. "
            "Each anchor has unique id and represents a specific timepoint (action/cell state/morphology milestone). "
            "Anchors are referenced by time_axis branch axes and biomarker fields via TimeAxisAnchorRefInfo."
            "**Three anchor types** (per RULE 26 Anchor Semantic Classification):"
            "1. MILESTONE: Inherent culture stages (seeding, passage, differentiation) - included in Main branch "
            "2. INTERVENTION: Experimental manipulations (drug, co-culture, infection) - Branch merge points "
            "3. OBSERVATION: Detection sampling (qPCR, imaging, detect xxx biomarker, observe xxx phenotype) - never create segments. "
            "**Key requirements**: All ids UNIQUE; fill timing field ONLY when explicitly stated; time can be precise/range/null."
            "**See RULE 26** for complete anchor type definitions, naming conventions, MILESTONE vs INTERVENTION judgment criteria, and day/duration extraction rules."
            "Ensure biomarker.detect_time and phenotype.appear_time reference these anchors correctly."
        )
    )

    time_axis: List[TimeAxisBranchInfo] = Field(
        description=(
            "List of timeline branches (each with ordered time segments in axes field) representing component lifecycles. "
            "**Structure**: List[TimeAxisBranchInfo] ordered with Main branch first: "
            "- Exactly ONE Main branch (is_main=True, branch_name='Main', component_id='C1') "
            "- Optional component-based branches (branch_name='VirusExpansion', component_id='C2', is_main=False) "
            "- Optional treatment branches (branch_name='DrugA', component_id=null, is_main=False) "
            ""
            "**⚠️ Multiple experimental groups (different genetic variants, disease conditions, separate vessels) MUST be split into separate OrganoidCultureResult entries — see ExtractionResult.cultures field for splitting rules.** "
            ""
            "**CRITICAL: axes is the SOLE carrier of temporal order. Anchor IDs are opaque identifiers — lower ID does NOT mean earlier.** "
            "Chronological order is determined exclusively by the axes segment sequence. "
            ""
            "**Per-branch axes requirements (see also TimeAxisBranchInfo.axes field):** "
            "1. **Component-scoped MILESTONE Coverage (MUST)**: Each branch must include ALL MILESTONE anchors belonging to that branch's own component. "
            "   Anchor IDs from OTHER components are irrelevant to this branch and MUST be omitted. "
            "   • Main (C1): Must cover every C1 MILESTONE. May omit C2/C3/… MILESTONEs and all OBSERVATIONs. "
            "   • Component branch (C2): Must cover every C2 MILESTONE. May omit C1/C3/… MILESTONEs and all OBSERVATIONs. "
            "   ❌ WRONG: C1 has MILESTONE anchors id={1,6,3} but Main axes = [1→6] — id=3 (C1 MILESTONE) is missing. "
            "   ✅ CORRECT example (same anchors as above, id=9 is INTERVENTION merge point, id=4/7 are C2 MILESTONEs): "
            "     Main (C1)          : axes = [1→6, 6→3, 3→9]  (id=6 precedes id=3 in narrative order, even though 6>3 numerically) "
            "     VirusExpansion (C2): axes = [4→7, 7→9]        (all C2 MILESTONEs covered; ends at same merge point id=9) "
            "   Both branches converge at INTERVENTION anchor id=9 ('co-culture setup'). "
            "   C2 MILESTONEs {4,7} are absent from Main; C1 MILESTONEs {1,6,3} are absent from VirusExpansion. "
            "2. **Strict Chain Continuity (MUST)**: axes[i].end_anchor.id == axes[i+1].start_anchor.id "
            "   ❌ WRONG: [1→6, 3→9] — gap between 6 and 3 breaks the chain. "
            "   ✅ CORRECT: [1→6, 6→3, 3→9] — unbroken chain A→B→C→D. "
            "3. **No Zero-Length Segments (MUST)**: start_anchor.id MUST NOT equal end_anchor.id. "
            "4. **Adequate Granularity**: Segments ≈ (this branch's MILESTONE anchor count - 1). "
            "   ❌ WRONG: 8 C1 MILESTONE anchors → 2 segments [A1→A2, A2→A8] — 6 milestones unreachable in ordering. "
            "   ✅ CORRECT: 5 C1 MILESTONE anchors → 4 segments [A1→A2, A2→A5, A5→A4, A4→A8]. "
            "5. **OBSERVATION anchors NEVER appear as segment endpoints** in any branch. "
            ""
            "**Main branch requirements** (per RULE 27): "
            "- MUST include ALL MILESTONE anchors for primary organoid (seeding, passages, differentiation, maturation) "
            "- Continues BEYOND merge point to capture post-integration phases "
            "**Component-based branches** (per RULE 27): "
            "- Create ONLY when component has construction process (expansion, activation, culturing) "
            "- Do NOT create for ready-to-use components (commercial stocks, direct addition) "
            "- Branch axes end at merge point (INTERVENTION anchor on Main) "
            "**See RULE 26** for TimeAxisBranchInfo structure and Main vs Branch determination. "
            "**See RULE 27** for complete component-based timeline strategy and Branch creation criteria."
        )
    )

    story: OrganoidCultureInfo = Field(description=f"The Specific and Complete story of culture protocol. not containing 'techologies' field.")
    
    techologies: OrganoidUsedTechnologiesInfo = Field(description=f"The Used technologies information of this culture protocol, the same level as 'story' field.")
    
    model_config = ConfigDict(extra='forbid')
    
    @model_validator(mode='after')
    def validate_time_axis_references(self):
        """Validate time_anchors and time_axis structure:
        1. All anchor ids in time_anchors are unique
        2. Exactly one Main branch (is_main=True)
        3. Main branch must be first in time_axis list
        4. All TimeAxisAnchorRefInfo in branch axes reference valid anchors from time_anchors
        5. Reference names match anchor name fields
        6. Component_id references valid composition components
        7. [NEW] No zero-length segments: start_anchor.id must != end_anchor.id
        8. [NEW] Chain continuity: axes[i].end_anchor.id == axes[i+1].start_anchor.id within each branch
        """
        if self.base_info.if_organoid is False:
            return self  # Skip validation for non-organoid cultures
        # 1. Build anchor lookup: id -> TimeAxisAnchorInfo
        anchors = {}
        for anchor in self.time_anchors:
            if anchor.id in anchors:
                raise ValueError(
                    f"Duplicate anchor id {anchor.id} in time_anchors. All anchor ids must be unique."
                )
            anchors[anchor.id] = anchor

        # 2. Validate exactly one Main branch
        main_branches = [b for b in self.time_axis if b.is_main]
        if len(main_branches) != 1:
            raise ValueError(
                f"Exactly one Main branch required (is_main=True), found {len(main_branches)}. "
                f"Branch names: {[b.branch_name for b in self.time_axis]}"
            )
        
        # 3. Main branch should be first (convention)
        if not self.time_axis[0].is_main:
            raise ValueError(
                f"First branch in time_axis list should be Main branch. "
                f"Found: {self.time_axis[0].branch_name} (is_main={self.time_axis[0].is_main})"
            )

        # 4. Validate component_id references for component-based branches
        if hasattr(self.base_info, 'composition') and self.base_info.composition:
            comp_ids = {comp.component_id for comp in self.base_info.composition}
            for branch in self.time_axis:
                if branch.component_id and branch.component_id not in comp_ids:
                    raise ValueError(
                        f"Branch '{branch.branch_name}' references unknown component_id '{branch.component_id}'. "
                        f"Valid component_ids: {comp_ids}"
                    )

        # 5. Validate all axes segments in all branches
        for branch in self.time_axis:
            if not branch.axes:
                raise ValueError(f"Branch '{branch.branch_name}' has empty axes list")
            
            for i, segment in enumerate(branch.axes):
                # Validate start_anchor reference
                ref_id = segment.start_anchor.id
                if ref_id not in anchors:
                    raise ValueError(
                        f"Branch '{branch.branch_name}' axes[{i}].start_anchor references unknown anchor id {ref_id}"
                    )
                anchor = anchors[ref_id]
                valid_names = [n for n in (anchor.name_action, anchor.name_cell_state, anchor.name_morphology) if n]
                if segment.start_anchor.name not in valid_names:
                    raise ValueError(
                        f"Branch '{branch.branch_name}' axes[{i}].start_anchor (id={ref_id}, name='{segment.start_anchor.name}') "
                        f"does not match any anchor name fields. Valid names: {valid_names}"
                    )
                
                # Validate end_anchor reference
                ref_id = segment.end_anchor.id
                if ref_id not in anchors:
                    raise ValueError(
                        f"Branch '{branch.branch_name}' axes[{i}].end_anchor references unknown anchor id {ref_id}"
                    )
                anchor = anchors[ref_id]
                valid_names = [n for n in (anchor.name_action, anchor.name_cell_state, anchor.name_morphology) if n]
                if segment.end_anchor.name not in valid_names:
                    raise ValueError(
                        f"Branch '{branch.branch_name}' axes[{i}].end_anchor (id={ref_id}, name='{segment.end_anchor.name}') "
                        f"does not match any anchor name fields. Valid names: {valid_names}"
                    )

            # Auto-remove zero-length segments (start_anchor.id == end_anchor.id), print warning
            valid_axes = []
            for j, seg in enumerate(branch.axes):
                if seg.start_anchor.id == seg.end_anchor.id:
                    print(
                        f"[WARNING] Branch '{branch.branch_name}' axes[{j}] is a zero-length segment "
                        f"(start_anchor.id == end_anchor.id == {seg.start_anchor.id}, "
                        f"name='{seg.start_anchor.name}'). Automatically removed."
                    )
                else:
                    valid_axes.append(seg)
            branch.axes = valid_axes

            # After zero-length removal, axes must still have at least 1 valid segment
            if len(branch.axes) == 0:
                all_anchor_ids = list(anchors.keys())
                raise ValueError(
                    f"Branch '{branch.branch_name}' has 0 valid axes after removing zero-length segments. "
                    f"All axes had start_anchor.id == end_anchor.id, which means the LLM failed to build a real timeline chain. "
                    f"Available anchor ids in this culture: {all_anchor_ids}. "
                    f"Fix: axes must form a proper chain connecting at least 2 distinct anchors, e.g. [A→B, B→C]. "
                    f"A single-step protocol (seeding → assay) still needs 1 segment: axes=[seeding_id→assay_id]. "
                    f"Do NOT create axes where start_anchor.id == end_anchor.id."
                )

            # Validate chain continuity within each branch
            # axes[i].end_anchor.id must equal axes[i+1].start_anchor.id
            for i in range(len(branch.axes) - 1):
                end_id = branch.axes[i].end_anchor.id
                next_start_id = branch.axes[i + 1].start_anchor.id
                if end_id != next_start_id:
                    raise ValueError(
                        f"Branch '{branch.branch_name}' axes chain is broken between axes[{i}] and axes[{i+1}]: "
                        f"axes[{i}].end_anchor.id={end_id} ('{branch.axes[i].end_anchor.name}') != "
                        f"axes[{i+1}].start_anchor.id={next_start_id} ('{branch.axes[i+1].start_anchor.name}'). "
                        f"The timeline must form an unbroken chain where each segment's end equals the next segment's start. "
                        f"Fix: either change axes[{i}].end_anchor to id={next_start_id}, or change "
                        f"axes[{i+1}].start_anchor to id={end_id}, or insert a bridging segment "
                        f"[id={end_id}→id={next_start_id}] between them."
                    )

        # 6. Validate TimeAxisAnchorRefInfo in other nested structures (biomarker.detect_time, etc.)
        def _validate_ref(obj, path="root"):
            # Direct reference
            if isinstance(obj, TimeAxisAnchorRefInfo):
                ref_id = obj.id
                if ref_id not in anchors:
                    raise ValueError(f"TimeAxisAnchorRefInfo at {path} references unknown anchor id {ref_id}")
                anchor = anchors[ref_id]
                valid_names = [n for n in (anchor.name_action, anchor.name_cell_state, anchor.name_morphology) if n]
                if obj.name not in valid_names:
                    raise ValueError(
                        f"TimeAxisAnchorRefInfo at {path} (id={ref_id}, name='{obj.name}') "
                        f"does not match any anchor name fields. Valid names: {valid_names}"
                    )
                return

            # Pydantic models (our BaseModel subclass)
            if isinstance(obj, PydanticBaseModel):
                # iterate declared fields to preserve original nested model objects
                for fname in getattr(obj, 'model_fields', {}).keys():
                    try:
                        val = getattr(obj, fname)
                    except Exception:
                        # fallback to model_dump if getattr fails
                        val = obj.model_dump().get(fname)
                    _validate_ref(val, path + f".{fname}")
                return

            # Lists/tuples
            if isinstance(obj, (list, tuple)):
                for i, it in enumerate(obj):
                    _validate_ref(it, path + f"[{i}]")
                return

            # Dicts
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _validate_ref(v, path + f"[{k}]")
                return

            # primitives -> ignore
            return

        # Validate across the common nested containers that may hold TimeAxisAnchorRefInfo
        if self.story is not None:
            _validate_ref(self.story, 'story')

        # Done
        return self

class AuthorInfo(BaseModel):
    name: str = Field(description="Full name of the author.")
    affil_refs: Optional[List[int]] = Field(
        description=(
            "List of 1-based integer indices referencing the institutions listed in the sibling `MetaDataInfo.affiliations` array. "
            "Example: [1] or [1,2,3]. Each integer MUST be >= 1 and correspond to the position of the institution string inside `MetaDataInfo.affiliations`. "
            "If the author has no known affiliation or it cannot be resolved, set this field to an empty list `[]`; do NOT invent institution names here. "
            "Keep institution strings in `MetaDataInfo.affiliations` as the single source of truth for affiliation text."
        )
    )

class MetaDataInfo(BaseModel):
    # article_type: str = Field(description="Article type. Examples: Research Article, Review, Case Report, Letter, Methodology, Short Communication.")
    title: str = Field(description="the title of the article in ORIGINAL_TEXT.")
    doi: str = Field(description="The ORIGINAL article DOI from ORIGINAL_TEXT. Format: must start with '10.'. Use pubmed search to verify title matches DOI. **Never use correction/erratum DOIs here - those belong in correction_notice_dois**.")
    correction_notice_dois: List[str] = Field(
        default_factory=list,
        description=(
            "List of DOIs for CORRECTION/ERRATUM NOTICES published after the original article (e.g., when PubMed search returns 'A correction notice for this article is also available with DOI 10.xxxx'). "
            "**CRITICAL EXTRACTION RULE**: If pubmed search says 'correction notice' or 'erratum' exists, you MUST extract its DOI into this list. Use array format even for single item: ['10.1038/s41418-020-00630-w']. "
            "If no correction exists, keep as empty list []."
        )
    )
    # publication_year:int = Field(description="the publication year of the article in ORIGINAL_TEXT.")
    # journal: str = Field(description="the journal whole name of the article in ORIGINAL_TEXT.")
    # affiliations: Optional[List[str]] = Field(
    #     default=None,
    #     description=(
    #         "Canonical list of affiliation strings (institutions). Author entries reference this list by 1-based indices in `AuthorInfo.affiliations`. "
    #         "Each unique institution should appear once here; order defines the index values used by authors (first item = 1). "
    #         "If affiliation text is not available, omit entries or set to `['not specified']` as appropriate."
    #     )
    # )
    # author:List[AuthorInfo] = Field(
    #     min_length=1,   
    #     description=(
    #         "List of all authors of the article. Must contain at least one author and be ordered by author position in the paper. "
    #         "Each author's `affil_refs` field should be a list of 1-based indices into `MetaDataInfo.affiliations` (e.g. [1] or [1,2])."
    #     )
    # )
    # # validate: Ensure affil_refs in author references valid indices in affiliations
    # @model_validator(mode='after')
    # def validate_author_affiliations(self):
    #     """Validate that author affiliation references are valid indices into affiliations list"""
    #     num_affiliations = len(self.affiliations)
    #     for author in self.author:
    #         if author.affil_refs is None:
    #             continue  # No affiliations for this author
    #         for ref in author.affil_refs:
    #             if ref < 1 or ref > num_affiliations:
    #                 raise ValueError(
    #                     f"Author '{author.name}' has invalid affiliation reference `{ref}`. Must be between 1 and {num_affiliations}."
    #                 )
    #     return self

class PuzzledSourceEnums(StrEnumBase):
    """Puzzle source classification (based on responsibility attribution)"""
    Source = EnumValue("Source", "Data source issue (original text + review + PDF conversion, LLM cannot distinguish responsibility). markdown data quality (author/reviewer/conversion) and marked with [❓️];")              
    TaskRules = EnumValue("Task Rules", "Task rules (global rules + disambiguation strategy + conflict resolution)")
    FieldDoc = EnumValue("Field Doc", "Field documentation (single field description + examples + default values)")
    Validation = EnumValue("Validation", "Validation specification (data type + format + enum values + constraints + validator)")
    Structure = EnumValue("Structure", "Structure design (hierarchy + field ownership + information architecture)")
    Anomaly = EnumValue("Anomaly", "Data anomaly (suspicious raw data marked with [❓]), ONLY suspicious original data wrong and marked with [❓️]")

class PuzzleSeverityEnums(StrEnumBase):
    """Severity level for puzzle impact on work quality"""
    Blocking = "Blocking"  # Cannot proceed or must guess randomly
    Degrading = "Degrading"  # Can proceed but result quality degraded
    Inconvenient = "Inconvenient"  # Minor friction, result quality unaffected

class PuzzleFixTypeEnums(StrEnumBase):
    """Type of fix needed to resolve puzzle"""
    AddDetail = "Add Detail"  # Add missing information/examples
    Clarify = "Clarify"  # Resolve ambiguity/contradiction
    DocClarify = "Doc Clarify"  # Improve field documentation
    Restructure = "Restructure"  # Change schema structure
    RuleRevise = "Rule Revise"  # Update global extraction rules
    Remove = "Remove"  # Delete conflicting/unnecessary element
    EnumExpand = "EnumExpand"  # Add new enum values

class WorkingPuzzledInfo(BaseModel):
    """Agent self-reported confusion during extraction for schema improvement"""
    source: PuzzledSourceEnums = Field(description=PuzzledSourceEnums.get_field_description())

    source_desc: List[str] = Field(
        min_length=1,
        description="Specific location identifiers. Each string should be limited to a maximum of 100 characters; if longer, truncate and append '...'. Examples: "
                    "Source: ['Methods section paragraph 2']; "
                    "TaskRules: ['RULE 20: GLOBAL EXTRACTION RULES', 'RULE 19: PCR_INTERPRETATION']; "
                    "FieldDoc: ['OrganoidCultureStepInfo.medium']; "
                    "Validation: ['Gender enum values', 'concentration format rule']; "
                    "Structure: ['biomarker vs protocol relationship']; "
                    "Anomaly: ['biomarker[0].biomarker_name', 'MaterialSourceOrganoidInfo[2].concentration']."
    )

    severity: PuzzleSeverityEnums = Field(
        description=f"Impact level. Select ONE from: {[e.value for e in PuzzleSeverityEnums]}. "
                    "Blocking = cannot complete task without guessing; "
                    "Degrading = can proceed but accuracy/completeness reduced; "
                    "Inconvenient = minor friction only."
    )
    puzzle_reason: str = Field(
        description="Each string should be limited to a maximum of 100 characters; if longer, truncate and append '...'. Root cause description. Be specific. Examples: "
                    "'Field description says exclude supplements but example includes B-27', "
                    "'Cannot determine if Matrigel goes to medium or material_source'. "
                    "If confused by biological concepts/terminology, explicitly state what you don't understand "
                    "(e.g., 'Unsure if TUBB3 and TUJ1 are same protein', 'Don't know typical EGF concentration range')."
    )
    fix_type: str = Field(
        description=f"Recommended fix category. Examples: {[e.value for e in PuzzleFixTypeEnums]}."
    )
    fix_target: str = Field(
        description="Each string should be limited to a maximum of 100 characters; if longer, truncate and append '...'. What to fix. Examples: "
                    "'OrganoidCultureStepInfo.medium description', "
                    "'`RULE 1: TIME EXTRACTION` priority 2 definition', "
                    "'Relationship between material_source and protocol steps growth_factors'."
    )
    fix_action: str = Field(
        description="Each string should be limited to a maximum of 100 characters; if longer, truncate and append '...'. Specific actionable fix. Examples: "
                    "'Add counter-example: Matrigel as embedding goes to material_source, not medium', "
                    "'Clarify Day 0 rule: if seeding + Matrigel in same step, that IS Day 0', "
                    "'Add new enum MaterialUsageContext to distinguish culture vs experimental materials'."
    )

class ExtractionResult(BaseModel):
    """Root model for all extracted organoid culture protocols"""
    meta: MetaDataInfo = Field(
        description="Metadata about the source article."
    )
    is_extractable: bool = Field(
        default=True,
        description=(
            "Whether this article contains extractable organoid/cell culture protocols. "
            "**Set to false** when the article does NOT contain any concrete, step-by-step culture protocol that can be meaningfully extracted. "
            "When false, omit the `cultures` field entirely (output as empty list or omit) to save tokens. "
            ""
            "**Criteria for is_extractable=False (ALL of the following indicate non-extractable):** "
            "1. **Review / Commentary / Opinion**: Article summarizes or discusses other papers' methods without describing its own experiments. "
            "   Signal: No 'Methods' section describing original cell/organoid culture; only cites other protocols. "
            "2. **No culture protocol**: Article uses organoids/cells only as reagents with no described culture procedure "
            "   (e.g., commercially sourced cells used directly in a biochemistry assay, no seeding/growth steps described). "
            "3. **Protocol paper with no experimental data**: Pure methodology/protocol paper with no actual experimental execution described. "
            "4. **Non-experimental article types**: Editorials, letters without original data, database/resource papers, purely computational studies. "
            ""
            "**Criteria for is_extractable=True (ANY of the following indicate extractable):** "
            "1. Article has a Methods section describing cell seeding, culture medium, growth factors, passage, or differentiation steps. "
            "2. Article describes organoid formation, maintenance, or experimental manipulation with specific reagents and timing. "
            "3. Article uses patient-derived, iPSC-derived, or tissue-derived cultures with described preparation steps. "
            "**When in doubt, set is_extractable=True** and attempt extraction. "
            "Use is_extractable=False ONLY when you are confident there is no culture protocol to extract."
        )
    )
    not_extractable_reason: Optional[str] = Field(
        default=None,
        description=(
            "Required when is_extractable=False. Brief explanation of why this article cannot be extracted. "
            "Examples: "
            "'Narrative review summarizing organoid literature; no original culture protocol described.' "
            "'Commentary/opinion article; no Methods section or experimental data.' "
            "'Cells used as reagents only; no seeding, growth, or differentiation steps described.' "
            "If is_extractable=True, set this field to null or omit it."
        )
    )
    cultures: List[OrganoidCultureResult] = Field(
        default_factory=list,
        description=(
            "All distinct core culture workflows ('protocols') extracted from the article. Each OrganoidCultureResult represents one coherent culture timeline with a single global Day 0 and a consistent set of core steps, materials, and model_category/organ/organ_system definitions. "
            "**If is_extractable=False, output this as an empty list [] or omit entirely.** "
            ""
            "**CRITICAL: Culture Splitting Decision Rules** "
            "**Rule 1: Separate Vessels + Independent Timelines → MULTIPLE Results** "
            "- Example: 6 genetic variants in separate wells → 6 results, each with [C1:single_variant] "
            "- **⚠️ Multiple Experimental Groups**: If the paper describes distinct experimental groups run in separate vessels "
            "(e.g., syngeneic models vs. KO mice vs. orthotopic models, different genetic variants, different disease conditions), "
            "each group MUST be a separate OrganoidCultureResult — NOT multiple branches or axes segments within one result. "
            "❌ WRONG signal: time_axis with many axes segments all starting from the same anchor id (fan-out tree) = groups incorrectly merged. "
            "✅ CORRECT: one OrganoidCultureResult per independent experimental group. "
            ""
            "**Rule 2: Same Vessel + Interactions → ONE Result with Multi-Component Composition** "
            "- Example: Organoid + T cells + bacteria in same insert → 1 result with [C1, C2, C3] "
            ""
            "**Rule 3: Same Model + Different Treatments → ONE Result with Branches** "
            "- Example: Cortical organoids with Drug A/B/Vehicle → 1 result with time_axis.branch "
            ""
            "**Rule 4: Distinct Models + Different Workflows → Separate Results** "
            "- Example: Cerebral vs Liver protocols → 2 results "
            ""
            "ORIGINAL DECISION TREE (for reference): "
            "1. If the paper describes clearly named, independently run culture workflows with different final models or incompatible timelines (e.g., 'Protocol A' vs 'Protocol B', or two distinct organoid types with their own seeding/embedding logic), create separate OrganoidCultureResult entries. "
            "2. If the paper describes variations on a single base protocol for the same organoid model (same Day 0 definition and same overall step structure) that differ only by perturbations, experimental conditions, batches, or donor sources, keep them under a single OrganoidCultureResult and encode differences via metadata (condition labels, sample-level annotations), NOT by splitting into multiple cultures. "
            "3. If the article explicitly labels multiple culture methods (e.g., 'Method 1: Cerebral organoids', 'Method 2: Spinal organoids'), each method that yields a distinct final model should correspond to its own OrganoidCultureResult. "
            "4. Do NOT split cultures solely because the downstream experiments have multiple arms (e.g., drug vs vehicle, short vs long treatment) if they share exactly the same core culture workflow; splitting is driven by distinct culture workflows, not by analysis groups. "
            "When in doubt, prefer fewer, more inclusive OrganoidCultureResult entries and document the ambiguity and reasoning in puzzles."
        )
    )
    puzzles: Optional[List[WorkingPuzzledInfo]] = Field(
        default=None,
        description=(
            "List of puzzles or dilemmas encountered during the working, "
            "especially cases where data, protocol or task assignments remain ambiguous "
            "even after applying all disambiguation rules. If no puzzles, omit this field."
        )
    )

    @model_validator(mode='after')
    def validate_cultures(self):
        if self.is_extractable is None:
            self.is_extractable = True
            self.not_extractable_reason = None
        if self.is_extractable and len(self.cultures) == 0:
            raise ValueError(
                "cultures list cannot be empty when is_extractable=True. "
                "Possible causes: "
                "(1) Over-splitting: too many OrganoidCultureResult entries were created and later ones are empty shells — "
                "reduce the number of cultures and merge related protocols into fewer, more complete entries. "
                "(2) Non-extractable article: if this is a review, commentary, or article with no concrete culture protocol, "
                "set is_extractable=False and provide not_extractable_reason instead of forcing an empty cultures list."
            )
        if not self.is_extractable and self.not_extractable_reason is None:
            raise ValueError(
                "not_extractable_reason is required when is_extractable=False. "
                "Please provide a brief explanation of why this article cannot be extracted."
            )
        return self

class DataErrorInfo(BaseModel):
    error_path: str = Field(description="the location in the result JSON where the error is located, e.g., 'cultures[0].base_info.organoid_species'")
    error_reason: str = Field(description="the reason why you think it is wrong or error.  e.g., 'The Mouse is not a valid species name, it should be Mus musculus'")
    suggestion: str = Field(description="suggestion to fix the error. e.g., 'Please provide the scientific name of Mouse, which is Mus musculus'")
    who: Optional[str] = Field(default=None, description="[PLACEHOLDER] Auto-filled by system. DO NOT output.")

class DataCheckResult(BaseModel):
    is_pass: bool = Field(description="Indicates whether the data passed the check. Set to `true` if no errors are found; otherwise, set to `false`.")
    errors: Optional[List[DataErrorInfo]] = Field(description="List of data errors found during the check. correct info should not be there. MUST use array format: [{'error_path':'...',...}]. If no errors are found, this field should be null or an empty list.")

    puzzles: Optional[List[WorkingPuzzledInfo]] = Field(description="List of puzzles or dilemmas encountered during the check process. If no puzzles, no output this field.")

class DataSearchInfo(BaseModel):
    keyword: str = Field(description="The search query used to find the data.")
    info: str = Field(description="Search results have retrieved the key information related to the keyword. You can summarize the key information in a few sentences In English while maintaining the original meaning and key details. MUST be English.")
    data_from: str = Field(description="The name function of searching tool, if you using browser, set it to 'specific url'.")

class DataSearchResult(BaseModel):
    n_querys: int = Field(description="If you search N keywords, output EXACTLY N DataSearchInfo records in 'searchings' array, the N must equal to this field.")
    searchings: Optional[List[DataSearchInfo]] = Field(description="List of data search information. It must include at least a search result for DOI. Mathching searched items follow the plan in DataSearchPlan. ")
    puzzles: Optional[List[WorkingPuzzledInfo]] = Field(default=None, description="List of puzzles or dilemmas encountered during the search process. If no puzzles, no output this field.")

    @model_validator(mode='after')
    def validate_n_querys(self):
        """Validate that n_querys equals length of searchings list"""
        actual_count = len(self.searchings) if self.searchings is not None else 0
        if self.n_querys != actual_count:
            raise ValueError(f"n_querys {self.n_querys} does not equal actual number of searchings {actual_count}. Correcting n_querys.")
        if self.n_querys == 0:
            raise ValueError(f"n_querys cannot be zero - at least one search query must be performed.")
        return self

class SearchItemPlan(BaseModel):
    """Structured search plan for a single keyword."""
    keyword: str = Field(description="The keyword content to search for. Examples: 'GSE123456', 'EGF', '10.1038/nature12345', 'Catalog#12345'.")
    keyword_type: str = Field(
        description=(
            "Type of the keyword to guide tool selection. Common types:"
            "- 'DOI': Digital Object Identifier of papers"
            "- 'TITLE': Paper title"
            "- 'GSE_ID': GEO Series ID like GSE123456"
            "- 'GPL_ID': GEO Platform ID like GPL570"
            "- 'GSM_ID': GEO Sample ID like GSM123456"
            "- 'gene_symbol': Gene name like EGF, TP53"
            "- 'catalog_number': Product catalog number"
            "- 'equipment_model': Equipment model number"
            "- 'reagent_name': Reagent/antibody name"
            "- 'term': General scientific term"
            "- 'Ref': Reference Paper"
            "- 'other': Unclassified keywords"
        )
    )
    search_reason: str = Field(
        description=(
            "Brief explanation of why this keyword needs searching. Examples:"
            "- 'Verify paper DOI for MetaDataInfo validation'"
            "- 'Get full gene name and organism for standardization'"
            "- 'Retrieve product specifications for catalog number ABC123'"
            "- 'Validate term definition mentioned in EXTRACTED_DATA'"
        )
    )

class DataSearchPlan(BaseModel):
    """Complete search plan with structured items."""
    n_querys: int = Field(description="Total number of keywords to search for. Must equal len(searchings).")
    doi: str = Field(description="The DOI of the original article from which data is extracted. Used to contextualize searches. can be 'not specified' if unknown.")
    title: str = Field(description="The title of the original article from which data is extracted. Used to contextualize searches. can not be 'not specified'.")
    searchings: List[SearchItemPlan] = Field(
        description=(
            "List of structured search items. Each item contains keyword, type, suggested tools, reason."
            "The number of items MUST equal n_querys. It must include at least a search task for DOI."
        )
    )

    @model_validator(mode='after')
    def validate_n_querys(self):
        """Validate that n_querys equals length of searchings list"""
        actual_count = len(self.searchings) if self.searchings is not None else 0
        if self.n_querys != actual_count:
            self.n_querys = actual_count
        if self.n_querys == 0:
            raise ValueError("DataSearchPlan must contain at least one SearchItemPlan (n_querys > 0)")
        return self

class DataSearchCheckResult(BaseModel):
    check: DataCheckResult = Field(description="The result of the data check after performing searches.")
    search: Optional[DataSearchResult] = Field(description="The result of the data search performed.")

class JudgementDeduction(BaseModel):
    criterion: str = Field(description="the scoring criterion or deduction explanation.")
    deduction_score: int = Field(description="the deduction score for this criterion.")

class JudgementInfo(BaseModel):
    name: str = Field(description="The name of one of results.")
    total_score: int = Field(description="The total score for one of results. Normally, the total score is 100.")
    deductions: List[JudgementDeduction] = Field(description="Scoring criteria or deduction explanations for this result. **Only list the items that are considered incorrect for deduction. Correct items(deduction_score=0) do not need to be listed here.")
    final_score: int = Field(description="The final_score for one of results. Note that this score should be equal to the total score minus the scores that were deducted in the `deductions` section. final_score = total_score - sum(deduction_scores).")

    # Validate that final_score equals total_score minus sum of all deduction_scores in deductions; if not, correct it and print warning
    @model_validator(mode='after')
    def validate_final_score(self):
        total_deduction = sum(d.deduction_score for d in self.deductions)
        correct_final_score = self.total_score - total_deduction
        if self.final_score != correct_final_score:
            print(f"Warning: final_score {self.final_score} does not equal total_score {self.total_score} minus deductions {total_deduction}. Correcting to {correct_final_score}.")
            self.final_score = correct_final_score
        return self

class JudgementResult(BaseModel):
    judgements: List[JudgementInfo] = Field(min_length=1, description="List of judgements for each results. MUST use array format. by order corresponds to the order of results.")
    # final_result: ExtractionResult = Field(description="The final corrected ExtractionResult after applying all valid corrections from CHECKED_WITH_SEARCHED_DATA and judging scores.")


