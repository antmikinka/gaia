import subprocess

import requests

from pathlib import Path

from datetime import datetime

import sys

# ====================== CONFIG ======================

JSONL_PATH = Path(r"C:\Users\antmi\Downloads\stratified_1000.jsonl")

# Dummy MBOX path (required by CLI even when using JSONL)

DUMMY_MBOX_PATH = Path(r"C:\Users\antmi\Downloads\dummy.mbox")

SERVER_URL = "http://localhost:13305"

BASE_OUTPUT = Path("benchmark_results")

CHART_BASE = Path("benchmark_charts")

LOG_BASE = Path("benchmark_logs")

MODELS = [

    "Qwen3.5-0.8B-GGUF",

    "Qwen3.5-4B-GGUF",

    "Qwen3.5-9B-GGUF",

    "Qwen3.5-35B-A3B-GGUF",

]

LIMITS = [10, 20, 50, 100]

BATCH_SIZES = [10, 20, 50]

EXPERIMENTS = 3

PROFILES = {

    "baseline": {

        "flags": [],

        "description": "Normal full mode (heuristic heavy)"

    },

    "smart": {

        "flags": ["--smart"],

        "description": "Hybrid heuristic + selective LLM batching"

    },

}

# ====================================================

def check_jsonl_exists():

    if not JSONL_PATH.exists():

        print(f"ERROR: JSONL file not found: {JSONL_PATH}")

        sys.exit(1)

def load_model(model_name):

    print(f"  [LOAD] {model_name}...", end=" ", flush=True)

    try:

        r = requests.post(f"{SERVER_URL}/v1/load", json={"model_name": model_name}, timeout=120)

        if r.json().get("status") == "success":

            print("OK")

            return True

        print("FAILED")

        return False

    except Exception as e:

        print(f"ERROR: {e}")

        return False

def unload_model(model_name):

    print(f"  [UNLOAD] {model_name}")

    try:

        requests.post(f"{SERVER_URL}/v1/unload", json={"model_name": model_name}, timeout=30)

    except:

        pass

def run_profile(profile_name, profile_config):

    print(f"\n{'='*70}")

    print(f"PROFILE: {profile_name.upper()}")

    print(f"Description: {profile_config['description']}")

    print(f"{'='*70}")

    output_dir = BASE_OUTPUT / profile_name

    chart_dir = CHART_BASE / profile_name

    log_dir = LOG_BASE / profile_name

    output_dir.mkdir(parents=True, exist_ok=True)

    chart_dir.mkdir(parents=True, exist_ok=True)

    log_dir.mkdir(parents=True, exist_ok=True)

    for model in MODELS:

        if not load_model(model):

            print(f"  Skipping {model} due to load failure.\n")

            continue

        for limit in LIMITS:

            for batch_size in BATCH_SIZES:

                if batch_size > limit:

                    continue

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                log_file = log_dir / f"{model}_limit{limit}_batch{batch_size}_{timestamp}.log"

                cmd = [

                    "gaia", "email", "bench",

                    "--jsonl-path", str(JSONL_PATH),

                    "--mbox-path", str(DUMMY_MBOX_PATH),   # ← Added dummy mbox path

                    "--model", model,

                    "--limit", str(limit),

                    "--batch-size", str(batch_size),

                    "--experiments-per-model", str(EXPERIMENTS),

                    "--output-dir", str(output_dir),

                ] + profile_config["flags"]

                print(f"\n  → {model} | limit={limit} | batch={batch_size}")

                print(f"    CMD: {' '.join(cmd)}")

                try:

                    with open(log_file, "w", encoding="utf-8") as f:

                        result = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=3600)

                    if result.returncode == 0:

                        print(f"    ✅ Done (code {result.returncode})")

                    else:

                        print(f"    ❌ FAILED (code {result.returncode}) — Check log: {log_file}")

                except Exception as e:

                    print(f"    ERROR: {e}")

        unload_model(model)

    print(f"\n[CHARTS] Generating charts for profile '{profile_name}'...")

    subprocess.run([

        "gaia", "email", "report",

        "--input-dir", str(output_dir),

        "--charts",

        "--chart-dir", str(chart_dir)

    ])

def main():

    check_jsonl_exists()

    start_time = datetime.now()

    for profile_name, config in PROFILES.items():

        run_profile(profile_name, config)

    end_time = datetime.now()

    duration = end_time - start_time

    print(f"\n{'='*70}")

    print("BENCHMARK COMPLETE")

    print(f"Results saved in: {BASE_OUTPUT}")

    print(f"Charts saved in:  {CHART_BASE}")

    print(f"Logs saved in:    {LOG_BASE}")

    print(f"{'='*70}")

if __name__ == "__main__":

    main()