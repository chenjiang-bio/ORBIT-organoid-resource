# Release checklist

Publishing this working tree as the OCSP module inside the ORBIT resource
repository, and optionally to PyPI.

## Where it goes

OCSP ships as one subdirectory of the paper's resource monorepo:

- Repository: <https://github.com/chenjiang-bio/ORBIT-organoid-resource>
- Subdirectory: `signature-prioritization/`
- Default branch: `main`

That repository is already organized as independent modules
(`omics-pipeline/`, `literature-agent/`, `knowledge-graph/`,
`literature-mcp/`), each self-contained with its own README. OCSP follows the
same convention, so all of its code, docs and configs stay inside its
subdirectory.

`scripts/build_release_tree.py` bakes these values in as `GITHUB_OWNER`,
`GITHUB_REPO`, `REPO_SUBDIR` and `VERSION`, and rewrites every placeholder URL
during the build. A build fails if any placeholder org name or unresolved
template token survives, or if the package version and the data-bundle version
disagree.

## Build the release tree

The working tree is ~36 GB; almost none of it is publishable.

```bash
python scripts/build_release_tree.py --dest ../orbit-ocsp
python scripts/build_release_tree.py --check     # preview exclusions only
```

Result: **~100 files, ~10 MB**, standard Python layout, no file above GitHub's
100 MB limit. The script prints what it excluded and exits non-zero if anything
oversized slips through.

```text
signature-prioritization/
├── orbit_ocsp/        package
├── examples/data/     sample inputs, one folder per mode
├── tests/             unit + integration
├── data/              small resources + README pointing at the download
├── docs/              SEQUENCE_ANNOTATION, OUTPUTS, ADVANCED, RELEASE
├── R/                 DE scripts
├── scripts/           pack_data_release.py
├── ci-workflow-for-repo-root.yml   → move to <repo>/.github/workflows/
├── README.md, CHANGELOG.md, CONTRIBUTING.md, LICENSE
└── pyproject.toml, MANIFEST.in
```

Notably excluded, with reasons the script reports:

| Path | Why |
|------|-----|
| `orbit-ocsp_tool_bundle/` | ~24 GB of annotation binaries; users install the tools themselves (see `docs/SEQUENCE_ANNOTATION.md`) |
| `handoff/` | 417 MB ORBIT UI contract plus a stale vendored copy of the package |
| `background/`, `prototype/` | ~12 GB internal scratch |
| `tests/Ana_Meta_example/` | 387 MB GEO corpus |
| `RESULTS_GUIDE.md` | documented the old `ENSEMBLE.md`/MoE output, superseded by `docs/OUTPUTS.md` |
| `gene/` | pre-refactor copy of `examples/data/sequence/` |
| `data/data_b/`, `data/protein/`, `data/DAG/` | scoring data → Release asset |

## ⚠️ Never push this working tree's git history

`data/data_b/B_terms_hsa.json` (209 MB) and `B_terms_mmu.json` (140 MB) are
already committed here, without Git LFS. GitHub rejects any push containing a
blob over 100 MB, so pushing this repository fails regardless of `.gitignore`.

This matters more in a monorepo: adding this tree as a remote or merging its
history would poison the shared repository for every other module. Copy the
built files into a clone instead, so none of this history travels.

```bash
python scripts/build_release_tree.py --dest ../orbit-ocsp

git clone git@github.com:chenjiang-bio/ORBIT-organoid-resource.git
cp -R ../orbit-ocsp/ ORBIT-organoid-resource/signature-prioritization/
cd ORBIT-organoid-resource
git switch -c add-signature-prioritization
git add signature-prioritization
git commit -m "Add OCSP context-guided signature prioritization module"
git push -u origin add-signature-prioritization
```

Then open a pull request rather than pushing to `main` directly.

### Two things to do by hand in the monorepo

1. **Add a row to the repo-root `README.md` table**, alongside the other
   modules:

   ```markdown
   | [`signature-prioritization/`](signature-prioritization/) | OCSP: context-guided prioritization of candidate genes against condition-specific organoid pathway backgrounds |
   ```

2. **Install the CI workflow at the repository root.** GitHub Actions ignores
   `.github/` directories inside subdirectories, so the build writes the
   workflow to `ci-workflow-for-repo-root.yml` instead of a `.github/` path
   that would silently never run:

   ```bash
   mkdir -p .github/workflows
   mv signature-prioritization/ci-workflow-for-repo-root.yml \
      .github/workflows/signature-prioritization-ci.yml
   ```

   It is already scoped with `paths: ["signature-prioritization/**"]` and
   `working-directory`, so it only runs when this module changes and does not
   fire on sibling modules.

## Host the scoring data

Decision: **GitHub Release asset.** Free, no bandwidth quota, keeps the
repository small.

```bash
python scripts/pack_data_release.py --species full   # and/or --species hsa / mmu
```

Releases are shared across the whole monorepo, so the tag is namespaced to this
module: **`ocsp-data-v<version>`**. A bare `data-v…` tag would collide with
sibling modules publishing their own data.

Create a Release tagged `ocsp-data-v0.1.0` and upload the tarballs. The download
URL is built from `DEFAULT_RELEASE_BASE` in `orbit_ocsp/data_manager.py`:

```text
https://github.com/chenjiang-bio/ORBIT-organoid-resource/releases/download/ocsp-data-v<version>/orbit-ocsp-data-<species>-<version>.tar.gz
```

Users override it with `ORBIT_OCSP_DATA_BASE_URL` if they mirror the data.

The version in that URL comes from `data_manager.__version__`, which the build
forces to match the version in `pyproject.toml`. Bump `VERSION` in
`scripts/build_release_tree.py` and both follow; the build refuses to emit a
tree where they disagree, because a mismatch sends `download-data` at a release
tag that does not exist.

`required_paths()` in `data_manager.py` is the single source of truth for what a
working install needs — the downloader, `missing_paths()`, the packer and the
tests all derive from it. Add a newly required file there and everything follows.

Keep the data tag in step with the package version, since `data_manager` builds
the URL from `__version__`.

## Before the first push

1. URLs and versions are resolved and checked by the build — nothing to edit by
   hand. To publish elsewhere, change the constants at the top of
   `scripts/build_release_tree.py` and rebuild.
2. Confirm the contact address in `pyproject.toml` (`authors`) is the one you
   want public.
3. Verify both data states in the release tree:

   ```bash
   cd ../orbit-ocsp
   pip install -e ".[dev]"
   ORBIT_OCSP_DATA=/path/to/data pytest -q     # all pass
   ORBIT_OCSP_DATA=/tmp/absent   pytest -q     # data-dependent tests skip
   ```

   The second run is what CI sees: parsing, merging and argument validation must
   work without the data bundle.

4. Confirm no secrets: `.pypirc`, `.env`, API keys.

## Dependency surface

Core requirements are NumPy, SciPy, pandas, requests, PyYAML, tqdm, psutil.
Everything else is an extra:

| Extra | Contents | Needed for |
|-------|----------|------------|
| `llm` | langchain, openai | `orbit-ocsp-ensemble --llm-explain` |
| `plots` | matplotlib, seaborn | figures in case reports |
| `benchmark` | scikit-learn, statsmodels | benchmark tooling (not shipped) |
| `notebook` | jupyter, ipykernel | the tutorial notebook |

`tests/unit/test_core_dependencies.py` hides the optional packages from the
import system and asserts every core module still imports, so a regression that
makes an extra mandatory fails the suite.

The released package drops seven internal modules (benchmarking, weight
training, expression case reports) because they import scikit-learn or
matplotlib at module level and have no console script. See `DROP_MODULES` in
`scripts/build_release_tree.py`.

## PyPI

**Required before the README is accurate.** The README leads with
`pip install orbit-ocsp`, which only resolves once the package is on PyPI. Until
then, the `git+…#subdirectory=` form under "Other ways to install" is the only
one that works, so either publish or reorder that section.

The distribution name `orbit-ocsp` was free on PyPI when this was written;
re-check before the first upload, since names cannot be reused once taken.

Building is independent of the monorepo layout. Build from the module
subdirectory, since that is where `pyproject.toml` lives:

```bash
cd signature-prioritization
python -m build
twine check dist/*
twine upload dist/orbit_ocsp-0.1.0*
```

Check the distribution name `orbit-ocsp` is still free on PyPI before the first
upload. Use an API token, never a committed `.pypirc`.

Users can also install straight from the repository without PyPI, which is worth
stating in the README because the subdirectory makes the command less obvious:

```bash
pip install "orbit-ocsp @ git+https://github.com/chenjiang-bio/ORBIT-organoid-resource.git#subdirectory=signature-prioritization"
```

### conda

There is no conda package. `conda install orbit-ocsp` will not work, and the
README says so explicitly rather than leaving users to discover it.

`environment.yml` ships instead: conda creates the environment — including the
R/Bioconductor packages that expression mode needs and pip cannot install — and
pip installs OCSP into it. That covers the practical reason someone reaches for
conda here.

Publishing to bioconda would mean a recipe in bioconda-recipes plus a pinned
upstream release; worth doing only if there is demand. It is not required for
the paper, which states OCSP is available "through the ORBIT web platform and as
a Python package".

Smoke test in a clean environment:

```bash
pip install orbit-ocsp==0.1.0
orbit-ocsp --help
orbit-ocsp-download-data --species hsa
orbit-ocsp --mode genes --genes CD44 --species hsa \
  --condition "Colorectal Cancer" --outdir /tmp/smoke
```

## Repository settings

Topics belong on the monorepo, not this module, and are shared with the other
modules. Relevant additions: `organoid`, `bioinformatics`, `biomarker`,
`gene-set-enrichment`, `kegg`, `gene-ontology`.
