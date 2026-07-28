# DOMAIN KNOWLEDGE

## BIOMAKER
In biomedical contexts, a biomarker, or biological marker, is a measurable indicator of some biological state or condition. Biomarkers are often measured and evaluated using blood, urine, or soft tissues to examine normal biological processes, pathogenic processes, or pharmacologic responses to a therapeutic intervention. Biomarkers are used in many scientific fields. In cell biology, a biomarker is a molecule that allows the detection and isolation of a particular cell type (for example, the protein Oct-4 is used as a biomarker to identify embryonic stem cells).

## PCR series
### List of PCR
- PCR: Polymerase chain reaction
- RT-PCR: Reverse transcription polymerase chain reaction
- qRT-PCR: Quantitative reverse transcription polymerase chain reaction
- qPCR: Quantitative polymerase chain reaction
- RT-qPCR: Reverse transcription quantitative polymerase chain reaction
- Nested PCR: Nested polymerase chain reaction, Nested polymerase chain reaction involves two sets of primers, used in two successive runs of polymerase chain reaction, the second set intended to amplify a secondary target within the first run product.
- inverse PCR: Inverse polymerase chain reaction
- Other types of PCR: Digital PCR (dPCR), Multiplex PCR, Hot Start PCR, Touchdown PCR, Colony PCR, Long-range PCR, etc.

## Materials For Culture
### Medium
A cell culture medium or growth medium is a liquid, semi-solid, or solid substance designed to support the growth, proliferation, and maintenance of cells in an artificial, in vitro environment (i.e., in a petri dish or flask, outside of a living organism). The primary purpose of a medium is to mimic the natural in vivo environment of a cell (such as blood plasma or interstitial fluid). Base medium examples: DMEM, DMEM/F12, Neurobasal, RPMI 1640, mTeSR1, etc.

### Supplements
Culture medium supplements are commercially available or custom-prepared additives that enhance the nutritional content, stability, or functionality of base culture media. Examples include: B-27 Supplement, N-2 Supplement, GlutaMax, Fetal Bovine Serum (FBS), KnockOut Serum Replacement (KSR), Penicillin-Streptomycin, HEPES buffer, Normocin, ITS (Insulin-Transferrin-Selenium), non-essential amino acids (NEAA), sodium pyruvate, β-mercaptoethanol, and other nutritional or protective additives.

#### Growth Factors
Protein-based growth factors, cytokines, and morphogens are signaling molecules (typically proteins or peptides) that regulate cell proliferation, differentiation, survival, and patterning by binding to cell surface receptors. Examples include: EGF (Epidermal Growth Factor), bFGF/FGF2 (basic Fibroblast Growth Factor), Wnt3a, Noggin, BMP4 (Bone Morphogenetic Protein 4), Activin A, FGF8, IGF-1 (Insulin-like Growth Factor 1), VEGF (Vascular Endothelial Growth Factor), HGF (Hepatocyte Growth Factor), TGF-β (Transforming Growth Factor beta), and other cytokines.

### Small Molecules
Small molecule compounds are low-molecular-weight chemical compounds (typically < 900 Da) that modulate cellular signaling pathways by acting as inhibitors, activators, or agonists/antagonists of specific targets. Examples include: CHIR99021 (GSK3 inhibitor, Wnt pathway activator), SB431542 (TGF-β/ALK inhibitor), LDN193189 (BMP inhibitor), Y-27632 (ROCK inhibitor), A83-01 (TGF-β inhibitor), PD0325901 (MEK inhibitor), Forskolin (adenylyl cyclase activator), Retinoic acid, Dexamethasone, and other pathway modulators.


## DOI & TITLE
### DOI Types
- **Original Article DOI**: The DOI assigned to the original published research article (e.g., `10.1038/s41418-018-0070-2`). This DOI never changes.
- **Correction Notice DOI**: The DOI assigned to a separate correction/erratum document published after the original article to amend errors (e.g., `10.1038/s41418-020-00630-w`). One original article may have multiple correction notices, each with its own DOI.

### PubMed Tools Usage
- **Search By Title**: Use tool=`get_pubmed_article_by_text` args=`{"texts":['title']}` to retrieve both the original article DOI and any associated correction notice DOIs (if corrections exist). 
- **Search By Title Example**: 
  - Search Title: "Epithelial and Neutrophil Interactions and Coordinated Response to Shigella in a Human Intestinal Enteroid-Neutrophil Coculture Model". 
  - [SearchMode1]: tool=`get_pubmed_article_by_text`  args=`{"texts":["Epithelial and Neutrophil Interactions and Coordinated Response to Shigella in a Human Intestinal Enteroid-Neutrophil Coculture Model"]}`
  - If Not Found, [SearchMode2]: tool=`get_pubmed_article_by_text` args=`{"texts":["\"Epithelial\"[Title] AND \"Neutrophil\"[Title] AND \"Interactions\"[Title] AND \"Coordinated\"[Title] AND \"Response\"[Title] AND \"Shigella\"[Title] AND \"Human\"[Title] AND \"Intestinal\"[Title] AND \"Enteroid-Neutrophil\"[Title] AND \"Coculture\"[Title] AND \"Model"\[Title]"]}`
- **Validate DOI**: Use tool=`get_pubmed_article_by_doi()` args=`{"dois":["10.1038/xxxxxxxx"]}` to verify a DOI by retrieving its title and abstract. Invalid DOI if: (1) not found, or (2) returned title doesn't match expected article title.  
