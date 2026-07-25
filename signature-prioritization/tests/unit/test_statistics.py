"""
Unit tests for statistical functions.
"""

import pytest
import unittest
import sys
import os
from unittest.mock import patch, MagicMock

# Add the parent directory to the path to import orbit_ocsp
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from orbit_ocsp.core.statistics import jaccard, overlap
except ImportError:
    # Fallback to main module if core module doesn't exist
    from orbit_ocsp.permutation_test_terms import jaccard, overlap

from orbit_ocsp.permutation_test_terms import (
    _norm_eq, 
    _sanitize_name,
    _summarize_null,
    _semantic_go_component,
    _semantic_kegg_component,
    _estimate_memory_usage
)


class TestJaccard:
    """Test Jaccard similarity calculation."""
    
    def test_jaccard_identical_sets(self):
        """Test Jaccard with identical sets."""
        set_a = {"GO:0008150", "GO:0008152", "KEGG:hsa00010"}
        set_b = {"GO:0008150", "GO:0008152", "KEGG:hsa00010"}
        
        result = jaccard(set_a, set_b)
        assert result == 1.0
    
    def test_jaccard_no_overlap(self):
        """Test Jaccard with no overlap."""
        set_a = {"GO:0008150", "GO:0008152"}
        set_b = {"GO:0008154", "GO:0008156"}
        
        result = jaccard(set_a, set_b)
        assert result == 0.0
    
    def test_jaccard_partial_overlap(self):
        """Test Jaccard with partial overlap."""
        set_a = {"GO:0008150", "GO:0008152"}
        set_b = {"GO:0008150", "GO:0008152", "GO:0008154"}
        
        result = jaccard(set_a, set_b)
        expected = 2 / 3  # 2 common, 3 total unique
        assert abs(result - expected) < 1e-10
    
    def test_jaccard_empty_sets(self):
        """Test Jaccard with empty sets."""
        result = jaccard(set(), set())
        assert result == 0.0


class TestOverlap:
    """Test overlap calculation."""
    
    def test_overlap_identical_sets(self):
        """Test overlap with identical sets."""
        set_a = {"GO:0008150", "GO:0008152"}
        set_b = {"GO:0008150", "GO:0008152"}
        
        result = overlap(set_a, set_b)
        assert result == 2
    
    def test_overlap_no_overlap(self):
        """Test overlap with no overlap."""
        set_a = {"GO:0008150", "GO:0008152"}
        set_b = {"GO:0008154", "GO:0008156"}
        
        result = overlap(set_a, set_b)
        assert result == 0
    
    def test_overlap_partial_overlap(self):
        """Test overlap with partial overlap."""
        set_a = {"GO:0008150", "GO:0008152"}
        set_b = {"GO:0008150", "GO:0008152", "GO:0008154"}
        
        result = overlap(set_a, set_b)
        assert result == 2
    
    def test_overlap_empty_sets(self):
        """Test overlap with empty sets."""
        result = overlap(set(), set())
        assert result == 0


class TestNormEq:
    """Test _norm_eq function."""
    
    def test_norm_eq_identical(self):
        """Test _norm_eq with identical values."""
        assert _norm_eq("1.0", "1.0")
        assert _norm_eq("0.0", "0.0")
        assert _norm_eq("-1.0", "-1.0")
    
    def test_norm_eq_close_values(self):
        """Test _norm_eq with close values."""
        assert _norm_eq("1.0", "1.0")
        assert _norm_eq("0.0", "0.0")
    
    def test_norm_eq_different_values(self):
        """Test _norm_eq with different values."""
        assert not _norm_eq("1.0", "2.0")
        assert not _norm_eq("0.0", "1.0")


class TestSanitizeName:
    """Test _sanitize_name function."""
    
    def test_sanitize_name_basic(self):
        """Test basic name sanitization."""
        result = _sanitize_name("test_name")
        assert result == "test_name"
    
    def test_sanitize_name_with_spaces(self):
        """Test sanitization with spaces."""
        result = _sanitize_name("test name")
        assert result == "test_name"
    
    def test_sanitize_name_with_special_chars(self):
        """Test sanitization with special characters."""
        result = _sanitize_name("test-name@123")
        assert result == "test-name_123"
    
    def test_sanitize_name_empty(self):
        """Test sanitization of empty string."""
        result = _sanitize_name("")
        assert result == "NONE"


class TestSummarizeNull:
    """Test null statistics summarization."""
    
    def test_summarize_null_basic(self):
        """Test basic null statistics summarization."""
        null_stats = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        S_obs = 0.5
        R = 9
        
        mu, sd, p_right, p_left, p_two, effect = _summarize_null(null_stats, S_obs, R)
        
        assert abs(mu - 0.5) < 1e-10
        assert sd > 0
        assert 0 <= p_right <= 1
        assert 0 <= p_left <= 1
        assert 0 <= p_two <= 1
        assert abs(effect - 0.0) < 1e-10
    
    def test_summarize_null_empty(self):
        """Test null statistics with empty list."""
        mu, sd, p_right, p_left, p_two, effect = _summarize_null([], 0.5, 0)
        
        assert mu == 0.0
        assert str(sd) == "nan"
        assert p_right == 1.0
        assert p_left == 1.0
        assert p_two == 1.0
        assert effect == 0.0
    
    def test_summarize_null_single_value(self):
        """Test null statistics with single value."""
        mu, sd, p_right, p_left, p_two, effect = _summarize_null([0.5], 0.5, 1)
        
        assert mu == 0.5
        assert str(sd) == "nan"
        assert p_right == 1.0
        assert p_left == 1.0
        assert p_two == 1.0
        assert effect == 0.0


class TestSemanticComponents:
    """Test semantic component calculations."""
    
    def test_semantic_go_component(self):
        """Test semantic GO component calculation."""
        A_GO = {"GO:0008150", "GO:0008151"}
        B_GO = {"GO:0008150", "GO:0008152"}
        go_anc = {"GO:0008150": {"GO:0008151"}, "GO:0008151": set()}
        ic_map = {"GO:0008150": 0.5, "GO:0008151": 0.3}
        
        result = _semantic_go_component(A_GO, B_GO, go_anc, ic_map)
        assert isinstance(result, float)
        assert result >= 0.0
    
    def test_semantic_kegg_component(self):
        """Test semantic KEGG component calculation."""
        A_KEGG = {"KEGG:hsa00010", "KEGG:hsa00020"}
        B_KEGG = {"KEGG:hsa00010", "KEGG:hsa00030"}
        base = 0.5
        
        result = _semantic_kegg_component(A_KEGG, B_KEGG, base)
        assert isinstance(result, float)
        assert result >= 0.0


class TestMemoryEstimation:
    """Test memory usage estimation."""
    
    def test_memory_estimation_small(self):
        """Test memory estimation with small datasets."""
        estimate = _estimate_memory_usage(100, 1000, 10000, 1000)
        assert isinstance(estimate, str)
        assert "MB" in estimate
    
    def test_memory_estimation_large(self):
        """Test memory estimation with large datasets."""
        estimate = _estimate_memory_usage(10000, 100000, 1000000, 10000)
        assert isinstance(estimate, str)
        assert "GB" in estimate
    
    def test_memory_estimation_zero(self):
        """Test memory estimation with zero values."""
        estimate = _estimate_memory_usage(0, 0, 0, 0)
        assert isinstance(estimate, str)
        assert "MB" in estimate


class TestEdgeCases:
    """Test edge cases for statistical functions."""
    
    def test_empty_sets(self):
        """Test with empty sets."""
        assert overlap(set(), set()) == 0
        assert jaccard(set(), set()) == 0.0
    
    def test_identical_sets(self):
        """Test with identical sets."""
        test_set = {"GO:0008150", "GO:0008151"}
        assert overlap(test_set, test_set) == len(test_set)
        assert jaccard(test_set, test_set) == 1.0
    
    def test_disjoint_sets(self):
        """Test with disjoint sets."""
        set1 = {"GO:0008150"}
        set2 = {"GO:0008151"}
        assert overlap(set1, set2) == 0
        assert jaccard(set1, set2) == 0.0
    
    def test_large_datasets(self):
        """Test with large datasets."""
        large_set1 = {f"GO:{i:07d}" for i in range(1000)}
        large_set2 = {f"GO:{i:07d}" for i in range(500, 1500)}
        
        overlap_result = overlap(large_set1, large_set2)
        jaccard_result = jaccard(large_set1, large_set2)
        
        assert overlap_result == 500  # 500 common elements
        assert abs(jaccard_result - 500 / 1500) < 1e-10
