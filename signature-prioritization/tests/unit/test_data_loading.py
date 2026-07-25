"""
Unit tests for data loading functions.
"""

import pytest
import json
import tempfile
import os
from orbit_ocsp.permutation_test_terms import _load_json_items, _match_filters


class TestLoadJsonItems:
    """Test _load_json_items function."""
    
    def test_load_json_items_valid_file(self):
        """Test loading valid JSON file."""
        test_data = [
            {"gene": "GENE1", "pathway": ["GO:0008150", "GO:0008152"]},
            {"gene": "GENE2", "pathway": ["KEGG:hsa00010"]}
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            temp_file = f.name
        
        try:
            result = _load_json_items(temp_file)
            assert len(result) == 2
            assert result[0]["gene"] == "GENE1"
            assert result[1]["gene"] == "GENE2"
        finally:
            os.unlink(temp_file)
    
    def test_load_json_items_invalid_file(self):
        """Test loading invalid JSON file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("invalid json content")
            temp_file = f.name
        
        try:
            with pytest.raises(json.JSONDecodeError):
                _load_json_items(temp_file)
        finally:
            os.unlink(temp_file)
    
    def test_load_json_items_nonexistent_file(self):
        """Test loading nonexistent file."""
        with pytest.raises(FileNotFoundError):
            _load_json_items("nonexistent_file.json")


class TestMatchFilters:
    """Test _match_filters function."""
    
    def test_match_filters_no_filters(self):
        """Test matching with no filters."""
        item = {"condition": "cancer", "organ": "colon"}
        result = _match_filters(item)
        assert result is True
    
    def test_match_filters_matching_condition(self):
        """Test matching with condition filter."""
        item = {"condition": "cancer", "organ": "colon"}
        result = _match_filters(item, cond_filter="cancer")
        assert result is True
    
    def test_match_filters_non_matching_condition(self):
        """Test non-matching condition filter."""
        item = {"condition": "cancer", "organ": "colon"}
        result = _match_filters(item, cond_filter="diabetes")
        assert result is False
    
    def test_match_filters_multiple_filters(self):
        """Test matching with multiple filters."""
        item = {"condition": "cancer", "organ": "colon", "model": "organoid"}
        result = _match_filters(item, cond_filter="cancer", organ_filter="colon")
        assert result is True
    
    def test_match_filters_partial_match(self):
        """Test partial match with multiple filters."""
        item = {"condition": "cancer", "organ": "colon", "model": "organoid"}
        result = _match_filters(item, cond_filter="cancer", organ_filter="liver")
        assert result is False
    
    def test_match_filters_none_values(self):
        """Test matching with None filter values."""
        item = {"condition": "cancer", "organ": "colon"}
        result = _match_filters(item, cond_filter=None, organ_filter="colon")
        assert result is True
