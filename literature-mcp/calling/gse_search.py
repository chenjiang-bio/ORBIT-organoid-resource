import json
import requests
from typing import Optional
from xml.etree import ElementTree as ET
import os

def search_gpl(gpl_id: str, mode: str = 'quick') -> Optional[dict]:
    """
    Search GEO database and return GPL information.
    
    Args:
        gpl_id: GPL ID (e.g., 'GPL570' or '570')
        mode: View mode ('quick' or 'brief')
    Returns:
        Dictionary containing GPL information or None if not found
    """
    # ensure GPL ID format is correct
    if not gpl_id.upper().startswith('GPL'):
        gpl_id = f'GPL{gpl_id}'
    
    # use NCBI E-utilities API
    base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
    
    # Step 1: search and obtain UID
    search_url = f'{base_url}esearch.fcgi'
    search_params = {
        'db': 'gds',
        'term': gpl_id,
        'retmode': 'json'
    }
    
    try:
        search_response = requests.get(search_url, params=search_params)
        search_data = search_response.json()
        
        if not search_data.get('esearchresult', {}).get('idlist'):
            return None
        
        uid = search_data['esearchresult']['idlist'][0]
        
        # Step 2: fetch summary info
        summary_url = f'{base_url}esummary.fcgi'
        summary_params = {
            'db': 'gds',
            'id': uid,
            'retmode': 'json'
        }
        
        summary_response = requests.get(summary_url, params=summary_params)
        summary_data = summary_response.json()
        
        if 'result' not in summary_data or uid not in summary_data['result']:
            return None
        
        result = summary_data['result'][uid]
        
        # Note: GEO API does not support json; supported formats: text(SOFT), xml(MINiML), html
        # optionally fetch extra info in SOFT format if needed
        geo_url = f'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi'
        geo_params = {
            'acc': gpl_id,
            'targ': 'self',
            'form': 'text',  # use SOFT format
            'view': mode
        }
        
        try:
            geo_response = requests.get(geo_url, params=geo_params)
            text = geo_response.text
            # strip lines like !Platform_sample_id = GSM1166059
            filtered_lines = [line for line in text.split('\n') if not line.startswith('!Platform_sample_id') and not line.startswith('!Platform_series_id')]
            result['soft_data'] = '\n'.join(filtered_lines)
        except Exception as soft_error:
            print(f"Error fetching SOFT format: {soft_error}")
        
        return result
    
    except Exception as e:
        print(f"Error fetching GPL data: {e}")
        return None

def search_gsm(gsm_id: str, mode: str) -> Optional[dict]:
    """
    Search GEO database and return GSM information.
    
    Args:
        gsm_id: GSM ID (e.g., 'GSM12345' or '12345')
        mode: View mode ('quick' or 'brief')
    
    Returns:
        Dictionary containing GSM information or None if not found
    """
    # ensure GSM ID format is correct
    if not gsm_id.upper().startswith('GSM'):
        gsm_id = f'GSM{gsm_id}'
    
    # use NCBI E-utilities API
    base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
    
    # Step 1: search and obtain UID
    search_url = f'{base_url}esearch.fcgi'
    search_params = {
        'db': 'gds',
        'term': gsm_id,
        'retmode': 'json'
    }
    
    try:
        search_response = requests.get(search_url, params=search_params)
        search_data = search_response.json()
        
        if not search_data.get('esearchresult', {}).get('idlist'):
            return None
        
        uid = search_data['esearchresult']['idlist'][0]
        
        # Step 2: fetch summary info
        summary_url = f'{base_url}esummary.fcgi'
        summary_params = {
            'db': 'gds',
            'id': uid,
            'retmode': 'json'
        }
        
        summary_response = requests.get(summary_url, params=summary_params)
        summary_data = summary_response.json()
        
        if 'result' not in summary_data or uid not in summary_data['result']:
            return None
        
        result = summary_data['result'][uid]
        
        # Note: GEO API does not support json; supported formats: text(SOFT), xml(MINiML), html
        # optionally fetch extra info in SOFT format if needed
        geo_url = f'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi'
        geo_params = {
            'acc': gsm_id,
            'targ': 'self',
            'form': 'text',  # use SOFT format
            'view': mode
        }
        
        try:
            geo_response = requests.get(geo_url, params=geo_params)
            result['soft_data'] = geo_response.text
        except Exception as soft_error:
            print(f"Error fetching SOFT format: {soft_error}")
        
        return result
    
    except Exception as e:
        print(f"Error fetching GSM data: {e}")
        return None

def search_gse(gse_id: str, mode: str) -> Optional[dict]:
    """
    Search GEO database and return GSE information.
    
    Args:
        gse_id: GSE ID (e.g., 'GSE12345' or '12345')
    
    Returns:
        Dictionary containing GSE information or None if not found
    """
    # ensure GSE ID format is correct
    if not gse_id.upper().startswith('GSE'):
        gse_id = f'GSE{gse_id}'
    
    # use NCBI E-utilities API
    base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
    
    # Step 1: search and obtain UID
    search_url = f'{base_url}esearch.fcgi'
    search_params = {
        'db': 'gds',
        'term': gse_id,
        'retmode': 'json'
    }
    
    try:
        search_response = requests.get(search_url, params=search_params)
        search_data = search_response.json()
        
        if not search_data.get('esearchresult', {}).get('idlist'):
            return None
        
        uid = search_data['esearchresult']['idlist'][0]
        
        # Step 2: fetch summary info
        summary_url = f'{base_url}esummary.fcgi'
        summary_params = {
            'db': 'gds',
            'id': uid,
            'retmode': 'json'
        }
        
        summary_response = requests.get(summary_url, params=summary_params)
        summary_data = summary_response.json()
        
        if 'result' not in summary_data or uid not in summary_data['result']:
            return None
        
        result = summary_data['result'][uid]

        # platform info is usually a GPL ID
        if 'gpl' in result:
            gpl_result = search_gpl(result['gpl'], mode='brief')
            result['platform'] = gpl_result


        # Note: GEO API does not support json; supported formats: text(SOFT), xml(MINiML), html
        # optionally fetch extra info in SOFT format if needed
        geo_url = f'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi'
        geo_params = {
            'acc': gse_id,
            'targ': 'self',
            'form': 'text',  # use SOFT format
            'view': mode
        }
        
        try:
            geo_response = requests.get(geo_url, params=geo_params)
            result['soft_data'] = geo_response.text
        except Exception as soft_error:
            print(f"Error fetching SOFT format: {soft_error}")
        
        return result
    
    except Exception as e:
        print(f"Error fetching GSE data: {e}")
        return None


def remove_soft_data(data: dict) -> dict:
    """
    Recursively remove all 'soft_data' keys from a dictionary at any level.
    
    Args:
        data: Dictionary that may contain 'soft_data' keys at any level
    
    Returns:
        Dictionary with all 'soft_data' keys removed
    """
    if not isinstance(data, dict):
        return data
    
    # create a new dict to avoid mutating the original
    result = {}
    
    for key, value in data.items():
        # skip soft_data key
        if key == 'soft_data':
            continue
        
        # if value is a dict, process recursively
        if isinstance(value, dict):
            result[key] = remove_soft_data(value)
        # if value is a list, process each element
        elif isinstance(value, list):
            result[key] = [
                remove_soft_data(item) if isinstance(item, dict) else item
                for item in value
            ]
        # copy other types as-is
        else:
            result[key] = value
    
    return result

    
def search_gse_with_cache(gse_id: str, mode:str ,cache_dir: str) -> Optional[dict]:
    """
    Search GEO database with caching to avoid redundant requests.
    
    Args:
        gse_id: GSE ID (e.g., 'GSE12345' or '12345')
        cache_dir: Directory to store cached results, the path of cache file is {cache_dir}/gse_id.json

    Returns:
        Dictionary containing GSE information or None if not found
    """
    cache_file = os.path.join(cache_dir, f"{gse_id}_{mode}.json")
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            return json.load(f)

    result = search_gse(gse_id, mode)
    # save cache only when result is not None
    if result is not None:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(result, f)
    
    return result

def search_gpl_with_cache(gpl_id: str, mode: str, cache_dir: str) -> Optional[dict]:
    """
    Search GEO database for GPL with caching to avoid redundant requests.
    
    Args:
        gpl_id: GPL ID (e.g., 'GPL570' or '570')
        mode: View mode ('quick' or 'brief')
        cache_dir: Directory to store cached results

    Returns:
        Dictionary containing GPL information or None if not found
    """
    # ensure GPL ID format is correct
    if not gpl_id.upper().startswith('GPL'):
        gpl_id = f'GPL{gpl_id}'
    
    cache_file = os.path.join(cache_dir, f"{gpl_id}_{mode}.json")
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            return json.load(f)

    result = search_gpl(gpl_id, mode)
    # save cache only when result is not None
    if result is not None:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(result, f)
    
    return result

def search_gsm_with_cache(gsm_id: str, mode: str, cache_dir: str) -> Optional[dict]:
    """
    Search GEO database for GSM with caching to avoid redundant requests.
    
    Args:
        gsm_id: GSM ID (e.g., 'GSM12345' or '12345')
        mode: View mode ('quick' or 'brief')
        cache_dir: Directory to store cached results

    Returns:
        Dictionary containing GSM information or None if not found
    """
    # ensure GSM ID format is correct
    if not gsm_id.upper().startswith('GSM'):
        gsm_id = f'GSM{gsm_id}'
    
    cache_file = os.path.join(cache_dir, f"{gsm_id}_{mode}.json")
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            return json.load(f)

    result = search_gsm(gsm_id, mode)
    # save cache only when result is not None
    if result is not None:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(result, f)
    
    return result

def search_gse_summary(gse_id: str, cache_dir: str) -> str:
    """
    Search GEO and return GSE summary.
    
    Args:
        gse_id: GSE ID (e.g., 'GSE12345' or '12345')
    
    Returns:
        GSE summary as string
    """
    data = search_gse_with_cache(gse_id, "brief",cache_dir)
    if not data:
        return f"No summary found for '{gse_id}'"
    
    samples = data.get('samples', [])
    data_summary = data.copy()
    if len(samples) > 30:
        # keep only selected key fields as the summary
        data_summary['samples_info'] = f"There are {len(samples)} samples, but only showing first 30."
        data_summary['samples'] = samples[:30]
        data_summary['n_samples'] = len(samples)
    
    platform_samples = data.get('platform', {})
    platform_samples = platform_samples.get('samples', []) if platform_samples else []
    if len(platform_samples) > 30:
        data_summary['platform']['samples_info'] = f"There are {len(platform_samples)} platform samples, but only showing first 30."
        data_summary['platform']['samples'] = platform_samples[:30]
        data_summary['platform']['n_samples'] = len(platform_samples)

    output = remove_soft_data(data_summary)
    return json.dumps(output)



def search_gse_full_info(gse_id: str, cache_dir: str) -> str:
    """
    Search GEO and return complete GSE information.
    
    Args:
        gse_id: GSE ID (e.g., 'GSE12345' or '12345')
    
    Returns:
        Complete GSE information as formatted string
    """
    data = search_gse_with_cache(gse_id, "quick", cache_dir)
    if not data:
        return f"No information found for '{gse_id}'"
    samples = data.get('samples', [])
    data_summary = data.copy()
    if len(samples) > 30:
        # keep only selected key fields as the summary
        data_summary['samples_info'] = f"There are {len(samples)} samples, but only showing first 30."
        data_summary['samples'] = samples[:30]
        data_summary['n_samples'] = len(samples)
    
    platform_samples = data.get('platform', {})
    platform_samples = platform_samples.get('samples', []) if platform_samples else []
    if len(platform_samples) > 30:
        data_summary['platform']['samples_info'] = f"There are {len(platform_samples)} platform samples, but only showing first 30."
        data_summary['platform']['samples'] = platform_samples[:30]
        data_summary['platform']['n_samples'] = len(platform_samples)
    
    data_summary = remove_soft_data(data_summary)
    return json.dumps(data_summary)

def search_gpl_full_info(gpl_id: str, cache_dir: str) -> str:
    """
    Search GEO and return complete GPL information.
    
    Args:
        gpl_id: GPL ID (e.g., 'GPL570' or '570')
        cache_dir: Directory to store cached results
    
    Returns:
        Complete GPL information as formatted string
    """
    data = search_gpl_with_cache(gpl_id, "quick", cache_dir)
    if not data:
        return f"No information found for '{gpl_id}'"
    
    output = remove_soft_data(data)
    return json.dumps(output)


def search_gsm_full_info(gsm_id: str, cache_dir: str) -> str:
    """
    Search GEO and return complete GSM information.
    
    Args:
        gsm_id: GSM ID (e.g., 'GSM12345' or '12345')
        cache_dir: Directory to store cached results
    
    Returns:
        Complete GSM information as formatted string
    """
    data = search_gsm_with_cache(gsm_id, "quick", cache_dir)
    if not data:
        return f"No information found for '{gsm_id}'"
    
    output = remove_soft_data(data)
    return json.dumps(output)


if __name__ == "__main__":
    # test example
    test_gse_id = "GSE14594"
    test_gpl_id = "GPL570"
    test_gsm_id = "GSM364659"
    
    print("=" * 100)
    print("GSE Tests:")
    print("=" * 100)
    print("GSE Summary:")
    print(search_gse_summary(test_gse_id, "./cache"))
    print("-" * 100)
    
    print("GSE Full Information:")
    print(search_gse_full_info(test_gse_id, "./cache"))
    print("=" * 100)
    
    print("\n" + "=" * 100)
    print("GPL Tests:")
    print("=" * 100)
    print("GPL Full Information:")
    print(search_gpl_full_info(test_gpl_id, "./cache"))
    print("=" * 100)
    
    print("\n" + "=" * 100)
    print("GSM Tests:")
    print("=" * 100)
    print("GSM Full Information:")
    print(search_gsm_full_info(test_gsm_id, "./cache"))
    print("=" * 100)