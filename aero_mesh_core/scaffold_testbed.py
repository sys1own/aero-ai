"""
Aero-Mesh testbed scaffolder
============================

Programmatically generates a *local* technical corpus for benchmarking the
parallel scanning / linking / aggregation topology described in
``recipes/seed_topology.txt``.

The corpus is deliberately "messy": nested domain/shard folders full of
Markdown files that cross-reference each other (wiki-style ``[[links]]`` and
relative ``[label](../path.md)`` links) and repeat a small keyword vocabulary
so a harvester has something measurable to index.

Design constraints (intentional):
    * Standard library only — no third-party deps, no network access.
    * Deterministic — a fixed ``--seed`` produces byte-identical output, so
      timing benchmarks are reproducible across runs.
    * Write-scoped — every path is validated to live *inside* ``testbed/``.
      The script never deletes anything and never writes outside that root.

Usage::

    python aero_mesh_core/scaffold_testbed.py            # defaults
    python aero_mesh_core/scaffold_testbed.py --domains 4 --shards 3 --docs 5
    python aero_mesh_core/scaffold_testbed.py --seed 7 --summary
"""

import argparse
import os
import random
import sys

# ── Paths ──────────────────────────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))
TESTBED_ROOT = os.path.join(_HERE, "testbed")

# ── Corpus vocabulary ──────────────────────────────────────────────────────

KEYWORDS = [
    "telemetry", "topology", "scheduler", "bytecode", "lexer", "opcode",
    "frame", "dependency", "aggregate", "scout", "linker", "semantic",
    "harvest", "index", "throughput", "latency", "checkpoint", "manifest",
]

_LOREM = (
    "The {kw_a} subsystem hands off to the {kw_b} stage once the working set "
    "is resident. Each pass records {kw_c} deltas so the scheduler can rebalance "
    "the {kw_d} graph on the next sweep."
)


def _safe_join(*parts):
    """Join under TESTBED_ROOT and refuse any path that escapes it."""
    target = os.path.realpath(os.path.join(TESTBED_ROOT, *parts))
    root = os.path.realpath(TESTBED_ROOT)
    if target != root and not target.startswith(root + os.sep):
        raise ValueError(f"refusing to write outside testbed/: {target}")
    return target


def _write(rel_path, text):
    path = _safe_join(rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


# ── Generation ─────────────────────────────────────────────────────────────

def _plan(domains, shards, docs):
    """Build the full (rel_path, title) list up front so links can target it."""
    plan = []
    for d in range(domains):
        for s in range(shards):
            for n in range(docs):
                rel = os.path.join(f"domain_{d:02d}", f"shard_{s:02d}", f"doc_{n:03d}.md")
                plan.append((rel, f"Domain {d:02d} / Shard {s:02d} / Doc {n:03d}"))
    return plan


def _doc_body(rng, title, rel_path, plan):
    """Render one Markdown doc with keywords and cross-references."""
    kws = rng.sample(KEYWORDS, k=4)
    lines = [f"# {title}", ""]
    lines.append(f"tags:: {', '.join(rng.sample(KEYWORDS, k=3))}")
    lines.append("")

    # A few keyword-laden paragraphs.
    for _ in range(rng.randint(2, 4)):
        kw = rng.sample(KEYWORDS, k=4)
        lines.append(_LOREM.format(kw_a=kw[0], kw_b=kw[1], kw_c=kw[2], kw_d=kw[3]))
        lines.append("")

    # Cross-references: relative links to other real docs + wiki-style links.
    others = [p for p in plan if p[0] != rel_path]
    targets = rng.sample(others, k=min(3, len(others)))
    if targets:
        lines.append("## See also")
        here_dir = os.path.dirname(rel_path)
        for tgt_rel, tgt_title in targets:
            relative = os.path.relpath(tgt_rel, here_dir).replace(os.sep, "/")
            lines.append(f"- [{tgt_title}]({relative})")
            lines.append(f"- [[{tgt_title}]]")
        lines.append("")

    lines.append(f"keyword-focus:: {kws[0]} {kws[1]}")
    return "\n".join(lines) + "\n"


def generate(domains, shards, docs, seed):
    rng = random.Random(seed)
    plan = _plan(domains, shards, docs)

    written = []
    for rel_path, title in plan:
        written.append(_write(rel_path, _doc_body(rng, title, rel_path, plan)))

    # Root manifest linking every generated domain (more cross-reference fuel).
    manifest = ["# Testbed Manifest", "",
                f"Generated corpus: {len(plan)} documents "
                f"({domains} domains x {shards} shards x {docs} docs).", ""]
    for rel_path, title in plan:
        manifest.append(f"- [{title}]({rel_path.replace(os.sep, '/')})")
    written.append(_write("MANIFEST.md", "\n".join(manifest) + "\n"))
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate the Aero-Mesh local testbed corpus.")
    ap.add_argument("--domains", type=int, default=3, help="top-level domain folders (default 3)")
    ap.add_argument("--shards", type=int, default=3, help="shard subfolders per domain (default 3)")
    ap.add_argument("--docs", type=int, default=4, help="markdown docs per shard (default 4)")
    ap.add_argument("--seed", type=int, default=1337, help="RNG seed for reproducibility")
    ap.add_argument("--summary", action="store_true", help="print a count summary when done")
    args = ap.parse_args(argv)

    written = generate(args.domains, args.shards, args.docs, args.seed)
    print(f"scaffold_testbed: wrote {len(written)} files under "
          f"{os.path.relpath(TESTBED_ROOT)}/ (seed={args.seed})")
    if args.summary:
        docs = len(written) - 1  # minus MANIFEST.md
        print(f"  domains={args.domains} shards={args.shards} docs/shard={args.docs} "
              f"=> {docs} docs + 1 manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
