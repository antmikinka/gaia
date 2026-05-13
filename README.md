# <img src="https://raw.githubusercontent.com/amd/gaia/main/src/gaia/img/gaia.ico" alt="GAIA Logo" width="64" height="64" style="vertical-align: middle;"> GAIA: AI Agent Framework for AMD Ryzen AI

[![GAIA CLI Tests](https://github.com/amd/gaia/actions/workflows/test_gaia_cli.yml/badge.svg)](https://github.com/amd/gaia/tree/main/tests "Check out our cli tests")
[![Latest Release](https://img.shields.io/github/v/release/amd/gaia?include_prereleases)](https://github.com/amd/gaia/releases/latest "Download the latest release")
[![PyPI](https://img.shields.io/pypi/v/amd-gaia)](https://pypi.org/project/amd-gaia/)
[![GitHub downloads](https://img.shields.io/github/downloads/amd/gaia/total.svg)](https://github.com/amd/gaia/releases)
[![OS - Windows](https://img.shields.io/badge/OS-Windows-blue)](https://amd-gaia.ai/docs/quickstart "Windows installation")
[![OS - Linux](https://img.shields.io/badge/OS-Linux-green)](https://amd-gaia.ai/docs/quickstart "Linux installation")
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Discord](https://img.shields.io/badge/Discord-Join%20Community-7289DA?logo=discord&logoColor=white)](https://discord.com/channels/1392562559122407535/1402013282495102997)

**GAIA** is AMD's open-source framework for building intelligent AI agents that run **100% locally** on AMD Ryzen AI hardware. Keep your data private, eliminate cloud costs, and deploy in air-gapped environments—all with hardware-accelerated performance.

<p align="center">
  <a href="https://amd-gaia.ai/docs/quickstart"><strong>Get Started →</strong></a>
</p>

---

## Download

[![Download for Windows](https://img.shields.io/badge/Download-Windows-0078d4?style=for-the-badge&logo=windows)](https://github.com/amd/gaia/releases/latest)
[![Download for macOS](https://img.shields.io/badge/Download-macOS-000000?style=for-the-badge&logo=apple)](https://github.com/amd/gaia/releases/latest)
[![Download for Linux](https://img.shields.io/badge/Download-Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black)](https://github.com/amd/gaia/releases/latest)

See the [installation guide](https://github.com/amd/gaia/blob/main/docs/guides/install.mdx) for setup instructions.

---

## Why GAIA?

| Feature | Description |
|---------|-------------|
| **100% Local** | All data stays on your machine—perfect for sensitive workloads and air-gapped deployments |
| **Zero Cloud Costs** | No API fees, no usage limits, no subscriptions—unlimited AI at no extra cost |
| **Privacy-First** | HIPAA-compliant, GDPR-friendly—ideal for healthcare, finance, and enterprise |
| **Ryzen AI Optimized** | Hardware-accelerated inference using NPU + iGPU on AMD Ryzen AI processors |

---

## Build Your First Agent

```python
from gaia.agents.base.agent import Agent
from gaia.agents.base.tools import tool

class MyAgent(Agent):
    """A simple agent with custom tools."""

    def _get_system_prompt(self) -> str:
        return "You are a helpful assistant."

    def _register_tools(self):
        @tool
        def get_weather(city: str) -> dict:
            """Get weather for a city."""
            return {"city": city, "temperature": 72, "conditions": "Sunny"}

agent = MyAgent()
result = agent.process_query("What's the weather in Austin?")
print(result)
```

**[See the full quickstart guide →](https://amd-gaia.ai/docs/quickstart)**

---

## Key Capabilities

- **Agent Framework** — Base class with tool orchestration, state management, and error recovery
- **Agent UI** — Privacy-first desktop app with chat, file browser, document indexing, and tool execution
- **RAG System** — Document indexing and semantic search for Q&A over 50+ file formats
- **Voice Integration** — Whisper ASR + Kokoro TTS for speech interaction (P0 enabling technology)
- **Vision Models** — Extract text from images with Qwen3-VL-4B
- **MCP Integration** — Connect to any MCP server for external tool access
- **Plugin System** — Distribute agents via PyPI with auto-discovery

---

## Email Benchmark

GAIA includes a benchmark suite for evaluating email triage performance across models and frameworks. The workflow has three commands:

1. **`gaia email bench`** — Run benchmarks against a set of emails, producing `results_*.jsonl` files.
2. **`gaia email clawflow`** — Run ClawFlow-specific email benchmarks for cross-framework comparison.
3. **`gaia email report`** — Generate a unified report and visualizations from existing benchmark data.

### Generating Reports

```bash
gaia email report --input-dir benchmark_results --charts --chart-dir benchmark_charts
```

**Output files:**

| File | Description |
|------|-------------|
| `report.csv` | Unified benchmark results table |
| `variance.json` | Statistical variance analysis (requires 2+ runs) |
| `charts/` | PNG visualizations (auto-selected based on available data) |

**Available flags:**

| Flag | Purpose |
|------|---------|
| `--input-dir` | Directory containing benchmark `results_*.jsonl` files |
| `--output-dir` | Directory for report files (defaults to `--input-dir`) |
| `--charts` | Enable chart generation |
| `--chart-dir` | Directory for chart PNGs (defaults to `<input-dir>/charts`) |
| `--skip-cold-start` | Exclude cold-start runs from variance analysis |
| `--ground-truth <path>` | Path to ground truth JSON for quality scoring |
| `--cost-per-1m-input` / `--cost-per-1m-output` | Cost estimation parameters |

**Chart taxonomy (21 charts, auto-selected based on data availability):**

| Chart | Name | When Generated |
|-------|------|----------------|
| 1 | Category Distribution (horizontal bar) | Single run present |
| 2 | Token Composition (donut) | Full/interactive mode |
| 3 | Duration vs Tokens (grouped column) | Full/interactive mode |
| 4 | Per-Email Duration Histogram | Single run present |
| 5a | LLM Latency Consistency (line) | 2+ runs |
| 5b | LLM Token Variance (line) | 2+ runs, tokens > 0 |
| 5c | Per-Email Cost Variance (dual-axis) | 2+ runs |
| 5d | TTFT Consistency (line) | 2+ runs, TTFT > 0 |
| 5e | TPS Consistency (line) | 2+ runs, TPS > 0 |
| 6 | Interactive Turn Breakdown | Interactive JSON present |
| 7 | Interactive Token Heatmap | Interactive JSON present |
| 8 | Category Stability (stacked bar) | 2+ runs |
| 9 | Token vs Duration Scatter | Single run present |
| 10 | Per-Step TTFT & TPS | Full/interactive mode, stats available |
| 11 | Model Duration Comparison | 2+ distinct models |
| 12 | Model Token Cost (stacked) | 2+ distinct models |
| 13 | TTFT Comparison (horizontal bar) | 2+ models, TTFT > 0 |
| 14 | TPS Comparison (horizontal bar) | 2+ models, TPS > 0 |
| 15 | Framework Category Comparison | ClawFlow + GAIA present |
| 16 | Architecture Radar | ClawFlow + GAIA present |
| 17 | Per-Model Variance Trend | 2+ models, each with 2+ runs |
| 18 | Cold-Start Impact (scatter) | 2+ models, has cold-start runs |
| 19 | Model x Architecture Duration | ClawFlow + GAIA + 1+ model |
| 20 | Model x Architecture Tokens | ClawFlow + GAIA + 1+ model |
| 21 | Architecture Performance Dashboard | ClawFlow + GAIA + 1+ model |

---

## C++ Framework

A C++17 port of the GAIA base agent framework is available under [`cpp/`](cpp/README.md). It implements the same agent loop, tool registry, and MCP client interface without any Python dependency — suitable for embedding in native applications or resource-constrained environments.

```cpp
#include <gaia/agent.h>

class MyAgent : public gaia::Agent {
protected:
    std::string getSystemPrompt() const override {
        return "You are a helpful assistant.";
    }
};
```

**[C++ build and usage instructions →](cpp/README.md)**

---

## Quick Install

```bash
pip install amd-gaia
```

For complete setup instructions including Lemonade Server, see the **[Quickstart Guide](https://amd-gaia.ai/docs/quickstart)**.

---

## System Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| **Processor** | AMD Ryzen AI 300-series | AMD Ryzen AI Max+ 395 |
| **OS** | Windows 11, Linux | - |
| **RAM** | 16GB | 64GB |

---

## Documentation

- **[Quickstart](https://amd-gaia.ai/docs/quickstart)** — Build your first agent in 10 minutes
- **[SDK Reference](https://amd-gaia.ai/docs/sdk)** — Complete API documentation
- **[Guides](https://amd-gaia.ai/docs/guides)** — Chat, Voice, RAG, and more
- **[FAQ](https://amd-gaia.ai/docs/reference/faq)** — Frequently asked questions

---

## Releases

See the full [Release Notes](https://amd-gaia.ai/docs/releases) on the documentation site, or browse [GitHub Releases](https://github.com/amd/gaia/releases).

### Release Process

To publish a new release (e.g. `v0.17.0`), create a release PR that updates these 3 files:

| # | File | What to change |
|---|------|----------------|
| 1 | `src/gaia/version.py` | Set `__version__ = "0.17.0"` |
| 2 | `docs/releases/v0.17.0.mdx` | Create release notes (see [format guide](https://amd-gaia.ai/docs/releases)) |
| 3 | `docs/docs.json` | **(a)** Add `"releases/v0.17.0"` to the Releases tab pages array, **(b)** update the navbar label to `"v0.17.0 · Lemonade X.Y.Z"` |

Then merge and tag:

```bash
git tag v0.17.0 && git push origin v0.17.0
```

CI validates all three files are consistent with the tag before publishing to [GitHub Releases](https://github.com/amd/gaia/releases) and [PyPI](https://pypi.org/project/amd-gaia/).

---

## Contributing

We welcome contributions! See our [Contributing Guide](CONTRIBUTING.md) for details.

- **Build agents** in your own repository using GAIA as a dependency
- **Improve the framework** — check [GitHub Issues](https://github.com/amd/gaia/issues) for open tasks
- **Add documentation** — examples, tutorials, and guides

---

## Contact

- **Email**: [gaia@amd.com](mailto:gaia@amd.com)
- **Discord**: [Join our community](https://discord.com/channels/1392562559122407535/1402013282495102997)
- **Issues**: [GitHub Issues](https://github.com/amd/gaia/issues)

---

## License

[MIT License](./LICENSE.md)

Copyright(C) 2024-2026 Advanced Micro Devices, Inc. All rights reserved.
SPDX-License-Identifier: MIT
