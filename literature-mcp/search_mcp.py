import time
import asyncio
from fastmcp import FastMCP, utilities
from typing import List
import json
import os
from calling.wiki_search import (
    search_wikipedia_summary,
    search_wikipedia_categories,
    search_wikipedia_text,
    search_wikipedia_links,
    search_wikipedia_backlinks
)

from calling.gse_search import (
    search_gse_summary,
    search_gse_full_info,
    search_gpl_full_info,
    search_gsm_full_info
)

from calling.gene_search import (
    search_gene_summary,
    search_gene_full_info,
)

from calling.google_search import (
    search_from_google_with_cache,
    search_web_with_cache,
)

from calling.pubmed_search import (
    get_pubmed_by_pmid,
    get_pubmed_by_doi,
    get_pubmed_by_pmcid,
    get_pubmed_by_text,
)   

from pydantic import BaseModel

# initialize FastMCP service
mcp = FastMCP("wikipedia-search-service")
cache_dir = "./cache"
logger = utilities.logging.get_logger("call")

# global lock for Google search to avoid rate limits under concurrency
_google_search_lock = asyncio.Lock()

@mcp.tool()
async def get_wikipedia_summary(keywords: List) -> str:
    """
    Search Wikipedia and return page summary.
    
    Args:
        keywords[List[str]]: Search terms to look up on Wikipedia

    Returns:
        JSON string:
        {"keyword1":"summary of keyword1", "keyword2":"summary of keyword2", "keyword3":"not found, need to check", ...}
    """
    logger.info(f"Searching Wikipedia for summary related to keywords: {keywords}")
    summaries = {}
    
    # deduplicate
    unique_keywords = []
    seen = set()
    for keyword in keywords:
        if keyword in seen:
            logger.info(f"[get_wikipedia_summary] Duplicate keyword: {keyword}")
            continue
        seen.add(keyword)
        unique_keywords.append(keyword)
    
    # process all keywords concurrently
    async def fetch_one(keyword):
        logger.info(f"[get_wikipedia_summary] related to: {keyword}")
        result = await asyncio.to_thread(
            search_wikipedia_summary, 
            keyword, 
            os.path.join(cache_dir, "wikipedia")
        )
        return keyword, result
    
    results = await asyncio.gather(*[fetch_one(kw) for kw in unique_keywords])
    
    for keyword, summary in results:
        summaries[keyword] = summary

    return json.dumps(summaries, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_wikipedia_categories(keywords: List[str]) -> str:
    """
    Search Wikipedia and return page categories.

    Args:
        keywords[List[str]]: Search terms to look up on Wikipedia

    Returns:
        JSON string:
        {"keyword1":"categories of keyword1", "keyword2":"categories of keyword2", "keyword3":"not found, need to check", ...}
    """
    logger.info(f"Searching Wikipedia for categories related to: {keywords}")
    categories = {}
    
    # deduplicate
    unique_keywords = []
    seen = set()
    for keyword in keywords:
        if keyword in seen:
            logger.info(f"[get_wikipedia_categories] Duplicate keyword: {keyword}")
            continue
        seen.add(keyword)
        unique_keywords.append(keyword)
    
    # process concurrently
    async def fetch_one(keyword):
        logger.info(f"[get_wikipedia_categories] related to: {keyword}")
        result = await asyncio.to_thread(
            search_wikipedia_categories,
            keyword,
            os.path.join(cache_dir, "wikipedia")
        )
        return keyword, result
    
    results = await asyncio.gather(*[fetch_one(kw) for kw in unique_keywords])
    
    for keyword, category in results:
        categories[keyword] = category
    
    return json.dumps(categories, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_wikipedia_text(keywords: List[str]) -> str:
    """
    Search Wikipedia and return full page text content.

    Args:
        keywords: Search terms to look up on Wikipedia

    Returns:
        JSON string:
        {"keyword1":"full text of keyword1", "keyword2":"full text of keyword2", "keyword3":"not found, need to check", ...}
    """
    logger.info(f"Searching Wikipedia for full text content related to: {keywords}")

    texts = {}
    
    # deduplicate
    unique_keywords = []
    seen = set()
    for keyword in keywords:
        if keyword in seen:
            logger.info(f"[get_wikipedia_text] Duplicate keyword: {keyword}")
            continue
        seen.add(keyword)
        unique_keywords.append(keyword)
    
    # process concurrently
    async def fetch_one(keyword):
        logger.info(f"[get_wikipedia_text] related to: {keyword}")
        result = await asyncio.to_thread(
            search_wikipedia_text,
            keyword,
            os.path.join(cache_dir, "wikipedia")
        )
        return keyword, result
    
    results = await asyncio.gather(*[fetch_one(kw) for kw in unique_keywords])
    
    for keyword, text in results:
        texts[keyword] = text

    return json.dumps(texts, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_wikipedia_links(keywords: List[str]) -> str:
    """
    Search Wikipedia and return all outgoing links from the page.

    Args:
        keywords: Search terms to look up on Wikipedia

    Returns:
        JSON string:
        {"keyword1":"links of keyword1", "keyword2":"links of keyword2", "keyword3":"not found, need to check", ...}
    """
    logger.info(f"Searching Wikipedia for outgoing links related to: {keywords}")

    links = {}
    
    # deduplicate
    unique_keywords = []
    seen = set()
    for keyword in keywords:
        if keyword in seen:
            logger.info(f"[get_wikipedia_links] Duplicate keyword: {keyword}")
            continue
        seen.add(keyword)
        unique_keywords.append(keyword)
    
    # process concurrently
    async def fetch_one(keyword):
        logger.info(f"[get_wikipedia_links] related to: {keyword}")
        result = await asyncio.to_thread(
            search_wikipedia_links,
            keyword,
            os.path.join(cache_dir, "wikipedia")
        )
        return keyword, result
    
    results = await asyncio.gather(*[fetch_one(kw) for kw in unique_keywords])
    
    for keyword, link in results:
        links[keyword] = link

    return json.dumps(links, ensure_ascii=False, indent=2)
    

@mcp.tool()
async def get_wikipedia_backlinks(keywords: List[str]) -> str:
    """
    Search Wikipedia and return all incoming links to the page.

    Args:
        keywords: Search terms to look up on Wikipedia

    Returns:
        JSON string:
        {"keyword1":"links of keyword1", "keyword2":"links of keyword2", "keyword3":"not found, need to check", ...}
    """
    logger.info(f"Searching Wikipedia for backlinks related to: {keywords}")

    backlinks = {}
    
    # deduplicate
    unique_keywords = []
    seen = set()
    for keyword in keywords:
        if keyword in seen:
            logger.info(f"[get_wikipedia_backlinks] Duplicate keyword: {keyword}")
            continue
        seen.add(keyword)
        unique_keywords.append(keyword)
    
    # process concurrently
    async def fetch_one(keyword):
        logger.info(f"[get_wikipedia_backlinks] related to: {keyword}")
        result = await asyncio.to_thread(
            search_wikipedia_backlinks,
            keyword,
            os.path.join(cache_dir, "wikipedia")
        )
        return keyword, result
    
    results = await asyncio.gather(*[fetch_one(kw) for kw in unique_keywords])
    
    for keyword, backlink in results:
        backlinks[keyword] = backlink

    return json.dumps(backlinks, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_gse_summary(gse_ids: List[str]) -> str:
    """
    Search GEO and return GSE summary.

    Args:
        gse_ids: List of GSE IDs (e.g., ['GSE12345', 'GSE67890'])

    Returns:
        JSON string: 
        {"keyword1":"summary of keyword1", "keyword2":"summary of keyword2", "keyword3":"not found, need to check", ...}
    """
    logger.info(f"Searching GEO for summary related to: {gse_ids}")
    summaries = {}
    
    # deduplicate
    unique_ids = []
    seen = set()
    for gse_id in gse_ids:
        if gse_id in seen:
            logger.info(f"[get_gse_summary] Duplicate GSE ID: {gse_id}")
            continue
        seen.add(gse_id)
        unique_ids.append(gse_id)
    
    # process concurrently
    async def fetch_one(gse_id):
        logger.info(f"[get_gse_summary] related to: {gse_id}")
        result = await asyncio.to_thread(
            search_gse_summary,
            gse_id,
            os.path.join(cache_dir, "geo")
        )
        return gse_id, result
    
    results = await asyncio.gather(*[fetch_one(gse_id) for gse_id in unique_ids])
    
    for gse_id, summary in results:
        summaries[gse_id] = summary

    return json.dumps(summaries, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_gse_full_info(gse_ids: List[str]) -> str:
    """
    Search GEO and return full GSE information.

    Args:
        gse_ids: List of GSE IDs (e.g., ['GSE12345', 'GSE67890'])

    Returns:
        JSON string: 
        {"keyword1":"full info of keyword1", "keyword2":"full info of keyword2", "keyword3":"not found, need to check", ...}
    """
    logger.info(f"Searching GEO for full info related to: {gse_ids}")

    summaries = {}
    
    # deduplicate
    unique_ids = []
    seen = set()
    for gse_id in gse_ids:
        if gse_id in seen:
            logger.info(f"[get_gse_full_info] Duplicate GSE ID: {gse_id}")
            continue
        seen.add(gse_id)
        unique_ids.append(gse_id)
    
    # process concurrently
    async def fetch_one(gse_id):
        logger.info(f"[get_gse_full_info] related to: {gse_id}")
        result = await asyncio.to_thread(
            search_gse_full_info,
            gse_id,
            os.path.join(cache_dir, "geo")
        )
        return gse_id, result
    
    results = await asyncio.gather(*[fetch_one(gse_id) for gse_id in unique_ids])
    
    for gse_id, info in results:
        summaries[gse_id] = info

    return json.dumps(summaries, ensure_ascii=False, indent=2)

@mcp.tool()
async def get_gpl_full_info(gpl_ids: List[str]) -> str:
    """
    Search GEO and return full GPL information.

    Args:
        gpl_ids: List of GPL IDs (e.g., ['GPL12345', 'GPL67890'])
    Returns:
        JSON string: 
        {"keyword1":"full info of keyword1", "keyword2":"full info of keyword2", "keyword3":"not found, need to check", ...}
    """
    logger.info(f"Searching GEO for full info related to: {gpl_ids}")

    summaries = {}
    
    # deduplicate
    unique_ids = []
    seen = set()
    for gpl_id in gpl_ids:
        if gpl_id in seen:
            logger.info(f"[get_gpl_full_info] Duplicate GPL ID: {gpl_id}")
            continue
        seen.add(gpl_id)
        unique_ids.append(gpl_id)
    
    # process concurrently
    async def fetch_one(gpl_id):
        logger.info(f"[get_gpl_full_info] related to: {gpl_id}")
        result = await asyncio.to_thread(
            search_gpl_full_info,
            gpl_id,
            os.path.join(cache_dir, "geo")
        )
        return gpl_id, result
    
    results = await asyncio.gather(*[fetch_one(gpl_id) for gpl_id in unique_ids])
    
    for gpl_id, info in results:
        summaries[gpl_id] = info

    return json.dumps(summaries, ensure_ascii=False, indent=2)

@mcp.tool()
async def get_gsm_full_info(gsm_ids: List[str]) -> str:
    """
    Search GEO and return full GSM information.

    Args:
        gsm_ids: List of GSM IDs (e.g., ['GSM12345', 'GSM67890'])

    Returns:
        JSON string: 
        {"keyword1":"full info of keyword1", "keyword2":"full info of keyword2", "keyword3":"not found, need to check", ...}
    """
    logger.info(f"Searching GEO for full info related to: {gsm_ids}")

    summaries = {}
    
    # deduplicate
    unique_ids = []
    seen = set()
    for gsm_id in gsm_ids:
        if gsm_id in seen:
            logger.info(f"[get_gsm_full_info] Duplicate GSM ID: {gsm_id}")
            continue
        seen.add(gsm_id)
        unique_ids.append(gsm_id)
    
    # process concurrently
    async def fetch_one(gsm_id):
        logger.info(f"[get_gsm_full_info] related to: {gsm_id}")
        result = await asyncio.to_thread(
            search_gsm_full_info,
            gsm_id,
            os.path.join(cache_dir, "geo")
        )
        return gsm_id, result
    
    results = await asyncio.gather(*[fetch_one(gsm_id) for gsm_id in unique_ids])
    
    for gsm_id, info in results:
        summaries[gsm_id] = info

    return json.dumps(summaries, ensure_ascii=False, indent=2)

class GeneQueryInput(BaseModel):
    gene_name: str
    organism: str

@mcp.tool()
async def get_gene_summary(querys:List[GeneQueryInput]) -> str:
    """
    Search NCBI Gene database and return gene summary.

    Args:
        querys: List of GeneQueryInput objects containing gene_name(str) and organism(str)
        example: [{"gene_name": "TP53", "organism": "Homo sapiens"}, {"gene_name": "BRCA1", "organism": "Mus musculus"}]

    Returns:
        JSON string: 
        [
            {"gene_name":"gene_name1", "organism": "organism1", "summary": "summary of gene_name1 in organism1"},
            {"gene_name":"gene_name2", "organism": "organism2", "summary": "summary of gene_name2 in organism2"},
            {"gene_name":"gene_name3", "organism": "organism3", "summary": "not found, need to check"},
            ...
        ]
    """
    logger.info(f"Searching NCBI Gene database for summary related to: {querys}")

    results = []
    
    # deduplicate
    unique_querys = []
    keys = set()
    for query in querys:
        gene_name = query.gene_name
        organism = query.organism
        combine_key = f"{gene_name}---{organism}"
        if combine_key in keys:
            logger.info(f"[get_gene_summary] Duplicate gene query: {combine_key}")
            continue
        keys.add(combine_key)
        unique_querys.append(query)
    
    # process concurrently
    async def fetch_one(query):
        gene_name = query.gene_name
        organism = query.organism
        logger.info(f"[get_gene_summary] related to: {gene_name} in {organism}")
        summary = await asyncio.to_thread(
            search_gene_summary,
            gene_name,
            organism,
            os.path.join(cache_dir, "gene")
        )
        return {
            "gene_name": gene_name,
            "organism": organism,
            "summary": summary
        }
    
    results = await asyncio.gather(*[fetch_one(query) for query in unique_querys])
    
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_gene_full_info(querys:List[GeneQueryInput]) -> str:
    """
    Search NCBI Gene database and return gene full info.

    Args:
        querys: List of GeneQueryInput objects containing gene_name(str) and organism(str)
        example: [{"gene_name": "TP53", "organism": "Homo sapiens"}, {"gene_name": "BRCA1", "organism": "Mus musculus"}]

    Returns:
        JSON string: 
        [
            {"gene_name":"gene_name1", "organism": "organism1", "info": "full info of gene_name1 in organism1"},
            {"gene_name":"gene_name2", "organism": "organism2", "info": "full info of gene_name2 in organism2"},
            {"gene_name":"gene_name3", "organism": "organism3", "info": "not found, need to check"},
            ...
        ]
    """
    logger.info(f"Searching NCBI Gene database for full info related to: {querys}")

    results = []
    
    # deduplicate
    unique_querys = []
    keys = set()
    for query in querys:
        gene_name = query.gene_name
        organism = query.organism
        combine_key = f"{gene_name}---{organism}"
        if combine_key in keys:
            logger.info(f"[get_gene_full_info] Duplicate gene query: {combine_key}")
            continue
        keys.add(combine_key)
        unique_querys.append(query)
    
    # process concurrently
    async def fetch_one(query):
        gene_name = query.gene_name
        organism = query.organism
        logger.info(f"[get_gene_full_info] related to: {gene_name} in {organism}")
        info = await asyncio.to_thread(
            search_gene_full_info,
            gene_name,
            organism,
            os.path.join(cache_dir, "gene")
        )
        return {
            "gene_name": gene_name,
            "organism": organism,
            "info": info
        }
    
    results = await asyncio.gather(*[fetch_one(query) for query in unique_querys])
    
    return json.dumps(results, ensure_ascii=False, indent=2)

@mcp.tool()
async def google_search(querys: List[str]) -> str:
    """
    Using Google Custom Search Engine (CSE) to perform web search.

    Args:
        querys (List[str]): List of search queries.

    Returns:
        JSON string: [{'query':'query words1', 'result':[]},{'query':'query words2', 'result':[]},{'query':'query words3', 'result':[]},...]
    """
    logger.info(f"Searching Google for queries: {querys}")
    results = []
    
    # use global lock for serial execution to avoid rate limits
    async with _google_search_lock:
        for query in querys:
            logger.info(f"🔍[google_search] related to: {query}")
            result, is_cached = search_web_with_cache(query, 10, cache_dir=os.path.join(cache_dir, "google"))
            if not is_cached:
                await asyncio.sleep(3)  # extra delay to more safely avoid rate limits
            results.append(result)
            logger.info(f"✅[google_search] related to: {query}")
    return json.dumps(results, ensure_ascii=False, indent=2)

@mcp.tool()
async def get_pubmed_article_by_pmid(pmids: List[str]) -> str:
    """
    Search PubMed by PMIDs and return article information.

    Args:
        pmids (List[str]): List of PubMed IDs.  e.g. ['31452104', '12345678',...]
        pmid: PubMed ID (e.g., '31452104', '12345678')
    Returns:
        JSON string: 
        [
            {"pmid":"pmid1", "info": "info of pmid1"},
            {"pmid":"pmid2", "info": "info of pmid2"},
            {"pmid":"pmid3", "info": "not found, need to check"},
            ...
        ]
    """
    logger.info(f"Searching PubMed for PMIDs: {pmids}")

    results = []
    
    # deduplicate
    unique_pmids = []
    keys = set()
    for pmid in pmids:
        if pmid in keys:
            logger.info(f"[pubmed_search_by_pmid] Duplicate PMID query: {pmid}")
            continue
        keys.add(pmid)
        unique_pmids.append(pmid)
    
    # process concurrently
    async def fetch_one(pmid):
        logger.info(f"[pubmed_search_by_pmid] related to: {pmid}")
        info = await asyncio.to_thread(
            get_pubmed_by_pmid,
            pmid,
            os.path.join(cache_dir, "pubmed")
        )
        return {
            "pmid": pmid,
            "info": info
        }
    
    results = await asyncio.gather(*[fetch_one(pmid) for pmid in unique_pmids])
    
    return json.dumps(results, ensure_ascii=False, indent=2)

@mcp.tool()
async def get_pubmed_article_by_doi(dois: List[str]) -> str:
    """
    Search PubMed by DOIs and return article information.

    Args:
        dois (List[str]): List of DOIs.  e.g. ["10.1038/s41586-020-2649-2", "10.14440/jbm.2015.73",...]
    Returns:
        JSON string: 
        [
            {"doi":"doi1", "info": "info of doi1"},
            {"doi":"doi2", "info": "info of doi2"},
            {"doi":"doi3", "info": "not found, need to check"},
            ...
        ]
    """
    logger.info(f"Searching PubMed for DOIs: {dois}")

    results = []
    
    # deduplicate
    unique_dois = []
    keys = set()
    for doi in dois:
        if doi in keys:
            logger.info(f"[pubmed_search_by_doi] Duplicate DOI query: {doi}")
            continue
        keys.add(doi)
        unique_dois.append(doi)
    
    # process concurrently
    async def fetch_one(doi):
        logger.info(f"[pubmed_search_by_doi] related to: {doi}")
        info = await asyncio.to_thread(
            get_pubmed_by_doi,
            doi,
            os.path.join(cache_dir, "pubmed")
        )
        return {
            "doi": doi,
            "info": info
        }
    
    results = await asyncio.gather(*[fetch_one(doi) for doi in unique_dois])
    
    return json.dumps(results, ensure_ascii=False, indent=2)

@mcp.tool()
async def get_pubmed_article_by_pmcid(pmcids: List[str]) -> str:
    """
    Search PubMed by PMCIDs and return article information.

    Args:
        pmcids (List[str]): List of PMC IDs.  e.g. ["PMC4770449", "7987217",...]
    Returns:
        JSON string: 
        [
            {"pmcid":"pmcid1", "info": "info of pmcid1"},
            {"pmcid":"pmcid2", "info": "info of pmcid2"},
            {"pmcid":"pmcid3", "info": "not found, need to check"},
            ...
        ]
    """
    logger.info(f"Searching PubMed for PMCIDs: {pmcids}")

    results = []
    
    # deduplicate
    unique_pmcids = []
    keys = set()
    for pmcid in pmcids:
        if pmcid in keys:
            logger.info(f"[pubmed_search_by_pmcid] Duplicate PMCID query: {pmcid}")
            continue
        keys.add(pmcid)
        unique_pmcids.append(pmcid)
    
    # process concurrently
    async def fetch_one(pmcid):
        logger.info(f"[pubmed_search_by_pmcid] related to: {pmcid}")
        info = await asyncio.to_thread(
            get_pubmed_by_pmcid,
            pmcid,
            os.path.join(cache_dir, "pubmed")
        )
        return {
            "pmcid": pmcid,
            "info": info
        }
    
    results = await asyncio.gather(*[fetch_one(pmcid) for pmcid in unique_pmcids])
    
    return json.dumps(results, ensure_ascii=False, indent=2)

@mcp.tool()
async def get_pubmed_article_by_text(texts: List[str]) -> str:
    """
    Search text in title and abstract in PubMed and return search top 10 results for per text.

    Args:
        texts (List[str]): List of article texts/titles.  e.g. ["CRISPR-Cas9 genome editing induces a p53-mediated DNA damage response", "A high-resolution map of human evolutionary constraint using 29 mammals",...]
    Returns:
        JSON string: 
        [
            {"text":"text1", "infos": [{"abstract":"xxxx","doi":"xxx","title":"xxxx","keywords":["xxx","xxxx"]}, {"abstract":"xxxx","doi":"xxx","title":"xxxx","keywords":["xxx","xxxx"]}, ...]},
            {"text":"text2", "infos": [search result1 of text2, search result2 of text2, ...]},
            {"text":"text3", "infos": "not found, need to check"},
            ...
        ]
    """
    logger.info(f"Searching PubMed for texts: {texts}")
    results = []
    
    # deduplicate
    unique_texts = []
    keys = set()
    for text in texts:
        if text in keys:
            logger.info(f"[pubmed_search_by_text] Duplicate text query: {text}")
            continue
        keys.add(text)
        unique_texts.append(text)
    
    # process concurrently
    async def fetch_one(text):
        logger.info(f"[pubmed_search_by_text] related to: {text}")
        info = await asyncio.to_thread(
            get_pubmed_by_text,
            text,
            os.path.join(cache_dir, "pubmed")
        )
        return {
            "text": text,
            "infos": info
        }
    
    results = await asyncio.gather(*[fetch_one(text) for text in unique_texts])
    
    return json.dumps(results, ensure_ascii=False, indent=2)

@mcp.tool()
async def wait_seconds(seconds: int) -> str:
    """
    Wait for a specified number of seconds.

    Args:
        seconds (int): Number of seconds to wait. Range: 1-60
    Returns:
        str: Confirmation message after waiting.
    """
    logger.info(f"Expect to Wait for {seconds} seconds...")
    if seconds < 1:
        seconds = 1
    if seconds > 60:
        seconds = 60
    await asyncio.sleep(seconds)
    logger.info(f"Finally Waited for {seconds} seconds.")
    return f"Finally Waited for {seconds} seconds."


if __name__ == "__main__":
    mcp.run()