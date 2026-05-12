---
name: ci-browse
description: Browse the Consumer Industries shared knowledge base. List documents by folder, contributor, or tag.
---

# CI Knowledge Base Browser

Browse the Consumer Industries shared knowledge base stored in Google Drive. List documents by folder, contributor, or tag.

## Prerequisites

### Auth Check
Before running any commands, verify Google Drive authentication is available. The `resources/drive_helpers.py` script depends on the shared `google_api_utils` auth module. If auth fails, instruct the user to run `/google-auth` first.

### Configuration
The Drive folder ID is read from `config.json` in the plugin root directory.

```bash
FOLDER_ID=$(python3 -c "import json; print(json.load(open('config.json'))['drive_folder_id'])")
```

## Execution Steps

### Step 1: Read the Table of Contents

Run the following command to fetch the current TOC from the shared Drive folder:

```bash
python3 resources/drive_helpers.py read-toc "$FOLDER_ID"
```

Parse the returned JSON into a structured list of documents with their metadata (title, folder, author, tags, modified date, summary).

### Step 2: Check Staleness

Inspect the `last_synced` timestamp in the TOC response.

- If `last_synced` is more than 24 hours ago, display a warning to the user:
  ```
  Note: Knowledge base was last synced {time_ago}. Data may be stale. Run /ci-refresh to update.
  ```
- Continue with the browse operation regardless of staleness.

### Step 3: Parse Arguments and Display Results

The user may invoke this skill with different arguments. Handle each case as follows:

---

#### No Arguments — Folder Overview

When the user runs `/ci-browse` with no arguments, display a high-level overview of the knowledge base:

```
CI Knowledge Base ({total} documents, last synced {time})

  Account Strategies/    — {n} docs
  Playbooks/             — {n} docs
  Outcome Maps/          — {n} docs
  Talk Tracks/           — {n} docs
  Meeting Notes/         — {n} docs
  Best Practices/        — {n} docs

Top contributors:
  1. {author1} — {n} docs
  2. {author2} — {n} docs
  3. {author3} — {n} docs
```

- Group documents by their folder field.
- Count documents per folder.
- Rank contributors by document count (top 3).

---

#### Folder Name — List Files in Folder

When the user provides a folder name (e.g., `/ci-browse "Talk Tracks"`), list all documents in that folder:

```
Talk Tracks/ ({n} documents)

  1. Retail Lakehouse Pitch Strategy.docx (Lorraine Bacon, May 10)
     → Framework for positioning lakehouse architecture to retail CIOs...
  2. CPG Data Mesh Messaging.docx (Rob Saker, May 8)
     → Key talking points for data mesh conversations with CPG customers...
```

- Filter documents where the folder matches the provided name (case-insensitive).
- Sort by modified date, most recent first.
- Show each document's title, author, date, and a one-line summary (truncated from the document summary field).
- If the folder name does not match any known folder, suggest the closest match.

---

#### `--author` Flag — List Documents by Author

When the user provides the `--author` flag (e.g., `/ci-browse --author "lorraine.bacon"`), list all documents by that author grouped by folder:

```
Documents by Lorraine Bacon ({n} total)

  Account Strategies/
    - Retail Q2 Strategy.docx (May 10)
  Talk Tracks/
    - Retail Lakehouse Pitch Strategy.docx (May 8)
```

- Match on email prefix (partial match is acceptable). For example, `lorraine` should match `lorraine.bacon@databricks.com`.
- Group results by folder.
- Sort documents within each folder by modified date, most recent first.
- Display the author's full name in the header.

---

#### `--tag` Flag — List Documents by Tag

When the user provides the `--tag` flag (e.g., `/ci-browse --tag "retail"`), list all documents matching that tag:

```
Documents tagged "retail" ({n} total)

  1. Retail Lakehouse Pitch Strategy.docx (Lorraine Bacon)
     Talk Tracks/ — Tags: retail, lakehouse, CIO
  2. Retail Inventory Outcome Map.docx (Justin Fenton)
     Outcome Maps/ — Tags: retail, inventory, real-time
```

- Match tags case-insensitively.
- Show each document's title, author, folder, and full tag list.
- Sort by relevance (documents with the tag appearing first in their tag list rank higher), then by modified date.

## Error Handling

- If the TOC file is empty or missing, instruct the user to run `/ci-refresh` to populate the knowledge base.
- If `config.json` still has `REPLACE_WITH_YOUR_GOOGLE_DRIVE_FOLDER_ID`, inform the user to edit `config.json` and set their actual folder ID.
- If authentication fails, direct the user to run `/google-auth`.
