#!/usr/bin/env python3
"""
Log Analyzer for Interactive-Smart Benchmark Runs
Extracts key metrics from log files and builds a structured dataset.
"""

import re
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import sys

LOG_DIR = Path("benchmark_logs/smart")
OUTPUT_JSON = Path("smart_benchmark_analysis.json")
OUTPUT_CSV = Path("smart_benchmark_analysis.csv")


def parse_log_file(log_path: Path) -> dict:
    """Parse a single log file and extract key metrics."""
    if not log_path.exists():
        return {"status": "missing"}

    text = log_path.read_text(encoding="utf-8", errors="ignore")

    result = {
        "log_file": str(log_path.name),
        "model": None,
        "limit": None,
        "batch_size": None,
        "status": "unknown",
        "duration_s": None,
        "heuristic_emails": 0,
        "llm_emails": 0,
        "total_tokens": 0,
        "categories": {},
        "turn_failures": 0,
        "error_snippet": None,
    }

    # Extract model, limit, batch_size from filename
    name = log_path.name
    model_match = re.search(r"(Qwen3\.5-[\d.]+[A-Z0-9-]*)", name)
    if model_match:
        result["model"] = model_match.group(1)

    limit_match = re.search(r"limit(\d+)", name)
    if limit_match:
        result["limit"] = int(limit_match.group(1))

    batch_match = re.search(r"batch(\d+)", name)
    if batch_match:
        result["batch_size"] = int(batch_match.group(1))

    # Status
    if "GAIA Email Triage Benchmark — SMART mode" in text:
        result["status"] = "completed"
    elif "Error:" in text or "FAILED" in text:
        result["status"] = "failed"
    elif "unrecognized arguments" in text or "required: --mbox-path" in text:
        result["status"] = "argparse_error"

    # Duration
    dur_match = re.search(r"Duration:\s+([\d.]+)s", text)
    if dur_match:
        result["duration_s"] = float(dur_match.group(1))

    # Heuristic vs LLM split (from successful smart runs)
    h_match = re.search(r"Heuristic:\s*(\d+)\s*emails", text)
    if h_match:
        result["heuristic_emails"] = int(h_match.group(1))

    llm_match = re.search(r"LLM:\s*(\d+)\s*emails", text)
    if llm_match:
        result["llm_emails"] = int(llm_match.group(1))

    # Total tokens
    tok_match = re.search(r"Total tokens:\s*([\d,]+)", text)
    if tok_match:
        result["total_tokens"] = int(tok_match.group(1).replace(",", ""))

    # Category distribution
    cat_section = re.search(r"Category Distribution:([\s\S]+?)(?=\n\n|\Z)", text)
    if cat_section:
        for line in cat_section.group(1).strip().split("\n"):
            m = re.search(r"(\w+(?:\s+\w+)?)\s+\(.*?(\d+)\s*\((\d+\.\d+)%\)", line)
            if m:
                result["categories"][m.group(1).strip()] = {
                    "count": int(m.group(2)),
                    "percent": float(m.group(3))
                }

    # Turn failures
    result["turn_failures"] = len(re.findall(r"Turn \d+ FAILED:", text))

    # Capture first error snippet if failed
    if result["status"] == "failed":
        err_match = re.search(r"Error: (.+)", text)
        if err_match:
            result["error_snippet"] = err_match.group(1)[:200]

    return result


def main():
    if not LOG_DIR.exists():
        print(f"ERROR: Log directory not found: {LOG_DIR}")
        sys.exit(1)

    log_files = sorted(LOG_DIR.glob("*.log"))
    print(f"Found {len(log_files)} log files in {LOG_DIR}")

    all_results = []
    summary = defaultdict(lambda: {"total": 0, "completed": 0, "failed": 0})

    for log_file in log_files:
        data = parse_log_file(log_file)
        all_results.append(data)

        model = data.get("model", "unknown")
        summary[model]["total"] += 1
        if data["status"] == "completed":
            summary[model]["completed"] += 1
        else:
            summary[model]["failed"] += 1

    # Save structured JSON
    output = {
        "generated_at": datetime.now().isoformat(),
        "total_logs_scanned": len(log_files),
        "results": all_results,
        "summary_by_model": dict(summary)
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Structured data saved to: {OUTPUT_JSON}")

    # Print quick summary
    print("\n=== Quick Summary by Model ===")
    for model, stats in summary.items():
        print(f"{model}: {stats['completed']} completed / {stats['total']} total")

    print(f"\nTotal successful SMART runs found: {sum(s['completed'] for s in summary.values())}")


if __name__ == "__main__":
    main()