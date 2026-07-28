from ..utils.json_schema import clean_schema
from ..beam.organoid_culture import ExtractionResult


# Assemble tools
tools = [
    {
        "type": "function",
        "function": {
            "name": "fix_ExtractionResult_json_structure",
            "description": "Extract structured data specifically matching the ExtractionResult format.",
            # Note: call clean_schema here
            "parameters": clean_schema(ExtractionResult)
        }
    }
]

