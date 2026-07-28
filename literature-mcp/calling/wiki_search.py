import wikipediaapi
from typing import Literal, Optional
from wikipediaapi import WikipediaPage
import os
import json
import time
import requests
import numpy as np

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(__file__), "wiki.env"))

# Embedding API timeout and retries (remote services like OpenRouter may occasionally raise ConnectionError)
_EMBEDDING_TIMEOUT = 30
_EMBEDDING_MAX_RETRIES = 3
_EMBEDDING_RETRY_BACKOFF = 1.5  # seconds, multiplies each attempt


def openai_embedding(texts: list[str]) -> Optional[list[list[float]]]:
    """Call remote embedding API. Returns None on failure (never raises)."""
    url = os.getenv("EMBEDDING_BASE_URL")
    api_key = os.getenv("EMBEDDING_API_KEY")
    model = os.getenv("EMBEDDING_MODEL")
    if not url or not api_key or not model:
        print("[openai_embedding] Missing EMBEDDING_BASE_URL / EMBEDDING_API_KEY / EMBEDDING_MODEL")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "input": texts,
        "encoding_format": "float",
    }

    last_err = None
    for attempt in range(1, _EMBEDDING_MAX_RETRIES + 1):
        try:
            res = requests.post(
                url=url,
                headers=headers,
                json=payload,
                timeout=_EMBEDDING_TIMEOUT,
            )
            if res.status_code == 200:
                embeddings = res.json().get("data", [])
                if len(embeddings) != len(texts):
                    print(
                        f"[openai_embedding] Expected {len(texts)} vectors, got {len(embeddings)}"
                    )
                    return None
                vec_length = 1
                for item in embeddings:
                    vec = item.get("embedding", [])
                    vec_length = max(vec_length, len(vec))
                return [
                    item.get("embedding", [0.0] * vec_length) for item in embeddings
                ]

            # 429 / 5xx: retry; other HTTP errors: fail fast
            if res.status_code in (429, 500, 502, 503, 504) and attempt < _EMBEDDING_MAX_RETRIES:
                wait = _EMBEDDING_RETRY_BACKOFF * attempt
                print(
                    f"[openai_embedding] HTTP {res.status_code}, "
                    f"retry {attempt}/{_EMBEDDING_MAX_RETRIES} after {wait:.1f}s"
                )
                time.sleep(wait)
                continue

            print(f"[openai_embedding] Error: {res.status_code}, {res.text[:500]}")
            return None

        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ) as e:
            last_err = e
            if attempt < _EMBEDDING_MAX_RETRIES:
                wait = _EMBEDDING_RETRY_BACKOFF * attempt
                print(
                    f"[openai_embedding] {type(e).__name__}: {e}; "
                    f"retry {attempt}/{_EMBEDDING_MAX_RETRIES} after {wait:.1f}s"
                )
                time.sleep(wait)
                continue
            print(f"[openai_embedding] Failed after {_EMBEDDING_MAX_RETRIES} attempts: {e}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"[openai_embedding] Request failed: {e}")
            return None

    if last_err:
        print(f"[openai_embedding] Failed: {last_err}")
    return None

def openai_embedding_cosine(keyword: str, match_values:list[str]) -> list[float]:
    cosines = [0.0] * len(match_values)
    texts = [keyword] + match_values
    embeddings = openai_embedding(texts)
    if not embeddings:
        return cosines

    keyword_embedding = np.array(embeddings[0:1])
    keyword_embedding = keyword_embedding / np.linalg.norm(keyword_embedding)

    match_embeddings = embeddings[1:]
    for i, vec in enumerate(match_embeddings):
        match_embedding = np.array(vec)
        match_embedding = match_embedding / np.linalg.norm(match_embedding)
        cosines[i] = np.dot(keyword_embedding, match_embedding)

    return cosines


def search_wikipedia(
    keyword: str,
) -> "WikipediaPage":
    """
    Search Wikipedia and return page content in specified format.
    
    Args:
        keyword: Search term
    
    Returns:
        Page content as string
    """
    wiki = wikipediaapi.Wikipedia(
        language='en',
        user_agent='orbit-quest/1.0 (your.email@example.com)'
    )
    
    page = wiki.page(keyword)
    if not page.exists():
        # Need search here: keyword may not exact-match, but the page can still exist on wiki. See https://www.mediawiki.org/wiki/Special:MyLanguage/API:Search 
        sess = requests.Session()

        wiki_request_url = "https://en.wikipedia.org/w/api.php"

        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": keyword
        }
        if 'User-Agent' in sess.headers:
            sess.headers['User-Agent'] += ' orbit-quest/1.0 (your.email@example.com)'
        else:
            sess.headers['User-Agent'] = 'orbit-quest/1.0 (your.email@example.com)'
        res = sess.get(url=wiki_request_url, params=params)
        if res.status_code != 200:
            return None
        data = res.json()
        print(f"[search_wikipedia] search for '{keyword}' got data: {data}")
        if "query" in data and "search" in data["query"]:
            search_results = data["query"]["search"]
            if search_results and len(search_results) > 0:
                max_cosine = 0.0
                matched_title = None
                title_list = []
                for item in search_results:
                    title = item['title']
                    title_list.append(title)
                cosines = openai_embedding_cosine(keyword, title_list)
                for i, cosine in enumerate(cosines):
                    print(f"[search_wikipedia] title: {title_list[i]} cosine distance: {cosine}")
                    if cosine > max_cosine:
                        max_cosine = cosine
                        matched_title = title_list[i]
                if matched_title and max_cosine > 0.9:
                    print(f"[search_wikipedia] matched title: {matched_title} with distance: {max_cosine}")
                    page = wiki.page(matched_title)
                    if page.exists():
                        return page
                    
        return None
    return page

def search_wikipedia_with_cache(
    keyword: str, cache_dir: str
) -> "WikipediaPage":
    """
    Search Wikipedia and return page content in specified format.
    
    Args:
        keyword: Search term
        cache_dir: Directory to store cached results, the path of cache file is {cache_dir}/keyword.pkl
    
    Returns:
        Page content as string
    """
    cache_file = os.path.join(cache_dir, f"wiki_{keyword}.json")
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    
    page = search_wikipedia(keyword)
    result = None
    if page:
        result = {}
        result['summary'] = page.summary

        categories = []
        for category in page.categories:
            categories.append(category)
        result['categories'] = categories
        result['text'] = page.text

        links = []
        for link_key_word in page.links:
            links.append(link_key_word)
        result['links'] =  links

        backlinks = []
        for link_key_word in page.backlinks:
            backlinks.append(link_key_word)
        result['backlinks'] =  backlinks
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def search_wikipedia_summary(
    keyword: str, cache_dir: str = "./cache"
) -> str:
    """
    Search Wikipedia and return page summary in specified format.
    
    Args:
        keyword: Search term
        cache_dir: Directory to store cached results, the path of cache file is {cache_dir}/keyword.pkl

    Returns:
        Page summary as string
    """
    result = search_wikipedia_with_cache(keyword, cache_dir)
    if not result:
        return f"No summary found for '{keyword}'"
    return result['summary']


def search_wikipedia_categories(
    keyword: str, cache_dir: str = "./cache"
) -> str:
    """
    Search Wikipedia and return page categories in specified format.
    

    Args:
        keyword: Search term
        cache_dir: Directory to store cached results, the path of cache file is {cache_dir}/keyword.pkl

    Returns:
        Page categories as string
    """
    result = search_wikipedia_with_cache(keyword, cache_dir)

    if not result:
        return f"No categories found for '{keyword}'"

    return "\n".join(result['categories'])


def search_wikipedia_text(
    keyword: str, cache_dir: str = "./cache"
) -> str:
    """
    Search Wikipedia and return page text in specified format.

    Args:
        keyword: Search term
        cache_dir: Directory to store cached results, the path of cache file is {cache_dir}/keyword.pkl

    Returns:
        Page text as string
    """
    result = search_wikipedia_with_cache(keyword, cache_dir)
    if not result:
        return f"No text found for '{keyword}'"
    return result['text']

def search_wikipedia_links(
    keyword: str, cache_dir: str = "./cache"
) -> str:
    """
    Search Wikipedia and return keywords (link from this page) in specified format.

    Args:
        keyword: Search term
        cache_dir: Directory to store cached results, the path of cache file is {cache_dir}/keyword.pkl

    Returns:
        Page links as string
    """
    result = search_wikipedia_with_cache(keyword, cache_dir)
    if not result:
        return f"No links found for '{keyword}'"

    return "\n".join(result['links'])

def search_wikipedia_backlinks(
    keyword: str, cache_dir: str = "./cache"
) -> str:
    """
    Search Wikipedia and return keywords(link to this page) in specified format.

    Args:
        keyword: Search term
        cache_dir: Directory to store cached results, the path of cache file is {cache_dir}/keyword.pkl

    Returns:
        Page backlinks as string
    """
    result = search_wikipedia_with_cache(keyword, cache_dir)
    if not result:
        return f"No backlinks found for '{keyword}'"
    
    return "\n".join(result['backlinks'])


if __name__ == "__main__":
    result = search_wikipedia_summary("SB431542", "./cache")
    print(result)
    print("-"*300)
    result = search_wikipedia_summary("Organoid", "./cache")
    print(result)
    print("-"*300)
    result = search_wikipedia_summary("Cell", "./cache")
    print(result)
    # print("-"*300)
    # result = search_wikipedia_backlinks("Organoid", "./cache")
    # print(result)