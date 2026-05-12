# Sharecon: Shared Consciousness Knowledge System

## Overview

Sharecon is a Claude Code plugin that gives anyone in the organization instant access to the Consumer Industries team's collective knowledge. Contributors drop files into a structured Google Drive folder. A standalone Python script (`sync_toc.py`) generates a lightweight table of contents (`_TOC.json`) with AI-generated summaries. Claude Code skills read the TOC and fetch relevant documents on demand to answer questions, surface experts, and browse the knowledge base.

## Problem

The CI team's effectiveness comes from deep tribal knowledge: account strategies, talk tracks, outcome maps, playbooks, and best practices. This knowledge lives in people's heads, scattered docs, and a 7-year-old Signal chat. AI tools boost individual task productivity, but the organizational knowledge doesn't compound because it isn't captured or accessible at scale.

## Design Principles

- **Zero friction for contributors** - drop files in Drive, that's it
- **Zero infrastructure for consumers** - Claude Code plugin, read-only skills
- **TOC as the abstraction layer** - skills don't care where files live, only where `_TOC.json` is
- **Delta-only sync** - only process new or modified files
- **Expert attribution from authorship** - Drive file ownership is the signal

## Architecture

### Components

| Component | Runs Where | Purpose |
|---|---|---|
| `sync_toc.py` | Standalone (cron, Databricks Jobs, manual) | Scans source, delta-syncs `_TOC.json` with AI-generated summaries |
| `/ci-ask` | Claude Code | Query knowledge base, get answers with citations + expert attribution |
| `/ci-browse` | Claude Code | Browse knowledge base by folder, topic, or contributor |
| `/ci-expert` | Claude Code | "Who knows the most about X?" ranked by doc authorship |

### Data Flow

```
Contributors                    System                         Consumers
───────────                    ──────                         ─────────
Drop files in        →    sync_toc.py reads source      →    /ci-ask reads _TOC.json
Google Drive              diffs against _TOC.json            identifies relevant docs
(or local folder)         OpenAI client → Databricks         fetches from source
                          for new summaries                  synthesizes answer
                          writes _TOC.json                   cites sources + experts
```

### Dependencies

- Google Drive auth (existing `fe-google-tools` plugin)
- `openai` Python package (pointed at Databricks Foundation Model serving endpoint)
- Databricks API token (for `sync_toc.py` only)
- `uv` for running the Python script

## TOC Structure

`_TOC.json` lives alongside the knowledge files (in Drive root or local folder root):

```json
{
  "last_synced": "2026-05-11T18:30:00Z",
  "synced_by": "sathish.gangichetty@databricks.com",
  "source": {
    "type": "google_drive",
    "folder_id": "GOOGLE_DRIVE_FOLDER_ID"
  },
  "files": [
    {
      "id": "drive_file_id_123",
      "name": "Retail Lakehouse Pitch Strategy.docx",
      "path": "Talk Tracks/Retail Lakehouse Pitch Strategy.docx",
      "folder": "Talk Tracks",
      "author": "lorraine.bacon@databricks.com",
      "last_modified": "2026-05-10T14:22:00Z",
      "mime_type": "application/vnd.google-apps.document",
      "summary": "Framework for positioning lakehouse architecture to retail CIOs. Covers data mesh concerns, real-time inventory use case, and cost comparison vs. legacy warehouse.",
      "tags": ["retail", "lakehouse", "CIO", "inventory", "data mesh"],
      "summary_generated": "2026-05-11T18:30:00Z"
    }
  ]
}
```

## sync_toc.py

Standalone Python script. Can be scheduled externally (cron, Databricks Jobs) or run manually. Does not need to run inside Claude Code.

### Sync Logic

1. List all files recursively in the configured source (metadata only - fast)
2. Read existing `_TOC.json` from source
3. Compare each file's `last_modified` against TOC entries
4. Three buckets:
   - **Unchanged** - skip entirely
   - **New/Modified** - read content, call Databricks Foundation Model via OpenAI client for summary + tags
   - **Deleted** (in TOC but not in source) - remove from TOC
5. Write updated `_TOC.json` back to source
6. Report: "Synced 3 new files, updated 1, removed 0, 47 total in knowledge base."

### Mass Deletion Protection

If a single sync would remove more than 50% of TOC entries, the script pauses and warns:

```
Warning: 24 of 47 files appear to have been removed since last sync.
This may indicate a folder permission change or accidental deletion.
Proceed? (yes/no)
```

### Summary Generation

Uses the OpenAI-compatible Databricks Foundation Model endpoint:

```python
from openai import OpenAI

client = OpenAI(
    api_key="DATABRICKS_TOKEN",
    base_url="https://<workspace>.cloud.databricks.com/serving-endpoints"
)

response = client.chat.completions.create(
    model="databricks-claude-sonnet-4",
    messages=[{
        "role": "user",
        "content": f"Summarize this document in 2-3 lines and extract 3-7 key tags.\n\nDocument:\n{doc_content}"
    }]
)
```

### Supported File Types

- Google Docs
- PDFs
- DOCX
- Plain text
- Markdown (.md)
- HTML (.html)
- Google Sheets (first sheet as text)
- Binary files (images, videos) - listed in TOC with filename only, no summary generated

## Claude Code Skills

All skills are read-only. They read `_TOC.json` and fetch documents from the source on demand.

### /ci-ask

Query the knowledge base with natural language.

**Flow:**
1. Read `_TOC.json` from source (cached locally per session)
2. Claude matches the user's question against TOC summaries + tags
3. Identifies the top 3-5 most relevant documents
4. Fetches those documents from source
5. Synthesizes an answer citing specific documents
6. Surfaces the top contributor(s) on the topic

**Example:**
```
> /ci-ask "how do we talk to retailers about lakehouse?"

Based on the CI knowledge base:

[Synthesized answer drawing from multiple docs...]

Sources:
- Talk Tracks/Retail Lakehouse Pitch Strategy.docx (Lorraine Bacon)
- Playbooks/Retail Data Platform Playbook.docx (Rob Saker)
- Outcome Maps/Retail Inventory Real-Time.docx (Justin Fenton)

People closest to this topic:
- Lorraine Bacon (3 docs) - may have additional context
- Rob Saker (1 doc)
```

### /ci-browse

Browse the knowledge base contents.

**Modes:**
- No arguments: list all folders with file counts
- By folder: `/ci-browse "Talk Tracks"` - list files in that folder
- By contributor: `/ci-browse --author "lorraine.bacon"` - list all docs by that person
- By tag: `/ci-browse --tag "retail"` - list all docs with that tag

### /ci-expert

Find who knows the most about a topic.

**Flow:**
1. Read `_TOC.json`
2. Match query against summaries + tags
3. Group relevant docs by author
4. Rank by count of relevant docs

**Example:**
```
> /ci-expert "real-time inventory analytics"

Based on the knowledge base, the people closest to this topic are:

1. Lorraine Bacon (3 docs) — Retail Lakehouse Pitch Strategy,
   CPG Data Mesh Playbook, Retail Inventory Outcome Map
2. Rob Saker (2 docs) — Consumer Industries AI Strategy,
   Retail CIO Messaging Framework
3. Justin Fenton (1 doc) — Quick-Service Restaurant Analytics Playbook
```

## Google Drive Folder Structure

Seeded with a recommended hierarchy, but contributors can add new folders at any time. The sync script discovers new folders automatically.

```
CI Knowledge Base/
├── _TOC.json
├── Account Strategies/
├── Playbooks/
├── Outcome Maps/
├── Talk Tracks/
├── Meeting Notes/
└── Best Practices/
```

## Plugin Configuration

The plugin needs one piece of information: where is `_TOC.json`?

For Google Drive, this is the root folder ID. For a local folder, this is a file path. Configured in the plugin's settings and can be changed at any time.

The `source` field in `_TOC.json` itself tells the skills how to fetch documents:
- `"type": "google_drive"` - use Google Drive API with existing `fe-google-tools` auth
- `"type": "local"` - read from local filesystem

## Source Flexibility

The TOC is the abstraction layer. Skills only read `_TOC.json` and fetch content based on `source.type`. To switch from Google Drive to a local folder (or S3, or anything else):

1. Update `source` in `_TOC.json`
2. Update `sync_toc.py` to read from the new source
3. Skills require zero changes

## Edge Cases

- **File without Drive owner metadata**: use "unknown" as author, skip from expert attribution
- **File too large to summarize**: truncate to first 10,000 characters for summary generation, note truncation in TOC entry
- **Binary files**: listed in TOC with filename/path/author but no summary or tags
- **Permission errors**: skip file, log warning, continue sync
- **Empty folders**: included in browse results but with zero file count
- **Duplicate filenames across folders**: distinguished by full path in TOC
