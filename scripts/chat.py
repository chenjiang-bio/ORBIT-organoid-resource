#!/usr/bin/env python3
"""
chat.py — Organoid Knowledge Graph LLM GraphRAG Interactive Chat Terminal

Supports any OpenAI-compatible LLM service (DeepSeek / OpenAI / Ollama / vLLM, etc.),
auto-detects the latest KG.

Usage:
  # DeepSeek
  set DEEPSEEK_API_KEY=sk-xxx
  python scripts/chat.py

  # OpenAI
  set OPENAI_API_KEY=sk-xxx
  python scripts/chat.py --base-url https://api.openai.com/v1 --model gpt-4o

  # Ollama local model
  python scripts/chat.py --base-url http://localhost:11434/v1 --model llama3

  # Custom API Key (passed via CLI)
  python scripts/chat.py --api-key sk-xxx --base-url https://your-api.com/v1 --model your-model

Special commands during session:
  /help       Show help
  /stats      View graph statistics
  /search kw  Keyword search (no LLM call)
  /subgraph id View node subgraph
  /clear      Clear screen
  /exit       Quit
"""

import os
import sys
import argparse
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from query_tool import KnowledgeGraphQuery

# =============================================================================
# Colors (ANSI)
# =============================================================================

C = {
    "reset":   "\033[0m",
    "bold":    "\033[1m",
    "dim":     "\033[2m",
    "cyan":    "\033[36m",
    "green":   "\033[32m",
    "yellow":  "\033[33m",
    "blue":    "\033[34m",
    "magenta": "\033[35m",
}


def _p(color: str, text: str) -> str:
    return f"{C.get(color, '')}{text}{C['reset']}"


# =============================================================================
# Banner
# =============================================================================

BANNER = r"""
   ██████╗  ██████╗  ██████╗  ██╗ ████████╗
  ██╔═══██╗ ██╔══██╗ ██╔══██╗ ██║ ╚══██╔══╝
  ██║   ██║ ██████╔╝ ██████╔╝ ██║    ██║
  ██║   ██║ ██╔══██╗ ██╔══██╗ ██║    ██║
  ╚██████╔╝ ██║  ██║ ██████╔╝ ██║    ██║
   ╚═════╝  ╚═╝  ╚═╝ ╚═════╝  ╚═╝    ╚═╝
       Organoid Knowledge Graph  GraphRAG Chat
"""


# =============================================================================
# Refinement Prompt — embeds KG Schema info to guide LLM in refining user questions
# =============================================================================

REFINE_SYSTEM_PROMPT = """You help users narrow down vague research questions about an organoid knowledge graph.

## Knowledge Graph Schema

The graph has 18 node types connected by 19 relationship types:

### Node Types
- Sample (smp_): An experiment record — the central hub. Properties: sample_id, culture_days, organ, organism.
- Organoid (org_): A standardized organoid type (e.g. "Intestinal Organoid", "Hepatic Organoid").
- Organ (orn_): The organ/tissue of origin (e.g. "Liver", "Small Intestine", "Brain").
- System (sys_): Physiological system (e.g. "Digestive System", "Nervous System").
- Organism (osm_): Species (e.g. "Homo sapiens", "Mus musculus").
- Source (src_): Tissue/cell origin source.
- CellFactor (cf_): Growth factors / small molecules (e.g. "EGF", "Wnt3a").
- Technology (tec_): Culture/analysis technologies (e.g. CRISPR, scRNA-seq).
- Drug (drg_): Screened drugs (e.g. "Cisplatin", "Urolithin A").
- Gene (gen_): Gene editing targets (e.g. "APC", "TP53").
- DiseaseModel (dm_): Disease models (e.g. "Colorectal Cancer", "IBD").
- Infection (inf_): Infection challenge (e.g. "H1N1", "SARS-CoV-2").
- Biomarker (bmk_): Biomarkers (e.g. "Lgr5", "Ki67").
- Phenotype (phn_): Observed phenotypes (e.g. "increased senescence").
- Omics (omc_): Omics datasets (e.g. "scRNA-seq", "GEO").
- Composition (cmp_): Cell composition profiles.
- Application (app_): Application directions.
- Publication (pub_): Cited references.

### Core Relationships
HAS_ORGANOID(Sample→Organoid), FROM_ORGAN(Organoid→Organ), BELONGS_TO_SYSTEM(Organ→System),
FROM_ORGANISM(Sample→Organism), DERIVED_FROM(Organoid→Source), USES_FACTOR(Sample→CellFactor),
USES_TECHNOLOGY(Sample→Technology), SCREENS_DRUG(Sample→Drug), HAS_GENE_EDIT(Sample→Gene),
MODELS_DISEASE(Organoid→DiseaseModel), HAS_INFECTION(Sample→Infection),
HAS_BIOMARKER(Sample→Biomarker), HAS_PHENOTYPE(Sample→Phenotype),
HAS_OMICS(Sample→Omics), HAS_COMPOSITION(Sample→Composition),
HAS_APPLICATION(Organoid→Application), CITES(Sample→Publication),
TREATS_DISEASE(Drug→DiseaseModel [inferred]), INDICATES_DISEASE(Biomarker→DiseaseModel [inferred])

## Your Role
You help the user turn a vague question into a SPECIFIC query the graph can answer.

## Output Format — ALWAYS follow this exactly
Present options as a multiple-choice list. Use this format:

OPTIONS:
(a) <option description>
(b) <option description>
(c) <option description>
(d) <option description>
(e) <option description>

Always include (e) as "Other — please describe what you're looking for".
After the user picks or types their own answer, if the question is now specific enough, output exactly:
READY: <the final refined search question>

If it's still vague, present another round of OPTIONS.

## Examples

User: "tell me about liver organoids"

OPTIONS:
(a) List all liver organoid samples with their organoid types
(b) Drugs screened on liver organoids
(c) Gene edits used in liver organoids
(d) Phenotypes observed in liver organoids
(e) Other — please describe what you're looking for

User: b

READY: Which liver organoid samples were screened with drugs? List sample IDs, drug names, and any screening details.

User: "lung cancer drug resistance"

OPTIONS:
(a) Samples modeling lung cancer with drug screening data
(b) Drugs associated with lung cancer disease models (inferred)
(c) Phenotypes related to drug resistance in lung samples
(d) Gene edits in lung cancer organoids
(e) Other — please describe what you're looking for

User: I want to compare cisplatin response across different cancer types

READY: Compare cisplatin screening results across different cancer disease models. List the sample IDs, cancer types, and any drug response data for cisplatin.

User: "show all samples expressing Lgr5"

READY: Which samples express the Lgr5 biomarker? List sample IDs and their organoid types."""



# =============================================================================
# ChatSession
# =============================================================================

class ChatSession:
    """Interactive GraphRAG chat session"""

    def __init__(self, kg: KnowledgeGraphQuery,
                 api_key: str, base_url: str, model: str):
        self.kg = kg
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.history: list = []  # Chat history (question, answer) pairs

    # -------------------------------------------------------------------------
    # Special command handlers
    # -------------------------------------------------------------------------

    def cmd_stats(self):
        """Show graph statistics"""
        from collections import Counter
        ntc = Counter(n.type for n in self.kg.nodes.values())
        etc = Counter(e.relation for e in self.kg.edges)
        print(f"\n{_p('bold', 'Knowledge Graph Statistics')}")
        print(f"  Nodes: {_p('cyan', f'{len(self.kg.nodes):,}')}  |  "
              f"Edges: {_p('cyan', f'{len(self.kg.edges):,}')}  |  "
              f"Node types: {len(ntc)}  |  Edge types: {len(etc)}")
        print(f"\n  {_p('bold', 'Top Node Types:')}")
        for t, c in ntc.most_common(8):
            bar = "#" * min(40, c // 500)
            print(f"    {t:<18} {c:>7,}  {_p('dim', bar)}")
        print(f"\n  {_p('bold', 'Top Edge Types:')}")
        for r, c in etc.most_common(8):
            bar = "#" * min(40, c // 800)
            print(f"    {r:<22} {c:>7,}  {_p('dim', bar)}")
        print()

    def cmd_search(self, query: str):
        """Keyword search"""
        results = self.kg.search(query, top_k=10)
        if not results:
            print(f"  {_p('yellow', 'No results found.')}\n")
            return
        print(f"  {_p('green', f'Found {len(results)} results:')}")
        for node, score in results[:10]:
            name = node.properties.get("name",
                     node.properties.get("sample_id", node.id))
            print(f"    [{_p('cyan', node.type):<15}] {str(name)[:65]}  "
                  f"{_p('dim', f'({score:.2f})')}")
        print()

    def cmd_subgraph(self, node_id: str):
        """View node subgraph"""
        if node_id not in self.kg.nodes:
            print(f"  {_p('yellow', f'Node {node_id} not found.')}\n")
            return
        node = self.kg.nodes[node_id]
        name = node.properties.get("name",
                 node.properties.get("sample_id", node.id))
        print(f"  Node: [{_p('cyan', node.type)}] {name}")
        print(f"  Properties: {len(node.properties)} fields")
        sub = self.kg.traverse(node_id, depth=1)
        from collections import Counter
        ntc = Counter(n.type for n in sub["nodes"])
        etc = Counter(e.relation for e in sub["edges"])
        print(f"  1-hop subgraph: {len(sub['nodes'])} nodes, {len(sub['edges'])} edges")
        print(f"  Neighbor types: {dict(ntc)}")
        print(f"  Edge types: {dict(etc)}")
        print()

    # -------------------------------------------------------------------------
    # Question refinement (interactive LLM conversation, no KG access)
    # -------------------------------------------------------------------------

    def _refine_question(self, question: str):
        """Interactive question refinement. LLM gives options → user selects/inputs → loops until confirmed.

        LLM outputs in OPTIONS: / READY: format. User can input letter selection,
        custom text, or 'ok'/'ready' to confirm the current question and search directly.

        Returns:
            refined question string, or None to cancel
        """
        print(f"  {_p('dim', '[refine] analyzing question...')}")
        messages = [
            {"role": "system", "content": REFINE_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]

        max_rounds = 3
        for round_num in range(max_rounds):
            # ---- Call LLM ----
            try:
                from openai import OpenAI
                client_kwargs = {"api_key": self.api_key}
                if self.base_url:
                    client_kwargs["base_url"] = self.base_url
                client = OpenAI(**client_kwargs)
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=400,
                    timeout=20,
                )
                reply = response.choices[0].message.content.strip()
            except Exception as e:
                print(f"  {_p('yellow', f'[refine] LLM error, using original question: {e}')}")
                return question

            # ---- Parse LLM reply ----
            ready_q = self._parse_refine_reply(reply)
            if ready_q is not None:
                # LLM considers it specific enough → show final question, wait for user confirmation
                print(f"\n  {_p('bold', 'Refined question:')}")
                print(f"  {_p('cyan', ready_q)}")
                confirm = input(f"\n  {_p('dim', '[Enter=search, (r)efine more, (c)ancel]')} ").strip().lower()
                if confirm in ("cancel", "c"):
                    print(f"  {_p('dim', '[refine] cancelled')}")
                    return None
                if confirm in ("refine", "r"):
                    # User wants to continue refining
                    messages.append({"role": "assistant", "content": reply})
                    messages.append({"role": "user", "content": "Please refine further — I need more specific dimensions."})
                    continue
                # Default: confirm search
                return ready_q

            # ---- LLM gave an options list → display and wait for user selection ----
            print(f"\n  {_p('magenta', reply)}")
            user_input = input(f"\n  {_p('green', 'Your choice (a/b/c/d/e, or type your own) > ')}").strip()

            if not user_input:
                print(f"  {_p('dim', '[refine] cancelled')}")
                return None
            if user_input.lower() in ("cancel", "quit"):
                print(f"  {_p('dim', '[refine] cancelled')}")
                return None
            if user_input.lower() in ("ok", "ready", "done"):
                # User confirms directly, search with original question
                return question

            # Feed user's choice back to LLM
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": user_input})

        # Exceeded max rounds, use the last round's result
        print(f"  {_p('dim', '[refine] max rounds reached, using original question')}")
        return question

    @staticmethod
    def _parse_refine_reply(reply: str):
        """Parse LLM reply, returns refined question string or None.

        - If contains READY: → return the text after the prefix
        - If contains OPTIONS: → return None (not ready yet)
        - Otherwise → if it looks like an options list (contains (a) etc.), return None;
          otherwise treat as READY
        """
        # Try to match READY: prefix
        import re
        m = re.search(r'^READY:\s*', reply, re.IGNORECASE | re.MULTILINE)
        if m:
            return reply[m.end():].strip()

        # Try to match OPTIONS: prefix → is an options list
        if re.search(r'OPTIONS:', reply, re.IGNORECASE):
            return None

        # Contains (a)(b) pattern → treat as options list
        if re.search(r'\(a\)', reply, re.IGNORECASE):
            return None

        # No clear marker → treat as READY (return the text directly as the question)
        return reply

    # -------------------------------------------------------------------------
    # LLM Q&A
    # -------------------------------------------------------------------------

    def ask(self, question: str):
        """GraphRAG Q&A (with question refinement)"""
        # Step 0: Clarify requirements
        refined = self._refine_question(question)
        if refined is None:
            return

        print(f"\n{_p('bold', 'Final question:')} {_p('cyan', refined)}")

        print(f"\n{_p('dim', 'Searching knowledge graph...')}")
        result = self.kg.ask(
            refined,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            top_k=15,
            traversal_depth=1,
            verbose=False,
        )

        # Display retrieval summary
        stats = result.get("subgraph_stats", {})
        nodes_n = stats.get('nodes', 0)
        edges_n = stats.get('edges', 0)
        print(f"{_p('dim', f'Retrieved subgraph: {nodes_n} nodes, {edges_n} edges')}\n")

        # Display answer
        response = result.get("response", "")
        print(_p("bold", "┌─ Answer " + "─" * 55))
        # Auto word-wrap
        wrapper = textwrap.TextWrapper(width=70, initial_indent="│ ",
                                       subsequent_indent="│ ")
        for line in response.split("\n"):
            if not line.strip():
                print("│")
            elif len(line) <= 70:
                print(f"│ {line}")
            else:
                for wrapped in wrapper.wrap(line):
                    print(wrapped)
        print(_p("bold", "└" + "─" * 65))

        # Sources
        sources = result.get("sources", [])
        if sources:
            print(f"\n{_p('dim', f'Sources: {", ".join(sources[:5])}')}")
        print()

        # Save to history
        self.history.append((question, response))

    # -------------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------------

    def run(self):
        """Start interactive main loop"""
        # Clear screen & Banner
        os.system("cls" if os.name == "nt" else "clear")
        print(_p("cyan", BANNER))
        print(_p("dim", f"  Model: {self.model}  |  "
                f"Nodes: {len(self.kg.nodes):,}  |  "
                f"Edges: {len(self.kg.edges):,}"))
        print(_p("dim", "  Type /help for commands, /exit to quit."))
        print()

        while True:
            try:
                question = input(_p("bold", "You > ")).strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{_p('dim', 'Goodbye!')}")
                break

            if not question:
                continue

            # ---- Special commands ----
            if question.startswith("/"):
                cmd, *args = question[1:].split(maxsplit=1)
                arg = args[0] if args else ""

                if cmd in ("exit", "quit", "q"):
                    print(f"{_p('dim', 'Goodbye!')}")
                    break
                elif cmd == "help":
                    self._print_help()
                elif cmd == "stats":
                    self.cmd_stats()
                elif cmd == "search":
                    self.cmd_search(arg)
                elif cmd == "subgraph":
                    self.cmd_subgraph(arg)
                elif cmd == "clear":
                    os.system("cls" if os.name == "nt" else "clear")
                elif cmd == "history":
                    for i, (q, a) in enumerate(self.history, 1):
                        print(f"{_p('dim', f'[{i}]')} {q[:60]}")
                    print()
                else:
                    print(f"  {_p('yellow', f'Unknown command: /{cmd}')}  "
                          f"Type /help for available commands.\n")
                continue

            # ---- GraphRAG Q&A ----
            self.ask(question)

    def _print_help(self):
        print(f"""
{_p('bold', 'Available Commands:')}
  {_p('cyan', '/help')}       Show this help
  {_p('cyan', '/stats')}      Show knowledge graph statistics
  {_p('cyan', '/search')} kw  Search nodes by keyword (e.g. {_p('dim', '/search EGF')})
  {_p('cyan', '/subgraph')} id View a node and its 1-hop neighbors (e.g. {_p('dim', '/subgraph smp_KM-00001')})
  {_p('cyan', '/history')}    Show conversation history
  {_p('cyan', '/clear')}      Clear screen
  {_p('cyan', '/exit')}       Quit

{_p('bold', 'Tips:')}
  - Ask questions in Chinese or English
  - The system searches the KG for relevant subgraphs before answering
  - Answers are grounded in the retrieved graph data
  - Use {_p('dim', '/search')} to explore the graph without consuming LLM tokens
""")
        print()


# =============================================================================
# Find latest KG
# =============================================================================

def _find_latest_kg(kg_dir: str):
    if not os.path.isdir(kg_dir):
        return None
    candidates = []
    for entry in os.listdir(kg_dir):
        subdir = os.path.join(kg_dir, entry)
        if not os.path.isdir(subdir):
            continue
        kg_file = os.path.join(subdir, "organoid_kg.json")
        if os.path.isfile(kg_file):
            candidates.append((entry, kg_file))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Organoid KG GraphRAG Interactive Chat")
    parser.add_argument("kg_file", nargs="?", default=None,
                        help="Path to organoid_kg.json (auto-detect latest if omitted)")
    parser.add_argument("--kg-dir", default="./organoid-kg-output",
                        help="Directory to scan for latest KG")
    parser.add_argument("--api-key", default=None,
                        help="LLM API Key (or set LLM_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY env var)")
    parser.add_argument("--base-url", default="https://api.deepseek.com",
                        help="API base URL (default: https://api.deepseek.com)")
    parser.add_argument("--model", default="deepseek-chat",
                        help="Model name (default: deepseek-chat)")
    args = parser.parse_args()

    # API Key — check multiple env vars in order
    api_key = (args.api_key
               or os.environ.get("LLM_API_KEY")
               or os.environ.get("DEEPSEEK_API_KEY")
               or os.environ.get("OPENAI_API_KEY"))
    if not api_key:
        print("Error: No API key provided. Use one of:")
        print("  --api-key sk-xxx")
        print("  set LLM_API_KEY=sk-xxx       (generic)")
        print("  set DEEPSEEK_API_KEY=sk-xxx   (DeepSeek)")
        print("  set OPENAI_API_KEY=sk-xxx     (OpenAI)")
        sys.exit(1)

    # KG file
    if args.kg_file is None:
        args.kg_file = _find_latest_kg(args.kg_dir)
        if args.kg_file is None:
            print(f"Error: No organoid_kg.json found under {args.kg_dir}/")
            print("  Run build_kg.py first, or specify a KG file path.")
            sys.exit(1)

    if not os.path.exists(args.kg_file):
        print(f"Error: File not found: {args.kg_file}")
        sys.exit(1)

    # Load
    print(f"Loading KG: {args.kg_file} ...")
    kg = KnowledgeGraphQuery.load(args.kg_file)
    print(f"Loaded {len(kg.nodes):,} nodes, {len(kg.edges):,} edges.")
    # Infer provider name
    provider = "DeepSeek" if "deepseek" in args.base_url else \
               "OpenAI" if "openai" in args.base_url else \
               "Ollama" if "localhost" in args.base_url or "ollama" in args.base_url else \
               "Custom"
    print(f"LLM: {args.model} @ {provider} ({args.base_url})\n")

    # Start chat
    session = ChatSession(kg, api_key=api_key,
                          base_url=args.base_url, model=args.model)
    session.run()


if __name__ == "__main__":
    main()
