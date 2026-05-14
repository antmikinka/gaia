# Migration Plan: MBOX to JSONL Email Data Format

## Executive Summary

Replace the MBOX-based email data loading in the GAIA email benchmark pipeline with a new JSONL-based loader. The JSONL format (`stratified_1000.jsonl`) contains 1,000 synthetically-generated emails with pre-computed categories and action labels. The migration introduces a new `FakeGmailBackend` data path while preserving backward compatibility with the existing MBOX mode.

---

## 1. JSONL Data Analysis

### File: `C:\Users\antmi\Downloads\stratified_1000.jsonl`
- **Total emails**: 1,000
- **Format**: One JSON object per line
- **All records**: `origin_type: synthetic`, `source_dataset: synthetic_llm`

### Schema (19 fields)

| Field | Type | Example | Required for Gmail mapping? |
|-------|------|---------|---------------------------|
| `id` | str | `"e654b348-..."` (UUID) | YES — becomes message `id` |
| `sender` | str | `"Maria Evans <m.evans@companyservicedesk.com>"` | YES — becomes `From` header |
| `subject` | str | `"Immediate Action Needed: SLA Breach..."` | YES — becomes `Subject` header |
| `date` | str | `"2026-05-08T09:25:00Z"` (ISO 8601) | YES — becomes `Date` header + `internalDate` |
| `body_preview` | str | `"Team, following up on my earlier note..."` | YES — becomes body snippet/payload |
| `category` | str | `URGENT`, `NEEDS_RESPONSE`, `FYI`, `PROMOTIONAL`, `PERSONAL` | YES — maps to Gmail label IDs |
| `suggestedAction` | str | `reply`, `none`, `archive` | NO — metadata only |
| `origin_type` | str | `"synthetic"` | NO — metadata only |
| `source_dataset` | str | `"synthetic_llm"` | NO — metadata only |
| `labeling_provider` | null | `null` | NO |
| `labeling_model` | null | `null` | NO |
| `label_prompt_id` | null | `null` | NO |
| `generation_provider` | str | `"openai"` | NO — metadata only |
| `generation_model` | str | `"gpt-4.1"` | NO — metadata only |
| `generation_prompt_id` | str | UUID | NO — metadata only |
| `variation_prompt_id` | str/null | UUID or null | NO — metadata only |
| `variation_strategy_name` | str | `"urgency_or_deadline"` | NO — metadata only |
| `variation_contextual_anchor` | str | `"critical customer blocker"` | NO — metadata only |
| `variation_thread_reference` | str | `"Current open ticket thread"` | YES — optional thread_id seed |
| `variation_thread_mode` | str | `"mail_thread"` | NO — metadata only |

### Category Distribution (exactly balanced)
- `URGENT`: 200
- `NEEDS_RESPONSE`: 200
- `FYI`: 200
- `PROMOTIONAL`: 200
- `PERSONAL`: 200

### Suggested Action Distribution
- `reply`: 600
- `none`: 200
- `archive`: 200

---

## 2. Current MBOX Pipeline Analysis

### Data flow: MBOX -> FakeGmailBackend -> Agent Tools

```
MBOX file (.mbox)
    |
    v
FakeGmailBackend.load_mbox()        [fake_gmail.py:290]
    |
    +-> mailbox.mbox(str(path))     [Python stdlib]
    +-> mbox_message_to_gmail_payload(msg) [fake_gmail.py:161]
    |       |
    |       +-> _walk_mime_to_payload() — recursive MIME->Gmail payload
    |       +-> _build_snippet() — first text/plain part
    |       +-> _internal_date_ms() — header Date -> millis string
    |       +-> _parse_x_gmail_labels() — X-Gmail-Labels -> system label IDs
    |       +-> SHA256-derived id/threadId from Message-ID header
    |
    v
Messages stored in self._messages: Dict[str, GmailPayload]
    |
    v
Agent tool calls (triage_inbox, list_inbox, get_message, etc.)
    |
    +-> gmail.list_messages(label_ids=["INBOX"], max_results=N)
    |       -> returns {"messages": [{"id":..., "threadId":...}, ...]}
    |
    +-> gmail.get_message(message_id)
    |       -> returns full Gmail API v1 payload with headers, parts, body
    |
    v
triage_inbox_impl() extracts headers from payload, runs heuristics
    |
    v
Agent classifies each email: urgent / actionable / informational / low priority
```

### Key contract: Gmail API v1 shape

Every message in `FakeGmailBackend._messages` must match this shape:

```python
{
    "id": str,                    # 16-char hex, SHA256-derived
    "threadId": str,              # 16-char hex, from References/In-Reply-To
    "labelIds": [str],            # ["INBOX", "UNREAD", "CATEGORY_PROMOTIONS", ...]
    "snippet": str,               # first 200 chars of text/plain body
    "internalDate": str,          # millis since epoch as string
    "payload": {
        "mimeType": str,          # "text/plain", "multipart/alternative", etc.
        "filename": str,
        "headers": [              # list of {name, value} dicts
            {"name": "Subject", "value": "..."},
            {"name": "From", "value": "..."},
            {"name": "Date", "value": "..."},
            {"name": "To", "value": "..."},
        ],
        "body": {
            "size": int,
            "data": str,          # URL-safe base64, no padding (b64url)
        },
    },
    "sizeEstimate": int,
}
```

### What the agent's triage_inbox tool actually consumes

From `triage_inbox_impl()` (read_tools.py:193-225):
```python
listing = gmail.list_messages(label_ids=["INBOX"], max_results=max_messages)
for stub in listing.get("messages", []):
    msg = gmail.get_message(stub["id"])
    payload_headers = {
        (h["name"]).lower(): h["value"]
        for h in msg["payload"]["headers"]
    }
    # Uses: payload_headers["subject"], payload_headers["from"], msg["labelIds"]
```

And from `list_inbox_impl()` / `_format_message_for_llm()`:
```python
# Extracts: id, threadId, subject, from, to, date, labelIds, snippet
# Decodes body via decode_message_body(payload)
```

### What `_query_matches()` needs (for search)

From `fake_gmail.py:621-651`:
- `payload.headers[]` for `from:` and `subject:` matching
- `labelIds` for `is:unread` matching
- `snippet` for free-text matching

---

## 3. Field Mapping: JSONL -> Gmail API v1 Shape

| Gmail Field | JSONL Source | Transformation |
|-------------|-------------|----------------|
| `id` | `id` | Use UUID as-is (truncate to 16 hex chars or keep full UUID) |
| `threadId` | `variation_thread_reference` | SHA256-hash the thread reference string to produce deterministic thread_id |
| `labelIds` | `category` | Map JSONL category -> Gmail label IDs (see mapping below) |
| `snippet` | `body_preview` | Use directly, truncate to 200 chars |
| `internalDate` | `date` | Parse ISO 8601 -> millis since epoch as string |
| `payload.headers` | `sender`, `subject`, `date` | Build `[{name, value}, ...]` list |
| `payload.body.data` | `body_preview` | Encode as b64url |
| `payload.mimeType` | — | `"text/plain"` (all JSONL emails are plain text) |
| `sizeEstimate` | `body_preview` | `len(body_preview)` |

### Category -> Gmail Label ID Mapping

| JSONL `category` | Gmail `labelIds` | Heuristic outcome |
|------------------|-----------------|-------------------|
| `URGENT` | `["INBOX", "UNREAD", "IMPORTANT"]` | Heuristic rule #7 fires (IMPORTANT -> actionable, confident=False -> LLM) |
| `NEEDS_RESPONSE` | `["INBOX", "UNREAD", "STARRED"]` | Heuristic rule #7 fires (STARRED -> actionable, confident=False -> LLM) |
| `FYI` | `["INBOX", "UNREAD"]` | No heuristic rule fires -> informational, confident=False -> LLM |
| `PROMOTIONAL` | `["INBOX", "UNREAD", "CATEGORY_PROMOTIONS"]` | Heuristic rule #2 fires -> low priority, confident=True (NO LLM) |
| `PERSONAL` | `["INBOX", "UNREAD", "CATEGORY_PERSONAL"]` | No specific heuristic rule -> informational, confident=False -> LLM |

**Note**: All emails are marked `UNREAD` to match the MBOX default behavior (fake_gmail.py:204-206).

---

## 4. Files That Need Changes

### 4.1 `src/gaia/agents/email/fake_gmail.py` — ADD JSONL loader

**New function**: `jsonl_record_to_gmail_payload(record: dict) -> Dict[str, Any]`
- Converts a single JSONL record to Gmail API v1 shape
- Handles: id, thread_id derivation, label mapping, date parsing, body encoding

**New method on `FakeGmailBackend`**: `load_jsonl(path: Path) -> None`
- Reads JSONL line by line
- Calls `jsonl_record_to_gmail_payload()` for each record
- Stores in `self._messages` (same dict as MBOX path)

**Modified `__init__`**: Accept either `mbox_path` or `jsonl_path` (mutually exclusive)

**Keep**: All existing MBOX code intact — backward compatibility preserved.

### 4.2 `src/gaia/agents/email/bench/runner.py` — ADD JSONL loading path

**New function**: `load_emails_from_jsonl(jsonl_path, *, limit=100) -> list[dict]`
- Mirrors `load_emails_from_mbox()` but uses the JSONL loader

**Modified `_run_full_agent`**: Accept `jsonl_path` as alternative to `mbox_path`
- Create `FakeGmailBackend(jsonl_path=Path(jsonl_path))` instead of mbox

**Modified `run_interactive_benchmark`**: Same pattern — accept `jsonl_path`

**Modified `run_interactive_session`**: Same pattern — accept `jsonl_path`

**Modified `RunResult` references**: Store `data_path` alongside `mbox_path`, or add `jsonl_path` field.

### 4.3 `src/gaia/agents/email/bench/cli.py` — ADD CLI flag

**New argument**: `--jsonl-path` (mutually exclusive with `--mbox-path`)
- Add to the main `bench` subparser
- Add to the `clawflow` subparser if needed

**Modified argument parsing**: Validate that exactly one of `--mbox-path` or `--jsonl-path` is provided

### 4.4 `src/gaia/agents/email/bench/bench_runner.py` — ADD JSONL path

**Modified**: Accept `--jsonl-path` alongside `--mbox-path`
- Pass through to `_run_full_agent()`

### 4.5 `src/gaia/agents/email/bench/clawflow_runner.py` — ADD JSONL path

**Modified**: Accept `--jsonl-path` CLI arg
- Pass to adapter

### 4.6 `src/gaia/agents/email/bench/data_shapes.py` — ADD data_source field

**Modified `RunResult`**: Add `data_source: str = "mbox"` field (values: `"mbox" | "jsonl"`)
- Keep `mbox_path` for backward compat; deprecate or make optional
- Add `jsonl_path: str = ""` field

### 4.7 `src/gaia/agents/email/bench/trace_extractor.py` — ADD jsonl_path

**Modified**: Functions that accept `mbox_path` should also accept `jsonl_path`
- `extract_from_agent_result()` — pass through data source info

### 4.8 `src/gaia/agents/email/bench/output.py` — ADD jsonl_path to reports

**Modified**: Report generation to include `jsonl_path` alongside `mbox_path`

### 4.9 `src/gaia/agents/email/bench/compare.py` — ADD jsonl_path

**Modified**: `ComparisonReport` dataclass — add `jsonl_path` field

### 4.10 `src/gaia/agents/email/bench/clawflow_adapter.py` — ADD jsonl_path

**Modified**: `clawflow_result_to_gaia_run()` — handle `jsonl_path` parameter

### 4.11 `src/gaia/agents/email/bench/README.md` — UPDATE documentation

**Modified**: Add `--jsonl-path` to all CLI examples and flag tables
- Add section explaining JSONL vs MBOX modes
- Document the category mapping

---

## 5. Proposed Implementation

### 5.1 New function in `fake_gmail.py`

```python
# Category -> Gmail label ID mapping
_JSONL_CATEGORY_TO_LABELS = {
    "URGENT": ["INBOX", "UNREAD", "IMPORTANT"],
    "NEEDS_RESPONSE": ["INBOX", "UNREAD", "STARRED"],
    "FYI": ["INBOX", "UNREAD"],
    "PROMOTIONAL": ["INBOX", "UNREAD", "CATEGORY_PROMOTIONS"],
    "PERSONAL": ["INBOX", "UNREAD", "CATEGORY_PERSONAL"],
}


def jsonl_record_to_gmail_payload(record: dict) -> Dict[str, Any]:
    """Convert a JSONL email record to Gmail API v1 message shape."""
    msg_id = record["id"][:16] if len(record["id"]) > 16 else record["id"]

    # Thread ID: derive from thread reference or use msg_id
    thread_ref = record.get("variation_thread_reference", "")
    if thread_ref:
        thread_id = hashlib.sha256(thread_ref.encode()).hexdigest()[:16]
    else:
        thread_id = msg_id

    # Labels from category
    category = record.get("category", "FYI")
    label_ids = list(_JSONL_CATEGORY_TO_LABELS.get(category, ["INBOX", "UNREAD"]))

    # Parse ISO 8601 date -> internalDate (millis)
    date_str = record.get("date", "")
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        internal_date = str(int(dt.timestamp() * 1000))
    except (ValueError, AttributeError):
        internal_date = str(int(datetime.now(timezone.utc).timestamp() * 1000))

    # Build headers
    headers = [
        {"name": "From", "value": record.get("sender", "")},
        {"name": "Subject", "value": record.get("subject", "")},
        {"name": "Date", "value": date_str},
    ]

    # Build body
    body_preview = record.get("body_preview", "")
    body_data = _b64url(body_preview.encode("utf-8"))

    payload = {
        "mimeType": "text/plain",
        "filename": "",
        "headers": headers,
        "body": {"size": len(body_preview.encode("utf-8")), "data": body_data},
    }

    return {
        "id": msg_id,
        "threadId": thread_id,
        "labelIds": label_ids,
        "snippet": body_preview[:200],
        "internalDate": internal_date,
        "payload": payload,
        "sizeEstimate": len(body_preview),
    }
```

### 5.2 New method on `FakeGmailBackend`

```python
def __init__(
    self,
    mbox_path: Optional[Path] = None,
    jsonl_path: Optional[Path] = None,
    *,
    user_email: str = "user@example.com",
    transport: Optional[FakeGmailTransport] = None,
):
    if mbox_path and jsonl_path:
        raise ValueError("Specify either mbox_path or jsonl_path, not both")
    self._user_email = user_email
    self._transport = transport or FakeGmailTransport()
    self._messages: Dict[str, Dict[str, Any]] = {}
    self._labels: List[Dict[str, Any]] = _DEFAULT_SYSTEM_LABELS[:]
    self._drafts: Dict[str, Dict[str, Any]] = {}
    self._next_draft_seq = 1
    self._data_source: str = "none"
    if mbox_path is not None:
        self.load_mbox(mbox_path)
        self._data_source = "mbox"
    elif jsonl_path is not None:
        self.load_jsonl(jsonl_path)
        self._data_source = "jsonl"

def load_jsonl(self, path: Path) -> None:
    with open(path, encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            payload = jsonl_record_to_gmail_payload(record)
            self._messages[payload["id"]] = payload
```

### 5.3 New function in `runner.py`

```python
def load_emails_from_jsonl(
    jsonl_path: str,
    *,
    limit: int = 100,
) -> list[dict]:
    """Load emails from a JSONL file via FakeGmailBackend.

    Returns a list of dicts with: id, subject, from, label_ids, payload.
    """
    from gaia.agents.email.fake_gmail import FakeGmailBackend
    from gaia.agents.email.tools.triage_heuristics import LABEL_INBOX

    backend = FakeGmailBackend(jsonl_path=Path(jsonl_path))
    listing = backend.list_messages(label_ids=[LABEL_INBOX], max_results=limit)

    emails = []
    for stub in listing.get("messages", [])[:limit]:
        msg = backend.get_message(stub["id"])
        headers = _extract_headers(msg.get("payload", {}))
        emails.append({
            "id": msg["id"],
            "thread_id": msg.get("threadId", msg["id"]),
            "subject": headers.get("subject", ""),
            "sender": headers.get("from", ""),
            "date": headers.get("date", ""),
            "label_ids": list(msg.get("labelIds", [])),
            "snippet": msg.get("snippet", ""),
            "payload": msg.get("payload", {}),
        })
    return emails
```

---

## 6. Risks and Edge Cases

### 6.1 ID Format Mismatch
**Risk**: JSONL uses full UUIDs (`e654b348-2465-428e-ba89-ec2890e687d4`), MBOX-derived IDs are 16-char hex (`a1b2c3d4e5f67890`). The agent and tools use these IDs as opaque strings — no code assumes a specific format.
**Mitigation**: Use the full UUID as the message ID. No truncation needed. Verify that `_extract_emails_affected()` regex patterns in runner.py still match UUID-format IDs (they use `json.loads` so should be fine).

### 6.2 Thread Cohesion
**Risk**: MBOX threads are derived from `References`/`In-Reply-To` headers. JSONL has `variation_thread_reference` (e.g., `"thread-6"`) but no explicit parent/child message structure.
**Mitigation**: SHA256-hash the thread reference to produce a deterministic `threadId`. Emails with the same `variation_thread_reference` will share a thread. This is sufficient for `get_thread()` lookups.

### 6.3 Missing MIME Structure
**Risk**: JSONL emails have only `body_preview` (plain text). MBOX emails can be multipart (HTML + plain text + attachments). The `decode_message_body()` function in `gmail_backend.py` expects Gmail payload shape with `parts[]`.
**Mitigation**: The `jsonl_record_to_gmail_payload()` function produces a single-part `text/plain` payload. `decode_message_body()` handles single-part messages correctly — it checks `body.data` on the payload node directly when there are no `parts[]`.

### 6.4 No `To` Header
**Risk**: JSONL has no `To` field. `_format_message_for_llm()` extracts `to` from headers and returns empty string if missing.
**Mitigation**: Set `"To": "user@example.com"` (the configured user email) in the headers list. This is consistent with the synthetic dataset being "emails sent to the user".

### 6.5 Search Functionality
**Risk**: `_query_matches()` does free-text search against `snippet`. JSONL `body_preview` is only a preview, not the full body.
**Mitigation**: Accept this limitation for benchmark purposes. The `body_preview` field is sufficiently long (~150-400 chars) for the subset of Gmail search queries used in eval scenarios (`is:unread`, `from:`, `subject:`, free-text).

### 6.6 Heuristic Behavior Change
**Risk**: The JSONL categories map to Gmail labels, which then flow through the heuristic classifier. The heuristic may produce different results than the JSONL's pre-labeled `category`.
**Mitigation**: This is **by design** — the benchmark measures how well the agent classifies emails, not whether it matches the pre-labels. The JSONL `category` is ground truth for eval scoring, not something injected into the agent. The heuristic + LLM pipeline should independently arrive at compatible classifications.

### 6.7 Body Content Truncation
**Risk**: `body_preview` is a truncated preview, not the full email body. The LLM may need more context for accurate classification.
**Mitigation**: For benchmark fidelity, this is a limitation to document. If full bodies are needed, the JSONL generation pipeline would need to be updated. Current `body_preview` lengths appear sufficient for triage classification.

### 6.8 Duplicate IDs
**Risk**: If the JSONL file contains duplicate UUIDs, later records will overwrite earlier ones in `_messages` dict.
**Mitigation**: Add a deduplication check in `load_jsonl()` with a warning log. Given the UUID format, this is extremely unlikely.

---

## 7. Backward Compatibility Strategy

- **Default unchanged**: `--mbox-path` remains the primary flag. `--jsonl-path` is additive.
- **Mutual exclusion**: Exactly one of `--mbox-path` or `--jsonl-path` must be specified.
- **FakeGmailBackend**: Constructor accepts both, validates mutual exclusivity.
- **RunResult dataclass**: Add `data_source` and `jsonl_path` fields with defaults preserving existing behavior.
- **Existing tests**: No changes needed — all tests use `add_message()` to inject pre-built Gmail payloads directly, bypassing the file loader.
- **Shape contract tests**: `tests/unit/email/test_fake_gmail_shape_contract.py` should continue to pass — the JSONL path produces the same Gmail API v1 shape.

---

## 8. Implementation Order

1. **`fake_gmail.py`** — Add `jsonl_record_to_gmail_payload()`, `load_jsonl()`, modify `__init__`
2. **`data_shapes.py`** — Add `data_source` and `jsonl_path` fields to `RunResult`
3. **`runner.py`** — Add `load_emails_from_jsonl()`, modify `_run_full_agent()`, `run_interactive_benchmark()`, `run_interactive_session()`
4. **`cli.py`** — Add `--jsonl-path` argument
5. **`bench_runner.py`** — Add `--jsonl-path` passthrough
6. **`clawflow_runner.py`** — Add `--jsonl-path` support
7. **`trace_extractor.py`** — Handle `jsonl_path` in extraction functions
8. **`output.py`** — Include `jsonl_path` in reports
9. **`compare.py`** — Add `jsonl_path` to comparison report
10. **`clawflow_adapter.py`** — Handle `jsonl_path` parameter
11. **`README.md`** — Update documentation

---

## 9. Testing Plan

### 9.1 Unit Tests
- Test `jsonl_record_to_gmail_payload()` for each of the 5 categories
- Verify output matches Gmail API v1 shape contract (use existing shape tests)
- Test date parsing for various ISO 8601 formats
- Test thread ID derivation (same reference -> same threadId)
- Test label mapping correctness for each category

### 9.2 Integration Tests
- Run `FakeGmailBackend(jsonl_path=...)` and verify `list_messages()` returns correct count
- Verify `get_message()` returns properly shaped payload
- Verify `get_thread()` groups emails by thread reference
- Verify `_query_matches()` works with JSONL-loaded messages

### 9.3 Benchmark Tests
- Run `gaia email bench --jsonl-path <path> --limit 10` and verify output
- Compare results with MBOX mode to validate pipeline parity
- Run with `--force-llm` to exercise full LLM classification path

---

## 10. Summary

This migration introduces a clean, additive JSONL loading path that produces **identical Gmail API v1 shapes** to the existing MBOX path. The agent and its tools are completely unaware of the data source — they interact with the `FakeGmailBackend` Protocol surface exactly as before. The key insight is that the JSONL format is **simpler** than MBOX (no MIME parsing, no RFC 2047 header decoding) and requires **less code** to implement.

The main risk is body content truncation (`body_preview` vs full body), which is a data-generation concern rather than a pipeline concern. All other risks have straightforward mitigations.
