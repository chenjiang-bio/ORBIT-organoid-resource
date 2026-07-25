"""Tests for edge cases and boundary conditions."""

import unittest
import os
import tempfile
import shutil
from unittest.mock import patch, MagicMock, mock_open
import sys

# Add the parent directory to the path to import orbit_ocsp
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from orbit_ocsp.permutation_test_terms import (
    _validate_parameters,
    _estimate_memory_usage,
    _summarize_null,
    overlap,
    jaccard,
    _semantic_go_component,
    _semantic_kegg_component
)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_empty_sets(self):
        """Test handling of empty sets."""
        # Test overlap with empty sets
        self.assertEqual(overlap(set(), set()), 0)
        self.assertEqual(overlap({"GO:0008150"}, set()), 0)
        self.assertEqual(overlap(set(), {"GO:0008150"}), 0)
        
        # Test jaccard with empty sets
        self.assertEqual(jaccard(set(), set()), 0.0)
        self.assertEqual(jaccard({"GO:0008150"}, set()), 0.0)
        self.assertEqual(jaccard(set(), {"GO:0008150"}), 0.0)
    
    def test_single_element_sets(self):
        """Test handling of single element sets."""
        # Test overlap with single elements
        self.assertEqual(overlap({"GO:0008150"}, {"GO:0008150"}), 1)
        self.assertEqual(overlap({"GO:0008150"}, {"GO:0008151"}), 0)
        
        # Test jaccard with single elements
        self.assertEqual(jaccard({"GO:0008150"}, {"GO:0008150"}), 1.0)
        self.assertEqual(jaccard({"GO:0008150"}, {"GO:0008151"}), 0.0)
    
    def test_identical_sets(self):
        """Test handling of identical sets."""
        test_set = {"GO:0008150", "GO:0008151", "KEGG:hsa00010"}
        
        # Test overlap with identical sets
        self.assertEqual(overlap(test_set, test_set), len(test_set))
        
        # Test jaccard with identical sets
        self.assertEqual(jaccard(test_set, test_set), 1.0)
    
    def test_disjoint_sets(self):
        """Test handling of disjoint sets."""
        set1 = {"GO:0008150", "GO:0008151"}
        set2 = {"GO:0008152", "GO:0008153"}
        
        # Test overlap with disjoint sets
        self.assertEqual(overlap(set1, set2), 0)
        
        # Test jaccard with disjoint sets
        self.assertEqual(jaccard(set1, set2), 0.0)
    
    def test_null_statistics_edge_cases(self):
        """Test null statistics with edge cases."""
        # Test with empty null_stats
        mu, sd, p_right, p_left, p_two, effect = _summarize_null([], 0.5, 0)
        self.assertEqual(mu, 0.0)
        self.assertTrue(isinstance(sd, float) and str(sd) == "nan")
        self.assertEqual(p_right, 1.0)
        self.assertEqual(p_left, 1.0)
        self.assertEqual(p_two, 1.0)
        self.assertEqual(effect, 0.0)
        
        # Test with single value
        mu, sd, p_right, p_left, p_two, effect = _summarize_null([0.5], 0.5, 1)
        self.assertEqual(mu, 0.5)
        self.assertTrue(isinstance(sd, float) and str(sd) == "nan")
        self.assertEqual(p_right, 1.0)
        self.assertEqual(p_left, 1.0)
        self.assertEqual(p_two, 1.0)
        self.assertEqual(effect, 0.0)
        
        # Test with two identical values
        mu, sd, p_right, p_left, p_two, effect = _summarize_null([0.5, 0.5], 0.5, 2)
        self.assertEqual(mu, 0.5)
        self.assertEqual(sd, 0.0)
        self.assertEqual(p_right, 1.0)
        self.assertEqual(p_left, 1.0)
        self.assertEqual(p_two, 1.0)
        self.assertEqual(effect, 0.0)
    
    def test_memory_estimation_edge_cases(self):
        """Test memory estimation with edge cases."""
        # Test with zero values
        estimate = _estimate_memory_usage(0, 0, 0, 0)
        self.assertIn("MB", estimate)
        
        # Test with very small values
        estimate = _estimate_memory_usage(1, 1, 1, 1)
        self.assertIn("MB", estimate)
        
        # Test with very large values
        estimate = _estimate_memory_usage(1000000, 1000000, 1000000, 1000000)
        self.assertIn("GB", estimate)
    
    def test_parameter_validation_edge_cases(self):
        """Test parameter validation with edge cases."""
        # Create a mock args object
        args = MagicMock()
        
        # Test with None values
        args.A = None
        args.species = None
        args.condition_list = False
        args.organ_list = False
        args.model_list = False
        args.llm_list = False
        args.R = 1
        args.alpha = 0.05
        args.seed = 42
        args.outdir = self.temp_dir
        args.llm_explain = False
        
        errors = _validate_parameters(args)
        self.assertIn("--A is required", str(errors))
        self.assertIn("--species is required", str(errors))
        
        # Test with invalid R
        args.A = "test.json"
        args.species = "hsa"
        args.R = 0
        errors = _validate_parameters(args)
        self.assertIn("--R must be positive", str(errors))
        
        # Test with invalid alpha
        args.R = 1000
        args.alpha = 0
        errors = _validate_parameters(args)
        self.assertIn("--alpha must be between 0 and 1", str(errors))
        
        args.alpha = 1.5
        errors = _validate_parameters(args)
        self.assertIn("--alpha must be between 0 and 1", str(errors))
        
        # Test with invalid seed
        args.alpha = 0.05
        args.seed = -1
        errors = _validate_parameters(args)
        self.assertIn("--seed must be non-negative", str(errors))
    
    def test_file_validation_edge_cases(self):
        """Test file validation with edge cases."""
        args = MagicMock()
        args.A = "nonexistent.json"
        args.B = None
        args.species = "hsa"
        args.condition_list = False
        args.organ_list = False
        args.model_list = False
        args.llm_list = False
        args.R = 1000
        args.alpha = 0.05
        args.seed = 42
        args.outdir = self.temp_dir
        args.llm_explain = False
        
        errors = _validate_parameters(args)
        self.assertIn("File not found: nonexistent.json", str(errors))
    
    def test_species_validation_edge_cases(self):
        """Test species validation with edge cases."""
        args = MagicMock()
        args.A = "test.json"
        args.B = None
        args.species = "invalid"
        args.condition_list = False
        args.organ_list = False
        args.model_list = False
        args.llm_list = False
        args.R = 1000
        args.alpha = 0.05
        args.seed = 42
        args.outdir = self.temp_dir
        args.llm_explain = False
        
        # Mock file existence
        with patch('os.path.exists', return_value=True):
            errors = _validate_parameters(args)
            self.assertIn("Invalid species format", str(errors))
    
    def test_semantic_computation_edge_cases(self):
        """Test semantic computation with edge cases."""
        # Test with empty GO ancestors
        result = _semantic_go_component(set(), set(), {}, {})
        self.assertEqual(result, 0.0)
        
        # Test with empty KEGG sets
        result = _semantic_kegg_component(set(), set(), 0.5)
        self.assertEqual(result, 0.0)
        
        # Test with identical sets
        go_set = {"GO:0008150"}
        result = _semantic_go_component(go_set, go_set, {}, {})
        self.assertEqual(result, 1.0)  # Falls back to weighted Jaccard on raw terms
        
        kegg_set = {"KEGG:hsa00010"}
        result = _semantic_kegg_component(kegg_set, kegg_set, 0.5)
        self.assertEqual(result, 1.0)  # Unknown base values use Jaccard
    
    def test_very_large_datasets(self):
        """Test handling of very large datasets."""
        # Create large sets
        large_set = {f"GO:{i:07d}" for i in range(10000)}
        
        # Test that operations don't crash
        result = overlap(large_set, large_set)
        self.assertEqual(result, len(large_set))
        
        result = jaccard(large_set, large_set)
        self.assertEqual(result, 1.0)
    
    def test_unicode_handling(self):
        """Test handling of unicode characters."""
        unicode_set = {"GO:0008150", "KEGG:hsa00010", "特殊字符"}
        
        # Test that operations handle unicode
        result = overlap(unicode_set, unicode_set)
        self.assertEqual(result, len(unicode_set))
        
        result = jaccard(unicode_set, unicode_set)
        self.assertEqual(result, 1.0)
    
    def test_mixed_data_types(self):
        """Test handling of mixed data types in sets."""
        mixed_set = {"GO:0008150", 123, "KEGG:hsa00010", None}
        
        # Filter out non-string elements
        string_set = {str(item) for item in mixed_set if item is not None}
        
        # Test that operations work with string sets
        result = overlap(string_set, string_set)
        self.assertEqual(result, len(string_set))
    
    def test_network_timeout_simulation(self):
        """Test simulation of network timeouts."""
        # This would test LLM API timeout handling
        # For now, we'll just test the structure
        pass
    
    def test_disk_space_errors(self):
        """Test handling of disk space errors."""
        # Create a read-only directory
        read_only_dir = os.path.join(self.temp_dir, "readonly")
        os.makedirs(read_only_dir)
        os.chmod(read_only_dir, 0o444)  # Read-only
        
        args = MagicMock()
        args.A = "test.json"
        args.B = None
        args.species = "hsa"
        args.condition_list = False
        args.organ_list = False
        args.model_list = False
        args.llm_list = False
        args.R = 1000
        args.alpha = 0.05
        args.seed = 42
        args.outdir = read_only_dir
        args.llm_explain = False
        
        # Mock file existence
        with patch('os.path.exists', return_value=True):
            errors = _validate_parameters(args)
            # Should detect permission error
            self.assertTrue(any("Cannot write to output directory" in str(error) for error in errors))


class TestBoundaryConditions(unittest.TestCase):
    """Test boundary conditions for numerical parameters."""
    
    def test_r_values(self):
        """Test different R values."""
        # Test R = 0
        mu, sd, p_right, p_left, p_two, effect = _summarize_null([], 0.5, 0)
        self.assertEqual(p_right, 1.0)
        self.assertEqual(p_left, 1.0)
        self.assertEqual(p_two, 1.0)
        
        # Test R = 1
        mu, sd, p_right, p_left, p_two, effect = _summarize_null([0.3], 0.5, 1)
        self.assertEqual(p_right, 0.5)
        self.assertEqual(p_left, 1.0)
        self.assertEqual(p_two, 1.0)
    
    def test_alpha_values(self):
        """Test boundary alpha values."""
        # Test alpha = 0.001 (very small)
        # Test alpha = 0.999 (very large)
        # These would be tested in parameter validation
        pass
    
    def test_seed_values(self):
        """Test boundary seed values."""
        # Test seed = 0
        # Test seed = 2**31 - 1 (max 32-bit int)
        # These would be tested in parameter validation
        pass


if __name__ == '__main__':
    unittest.main()
