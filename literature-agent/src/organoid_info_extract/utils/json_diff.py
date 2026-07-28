from collections.abc import Mapping, Sequence
from pydantic import BaseModel
from typing import Any
import os
import time
import requests
import numpy as np

class JsonDiffInfo(BaseModel):
    json_left_value: Any
    json_right_value: Any
    embedding_score: float | None = None

class JsonDiffResult(BaseModel):
    added: dict[str, Any]
    removed: dict[str, Any]
    modified: dict[str, JsonDiffInfo]  # (old_value, new_value)

def _is_json_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _get_embeddings(texts: list[str], max_retries: int = 3) -> list[list[float]] | None:
    """
    Batch-fetch embedding vectors for texts.
    
    Args:
        texts: Texts to embed
        max_retries: Max retry count (default 3)
        
    Returns:
        List of embedding vectors, or None on failure
    """
    if not texts:
        return []
    
    # Load config from environment
    model = os.getenv("DIFF_EMBEDDING_MODEL", "text-embedding-3-small")
    url = os.getenv("DIFF_EMBEDDING_BASE_URL", "https://api.openai.com/v1/embeddings")
    api_key = os.getenv("DIFF_EMBEDDING_API_KEY", "")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": model,
        "input": texts
    }
    
    # Retry loop
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            embeddings = [item["embedding"] for item in data["data"]]
            return embeddings
            
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"Embedding API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                time.sleep(1)  # Wait 1s before retry
            else:
                print(f"Embedding API call failed permanently: {e}")
                return None
    
    return None


def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """
    Compute cosine similarity of two vectors.
    
    Args:
        vec1: First vector
        vec2: Second vector
        
    Returns:
        Cosine similarity in [-1, 1]
    """
    v1 = np.array(vec1)
    v2 = np.array(vec2)
    
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    
    return float(dot_product / (norm_v1 * norm_v2))


def json_diff(json_left: dict, json_right: dict) -> JsonDiffResult:
    added = {}
    removed = {}
    modified = {}

    # Compare nested json_left/json_right fully; paths use JSON key notation; list/tuple use 0-based indices
    def compare_nested(left: Any, right: Any, path: str = "$") -> None:
        left_is_mapping = isinstance(left, Mapping)
        right_is_mapping = isinstance(right, Mapping)

        if left_is_mapping or right_is_mapping:
            if not (left_is_mapping and right_is_mapping):
                modified[path] = JsonDiffInfo(json_left_value=left, json_right_value=right)
                return

            left_keys = set(left.keys())
            right_keys = set(right.keys())
            
            # Keys added on the right
            for key in right_keys - left_keys:
                added[f"{path}.{key}"] = right[key]
            
            # Keys removed from the left
            for key in left_keys - right_keys:
                removed[f"{path}.{key}"] = left[key]
            
            # Shared keys: recurse
            for key in left_keys & right_keys:
                compare_nested(left[key], right[key], f"{path}.{key}")

            return

        left_is_seq = _is_json_sequence(left)
        right_is_seq = _is_json_sequence(right)

        # Handle lists and tuples
        if left_is_seq or right_is_seq:
            if not (left_is_seq and right_is_seq):
                modified[path] = JsonDiffInfo(json_left_value=left, json_right_value=right)
                return

            max_len = max(len(left), len(right))
            
            for i in range(max_len):
                current_path = f"{path}[{i}]"
                
                if i >= len(left):
                    # Present on right, missing on left
                    added[current_path] = right[i]
                elif i >= len(right):
                    # Present on left, missing on right
                    removed[current_path] = left[i]
                else:
                    # Present on both: recurse
                    compare_nested(left[i], right[i], current_path)
            return

        # Handle scalars
        if type(left) != type(right) or left != right:
            modified[path] = JsonDiffInfo(json_left_value=left, json_right_value=right)

    compare_nested(json_left, json_right)

    # Batch-embed string-type modified items and score similarity
    str_paths = []
    str_left_values = []
    str_right_values = []
    
    for path, diff_info in modified.items():
        if isinstance(diff_info.json_left_value, str) and isinstance(diff_info.json_right_value, str):
            str_paths.append(path)
            str_left_values.append(diff_info.json_left_value)
            str_right_values.append(diff_info.json_right_value)
    
    # If any strings need embeddings
    if str_paths:
        # Concatenate left/right strings and batch-embed
        all_texts = str_left_values + str_right_values
        embeddings = _get_embeddings(all_texts)
        
        if embeddings is not None:
            # Split left/right embeddings
            n = len(str_left_values)
            left_embeddings = embeddings[:n]
            right_embeddings = embeddings[n:]
            
            # Cosine similarity per string pair
            for i, path in enumerate(str_paths):
                similarity = _cosine_similarity(left_embeddings[i], right_embeddings[i])
                modified[path].embedding_score = similarity
        else:
            # On API failure, set all embedding_score values to -1
            for path in str_paths:
                modified[path].embedding_score = -1.0

    return JsonDiffResult(added=added, removed=removed, modified=modified)

# CLI entry: argparse two JSON paths, print diff
if __name__ == "__main__":
    import argparse
    import json
    import dotenv
    
    parser = argparse.ArgumentParser(description='Compare two JSON files')
    parser.add_argument('--left', required=True, help='Left JSON file path')
    parser.add_argument('--right', required=True, help='Right JSON file path')
    parser.add_argument('--env', required=True, type=str, help='Env file path (typically .env)')
    args = parser.parse_args()

    dotenv.load_dotenv(args.env)

    with open(args.left, 'r', encoding='utf-8') as f:
        json_left = json.load(f)
    
    with open(args.right, 'r', encoding='utf-8') as f:
        json_right = json.load(f)
    
    diff_result = json_diff(json_left, json_right)
    
    print("Added:")
    print(json.dumps(diff_result.added, indent=2, ensure_ascii=False))
    
    print("\nRemoved:")
    print(json.dumps(diff_result.removed, indent=2, ensure_ascii=False))
    
    print("\nModified:")
    modified_output = {
        k: {
            "left": v.json_left_value, 
            "right": v.json_right_value,
            "embedding_score": v.embedding_score
        } 
        for k, v in diff_result.modified.items()
    }
    print(json.dumps(modified_output, indent=2, ensure_ascii=False))