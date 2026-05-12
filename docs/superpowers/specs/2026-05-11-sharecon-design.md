# Sharecon: Shared Consciousness Knowledge System

## Overview

Sharecon is a Claude Code plugin that gives anyone in the organization instant access to the Consumer Industries team's collective knowledge. Contributors drop files into a structured Google Drive folder. Claude Code skills read a lightweight table of contents (`_TOC.json`) to find relevant documents, fetch them on demand, and answer questions with citations and expert attribution.

## Problem

The CI team's effectiveness comes from deep tribal knowledge: account strategies, talk tracks, outcome maps, playbooks, and best practices. This knowledge lives in people's heads, scattered docs, and a 7-year-old Signal chat. AI tools boost individual task productivity, but the organizational knowledge doesn't compound because it isn't captured or accessible at scale.

## Design Principles

- **Zero friction for contributors** - drop files in Drive, that's it
- **Zero infrastructure** - no external scripts, databases, or pipelines. Just Claude Code + Google Drive auth
- **TOC as the abstraction layer** - skills don't care where files live, only where `_TOC.json` is
- **Delta-only sync** - only process new or modified files
- **Claude is the summarizer** - no external AI services needed; Claude generates summaries during refresh
- **Expert attribution from authorship** - Drive file ownership is the signal

## Architecture

### Components

| Component | Purpose |
|---|---|
| `/ci-refresh` | Scan Drive, delta-sync `_TOC.json` - Claude reads new/changed docs and generates summaries |
| `/ci-ask` | Query knowledge base, get answers with citations + expert attribution |
| `/ci-browse` | Browse knowledge base by folder, topic, or contributor |
| `/ci-expert` | "Who knows the most about X?" ranked by doc authorship |

### Data Flow

```
Contributors                    System                         Consumers
───────────                    ──────                         ─────────
Drop files in        →    /ci-refresh scans Drive        →    /ci-ask reads _TOC.json
Google Drive              diffs against _TOC.json             identifies relevant docs
                          Claude reads new docs               fetches from Drive
                          (first 10K chars)                   synthesizes answer
                          generates summaries + tags          cites sources + experts
                          writes _TOC.json to Drive
```

### Dependencies

- Google Drive auth (existing `fe-google-tools` plugin)
- That's it.

## TOC Structure

`_TOC.json` lives in the root of the Google Drive knowledge base folder:

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

## Staleness Check

Every skill (`/ci-ask`, `/ci-browse`, `/ci-expert`) reads `_TOC.json` before executing. If `last_synced` is older than 24 hours, the skill informs the user before proceeding:

```
Knowledge base was last synced 2 days ago.
Run /ci-refresh to pick up any new or changed documents.
```

The skill still answers the query using the existing TOC - it doesn't block. The nudge ensures someone refreshes periodically without forcing it.

## /ci-refresh

Syncs the TOC with the current state of the Google Drive folder. Claude does all the work - no external scripts or services.

### Sync Logic

1. Read existing `_TOC.json` from Drive
2. List **all** files recursively in the Drive folder (metadata only - fast). This is the source of truth.
3. Build a full file manifest from Drive: every file ID, name, path, author, last_modified
4. Cross-reference the Drive manifest against the TOC to produce four buckets:
   - **Unchanged** - file exists in both, `last_modified` matches → skip entirely
   - **New** - file exists in Drive but not in TOC → read first 10,000 characters, Claude generates a 2-3 line summary and 3-7 tags
   - **Modified** - file exists in both but Drive's `last_modified` is newer → re-read and regenerate summary
   - **Deleted** - file exists in TOC but **not** in the Drive manifest → remove from TOC
5. For deletions: verify each TOC entry's file ID against the Drive manifest. Any TOC entry whose `id` is absent from Drive gets removed. This catches renamed files, moved files, and entire folder deletions.
6. Write updated `_TOC.json` back to Drive
6. Report to user:

```
Knowledge base synced:
  3 new files indexed
  1 file updated
  0 files removed
  47 total documents

New additions:
  - Talk Tracks/Retail Lakehouse Pitch Strategy.docx (Lorraine Bacon)
  - Playbooks/CPG Data Mesh Playbook.docx (Rob Saker)
  - Meeting Notes/QBR May 2026.docx (Justin Fenton)
```

### Mass Deletion Protection

If a single refresh would remove more than 50% of TOC entries, the skill warns before proceeding:

```
Warning: 24 of 47 files appear to have been removed from Drive
since last sync. This may indicate a folder permission change
or accidental deletion.

Proceed with sync? (yes/no)
```

### Supported File Types

| Type | How It's Read |
|---|---|
| Google Docs | Exported as plain text via Drive API |
| PDFs | Exported as text via Drive API |
| DOCX | Exported as text via Drive API |
| Plain text | Read directly |
| Markdown (.md) | Read directly |
| HTML (.html) | Read directly |
| Google Sheets | Exported as text (first sheet) via Drive API |
| Binary (images, videos) | Listed in TOC with filename only, no summary |

## Claude Code Skills

All skills read `_TOC.json` from Drive and fetch documents on demand. Each skill checks TOC staleness and nudges the user if needed.

### /ci-ask

Query the knowledge base with natural language.

**Flow:**
1. Read `_TOC.json` from Drive (check staleness, nudge if >24h)
2. Claude matches the user's question against TOC summaries + tags
3. Identifies the top 3-5 most relevant documents
4. Fetches those documents from Drive (first 10K characters each)
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
1. Read `_TOC.json` (check staleness)
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

Seeded with a recommended hierarchy, but contributors can add new folders at any time. `/ci-refresh` discovers new folders automatically.

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

The plugin needs one piece of information: the Google Drive root folder ID. Configured in the plugin's settings.

The `source` field in `_TOC.json` tells the skills how to fetch documents:
- `"type": "google_drive"` - use Google Drive API with existing `fe-google-tools` auth
- `"type": "local"` - read from local filesystem (future option)

## Edge Cases

- **File without Drive owner metadata**: use "unknown" as author, skip from expert attribution
- **File too large to read**: truncate to first 10,000 characters for summary generation, note truncation in TOC entry
- **Binary files**: listed in TOC with filename/path/author but no summary or tags
- **Permission errors**: skip file, log warning, continue sync
- **Empty folders**: included in browse results but with zero file count
- **Duplicate filenames across folders**: distinguished by full path in TOC
- **TOC doesn't exist yet**: `/ci-refresh` creates it from scratch on first run
