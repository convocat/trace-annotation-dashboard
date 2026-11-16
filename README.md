# trace-annotation-dashboard

A lightweight Flask dashboard for annotating LLM traces — pulls live content from Langfuse, applies Dutch PII scrubbing, and stores only your annotations locally.

Built for people who evaluate chatbot answers in projects where messages may contain sensitive data: traces are **fetched live from Langfuse** at render time and are **never written to disk**. The only thing stored locally is your own annotations (scores, notes) keyed by trace-ID.

## What it does

- **Pulls traces** from a configurable source (Langfuse by default).
- **Scrubs PII** on render: BSN, IBAN, email, Dutch phone numbers, postcodes, dates of birth (regex only — no LLM in the loop).
- **In-memory session cache**: fetched traces live in RAM for the dashboard session, never touch disk.
- **Annotations stored locally** as an Excel file keyed by trace-ID.
- **Zero CLI** if you want: drop a `.trace-dashboard.yml` in any project and launch via a one-line config or via the Claude Code skill.

## Install

```bash
pip install git+https://github.com/convocat/trace-annotation-dashboard.git
```

Or in a repo-local venv:

```bash
pipx install git+https://github.com/convocat/trace-annotation-dashboard.git
```

## Use

From inside any project repo, create a `.trace-dashboard.yml` at the root:

```yaml
source: langfuse
langfuse:
  host: https://langfuse.montferland.info
  project_id: cmipx4n58000bwb083x7khfqo
  dataset: gemeente-testset
  # Credentials from env: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

pii_filter:
  mode: strict           # strict | lenient | off
  patterns: [bsn, iban, email, phone, postcode, dob]
  replacement: "[{type}]"

annotations:
  path: testannotaties/annotations.xlsx

port: 5000
```

Credentials live next to the config in a `.env` file at your project root:

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

The dashboard picks these up automatically — no shell export needed. Shell-exported variables still win over `.env` entries, so you can override per-session.

Then either:

- **Via Claude Code**: ask the agent to "start the trace dashboard" (requires the `/trace-dashboard` skill).
- **Via shell**: `trace-dashboard` (reads `.trace-dashboard.yml` + `.env` from current dir).

Open `http://127.0.0.1:5000` in your browser.

## Design decisions

### Why live-fetch instead of local storage?

PII safety by default: trace content never lands on your disk. If Langfuse is unreachable, the dashboard shows "cannot load trace" rather than exposing something that shouldn't be there.

### Why store annotations locally?

Annotations are *your* work product — scores, qualitative notes — and belong next to the project they describe. They're also small, PII-free by nature, and benefit from being under your own version control.

### Why Dutch PII patterns specifically?

Primary users are Dutch municipal chatbot projects. Patterns follow Dutch formats: BSN with 11-proof validation, Dutch phone number prefixes, postcode-format `1234 AB`. Easy to extend with other locales via regex rules in `src/trace_annotator/pii/filter.py`.

### Why not an LLM-based PII filter?

Deterministic, auditable, no external API dependency, no cost per trace. Known trade-off: names and context-dependent identifiers may slip through. If that's a concern, rely on Langfuse's own ingest-time filter as the first layer and use this as defence-in-depth.

## Project structure

```
src/trace_annotator/
├── app.py              Flask app + routes
├── config.py           YAML config + defaults
├── loaders/            Pluggable trace sources
│   ├── base.py         Trace dataclass + Loader protocol
│   ├── langfuse.py     Fetch from Langfuse API
│   └── excel.py        Import annotation overlay (trace-ID → notes)
├── pii/
│   └── filter.py       Dutch regex patterns
├── storage/
│   └── annotations.py  Local annotation xlsx r/w
├── cache.py            In-memory session cache
├── templates/          Jinja HTML
└── static/             JS + CSS
```

## Status

Early scaffold. Core loaders and PII filter exist; the Flask UI is being ported from an earlier single-file prototype.

## License

MIT — see [LICENSE](LICENSE).
