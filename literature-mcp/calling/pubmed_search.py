import hashlib
import json
import requests
from typing import Optional
import os
import time
from xml.etree import ElementTree as ET

def pubmed_data_to_dict(pubmed_result:dict) -> dict:
    return {
        "abstract": pubmed_result.get('abstract', ''),
        "doi": pubmed_result.get('doi', ''),
        "title": pubmed_result.get('title', ''),
        "keywords": pubmed_result.get('keywords', []),
        "pmid": pubmed_result.get('pmid', ''),
    }


def fetch_pubmed_by_pmid(pmid: str) -> Optional[dict]:
    """
    Fetch article meta info (abstract, DOI, keywords, title) from PubMed using PMID.
    
    Args:
        pmid: PubMed ID (e.g., '31452104', '12345678')
    
    Returns:
        Dictionary containing article information or None if not found
    """
    base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
    
    # use efetch to get article info
    fetch_url = f'{base_url}efetch.fcgi'
    fetch_params = {
        'db': 'pubmed',
        'id': pmid,
        'retmode': 'xml'
    }
    
    try:
        fetch_response = requests.get(fetch_url, params=fetch_params, timeout=30)
        fetch_response.raise_for_status()
        
        # check response content
        if not fetch_response.content:
            print(f"Warning: Empty response for PMID {pmid}")
            return None
        
        root = ET.fromstring(fetch_response.content)
        article = root.find('.//PubmedArticle')
        
        if article is None:
            print(f"Warning: No PubmedArticle found for PMID {pmid}")
            return None
        
        # extract basic info
        result = {
            'pmid': pmid,
            'title': '',
            'abstract': '',
            'keywords': [],
            'authors': [],
            'journal': '',
            'publication_date': '',
            'doi': ''
        }
        
        # extract title
        title_elem = article.find('.//ArticleTitle')
        if title_elem is not None:
            result['title'] = title_elem.text or ''
        
        # extract abstract
        abstract_elem = article.find('.//AbstractText')
        if abstract_elem is not None:
            # handle possible multiple AbstractText nodes
            abstract_texts = article.findall('.//AbstractText')
            if len(abstract_texts) == 1:
                result['abstract'] = abstract_texts[0].text or ''
            else:
                # multiple abstract parts: merge them
                abstract_parts = []
                for ab in abstract_texts:
                    label = ab.get('Label', '')
                    text = ab.text or ''
                    if label:
                        abstract_parts.append(f"{label}: {text}")
                    else:
                        abstract_parts.append(text)
                result['abstract'] = ' '.join(abstract_parts)
        
        # extract keywords
        keyword_list = article.find('.//KeywordList')
        if keyword_list is not None:
            keywords = keyword_list.findall('.//Keyword')
            result['keywords'] = [kw.text for kw in keywords if kw.text]
        
        # if no KeywordList, try extracting from MeshHeadingList
        if not result['keywords']:
            mesh_list = article.find('.//MeshHeadingList')
            if mesh_list is not None:
                mesh_headings = mesh_list.findall('.//DescriptorName')
                result['keywords'] = [mh.text for mh in mesh_headings if mh.text]
        
        # extract authors
        author_list = article.find('.//AuthorList')
        if author_list is not None:
            authors = author_list.findall('.//Author')
            for author in authors:
                last_name = author.find('.//LastName')
                first_name = author.find('.//ForeName')
                affiliations = author.findall('.//AffiliationInfo')
                affil_list = []
                for aff in affiliations:
                    affiliation = aff.find('.//Affiliation')
                    # affiliation can be handled here if needed
                    if affiliation is not None and affiliation.text:
                        affil_list.append(affiliation.text)

                if last_name is not None:
                    author_name = last_name.text or ''
                    if first_name is not None:
                        author_name += f" {first_name.text or ''}"
                    result['authors'].append({'name': author_name.strip(), "affiliations":affil_list})
        
        # extract journal info
        journal_elem = article.find('.//Journal/Title')
        if journal_elem is not None:
            result['journal'] = journal_elem.text or ''
        
        # extract publication date
        pub_date_elem = article.find('.//PubDate')
        if pub_date_elem is not None:
            year = pub_date_elem.find('.//Year')
            month = pub_date_elem.find('.//Month')
            day = pub_date_elem.find('.//Day')
            date_parts = []
            if year is not None:
                date_parts.append(year.text or '')
            if month is not None:
                date_parts.append(month.text or '')
            if day is not None:
                date_parts.append(day.text or '')
            result['publication_date'] = '-'.join(date_parts) if date_parts else ''
        
        # extract DOI
        article_id_list = article.find('.//ArticleIdList')
        if article_id_list is not None:
            doi_elem = article_id_list.find('.//ArticleId[@IdType="doi"]')
            if doi_elem is not None:
                result['doi'] = doi_elem.text or ''
        
        return result
    
    except requests.exceptions.RequestException as e:
        print(f"Network error fetching PubMed data by PMID {pmid}: {e}")
        return None
    except ET.ParseError as e:
        print(f"XML parsing error for PMID {pmid}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error fetching PubMed data by PMID {pmid}: {e}")
        import traceback
        traceback.print_exc()
        return None


def fetch_pubmed_by_doi(doi: str) -> Optional[dict]:
    """
    Fetch article meta info (abstract, DOI, keywords, title) from PubMed using DOI.
    
    Args:
        doi: Digital Object Identifier (e.g., '10.1038/s41586-019-1507-6')
    
    Returns:
        Dictionary containing article information or None if not found
    """
    base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
    
    # Step 1: search by DOI to obtain PMID
    search_url = f'{base_url}esearch.fcgi'
    search_params = {
        'db': 'pubmed',
        'term': f'{doi}[DOI]',
        'retmode': 'json',
        'retmax': 1
    }
    
    try:
        time.sleep(0.34)  # respect NCBI rate limits (max 3 requests/sec)
        search_response = requests.get(search_url, params=search_params)
        search_response.raise_for_status()
        search_data = search_response.json()
        
        if not search_data.get('esearchresult', {}).get('idlist'):
            return None
        
        pmid = search_data['esearchresult']['idlist'][0]
        
        # Step 2: fetch article info with PMID
        time.sleep(0.34)  # respect NCBI rate limits
        return fetch_pubmed_by_pmid(pmid)
    
    except requests.exceptions.RequestException as e:
        print(f"Network error fetching PubMed data by DOI {doi}: {e}")
        return None
    except Exception as e:
        print(f"Error fetching PubMed data by DOI {doi}: {e}")
        import traceback
        traceback.print_exc()
        return None


def fetch_pubmed_by_pmid_with_cache(pmid: str, cache_dir: str) -> Optional[dict]:
    """
    Fetch PubMed article information by PMID with caching to avoid redundant requests.
    
    Args:
        pmid: PubMed ID (e.g., '31452104', '12345678')
        cache_dir: Directory to store cached results
    
    Returns:
        Dictionary containing article information or None if not found
    """
    # use PMID as cache file name
    cache_file = os.path.join(cache_dir, f"pubmed_pmid_{pmid}.json")
    
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding='utf-8') as f:
            return json.load(f)
    
    result = fetch_pubmed_by_pmid(pmid)
    
    if result:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w", encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    
    return result


def fetch_pubmed_by_doi_with_cache(doi: str, cache_dir: str) -> Optional[dict]:
    """
    Fetch PubMed article information by DOI with caching to avoid redundant requests.
    
    Args:
        doi: Digital Object Identifier (e.g., '10.1038/s41586-019-1507-6')
        cache_dir: Directory to store cached results
    
    Returns:
        Dictionary containing article information or None if not found
    """
    # use DOI as cache file name (sanitize special chars)
    safe_doi = doi.replace('/', '_').replace(':', '_')
    cache_file = os.path.join(cache_dir, f"pubmed_doi_{safe_doi}.json")
    
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding='utf-8') as f:
            return json.load(f)
    
    result = fetch_pubmed_by_doi(doi)
    
    if result:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w", encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    
    return result


def get_pubmed_by_pmid(pmid: str, cache_dir: str) -> str:
    """
    Get PubMed article meta info (abstract, DOI, keywords, title) by PMID, formatted for MCP tool usage.
    
    Args:
        pmid: PubMed ID (e.g., '31452104', '12345678')
        cache_dir: Directory to store cached results
    
    Returns:
        JSON string with meta info (abstract, DOI, keywords, title) only
    """
    data = fetch_pubmed_by_pmid_with_cache(pmid, cache_dir)
    
    if not data:
        return json.dumps({"error": f"No information found for PMID '{pmid}'"})
    
    return json.dumps(pubmed_data_to_dict(data), ensure_ascii=False)


def get_pubmed_by_doi(doi: str, cache_dir: str) -> str:
    """
    Get PubMed article meta info (abstract, DOI, keywords, title) by DOI, formatted for MCP tool usage.
    
    Args:
        doi: Digital Object Identifier (e.g., '10.1038/s41586-019-1507-6')
        cache_dir: Directory to store cached results
    
    Returns:
        JSON string with meta info (abstract, DOI, keywords, title) only
    """
    data = fetch_pubmed_by_doi_with_cache(doi, cache_dir)
    
    if not data:
        return json.dumps({"error": f"No information found for DOI '{doi}'"})
        
    return json.dumps(pubmed_data_to_dict(data), ensure_ascii=False)


def fetch_pubmed_by_pmcid(pmcid: str) -> Optional[dict]:
    """
    Fetch article meta info (abstract, DOI, keywords, title) from PubMed using PMCID.
    
    Args:
        pmcid: PubMed Central ID (e.g., 'PMC1234567' or '1234567')
    
    Returns:
        Dictionary containing article information or None if not found
    """
    base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
    
    # normalize PMCID format (ensure PMC prefix)
    pmcid_clean = pmcid.upper().strip()
    if not pmcid_clean.startswith('PMC'):
        pmcid_clean = f'PMC{pmcid_clean}'
    
    # Step 1: search by PMCID to obtain PMID
    # Method 1: find PMCID in pmc DB, then elink to pubmed
    search_url = f'{base_url}esearch.fcgi'
    
    # strip PMC prefix; keep digits only for search
    pmcid_number = pmcid_clean.replace('PMC', '').strip()
    
    # search in pmc database first
    search_params_pmc = {
        'db': 'pmc',
        'term': pmcid_number,
        'retmode': 'json',
        'retmax': 1
    }
    
    try:
        time.sleep(0.34)  # respect NCBI rate limits (max 3 requests/sec)
        search_response_pmc = requests.get(search_url, params=search_params_pmc, timeout=30)
        search_response_pmc.raise_for_status()
        search_data_pmc = search_response_pmc.json()
        
        pmc_idlist = search_data_pmc.get('esearchresult', {}).get('idlist', [])
        if not pmc_idlist:
            print(f"Warning: No PMC record found for PMCID {pmcid}")
            return None
        
        pmc_id = pmc_idlist[0]
        
        # use elink to link PMC ID to PubMed ID
        link_url = f'{base_url}elink.fcgi'
        link_params = {
            'dbfrom': 'pmc',
            'db': 'pubmed',
            'id': pmc_id,
            'retmode': 'json'
        }
        time.sleep(0.34)
        link_response = requests.get(link_url, params=link_params, timeout=30)
        link_response.raise_for_status()
        link_data = link_response.json()
        
        # extract linked PMID
        linksets = link_data.get('linksets', [])
        if not linksets or not linksets[0].get('linksetdbs', []):
            print(f"Warning: No PMID linked to PMCID {pmcid}")
            return None
        
        pmid_list = linksets[0]['linksetdbs'][0].get('links', [])
        if not pmid_list:
            print(f"Warning: No PMID linked to PMCID {pmcid}")
            return None
        
        pmid = str(pmid_list[0])
        
        # Step 2: fetch article info with PMID
        time.sleep(0.34)  # respect NCBI rate limits
        return fetch_pubmed_by_pmid(pmid)
    
    except requests.exceptions.RequestException as e:
        print(f"Network error fetching PubMed data by PMCID {pmcid}: {e}")
        return None
    except Exception as e:
        print(f"Error fetching PubMed data by PMCID {pmcid}: {e}")
        import traceback
        traceback.print_exc()
        return None


def fetch_pubmed_by_pmcid_with_cache(pmcid: str, cache_dir: str) -> Optional[dict]:
    """
    Fetch PubMed article information by PMCID with caching to avoid redundant requests.
    
    Args:
        pmcid: PubMed Central ID (e.g., 'PMC1234567' or '1234567')
        cache_dir: Directory to store cached results
    
    Returns:
        Dictionary containing article information or None if not found
    """
    # normalize PMCID for cache file name
    pmcid_clean = pmcid.upper().replace('PMC', '').strip()
    cache_file = os.path.join(cache_dir, f"pubmed_pmcid_{pmcid_clean}.json")
    
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding='utf-8') as f:
            return json.load(f)
    
    result = fetch_pubmed_by_pmcid(pmcid)
    
    if result:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w", encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    
    return result


def get_pubmed_by_pmcid(pmcid: str, cache_dir: str) -> str:
    """
    Get PubMed article meta info (abstract, DOI, keywords, title) by PMCID, formatted for MCP tool usage.
    
    Args:
        pmcid: PubMed Central ID (e.g., 'PMC1234567' or '1234567')
        cache_dir: Directory to store cached results
    
    Returns:
        JSON string with meta info (abstract, DOI, keywords, title) only
    """
    data = fetch_pubmed_by_pmcid_with_cache(pmcid, cache_dir)
    
    if not data:
        return json.dumps({"error": f"No information found for PMCID '{pmcid}'"})
    
    return json.dumps(pubmed_data_to_dict(data), ensure_ascii=False)


def fetch_pubmed_list_by_text(text: str, cache_dir: str) -> Optional[list[dict]]:
    """
    Fetch the list of searched article by text from PubMed.
    
    Args:
        text: Search text (e.g., 'Organoid')
    
    Returns:
        List of dictionaries containing article information or None if not found
    """
    base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
    
    # Step 1: search by DOI to obtain PMID
    search_url = f'{base_url}esearch.fcgi'
    search_params = {
        'db': 'pubmed',
        'term': f'{text}',
        'retmode': 'json',
        'retmax': 10
    }
    
    try:
        time.sleep(0.34)  # respect NCBI rate limits (max 3 requests/sec)
        search_response = requests.get(search_url, params=search_params)
        search_response.raise_for_status()
        search_data = search_response.json()
        
        if not search_data.get('esearchresult', {}).get('idlist'):
            return None
        
        pmids = search_data['esearchresult']['idlist']
        
        # Step 2: fetch article info with PMID
        time.sleep(0.34)  # respect NCBI rate limits
        result = []
        for pmid in pmids:
            result.append(fetch_pubmed_by_pmid_with_cache(pmid, cache_dir))
        return result
    
    except requests.exceptions.RequestException as e:
        print(f"Network error fetching PubMed data by text {text}: {e}")
        return None
    except Exception as e:
        print(f"Error fetching PubMed data by text {text}: {e}")
        import traceback
        traceback.print_exc()
        return None


def fetch_pubmed_list_by_text_with_cache(text: str, cache_dir: str) -> Optional[list[dict]]:
    """
    Fetch PubMed article information by Title with caching to avoid redundant requests.
    
    Args:
        text: Search text (e.g., 'Organoid')
        cache_dir: Directory to store cached results
    
    Returns:
        Dictionary containing article information or None if not found
    """
    # use text as cache file name (sanitize special chars)
    safe_text = hashlib.md5(text.encode('utf-8')).hexdigest()
    cache_file = os.path.join(cache_dir, f"pubmed_text_{safe_text}.json")
    
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding='utf-8') as f:
            return json.load(f)
    
    result = fetch_pubmed_list_by_text(text, cache_dir)
    
    if result:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w", encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    
    return result

def get_pubmed_by_text(text: str, cache_dir: str) -> str:
    """
    Get List of PubMed article meta info (abstract, DOI, keywords, title) by text/title, formatted for MCP tool usage.
    
    Args:
        text: Search text (e.g., 'Organoid')
        cache_dir: Directory to store cached results
    
    Returns:
        the list of JSON string with meta info (abstract, DOI, keywords, title) only
    """
    data_list = fetch_pubmed_list_by_text_with_cache(text, cache_dir)
    
    if not data_list:
        return json.dumps({"error": f"No information found for text '{text}'"})
    
    result = []
    for data in data_list:
        if data is None:
            continue
        result.append(pubmed_data_to_dict(data))
    
    return json.dumps(result, ensure_ascii=False)
