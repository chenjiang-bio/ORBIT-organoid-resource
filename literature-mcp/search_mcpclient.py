import asyncio
from fastmcp import Client

client = Client("http://localhost:12400/mcp")

async def list_tools():
    """List all available tools from the MCP server"""
    print("=" * 80)
    print("Available MCP Tools:")
    print("=" * 80)
    async with client:
        tools = await client.list_tools()
        for i, tool in enumerate(tools, 1):
            print(f"\n{i}. Tool: {tool.name}")
            print(f"   Description: {tool.description}")
            if 'inputSchema' in tool:
                print(f"   Parameters: {tool.inputSchema.properties}")
            if 'outputSchema' in tool:
                print(f"   Returns: {tool.outputSchema.properties.result.type}")
    print("\n" + "=" * 80)

async def test_get_wikipedia_summary():
    """Test get_wikipedia_summary tool"""
    print("\n[TEST] get_wikipedia_summary")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_wikipedia_summary", {
            "keywords": ["Organoid", "Cancer", "SB431542"],
        })
        print(result.content)

async def test_get_wikipedia_categories():
    """Test get_wikipedia_categories tool"""
    print("\n[TEST] get_wikipedia_categories")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_wikipedia_categories", {
            "keywords": ["Cell"]
        })
        print(result.content)

async def test_get_wikipedia_text():
    """Test get_wikipedia_text tool"""
    print("\n[TEST] get_wikipedia_text")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_wikipedia_text", {
            "keywords": ["Organoid"]
        })
        print(result.content)

async def test_get_wikipedia_links():
    """Test get_wikipedia_links tool"""
    print("\n[TEST] get_wikipedia_links")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_wikipedia_links", {
            "keywords": ["Homo sapiens", "Mus musculus"]
        })
        print(result.content)

async def test_get_wikipedia_backlinks():
    """Test get_wikipedia_backlinks tool"""
    print("\n[TEST] get_wikipedia_backlinks")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_wikipedia_backlinks", {
            "keywords": ["Model Context Protocol","HTTP"],
        })
        print(result.content)

async def test_get_empty_wikipedia_summary():
    """Test get_wikipedia_summary tool"""
    print("\n[TEST] get_wikipedia_summary")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_wikipedia_summary", {
            "keywords": ["NonExistentPage", "HTTPS"]
        })
        print(result.content)

async def test_get_gse_summary():
    """Test get_gse_summary tool"""
    print("\n[TEST] get_gse_summary")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_gse_summary", {
            "gse_ids": ["GSE14594","GSE28265"]
        })
        print(result.content)

async def test_get_gse_full_info():
    """Test get_gse_full_info tool"""
    print("\n[TEST] get_gse_full_info")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_gse_full_info", {
            "gse_ids": ["GSE126798"]
        })
        print(result.content)

async def test_get_gpl_full_info():
    """Test get_gpl_full_info tool"""
    print("\n[TEST] get_gpl_full_info")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_gpl_full_info", {
            "gpl_ids": ["GPL17303","GPL4134"]
        })
        print(result.content)

async def test_get_gsm_full_info():
    """Test get_gsm_full_info tool"""
    print("\n[TEST] get_gsm_full_info")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_gsm_full_info", {
            "gsm_ids": ["GSM699638","GSM699639","GSM3613434"]
        })
        print(result.content)

async def test_get_gene_summary():
    """Test get_gene_summary tool"""
    print("\n[TEST] get_gene_summary")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_gene_summary", {
            "querys":
                [
                    {"gene_name": "TP53","organism": "Homo sapiens"},
                    {"gene_name": "LGR4","organism": "Homo sapiens"},
                    {"gene_name": "LGR5","organism": "Homo sapiens"},
                    {"gene_name": "SOX10","organism": "Homo sapiens"},
                ]
            }
        )
        print(result.content)

async def test_get_gene_full_info():
    """Test get_gene_full_info tool"""
    print("\n[TEST] get_gene_full_info")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_gene_summary", {
            "querys":
                [
                    {"gene_name": "TP53","organism": "Mus musculus"},
                    {"gene_name": "LGR4","organism": "Mus musculus"},
                    {"gene_name": "LGR5","organism": "Mus musculus"},
                ]
            }
        )
        print(result.content)

async def test_google_search():
    """Test google_search tool"""
    print("\n[TEST] google_search")
    print("-" * 40)
    async with client:
        result = await client.call_tool("google_search", {
            "querys": ["Gene Ontology", "Cellular Component", "Molecular Function","IPSCs","nature communications222"]
        })
        print(result)

async def test_pubmed_by_pmid():
    """Test get_pubmed_article_by_pmid tool"""
    print("\n[TEST] get_pubmed_article_by_pmid")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_pubmed_article_by_pmid", {
            "pmids": ["31452104", "30049270"]
        })
        print(result.content)

async def test_pubmed_by_doi():
    """Test get_pubmed_article_by_doi tool"""
    print("\n[TEST] get_pubmed_article_by_doi")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_pubmed_article_by_doi", {
            "dois": ["10.1038/s41586-020-2649-2", "10.14440/jbm.2015.73"]
        })
        print(result.content)

async def test_pubmed_by_pmcid():
    """Test get_pubmed_article_by_pmcid tool"""
    print("\n[TEST] get_pubmed_article_by_pmcid")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_pubmed_article_by_pmcid", {
            "pmcids": ["PMC4770449", "7987217"]
        })
        print(result.content)

async def test_pubmed_by_text():
    """Test get_pubmed_article_by_text tool"""
    print("\n[TEST] get_pubmed_article_by_text")
    print("-" * 40)
    async with client:
        result = await client.call_tool("get_pubmed_article_by_text", {
            "texts": [
                "Lactobacillus accelerates ISCs regeneration to protect the integrity of intestinal mucosa through activation of STAT3 signaling pathway induced by LPLs secretion of IL-22",
                "Epithelial and Neutrophil Interactions and Coordinated Response to Shigella in a Human Intestinal Enteroid-Neutrophil Coculture Model",
                "aaaaa no exist data"
            ]
        })
        print(result.content)

async def run_all_tests():
    """Run all test cases"""
    await list_tools()
    
    print("\n" + "=" * 80)
    print("Running Test Cases:")
    print("=" * 80)

    await test_get_wikipedia_summary()
    await test_get_wikipedia_categories()
    await test_get_wikipedia_text()
    await test_get_wikipedia_links()
    await test_get_wikipedia_backlinks()
    await test_get_empty_wikipedia_summary()
    await test_get_gse_summary()
    await test_get_gse_full_info()
    await test_get_gpl_full_info()
    await test_get_gsm_full_info()
    await test_get_gene_summary()
    await test_get_gene_full_info()
    await test_google_search()
    await test_pubmed_by_pmid()
    await test_pubmed_by_doi()
    await test_pubmed_by_pmcid()
    await test_pubmed_by_text()

    print("\n" + "=" * 80)
    print("All tests completed!")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_all_tests())