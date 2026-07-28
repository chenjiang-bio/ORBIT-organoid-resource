from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema

import jsonref

# --- Step 1: custom schema generator ---
class SchemaWithoutDescription(GenerateJsonSchema):
    # Override field_schema
    def generate(self, schema, mode='validation'):
        # Call parent to get full schema
        json_schema = super().generate(schema, mode=mode)
        
        # Recursively strip description fields
        self._remove_description_in_place(json_schema)
        
        return json_schema

    def _remove_description_in_place(self, schema: dict):
        """Recursively remove 'description' keys from a schema dict."""
        if isinstance(schema, dict):
            # Drop description at this level
            if 'description' in schema:
                del schema['description']
            
            # Recurse into nested dicts
            for value in schema.values():
                self._remove_description_in_place(value)
        elif isinstance(schema, list):
            # Recurse into list items
            for item in schema:
                self._remove_description_in_place(item)


# Keep these lines so schema expansion stays compatible across model upgrades
def clean_schema(schema_or_model) -> dict:
    """
    Expand all refs in a JSON Schema and remove $defs / $ref.
    
    Args:
        schema_or_model: Either:
            1) A Pydantic BaseModel class (schema is generated)
            2) A JSON Schema dict (processed as-is)
    
    Returns:
        Schema dict with all refs expanded
    """
    # If BaseModel class, generate schema first
    if isinstance(schema_or_model, type) and issubclass(schema_or_model, BaseModel):
        schema = schema_or_model.model_json_schema()
    # If already a dict, use it directly
    elif isinstance(schema_or_model, dict):
        schema = schema_or_model.copy()  # Copy to avoid mutating the original
    else:
        raise TypeError(f"Expected BaseModel class or dict, got {type(schema_or_model)}")
    
    # Expand refs with jsonref
    schema = jsonref.replace_refs(schema, proxies=False) 
    
    # Drop $defs (already expanded)
    if "$defs" in schema:
        del schema["$defs"]
    
    return schema

