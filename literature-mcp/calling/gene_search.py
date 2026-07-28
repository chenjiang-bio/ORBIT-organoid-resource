import json
import requests
from typing import Optional
import os
import time

def search_gene(gene_name: str, organism: str) -> Optional[dict]:
    """
    Search NCBI Gene database and return gene information.
    
    Args:
        gene_name: Gene name or symbol (e.g., 'TP53', 'BRCA1')
        organism: Organism name (e.g., 'Homo sapiens', 'Mus musculus')
    
    Returns:
        Dictionary containing gene information or None if not found
    """
    base_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
    
    # Step 1: search and obtain Gene ID
    search_url = f'{base_url}esearch.fcgi'
    search_params = {
        'db': 'gene',
        'term': f'{gene_name}[Gene Name] AND {organism}[Organism]',
        'retmode': 'json',
        'retmax': 1
    }
    
    try:
        search_response = requests.get(search_url, params=search_params)
        search_data = search_response.json()
        
        if not search_data.get('esearchresult', {}).get('idlist'):
            return None
        
        gene_id = search_data['esearchresult']['idlist'][0]
        
        # Step 2: fetch gene summary info
        summary_url = f'{base_url}esummary.fcgi'
        summary_params = {
            'db': 'gene',
            'id': gene_id,
            'retmode': 'json'
        }
        time.sleep(1)  # respect NCBI rate limits
        summary_response = requests.get(summary_url, params=summary_params)
        summary_data = summary_response.json()
        
        if 'result' not in summary_data or gene_id not in summary_data['result']:
            return None
        
        result = summary_data['result'][gene_id]
        
        # Step 3: fetch detailed info (via efetch)
        fetch_url = f'{base_url}efetch.fcgi'
        fetch_params = {
            'db': 'gene',
            'id': gene_id,
            'retmode': 'xml'
        }
        
        try:
            time.sleep(1)  # respect NCBI rate limits
            from xml.etree import ElementTree as ET
            fetch_response = requests.get(fetch_url, params=fetch_params)
            root = ET.fromstring(fetch_response.content)
            
            # extract more detailed information
            gene_commentary = root.find('.//Gene-commentary')
            if gene_commentary is not None:
                # extract gene description
                label = gene_commentary.find('.//Gene-commentary_label')
                if label is not None:
                    result['gene_type'] = label.text
                    
        except Exception as soft_error:
            print(f"Error parsing detailed gene info: {soft_error}")
        
        return result
    
    except Exception as e:
        print(f"Error fetching gene data: {e}")
        return None

def search_gene_with_cache(gene_name: str, organism:str, cache_dir: str) -> Optional[dict]:
    """
    Search NCBI Gene database with caching to avoid redundant requests.
    
    Args:
        gene_name: Gene name or symbol (e.g., 'TP53', 'BRCA1')
        organism: Organism name (e.g., 'Homo sapiens', 'Mus musculus')
        cache_dir: Directory to store cached results
    
    Returns:
        Dictionary containing gene information or None if not found
    """
    # use gene name as cache file name
    cache_file = os.path.join(cache_dir, f"gene_{organism}_{gene_name}.json")
    
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding='utf-8') as f:
            return json.load(f)
    
    result = search_gene(gene_name, organism)
    
    if result:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w", encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    
    return result

def search_gene_summary(gene_name: str, organism:str, cache_dir: str) -> str:
    """
    Search NCBI Gene database and return gene summary.
    
    Args:
        gene_name: Gene name or symbol (e.g., 'TP53', 'BRCA1')
        organism: Organism name (e.g., 'Homo sapiens', 'Mus musculus')
        cache_dir: Directory to store cached results
    
    Returns:
        Gene summary as JSON string
    """
    data = search_gene_with_cache(gene_name, organism, cache_dir)
    
    if not data:
        return json.dumps({"error": f"No information found for gene '{gene_name}'"})
    
    info_lines = [
        f"Gene ID: {data.get('uid', 'N/A')}",
        f"Symbol: {data.get('name', 'N/A')}",
        f"Description: {data.get('description', 'N/A')}",
        f"Organism: {data.get('organism', {}).get('scientificname', 'N/A')}",
        f"Chromosome: {data.get('chromosome', 'N/A')}",
        f"Map Location: {data.get('maplocation', 'N/A')}",
        f"Gene Type: {data.get('geneticsource', 'N/A')}",
        f"Summary: {data.get('summary', 'N/A')}..." if data.get('summary') else "Summary: N/A",
    ]
    
    return json.dumps(info_lines, ensure_ascii=False)

def search_gene_full_info(gene_name: str,  organism:str, cache_dir: str) -> str:
    """
    Search NCBI Gene database and return complete gene information.
    
    Args:
        gene_name: Gene name or symbol (e.g., 'TP53', 'BRCA1')
        cache_dir: Directory to store cached results
    
    Returns:
        Complete gene information as JSON string
    """
    data = search_gene_with_cache(gene_name, organism, cache_dir)
    
    if not data:
        return json.dumps({"error": f"No information found for gene '{gene_name}'"})
    
    info_lines = [
        f"Gene ID: {data.get('uid', 'N/A')}",
        f"Symbol: {data.get('name', 'N/A')}",
        f"Description: {data.get('description', 'N/A')}",
        f"Organism: {data.get('organism', {}).get('scientificname', 'N/A')}",
        f"Taxonomy ID: {data.get('organism', {}).get('taxid', 'N/A')}",
        f"Chromosome: {data.get('chromosome', 'N/A')}",
        f"Map Location: {data.get('maplocation', 'N/A')}",
        f"Gene Type: {data.get('geneticsource', 'N/A')}",
        f"Nomenclature Status: {data.get('nomenclaturestatus', 'N/A')}",
        f"Other Aliases: {data.get('otheraliases', 'N/A')}",
        f"Other Aliases: {data.get('otherdesignations', 'N/A')}",
        f"Summary: {data.get('summary', 'N/A')}",
    ]
    
    return json.dumps(info_lines, ensure_ascii=False)

if __name__ == "__main__":
    # test example
    test_genes = ["KRT19", "KRT7", "SOX9", "GGT1", "ALPL", "EPCAM", "ALB"]
    
    for query in test_genes:
        gene_name = query
        organism = "Homo sapiens"
        summary = search_gene_summary(gene_name, organism, "./cache")
        print(f"Summary for {gene_name} ({organism}):\n{summary}\n")
