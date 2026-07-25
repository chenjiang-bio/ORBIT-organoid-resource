"""Tests for caching functionality."""

import unittest
import os
import tempfile
import shutil
import time
from unittest.mock import patch, MagicMock
import sys

# Add the parent directory to the path to import orbit_ocsp
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from orbit_ocsp.permutation_test_terms import (
    cached_computation, 
    clear_cache, 
    _get_cache_dir, 
    _get_cache_key,
)
import orbit_ocsp.permutation_test_terms as permutation_terms


class TestCaching(unittest.TestCase):
    """Test caching functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary directory for cache
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir_patcher = patch.object(
            permutation_terms,
            "_cache_dir",
            os.path.join(self.temp_dir, ".orbit_ocsp_cache"),
        )
        self.cache_dir_patcher.start()
        clear_cache()
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.cache_dir_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_cache_directory_creation(self):
        """Test that cache directory is created correctly."""
        cache_dir = _get_cache_dir()
        self.assertTrue(os.path.exists(cache_dir))
        self.assertTrue(os.path.isdir(cache_dir))
        self.assertEqual(cache_dir, os.path.join(self.temp_dir, ".orbit_ocsp_cache"))
    
    def test_cache_key_generation(self):
        """Test cache key generation."""
        # Test with different argument types
        key1 = _get_cache_key("string", 123, [1, 2, 3])
        key2 = _get_cache_key("string", 123, [1, 2, 3])
        key3 = _get_cache_key("string", 124, [1, 2, 3])
        
        # Same arguments should produce same key
        self.assertEqual(key1, key2)
        
        # Different arguments should produce different keys
        self.assertNotEqual(key1, key3)
        
        # Test with keyword arguments
        key4 = _get_cache_key("string", 123, kwarg1="value1")
        key5 = _get_cache_key("string", 123, kwarg1="value1")
        key6 = _get_cache_key("string", 123, kwarg1="value2")
        
        self.assertEqual(key4, key5)
        self.assertNotEqual(key4, key6)
    
    def test_cached_computation_decorator(self):
        """Test the cached_computation decorator."""
        
        @cached_computation("test_function", max_age_hours=1)
        def expensive_function(x, y):
            """A function that simulates expensive computation."""
            time.sleep(0.1)  # Simulate computation time
            return x + y
        
        # First call should compute and cache
        start_time = time.time()
        result1 = expensive_function(1, 2)
        first_call_time = time.time() - start_time
        
        # Second call should use cache
        start_time = time.time()
        result2 = expensive_function(1, 2)
        second_call_time = time.time() - start_time
        
        # Results should be the same
        self.assertEqual(result1, result2)
        self.assertEqual(result1, 3)
        
        # Second call should be faster (cached)
        self.assertLess(second_call_time, first_call_time)
        
        # Check that cache file was created
        cache_dir = _get_cache_dir()
        cache_files = [f for f in os.listdir(cache_dir) if f.startswith("test_function_")]
        self.assertGreater(len(cache_files), 0)
    
    def test_cache_expiration(self):
        """Test cache expiration."""
        
        @cached_computation("expiring_function", max_age_hours=0.001)  # Very short expiration
        def expiring_function(x):
            return x * 2
        
        # First call
        result1 = expiring_function(5)
        self.assertEqual(result1, 10)
        
        # Wait for cache to expire
        time.sleep(0.1)
        
        # Second call should recompute
        result2 = expiring_function(5)
        self.assertEqual(result2, 10)
    
    def test_cache_disabled(self):
        """Test behavior when cache is disabled."""
        original_state = permutation_terms._cache_enabled
        
        try:
            permutation_terms._cache_enabled = False
            
            @cached_computation("disabled_function", max_age_hours=1)
            def disabled_function(x):
                return x * 3
            
            # Both calls should compute (no caching)
            result1 = disabled_function(3)
            result2 = disabled_function(3)
            
            self.assertEqual(result1, 9)
            self.assertEqual(result2, 9)
            
            # No cache files should be created
            cache_dir = _get_cache_dir()
            cache_files = [f for f in os.listdir(cache_dir) if f.startswith("disabled_function_")]
            self.assertEqual(len(cache_files), 0)
            
        finally:
            permutation_terms._cache_enabled = original_state
    
    def test_clear_cache(self):
        """Test cache clearing functionality."""
        
        @cached_computation("clear_test_function", max_age_hours=1)
        def clear_test_function(x):
            return x * 4
        
        # Create some cache entries
        clear_test_function(1)
        clear_test_function(2)
        
        # Check that cache files exist
        cache_dir = _get_cache_dir()
        cache_files = [f for f in os.listdir(cache_dir) if f.startswith("clear_test_function_")]
        self.assertGreater(len(cache_files), 0)
        
        # Clear cache
        clear_cache("clear_test_function")
        
        # Check that cache files are gone
        cache_files_after = [f for f in os.listdir(cache_dir) if f.startswith("clear_test_function_")]
        self.assertEqual(len(cache_files_after), 0)
    
    def test_cache_corruption_handling(self):
        """Test handling of corrupted cache files."""
        
        @cached_computation("corruption_test", max_age_hours=1)
        def corruption_test_function(x):
            return x * 5
        
        # Create a cache entry
        result1 = corruption_test_function(2)
        self.assertEqual(result1, 10)
        
        # Corrupt the cache file
        cache_dir = _get_cache_dir()
        cache_files = [f for f in os.listdir(cache_dir) if f.startswith("corruption_test_")]
        self.assertGreater(len(cache_files), 0)
        
        cache_file = os.path.join(cache_dir, cache_files[0])
        with open(cache_file, 'w') as f:
            f.write("corrupted data")
        
        # Function should still work (recompute and recache)
        result2 = corruption_test_function(2)
        self.assertEqual(result2, 10)
    
    def test_concurrent_cache_access(self):
        """Test concurrent access to cache."""
        import threading
        import queue
        
        @cached_computation("concurrent_test", max_age_hours=1)
        def concurrent_test_function(x):
            time.sleep(0.01)  # Small delay to increase chance of race condition
            return x * 6
        
        results = queue.Queue()
        
        def worker(x):
            result = concurrent_test_function(x)
            results.put(result)
        
        # Start multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads to complete
        for t in threads:
            t.join()
        
        # Collect results
        collected_results = []
        while not results.empty():
            collected_results.append(results.get())
        
        # All results should be correct
        self.assertEqual(len(collected_results), 5)
        self.assertEqual(sorted(collected_results), [0, 6, 12, 18, 24])


class TestCachingIntegration(unittest.TestCase):
    """Integration tests for caching with actual functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary directory for cache
        self.temp_dir = tempfile.mkdtemp()
        
        self.cache_dir_patcher = patch.object(
            permutation_terms,
            "_cache_dir",
            os.path.join(self.temp_dir, ".orbit_ocsp_cache"),
        )
        self.cache_dir_patcher.start()
        clear_cache()
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.cache_dir_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_permutation_generation_caching(self):
        """Test caching of permutation generation."""
        from orbit_ocsp.permutation_test_terms import _generate_permutations_cached
        
        # Mock the required dependencies
        B = {"GO:0008150", "GO:0008152"}
        U_list = ["GO:0008150", "GO:0008152", "GO:0008151"]
        bins = None
        rng = MagicMock()
        R = 10
        desc = "test"
        
        # First call should compute
        result1 = _generate_permutations_cached(B, U_list, bins, rng, R, desc)
        
        # Second call should use cache
        result2 = _generate_permutations_cached(B, U_list, bins, rng, R, desc)
        
        # Results should be the same
        self.assertEqual(result1, result2)


if __name__ == '__main__':
    unittest.main()
