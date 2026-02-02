#!/usr/bin/env python3
"""Benchmark embedding models on an Obsidian vault.

Usage:
    uv run python scripts/benchmark.py --vault /path/to/vault --sample 50
"""

import argparse
import gc
import random
import sys
import time
from pathlib import Path

# Add the src directory to the path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def get_memory_usage_mb() -> float:
    """Get current process memory usage in MB."""
    try:
        import psutil

        process = psutil.Process()
        return process.memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0.0


def format_time(seconds: float) -> str:
    """Format time in human readable format."""
    if seconds < 1:
        return f"{seconds * 1000:.1f}ms"
    return f"{seconds:.2f}s"


def benchmark_model(
    model_name: str,
    documents: list[str],
    queries: list[str],
) -> dict:
    """Benchmark a single model."""
    from obsidian_index.index.encoder import Encoder
    from obsidian_index.index.models import get_model_config

    gc.collect()
    memory_before = get_memory_usage_mb()

    # Load model
    print("  Loading model...", end=" ", flush=True)
    load_start = time.perf_counter()
    model_config = get_model_config(model_name)
    encoder = Encoder(model_config=model_config)
    load_time = time.perf_counter() - load_start
    print(f"{format_time(load_time)}")

    memory_after_load = get_memory_usage_mb()
    model_memory = memory_after_load - memory_before

    # Index documents
    print(f"  Indexing {len(documents)} documents...", end=" ", flush=True)
    index_start = time.perf_counter()
    encoder.encode_documents(documents, batch_size=16)
    index_time = time.perf_counter() - index_start
    index_per_doc = index_time / len(documents) * 1000  # ms per doc
    print(f"{format_time(index_time)} ({index_per_doc:.1f}ms/doc)")

    # Query latency
    print(f"  Running {len(queries)} queries...", end=" ", flush=True)
    query_times = []
    for query in queries:
        q_start = time.perf_counter()
        encoder.encode_query(query)
        query_times.append(time.perf_counter() - q_start)
    avg_query_time = sum(query_times) / len(query_times) * 1000  # ms
    print(f"{avg_query_time:.1f}ms avg")

    memory_peak = get_memory_usage_mb()

    return {
        "model": model_name,
        "dimensions": model_config.dimensions,
        "load_time": load_time,
        "index_time": index_time,
        "index_per_doc_ms": index_per_doc,
        "query_avg_ms": avg_query_time,
        "memory_mb": max(model_memory, memory_peak - memory_before),
    }


def collect_documents(vault_path: Path, sample_size: int) -> list[str]:
    """Collect markdown documents from a vault."""
    all_files = list(vault_path.rglob("*.md"))
    print(f"Found {len(all_files)} markdown files in vault")

    if len(all_files) <= sample_size:
        selected = all_files
    else:
        selected = random.sample(all_files, sample_size)

    documents = []
    for path in selected:
        try:
            text = path.read_text(encoding="utf-8")
            documents.append(text)
        except Exception as e:
            print(f"  Warning: Could not read {path}: {e}")

    print(f"Loaded {len(documents)} documents for benchmarking")
    return documents


def print_results_table(results: list[dict]):
    """Print benchmark results in a table format."""
    print("\n" + "=" * 75)
    print("BENCHMARK RESULTS")
    print("=" * 75)

    # Header
    print(f"{'Model':<28} {'Dim':>4} {'Load':>8} {'Index':>10} {'Query':>8} {'Memory':>8}")
    print("-" * 75)

    for r in results:
        print(
            f"{r['model']:<28} "
            f"{r['dimensions']:>4} "
            f"{format_time(r['load_time']):>8} "
            f"{r['index_per_doc_ms']:>7.1f}ms "
            f"{r['query_avg_ms']:>5.1f}ms "
            f"{r['memory_mb']:>6.0f}MB"
        )

    print("=" * 75)
    print("\nNotes:")
    print("  - Load: Time to load model into memory")
    print("  - Index: Average time to encode one document")
    print("  - Query: Average time to encode one query")
    print("  - Memory: Peak memory usage for the model")


def main():
    parser = argparse.ArgumentParser(description="Benchmark embedding models on an Obsidian vault")
    parser.add_argument(
        "--vault",
        "-v",
        type=Path,
        required=True,
        help="Path to the Obsidian vault",
    )
    parser.add_argument(
        "--sample",
        "-s",
        type=int,
        default=50,
        help="Number of documents to sample (default: 50)",
    )
    parser.add_argument(
        "--models",
        "-m",
        type=str,
        nargs="+",
        default=None,
        help="Specific models to benchmark (default: all supported models)",
    )
    parser.add_argument(
        "--queries",
        "-q",
        type=int,
        default=10,
        help="Number of queries to test (default: 10)",
    )
    args = parser.parse_args()

    if not args.vault.exists():
        print(f"Error: Vault path does not exist: {args.vault}")
        sys.exit(1)

    # Import here to avoid loading models before argument parsing
    from obsidian_index.index.models import SUPPORTED_MODELS

    models_to_test = args.models or list(SUPPORTED_MODELS.keys())

    # Validate model names
    for model in models_to_test:
        if model not in SUPPORTED_MODELS:
            print(f"Error: Unknown model: {model}")
            print(f"Supported models: {', '.join(SUPPORTED_MODELS.keys())}")
            sys.exit(1)

    print(f"Benchmarking {len(models_to_test)} models on vault: {args.vault}")
    print()

    # Collect documents
    documents = collect_documents(args.vault, args.sample)
    if not documents:
        print("Error: No documents found in vault")
        sys.exit(1)

    # Generate test queries
    test_queries = [
        "meeting notes from last week",
        "project planning and roadmap",
        "bug fixes and debugging",
        "code review feedback",
        "documentation updates",
        "performance optimization",
        "database schema design",
        "API integration",
        "user authentication",
        "deployment configuration",
    ][: args.queries]

    print()

    # Run benchmarks
    results = []
    for i, model_name in enumerate(models_to_test, 1):
        print(f"[{i}/{len(models_to_test)}] {model_name}")
        try:
            result = benchmark_model(model_name, documents, test_queries)
            results.append(result)
        except Exception as e:
            print(f"  Error: {e}")
            results.append(
                {
                    "model": model_name,
                    "dimensions": 0,
                    "load_time": 0,
                    "index_time": 0,
                    "index_per_doc_ms": 0,
                    "query_avg_ms": 0,
                    "memory_mb": 0,
                }
            )
        print()

    # Print results
    print_results_table([r for r in results if r["dimensions"] > 0])


if __name__ == "__main__":
    main()
