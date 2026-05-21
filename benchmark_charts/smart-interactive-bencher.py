import re
import subprocess
import requests
from pathlib import Path
from datetime import datetime
import sys

# ====================== CONFIG ======================
JSONL_PATH = Path(r"C:\Users\antmi\Downloads\stratified_1000.jsonl")
SERVER_URL = "http://localhost:13305"

BASE_OUTPUT = Path("benchmark_results/interactive-smart")
CHART_BASE = Path("benchmark_charts/interactive-smart")
LOG_BASE = Path("benchmark_logs/interactive-smart")

MODELS = [
    "Qwen3.5-0.8B-GGUF",
    "Qwen3.5-4B-GGUF",
    "Qwen3.5-9B-GGUF",
    "Qwen3.5-35B-A3B-GGUF",
]

LIMITS = [10, 20, 50, 100]
BATCH_SIZES = [10, 20, 50]
EXPERIMENTS = 3

# Default interactive scenario (mirrors runner.py DEFAULT_INTERACTIVE_SCENARIO).
# The {limit} placeholder is pre-formatted by the script before piping.
DEFAULT_SCENARIO_TEMPLATE = [
    "Triage my inbox ({limit} emails)",
    "Archive the low priority emails",
    "Star any urgent or actionable messages",
    "Show me a summary of what's left in my inbox",
]
# ====================================================


def check_jsonl_exists():
    if not JSONL_PATH.exists():
        print(f"ERROR: JSONL file not found: {JSONL_PATH}")
        sys.exit(1)


def check_gaia_available():
    """Pre-flight check: verify 'gaia' CLI is on PATH."""
    try:
        subprocess.run(["gaia", "--help"], capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"ERROR: 'gaia' CLI not found or unresponsive: {e}")
        print("Run 'uv pip install -e .' or ensure gaia is on PATH.")
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
    except Exception as e:
        print(f"  [WARN] unload failed for {model_name}: {e}")


def scan_log_for_turn_failures(log_file: Path) -> dict:
    """Scan a log file for 'Turn N FAILED:' patterns and return counts."""
    if not log_file.exists():
        return {"turn_failures": 0, "errors": []}
    text = log_file.read_text(encoding="utf-8")
    failures = len(re.findall(r"Turn \d+ FAILED:", text))
    errors = re.findall(r"Error: (.+)", text)
    return {"turn_failures": failures, "errors": errors[:3]}  # first 3 errors


def build_scenario(limit: int) -> str:
    """Build the stdin string for a simulated interactive session.

    Each line is a command the user would type. The session ends with
    'quit' which causes run_interactive_session() to exit its input loop.
    """
    lines = []
    for template in DEFAULT_SCENARIO_TEMPLATE:
        lines.append(template.format(limit=limit))
    lines.append("quit")
    return "\n".join(lines) + "\n"


def run_interactive_smart_benchmark():
    """Run the interactive smart benchmark across the model/limit/batch-size matrix."""
    print(f"\n{'=' * 70}")
    print(f"PROFILE: INTERACTIVE SMART MODE (--mode interactive --smart)")
    print(f"Description: Multi-turn email triage with heuristic + selective LLM batching")
    print(f"Scenario: {len(DEFAULT_SCENARIO_TEMPLATE)} predefined turns + quit")
    print(f"{'=' * 70}")

    output_dir = BASE_OUTPUT
    chart_dir = CHART_BASE
    log_dir = LOG_BASE

    output_dir.mkdir(parents=True, exist_ok=True)
    chart_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    total_runs = 0
    completed_runs = 0
    failed_runs = 0
    timeout_runs = 0

    for model in MODELS:
        if not load_model(model):
            print(f"  Skipping {model} due to load failure.\n")
            continue

        for limit in LIMITS:
            for batch_size in BATCH_SIZES:
                if batch_size > limit:
                    print(f"    SKIP batch_size={batch_size} > limit={limit}")
                    continue

                total_runs += 1
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                log_file = log_dir / f"{model.replace('/', '-')}_limit{limit}_batch{batch_size}_{timestamp}.log"

                cmd = [
                    "gaia", "email", "bench",
                    "--jsonl-path", str(JSONL_PATH),
                    "--model", model,
                    "--limit", str(limit),
                    "--batch-size", str(batch_size),
                    "--experiments-per-model", str(EXPERIMENTS),
                    "--output-dir", str(output_dir),
                    "--mode", "interactive",
                    "--smart",
                ]

                stdin_data = build_scenario(limit)

                # === Print the exact command being run ===
                print(f"\n  -> Run #{total_runs}: {model} | limit={limit} | batch={batch_size}")
                print(f"    CMD: {' '.join(cmd)}")
                print(f"    Scenario lines: {len(DEFAULT_SCENARIO_TEMPLATE)} + quit")

                try:
                    with open(log_file, "w", encoding="utf-8") as f:
                        result = subprocess.run(
                            cmd,
                            input=stdin_data,
                            text=True,
                            stdout=f,
                            stderr=subprocess.STDOUT,
                            timeout=3600,
                        )

                    if result.returncode == 0:
                        scan = scan_log_for_turn_failures(log_file)
                        if scan["turn_failures"] > 0:
                            print(f"    OK (subprocess 0) but {scan['turn_failures']} turn(s) FAILED - Check log: {log_file}")
                            failed_runs += 1
                        else:
                            print(f"    OK Done (code {result.returncode})")
                            completed_runs += 1
                    else:
                        print(f"    FAILED (code {result.returncode}) - Check log: {log_file}")
                        failed_runs += 1

                except subprocess.TimeoutExpired:
                    print(f"    TIMEOUT after 1 hour")
                    timeout_runs += 1
                except Exception as e:
                    print(f"    ERROR: {e}")
                    failed_runs += 1

        unload_model(model)

    # Generate charts for interactive-smart profile
    print(f"\n[CHARTS] Generating charts for interactive-smart profile...")
    subprocess.run([
        "gaia", "email", "report",
        "--input-dir", str(output_dir),
        "--charts",
        "--chart-dir", str(chart_dir),
    ])

    return total_runs, completed_runs, failed_runs, timeout_runs


def main():
    check_jsonl_exists()
    check_gaia_available()
    start_time = datetime.now()

    total_runs, completed_runs, failed_runs, timeout_runs = run_interactive_smart_benchmark()

    end_time = datetime.now()
    duration = end_time - start_time

    print(f"\n{'=' * 70}")
    print("INTERACTIVE SMART BENCHMARK COMPLETE")
    print(f"Total runs:   {total_runs}")
    print(f"Completed:    {completed_runs}")
    print(f"Failed:       {failed_runs}")
    print(f"Timed out:    {timeout_runs}")
    print(f"Total time:   {duration}")
    print(f"Results saved in: {BASE_OUTPUT}")
    print(f"Charts saved in:  {CHART_BASE}")
    print(f"Logs saved in:    {LOG_BASE}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
