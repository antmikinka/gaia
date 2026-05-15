# Issue: Context Overflow During Interactive Email Session

**Observed:** 2026-05-13
**Affected command:** `gaia email bench` (interactive mode, multi-turn)
**Files:** `src/gaia/agents/email/bench/runner.py`, `src/gaia/agents/email/fake_gmail.py`

**Classification:** **DESIGN LIMITATION — full email bodies exceed model context window**

---

## Observed Error

```
Lemonade error: request (84306 tokens) exceeds the available context size (32768 tokens)
Error in send_messages: This conversation got too long for the model's context window.
Context overflow mid-loop — shrunk messages to 30 entries and retrying once
request (83904 tokens) exceeds the available context size (32768 tokens)
```

---

## What Happened

The interactive benchmark session loaded 10 emails from the MBOX file into the agent's context via the `triage_inbox` tool. The emails are **promotional marketing messages** with full HTML bodies:

| Sender | Subject | Body Size (est. tokens) |
|--------|---------|------------------------|
| Amazon | Easter deals / Retargeting | ~10K each (long tracking URLs) |
| Whole Foods | Easter promotions x2 | ~8K each (HTML + unsubscribe footers) |
| GroupGolfer | Golf deals x3 | ~5K each |
| Pulsetto | Cart abandonment x2 | ~6K each (markdown links) |
| Robinhood | "Quantum incoming" | ~1K |
| SJ Public Library | Events/Newsletter x2 | ~8K each |

**Total: ~84K tokens vs. 32K available context = 2.5x over limit.**

---

## Triage Results Before Failure

The triage completed successfully across the first 3 turns:

- **10 emails triaged** — `informational: 7`, `low priority: 3`
- **6 emails archived** (low-priority promotional messages)
- **0 errors** in classification

**The triage logic is correct.** All 10 emails are promotional or informational — no urgent items, no spam (legitimate senders), no phishing. The model classified them appropriately.

The failure occurred on **turn 4** — when the agent tried to generate a text response after completing the archival actions. The context was already over capacity from the email bodies alone.

---

## Root Cause: Full Email Bodies in Context

The `triage_inbox` tool passes **complete email dicts** to the LLM, including:

- Full `body` text (not just snippets)
- Complete `payload` dicts with MIME parts
- Long tracking URLs (`?utm_source=...&ref_=...&node=...&pf_rd_p=...`)
- Unsubscribe footers and legal text
- HTML content with CSS inline styles

Promotional emails are the worst case for context because they contain:
1. Multiple long URLs with tracking parameters
2. HTML/CSS markup
3. Legal disclaimers and unsubscribe text
4. Embedded marketing copy

Each promotional email can be **5K-10K tokens**. With a default context window of 32K, the agent can only handle ~3-4 promotional emails at once.

---

## Why the Retry Failed

The base agent's overflow recovery (in `agent.py:2522`) shrunk the conversation to 30 entries:

```
Context overflow mid-loop — shrunk messages to 30 entries and retrying once
```

But the token count barely moved: **84,306 → 83,904 tokens** (only 402 tokens removed).

**Why:** The recovery shrinks conversation *message count* but not message *content*. The email bodies themselves are the bulk — removing a few short system messages doesn't help when each tool result contains a 10K-token email.

---

## Impact on Benchmark Results

### Full benchmark mode (single-turn)
**Not affected.** The `_run_full_agent()` function runs one `process_query()` call. If the context overflows, it returns an error status. The benchmark harness captures this as a failed run.

### Interactive benchmark mode (multi-turn)
**Affected.** Each turn adds to the conversation history. By turn 2-3, the accumulated email bodies + conversation exceeds context. The interactive session breaks mid-flow.

### Live Gmail usage (`gaia email -i`)
**Not affected in the same way.** Live Gmail loads messages in smaller batches (the `list_messages` API returns stubs, `get_message` loads one at a time). The MBOX loader loads ALL messages upfront.

---

## Workaround

Increase the Lemonade server context size:

```bash
lemonade-server serve --ctx-size 131072  # 128K context
```

This allows ~15-20 promotional email bodies to fit.

---

## Proper Fixes (Candidates)

### Option 1: Truncate email bodies in triage results
The `triage_inbox` tool should include a `body_max_tokens` or `truncate_body` parameter. For classification, the first 500-1000 characters of the body are sufficient. Full bodies are only needed for reply/draft actions.

**Pros:** Reduces context by 80-90% per email. Classification accuracy unchanged for most categories.
**Cons:** May lose accuracy for phishing detection (which sometimes relies on body content).

### Option 2: Batch emails into smaller groups
Instead of loading all N emails at once, the benchmark could batch them into groups of 3-4 and run triage on each batch, then merge results.

**Pros:** No code change to the tool. Works within existing context limits.
**Cons:** Multiple LLM calls (more tokens, slower). Loses cross-email comparison context.

### Option 3: Use snippets instead of bodies for triage
Change the MBOX loader to only include `subject`, `from`, `date`, `snippet`, and `label_ids` in the email dict. Reserve `body` and `payload` for tools that need full content (reply, draft, archive with preview).

**Pros:** Snippets are ~100-200 characters each. 10 emails = ~2K tokens, well within 32K.
**Cons:** Requires changing the email agent's system prompt to work with snippet-based triage.

### Option 4: Increase default ctx-size in benchmark config
The benchmark runner could start a temporary Lemonade server with a larger context window, or warn users if the current ctx-size is insufficient.

**Pros:** No changes to agent logic. Simple config change.
**Cons:** Requires more VRAM. Not all hardware supports large contexts.

---

## Recommendation

**Option 1 + Option 3** together:
- `triage_inbox` should only return `subject`, `from`, `date`, `snippet`, and `label_ids` for initial triage
- If the model needs full body content (for a specific email it flags), it can call a separate `get_email_body` tool
- This matches how humans triage email — scan subject + preview, open only interesting ones

This would reduce per-email context from ~8K tokens to ~200 tokens, allowing 100+ emails in a 32K context.
