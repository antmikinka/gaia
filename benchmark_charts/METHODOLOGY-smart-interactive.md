# Benchmark Methodology: Smart Interactive Triage vs. Full Agent Loop

**Date:** 2026-05-21
**Applies to:** `--mode interactive --smart` benchmark runs

---

## How the Smart Interactive Path Differs

### Old Path: `process_query()` (Pre-Fix)

The old path treated every email as needing LLM classification, regardless of heuristic confidence:

```
User prompt -> process_query() -> full agent planning loop
    -> LLM decides what tool to call
    -> triage_inbox returns ALL emails with full bodies
    -> LLM reads all emails, classifies them
    -> LLM decides next action (archive, star, etc.)
    -> conversation_history accumulates tool results verbatim
    -> next turn: full history + new tool results -> LLM again
```

Token consumption grew exponentially: Turn 1 (~50K-100K), Turn 2 (~100K-200K), Turn 3 (~150K-400K), Turn 4 (~200K-500K). Total for 4 turns at limit 100: 400K-2M tokens.

The `confident` flag from `triage_inbox` was advisory metadata -- the LLM still read and classified every email.

### New Path: `process_interactive_smart_triage()` (Post-Fix)

The new path uses heuristic classification as a routing decision, not just metadata:

```
User prompt -> process_interactive_smart_triage()
    -> triage_inbox_impl() (direct call, no LLM)
    -> heuristic classifies ALL emails
    -> confident emails: cached, token_count=0, no LLM
    -> non-confident emails: checked against _smart_triaged_cache
       -> already classified (prior turn): skip, token_count=0
       -> new non-confident: batched through LLM
    -> returns compact dict (triage summary, not full bodies)
    -> runner syncs cache for next turn
```

Token consumption is bounded: Turn 1 (~5K-20K), Turn 2 (~2K-10K cache hits), Turn 3 (~1K-5K), Turn 4 (~1K-5K). Total for 4 turns at limit 100: 20K-50K tokens.

---

## Interpreting Token Counts

### Heuristic Emails Show 0 LLM Tokens

When an email is classified confidently by the heuristic, it consumes zero LLM tokens. This is correct -- no LLM was invoked. However, it means:

- A turn where all emails are heuristic-confident will show `total_tokens: 0`.
- The heuristic did real classification work; it just did not involve the LLM.
- Comparing "0 tokens" (smart path) to "80K tokens" (old path) for the same inbox is misleading if you interpret it as "less work was done."

### Two Metrics for Fair Comparison

Report both:

1. **LLM tokens consumed** -- the actual input + output + reasoning tokens from LLM calls.
2. **Estimated heuristic token savings** -- `heuristic_email_count * ~2048` (estimated per-email LLM cost avoided).

The benchmark runner reports both in the summary:

```
Heuristic fast-path: ~7 LLM calls avoided
Estimated tokens avoided: ~14,336 output tokens (7 emails x ~2048 avg)
```

---

## How to Compare Smart vs. Non-Smart Runs Fairly

### What Changes Between the Paths

| Aspect | Smart Interactive | Non-Smart Interactive |
|--------|-------------------|----------------------|
| Classification method | Same heuristic | Same heuristic |
| LLM quality on uncertain emails | Identical (same model, same prompt) | Identical |
| Token consumption | Heuristic emails cost 0 LLM tokens | All emails cost LLM tokens |
| Context growth | Bounded by compaction | Unbounded accumulation |

### What to Compare

- **Classification accuracy:** Compare the category distributions (urgent, actionable, low priority, informational). They should be nearly identical -- the heuristic handles clear-cut cases the same way in both paths.
- **LLM quality on uncertain emails:** The subset of emails that go through the LLM in smart mode should receive the same classifications as they would in non-smart mode.
- **Action correctness:** Archive, star, draft, and send actions should target the same emails in both modes.

### What NOT to Compare Directly

- **Token counts:** Pre-fix and post-fix token counts use fundamentally different measurement instruments. Do not mix them in the same chart without clear labeling.
- **Response time:** Smart mode skips LLM calls for confident emails, so wall-clock time is not comparable to non-smart mode that waits for LLM on every email.
- **Conversation history length:** Smart mode uses compacted context; non-smart mode accumulates verbatim. Length alone is not a quality metric.

---

## Chart Compatibility

All charts 24-29 work with post-fix smart-mode data:

- **Chart 24 (Planning Steps Heatmap):** Post-fix runs show near-zero planning steps for high-heuristic inboxes. This is correct.
- **Chart 25 (Token Efficiency Bars):** Post-fix bars are shorter. The "H: XX%" overlay now reflects actual LLM savings.
- **Chart 27 (Interactive LLM Activity):** Post-fix turns show dramatically fewer LLM calls. Turns after Turn 1 may show zero if all emails were classified earlier.

Pre-fix and post-fix results should not be mixed in the same chart without clear labeling.
