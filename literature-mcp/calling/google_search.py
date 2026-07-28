import json
import os
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import time
import hashlib
# from fastmcp import utilities

# Mock logger if fastmcp is not available
class MockLogger:
    def info(self, msg): print(f"[INFO] {msg}")
    def warning(self, msg): print(f"[WARN] {msg}")
    def error(self, msg): print(f"[ERROR] {msg}")
    def debug(self, msg): pass # print(f"[DEBUG] {msg}")

try:
    from fastmcp import utilities
    logger = utilities.logging.get_logger("call")
except ImportError:
    logger = MockLogger()



load_dotenv(os.path.join(os.path.dirname(__file__), "google.env"))
api_keys_str = os.getenv("GOOGLE_SEARCH_KEYS", "")
# parse comma-separated API keys string into a list
api_keys = [key.strip() for key in api_keys_str.split(",") if key.strip()] if api_keys_str else []
cur_api_key_index: int = 0


def _search_via_google_cse(query: str, num_results: int = 5) -> dict:
    """
    Use Google Custom Search JSON API.
    Requires env GOOGLE_SEARCH_KEY and GOOGLE_SEARCH_CX.
    """
    global cur_api_key_index, api_keys
    cx = os.getenv("GOOGLE_SEARCH_CX")
    if not api_keys or len(api_keys) == 0 or not cx:
        return {
            "query": query,
            "error": "Missing GOOGLE_SEARCH_KEY or GOOGLE_SEARCH_CX. Browse to https://developers.google.com/custom-search/v1/introduction for more details.",
            "results": []
        }
    n_retry = 5
    while n_retry > 0:
        try:
            params = {
                "q": query,
                "num": max(1, min(10, num_results)),  # API allows at most 10 results per request
                "key": api_keys[cur_api_key_index],
                "cx": cx,
                "safe": "off",
                "hl": "en"
            }
            # light backoff to avoid hitting rate limits
            time.sleep(1)
            resp = requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", []) or []
            results = []
            for it in items[:num_results]:
                descs = []
                pagemap = it.get("pagemap", {})
                metatags = pagemap.get("metatags", [])
                for tag in metatags:
                    desc = tag.get("og:description","")
                    descs.append(desc)
                results.append({
                    "title": it.get("title", ""),
                    "snippet": it.get("snippet", ""),
                    # "link": it.get("link", ""),
                    "desc": "\n".join(descs),
                    # "page": html_str,
                })
            return {"query": query, "results": results, "engine": "google_cse"}
        except Exception as e:
            if "429" in str(e):
                new_index = (cur_api_key_index + 1) % len(api_keys)
                err_msg = f"Rate limit exceeded for Google Custom Search API. Change API_KEY {cur_api_key_index} -> {new_index}, need to retry."
                logger.warning(err_msg)
                cur_api_key_index = new_index
                time.sleep(10)
                continue
            else:
                return {"query": query, "error": str(e), "engine": "google_cse"}
        finally:
            n_retry -= 1
    return {"query": query, "error": "Exceeded maximum retries for Google CSE.", "engine": "google_cse"}

def search_from_google(query: str, num_results: int = 5) -> dict:
    """
    Google search via CSE API
    """
    # Fallback to CSE
    r = _search_via_google_cse(query, num_results)
    return r

def search_from_google_with_cache(query: str, num_results: int = 5, cache_dir: str = "./cache") -> dict:
    """
    Search with simple file cache.
    """
    os.makedirs(cache_dir, exist_ok=True)

    # use stable md5 as cache key (includes query and count)
    md5 = hashlib.md5(f"{query}|{num_results}".encode("utf-8")).hexdigest()
    json_path = os.path.join(cache_dir, f"sgoogle_{md5}_{num_results}.json")

    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            cached_result = json.load(f)
            if cached_result:
                return cached_result, True

    results = search_from_google(query, num_results)
    if "error" not in results: # cache only error-free data
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    return results, False

def search_web(query: str, num_results: int = 5) -> dict:
    r = _search_via_google_cse(query, num_results)
    if r.get("results") and len(r["results"]) > 0:
        r["engine"] = r.get("engine", "google_cse")
        return r
    else:
        logger.info(f"No results from google_cse for query: {query}")
        if "error" in r:
            logger.info(f"Error: {r['error']}")
    last_error = r.get("error")

    return {"query": query, "results": [], "error": last_error or "no results from google_cse"}

def search_web_with_cache(
    query: str, num_results: int = 5, cache_dir: str = "./cache") -> dict:
    """
    Generic search (with cache). Cache key includes engine order so results from different engines do not overwrite each other.
    """
    os.makedirs(cache_dir, exist_ok=True)
    # use stable md5 as cache key (includes query and count)
    md5 = hashlib.md5(f"{query}|{num_results}".encode("utf-8")).hexdigest()
    json_path = os.path.join(cache_dir, f"sgoogle_{md5}_{num_results}.json")

    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            cached_result = json.load(f)
            if cached_result:
                return cached_result, True

    results = search_web(query, num_results)
    if "error" not in results: # cache only error-free data
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    return results, False

if __name__ == "__main__":
    # test all engines
    query = "DMEM:F12 cell culture medium"
    
    print("=" * 70)
    print(f"Testing search for: {query}")
    print("=" * 70)
    
    
    print(f"\n{'=' * 70}")
    print('=' * 70)
    
    results = search_web(query, num_results=10)
    
    if results.get("results"):
        print(f"✅ Found {len(results['results'])} results")
        for i, r in enumerate(results['results'][:5], 1):
            print(f"  {i}. {r['title']}")
            print(f"     {r['link']}")
            print(f"     {r['snippet'][:100]}...")
    else:
        error = results.get("error", "Unknown error")
        print(f"❌: {error}")