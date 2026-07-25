# data/

This directory holds only the small resources that fit in git (~17 MB): KO→pathway
maps, term universes, information content, KEGG metadata and topology.

The **scoring data is not here.** It is hosted as a GitHub Release asset because
`B_terms_hsa.json` alone is 199 MB, above GitHub's 100 MB per-file limit.

## Get it

```bash
orbit-ocsp-download-data                 # human + mouse, ~350 MB
orbit-ocsp-download-data --species hsa   # human only
orbit-ocsp-download-data --species mmu   # mouse only
```

Files land in `~/.orbit_ocsp/data/`. To use an existing copy instead:

```bash
export ORBIT_OCSP_DATA=/path/to/data
```

Resolution order: `$ORBIT_OCSP_DATA` → `~/.orbit_ocsp/data/` → `<repo>/data/` → `./data/`.

## Check what is present

```python
from orbit_ocsp.data_manager import data_status
print(data_status("hsa"))
```

## What gets downloaded

| Path | Contents |
|------|----------|
| `data_b/B_terms_{hsa,mmu}.json` | Condition pathway backgrounds (B) |
| `protein/all_merged_result.json` | Precomputed gene → pathway map |
| `protein/Gene_Annotation_{Human,Mouse}.txt` | Symbol / Entrez / Ensembl cross-map |
| `meta/go_meta.json` | GO term names and namespaces |
| `DAG/go_ancestors.json` | GO ancestor closure |
| `semantic_resources_v2/go_ancestors.json` | Semantic similarity resources |

`orbit_ocsp.data_manager.required_paths()` is the authoritative list.

## Mirrors

To host the bundle elsewhere:

```bash
export ORBIT_OCSP_DATA_BASE_URL=https://your.mirror/orbit-ocsp-data
```
