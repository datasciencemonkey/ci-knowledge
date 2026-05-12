# Sharecon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin with four skills (`/ci-refresh`, `/ci-ask`, `/ci-browse`, `/ci-expert`) that surfaces a team's collective knowledge from Google Drive via a TOC-based architecture.

**Architecture:** Skills are markdown files that instruct Claude. A shared Python helper (`drive_helpers.py`) handles all Google Drive API interactions (list files, read files, read/write TOC). Skills invoke the helper via bash and use Claude's reasoning for summarization and query matching.

**Tech Stack:** Python (Drive API helper), Google Drive API v3, existing `fe-google-tools` Google auth (`google_api_utils.py`)

---

## File Structure

```
sharecon/
├── skills/
│   ├── ci-refresh/
│   │   └── SKILL.md          — Sync skill: scan Drive, delta-update _TOC.json
│   ├── ci-ask/
│   │   └── SKILL.md          — Query skill: search TOC, fetch docs, answer with citations
│   ├── ci-browse/
│   │   └── SKILL.md          — Browse skill: list by folder/author/tag
│   └── ci-expert/
│       └── SKILL.md          — Expert skill: who knows about X?
├── resources/
│   └── drive_helpers.py      — Shared Drive API helper (list, read, TOC read/write)
└── docs/
    └── superpowers/
        ├── specs/
        │   ├── 2026-05-11-sharecon-design.md
        │   └── 2026-05-11-sharecon-design.html
        └── plans/
            └── 2026-05-11-sharecon-plan.md
```

**Key conventions (from `fe-google-tools` plugin):**
- Each skill has a `SKILL.md` with YAML frontmatter (`name`, `description`)
- Helper scripts live in `resources/` and use `google_api_utils.py` from the shared `google-auth` skill for auth
- All API calls include `x-goog-user-project` quota header

---

### Task 1: Create Drive API Helper Script

**Files:**
- Create: `resources/drive_helpers.py`

This is the foundation — every skill depends on it. It handles all Google Drive interactions.

- [ ] **Step 1: Create `resources/drive_helpers.py` with imports and constants**

```python
#!/usr/bin/env python3
"""
Drive Helpers - Google Drive API operations for Sharecon.

Provides:
- list_files() — recursively list all files in a Drive folder
- read_file() — read file content (exported as text for Google Docs/Sheets)
- read_toc() — read _TOC.json from Drive folder
- write_toc() — write _TOC.json back to Drive folder
- get_file_metadata() — get owner/author info for a file

Usage:
    python3 drive_helpers.py list-files --folder-id "FOLDER_ID"
    python3 drive_helpers.py read-file --file-id "FILE_ID"
    python3 drive_helpers.py read-toc --folder-id "FOLDER_ID"
    python3 drive_helpers.py write-toc --folder-id "FOLDER_ID" --toc-path "/tmp/toc.json"
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

# Import shared auth utilities from fe-google-tools
GOOGLE_AUTH_RESOURCES = os.path.expanduser(
    "~/.claude/plugins/cache/fe-vibe/fe-google-tools/1.4.0/skills/google-auth/resources"
)
sys.path.insert(0, GOOGLE_AUTH_RESOURCES)
from google_api_utils import api_call_with_retry, QUOTA_PROJECT

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"

# Maps Google Workspace MIME types to export MIME types for text extraction
EXPORT_MIME_MAP = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

# File extensions we can read as text directly
TEXT_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".csv", ".json", ".xml", ".yaml", ".yml"}
```

- [ ] **Step 2: Run to verify imports work**

Run: `python3 resources/drive_helpers.py --help 2>&1 || echo "imports check"`
Expected: No import errors. Script loads without crashing.

- [ ] **Step 3: Implement `list_files()` function**

```python
def list_files(folder_id: str, path_prefix: str = "") -> List[Dict]:
    """
    Recursively list all files in a Drive folder.
    Returns list of dicts with: id, name, path, folder, mime_type, modified_time, owner_email.
    """
    results = []
    page_token = None

    while True:
        url = (
            f"{DRIVE_API_BASE}/files"
            f"?q='{folder_id}'+in+parents+and+trashed=false"
            f"&fields=nextPageToken,files(id,name,mimeType,modifiedTime,owners)"
            f"&pageSize=100"
        )
        if page_token:
            url += f"&pageToken={page_token}"

        response = api_call_with_retry("GET", url)

        for f in response.get("files", []):
            file_path = f"{path_prefix}{f['name']}" if path_prefix else f["name"]
            owner_email = ""
            if f.get("owners"):
                owner_email = f["owners"][0].get("emailAddress", "unknown")

            if f["mimeType"] == "application/vnd.google-apps.folder":
                # Recurse into subfolders
                sub_files = list_files(f["id"], path_prefix=f"{file_path}/")
                results.extend(sub_files)
            else:
                folder_name = path_prefix.rstrip("/") if path_prefix else ""
                results.append({
                    "id": f["id"],
                    "name": f["name"],
                    "path": file_path,
                    "folder": folder_name,
                    "mime_type": f["mimeType"],
                    "last_modified": f["modifiedTime"],
                    "author": owner_email,
                })

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return results
```

- [ ] **Step 4: Implement `read_file()` function**

```python
def read_file(file_id: str, mime_type: str, max_chars: int = 10000) -> str:
    """
    Read file content from Drive. Exports Google Workspace files as text.
    Truncates to max_chars.
    """
    if mime_type in EXPORT_MIME_MAP:
        # Google Workspace file — export as text
        export_mime = EXPORT_MIME_MAP[mime_type]
        url = f"{DRIVE_API_BASE}/files/{file_id}/export?mimeType={export_mime}"
    else:
        # Binary or text file — download directly
        url = f"{DRIVE_API_BASE}/files/{file_id}?alt=media"

    try:
        content = api_call_with_retry("GET", url, raw_response=True)
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        elif isinstance(content, dict):
            # api_call_with_retry returned JSON — shouldn't happen for raw
            content = json.dumps(content)
        return content[:max_chars]
    except Exception as e:
        return f"[Error reading file: {e}]"
```

- [ ] **Step 5: Implement `read_toc()` and `write_toc()` functions**

```python
def find_toc_file(folder_id: str) -> Optional[str]:
    """Find _TOC.json in the given folder. Returns file ID or None."""
    url = (
        f"{DRIVE_API_BASE}/files"
        f"?q='{folder_id}'+in+parents+and+name='_TOC.json'+and+trashed=false"
        f"&fields=files(id)"
    )
    response = api_call_with_retry("GET", url)
    files = response.get("files", [])
    return files[0]["id"] if files else None


def read_toc(folder_id: str) -> Optional[Dict]:
    """Read _TOC.json from Drive. Returns parsed JSON or None if not found."""
    toc_id = find_toc_file(folder_id)
    if not toc_id:
        return None
    url = f"{DRIVE_API_BASE}/files/{toc_id}?alt=media"
    try:
        response = api_call_with_retry("GET", url, raw_response=True)
        if isinstance(response, bytes):
            return json.loads(response.decode("utf-8"))
        elif isinstance(response, str):
            return json.loads(response)
        return response
    except Exception:
        return None


def write_toc(folder_id: str, toc_data: Dict) -> bool:
    """Write _TOC.json to Drive. Creates if doesn't exist, updates if it does."""
    toc_id = find_toc_file(folder_id)
    toc_json = json.dumps(toc_data, indent=2)

    if toc_id:
        # Update existing file
        url = f"{DRIVE_UPLOAD_BASE}/files/{toc_id}?uploadType=media"
        try:
            api_call_with_retry("PATCH", url, data=toc_json, content_type="application/json")
            return True
        except Exception:
            return False
    else:
        # Create new file
        metadata = {
            "name": "_TOC.json",
            "parents": [folder_id],
            "mimeType": "application/json",
        }
        url = f"{DRIVE_UPLOAD_BASE}/files?uploadType=multipart"
        try:
            import email.mime.multipart
            import email.mime.base
            # Use simple upload with metadata
            boundary = "sharecon_boundary"
            body = (
                f"--{boundary}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{json.dumps(metadata)}\r\n"
                f"--{boundary}\r\n"
                f"Content-Type: application/json\r\n\r\n"
                f"{toc_json}\r\n"
                f"--{boundary}--"
            )
            api_call_with_retry(
                "POST", url, data=body,
                content_type=f"multipart/related; boundary={boundary}"
            )
            return True
        except Exception:
            return False
```

- [ ] **Step 6: Implement CLI interface**

```python
def cmd_list_files(args):
    files = list_files(args.folder_id)
    print(json.dumps(files, indent=2))


def cmd_read_file(args):
    content = read_file(args.file_id, args.mime_type, args.max_chars)
    print(content)


def cmd_read_toc(args):
    toc = read_toc(args.folder_id)
    if toc:
        print(json.dumps(toc, indent=2))
    else:
        print(json.dumps({"error": "No _TOC.json found"}))


def cmd_write_toc(args):
    with open(args.toc_path, "r") as f:
        toc_data = json.load(f)
    success = write_toc(args.folder_id, toc_data)
    print(json.dumps({"success": success}))


def main():
    parser = argparse.ArgumentParser(description="Sharecon Drive Helpers")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list-files")
    p_list.add_argument("--folder-id", required=True)
    p_list.set_defaults(func=cmd_list_files)

    p_read = sub.add_parser("read-file")
    p_read.add_argument("--file-id", required=True)
    p_read.add_argument("--mime-type", default="text/plain")
    p_read.add_argument("--max-chars", type=int, default=10000)
    p_read.set_defaults(func=cmd_read_file)

    p_toc_read = sub.add_parser("read-toc")
    p_toc_read.add_argument("--folder-id", required=True)
    p_toc_read.set_defaults(func=cmd_read_toc)

    p_toc_write = sub.add_parser("write-toc")
    p_toc_write.add_argument("--folder-id", required=True)
    p_toc_write.add_argument("--toc-path", required=True)
    p_toc_write.set_defaults(func=cmd_write_toc)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Test `list-files` against a real Drive folder**

Run: `python3 resources/drive_helpers.py list-files --folder-id "YOUR_TEST_FOLDER_ID"`
Expected: JSON array of file objects with id, name, path, folder, mime_type, last_modified, author

- [ ] **Step 8: Commit**

```bash
git add resources/drive_helpers.py
git commit -m "feat: add Drive API helper for Sharecon TOC operations"
```

---

### Task 2: Create `/ci-refresh` Skill

**Files:**
- Create: `skills/ci-refresh/SKILL.md`

The core sync skill. Scans Drive, diffs against TOC, generates summaries for new/changed docs, removes deleted entries.

- [ ] **Step 1: Create `skills/ci-refresh/SKILL.md`**

```markdown
---
name: ci-refresh
description: Sync the Sharecon knowledge base TOC with Google Drive. Scans for new, modified, and deleted files, generates summaries for changes, and writes updated _TOC.json back to Drive.
---

# CI Refresh — Knowledge Base Sync

Sync the shared knowledge base table of contents (`_TOC.json`) with the current state of the Google Drive folder.

## Configuration

The Drive folder ID is: `REPLACE_WITH_ACTUAL_FOLDER_ID`

Helper script path: `PLUGIN_DIR/resources/drive_helpers.py`
(where PLUGIN_DIR is the directory containing this skill)

## Authentication

Uses existing Google Drive auth from fe-google-tools:

\```bash
python3 GOOGLE_AUTH_DIR/google_auth.py status
\```

If not authenticated, tell the user to run `/google-auth`.

## Sync Procedure

Follow these steps exactly:

### Step 1: Read existing TOC

\```bash
python3 PLUGIN_DIR/resources/drive_helpers.py read-toc --folder-id "FOLDER_ID"
\```

If no TOC exists, start with an empty structure:
\```json
{
  "last_synced": null,
  "synced_by": null,
  "source": {"type": "google_drive", "folder_id": "FOLDER_ID"},
  "files": []
}
\```

### Step 2: List all files in Drive

\```bash
python3 PLUGIN_DIR/resources/drive_helpers.py list-files --folder-id "FOLDER_ID"
\```

This returns the complete Drive manifest — the source of truth.

### Step 3: Diff Drive manifest against TOC

Compare every file in the Drive manifest against the TOC by file `id`:

- **Unchanged**: file exists in both, `last_modified` matches → skip
- **New**: file in Drive but not in TOC → needs summary
- **Modified**: file in both but Drive's `last_modified` is newer → needs re-summary
- **Deleted**: file in TOC but its `id` is NOT in Drive manifest → remove from TOC

### Step 4: Mass deletion protection

If deleted files exceed 50% of the TOC, STOP and warn the user:

\```
Warning: {count} of {total} files appear to have been removed from Drive
since last sync. This may indicate a folder permission change or
accidental deletion.

Proceed with sync? (yes/no)
\```

Wait for user confirmation before continuing.

### Step 5: Generate summaries for new/modified files

For each new or modified file:

1. Read the file content (first 10,000 characters):
\```bash
python3 PLUGIN_DIR/resources/drive_helpers.py read-file --file-id "FILE_ID" --mime-type "MIME_TYPE" --max-chars 10000
\```

2. Generate a summary. Read the content and produce:
   - A 2-3 line summary of what the document covers
   - 3-7 topic tags (lowercase, specific to the domain)
   
3. Create the TOC entry:
\```json
{
  "id": "file_id",
  "name": "filename.docx",
  "path": "Folder/filename.docx",
  "folder": "Folder",
  "author": "email@databricks.com",
  "last_modified": "2026-05-11T14:22:00Z",
  "mime_type": "application/vnd.google-apps.document",
  "summary": "Your generated summary here.",
  "tags": ["tag1", "tag2", "tag3"],
  "summary_generated": "current ISO timestamp"
}
\```

Skip binary files (images, videos) — add them to TOC with empty summary and tags.

### Step 6: Write updated TOC to Drive

Save the complete TOC to a temp file, then upload:

\```bash
# Write TOC to temp file
cat > /tmp/sharecon_toc.json << 'TOCEOF'
{full TOC JSON here}
TOCEOF

python3 PLUGIN_DIR/resources/drive_helpers.py write-toc --folder-id "FOLDER_ID" --toc-path "/tmp/sharecon_toc.json"
\```

### Step 7: Report results

Tell the user what changed:

\```
Knowledge base synced:
  {new_count} new files indexed
  {modified_count} files updated
  {deleted_count} files removed
  {total_count} total documents

New additions:
  - Path/to/file1.docx (Author Name)
  - Path/to/file2.docx (Author Name)
\```

## Important Notes

- Only read the first 10,000 characters of each document for summary generation
- Binary files (images, videos) get listed in the TOC but with no summary
- If a file can't be read (permission error), skip it and log a warning
- Always set `last_synced` to the current ISO timestamp and `synced_by` to the authenticated user's email
```

- [ ] **Step 2: Verify the skill file has correct YAML frontmatter**

Run: `head -5 skills/ci-refresh/SKILL.md`
Expected: Valid YAML frontmatter with `name: ci-refresh` and `description`

- [ ] **Step 3: Commit**

```bash
git add skills/ci-refresh/SKILL.md
git commit -m "feat: add /ci-refresh skill for knowledge base sync"
```

---

### Task 3: Create `/ci-ask` Skill

**Files:**
- Create: `skills/ci-ask/SKILL.md`

- [ ] **Step 1: Create `skills/ci-ask/SKILL.md`**

```markdown
---
name: ci-ask
description: Query the Consumer Industries shared knowledge base. Searches the TOC, fetches relevant documents from Google Drive, and synthesizes an answer with citations and expert attribution.
---

# CI Ask — Query the Knowledge Base

Answer questions using the Consumer Industries shared knowledge base.

## Configuration

The Drive folder ID is: `REPLACE_WITH_ACTUAL_FOLDER_ID`

Helper script path: `PLUGIN_DIR/resources/drive_helpers.py`

## Procedure

### Step 1: Read the TOC

\```bash
python3 PLUGIN_DIR/resources/drive_helpers.py read-toc --folder-id "FOLDER_ID"
\```

### Step 2: Check staleness

Read the `last_synced` field. If it is more than 24 hours old, inform the user:

\```
Note: Knowledge base was last synced {time_ago}. Run /ci-refresh to pick up recent changes.
\```

Then continue answering — do not block.

### Step 3: Search the TOC

The user's question is provided as the ARGUMENTS to this skill.

Review the `files` array in the TOC. For each file, examine:
- `summary` — does it relate to the question?
- `tags` — do any tags match the topic?
- `folder` — does the category suggest relevance?
- `name` — does the filename suggest relevance?

Select the **top 3-5 most relevant** documents.

### Step 4: Fetch relevant documents

For each relevant document, read the content:

\```bash
python3 PLUGIN_DIR/resources/drive_helpers.py read-file --file-id "FILE_ID" --mime-type "MIME_TYPE" --max-chars 10000
\```

### Step 5: Synthesize answer

Using the fetched document contents, generate a comprehensive answer that:
1. Directly answers the user's question
2. Draws from specific details in the documents
3. Cites sources by document name and author

### Step 6: Format response

Use this format:

\```
[Your synthesized answer here, citing specific documents inline]

**Sources:**
- {path/to/doc1} ({author1})
- {path/to/doc2} ({author2})
- {path/to/doc3} ({author3})

**People closest to this topic:**
- {author1} ({N} docs) — may have additional context
- {author2} ({N} docs)
\```

The "People closest to this topic" section ranks authors by how many of the relevant documents they authored. This helps the user know who to talk to for deeper context.

## If no relevant documents found

Respond:

\```
No matching knowledge found in the CI knowledge base for this topic.
Consider adding a document about this to the Google Drive folder,
or try rephrasing your question.
\```
```

- [ ] **Step 2: Commit**

```bash
git add skills/ci-ask/SKILL.md
git commit -m "feat: add /ci-ask skill for knowledge base queries"
```

---

### Task 4: Create `/ci-browse` Skill

**Files:**
- Create: `skills/ci-browse/SKILL.md`

- [ ] **Step 1: Create `skills/ci-browse/SKILL.md`**

```markdown
---
name: ci-browse
description: Browse the Consumer Industries shared knowledge base. List documents by folder, contributor, or tag.
---

# CI Browse — Browse the Knowledge Base

List and explore what's in the shared knowledge base.

## Configuration

The Drive folder ID is: `REPLACE_WITH_ACTUAL_FOLDER_ID`

Helper script path: `PLUGIN_DIR/resources/drive_helpers.py`

## Procedure

### Step 1: Read the TOC

\```bash
python3 PLUGIN_DIR/resources/drive_helpers.py read-toc --folder-id "FOLDER_ID"
\```

### Step 2: Check staleness

If `last_synced` is more than 24 hours old, note:
\```
Note: Knowledge base was last synced {time_ago}. Run /ci-refresh to pick up recent changes.
\```

### Step 3: Parse arguments and display

The ARGUMENTS determine the browse mode:

**No arguments** — show folder overview:
\```
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
\```

**Folder name** (e.g., `/ci-browse "Talk Tracks"`) — list files in that folder:
\```
Talk Tracks/ ({n} documents)

  1. Retail Lakehouse Pitch Strategy.docx (Lorraine Bacon, May 10)
     → Framework for positioning lakehouse architecture to retail CIOs...
  2. CPG Data Mesh Messaging.docx (Rob Saker, May 8)
     → Key talking points for data mesh conversations with CPG customers...
\```

**`--author` flag** (e.g., `/ci-browse --author "lorraine.bacon"`) — list docs by author:
Match the author argument against the `author` field (partial match on email prefix is fine).
\```
Documents by Lorraine Bacon ({n} total)

  Account Strategies/
    - Retail Q2 Strategy.docx (May 10)
  Talk Tracks/
    - Retail Lakehouse Pitch Strategy.docx (May 8)
  Playbooks/
    - CPG Data Mesh Playbook.docx (Apr 30)
\```

**`--tag` flag** (e.g., `/ci-browse --tag "retail"`) — list docs matching tag:
\```
Documents tagged "retail" ({n} total)

  1. Retail Lakehouse Pitch Strategy.docx (Lorraine Bacon)
     Talk Tracks/ — Tags: retail, lakehouse, CIO
  2. Retail Inventory Outcome Map.docx (Justin Fenton)
     Outcome Maps/ — Tags: retail, inventory, real-time
\```
```

- [ ] **Step 2: Commit**

```bash
git add skills/ci-browse/SKILL.md
git commit -m "feat: add /ci-browse skill for knowledge base browsing"
```

---

### Task 5: Create `/ci-expert` Skill

**Files:**
- Create: `skills/ci-expert/SKILL.md`

- [ ] **Step 1: Create `skills/ci-expert/SKILL.md`**

```markdown
---
name: ci-expert
description: Find who on the Consumer Industries team knows the most about a topic, based on their authored documents in the shared knowledge base.
---

# CI Expert — Find the Right Person

Identify who has the most knowledge about a topic, based on document authorship in the knowledge base.

## Configuration

The Drive folder ID is: `REPLACE_WITH_ACTUAL_FOLDER_ID`

Helper script path: `PLUGIN_DIR/resources/drive_helpers.py`

## Procedure

### Step 1: Read the TOC

\```bash
python3 PLUGIN_DIR/resources/drive_helpers.py read-toc --folder-id "FOLDER_ID"
\```

### Step 2: Check staleness

If `last_synced` is more than 24 hours old, note:
\```
Note: Knowledge base was last synced {time_ago}. Run /ci-refresh to pick up recent changes.
\```

### Step 3: Match topic

The user's question is provided as ARGUMENTS.

Review the `files` array. For each file, check if the `summary`, `tags`, `name`, or `folder` are relevant to the user's topic.

Collect all relevant documents.

### Step 4: Rank authors

Group the relevant documents by `author`. Rank authors by:
1. Number of relevant documents (primary sort, descending)
2. Recency of most recent document (secondary sort, most recent first)

### Step 5: Format response

\```
Based on the knowledge base, the people closest to "{topic}" are:

1. {Author Name} ({email}) — {n} docs
   - {doc1_name} ({folder})
   - {doc2_name} ({folder})
   - {doc3_name} ({folder})

2. {Author Name} ({email}) — {n} docs
   - {doc1_name} ({folder})

3. {Author Name} ({email}) — {n} doc
   - {doc1_name} ({folder})

These rankings are based on authored documents in the CI knowledge base.
For deeper context, reach out to them directly.
\```

Show up to 5 authors. Include their email for easy contact.

## If no relevant documents found

\```
No documents in the knowledge base match this topic.
The knowledge base has {total} documents across these areas:
{list of folders with counts}

Consider adding content about this topic, or try a different search term.
\```
```

- [ ] **Step 2: Commit**

```bash
git add skills/ci-expert/SKILL.md
git commit -m "feat: add /ci-expert skill for expert finding"
```

---

### Task 6: Integration Test — End-to-End Validation

**Files:**
- No new files. Tests against a real Google Drive folder.

- [ ] **Step 1: Set up a test Drive folder**

Create a Google Drive folder called "Sharecon Test" with 3-4 sample documents across different subfolders:
- `Talk Tracks/Sample Talk Track.md` — a short markdown file about a fictional topic
- `Playbooks/Sample Playbook.md` — a short playbook document
- `Account Strategies/Sample Account Strategy.md` — a short account strategy

Use `/google-drive` skill or manual creation.

- [ ] **Step 2: Update skill files with real folder ID**

Replace `REPLACE_WITH_ACTUAL_FOLDER_ID` in all four SKILL.md files with the test folder's ID.

Also replace `PLUGIN_DIR` paths with the actual absolute path to the `sharecon` directory.

- [ ] **Step 3: Test `drive_helpers.py list-files`**

Run: `python3 resources/drive_helpers.py list-files --folder-id "TEST_FOLDER_ID"`
Expected: JSON array listing all 3 test files with correct paths, folders, and authors.

- [ ] **Step 4: Test `drive_helpers.py read-file`**

Run: `python3 resources/drive_helpers.py read-file --file-id "FILE_ID" --mime-type "text/plain"`
Expected: File content printed to stdout.

- [ ] **Step 5: Test `/ci-refresh`**

Run: `/ci-refresh`
Expected:
- TOC is created from scratch (first run)
- 3 files indexed with summaries and tags
- `_TOC.json` written to Drive folder

- [ ] **Step 6: Test `/ci-ask`**

Run: `/ci-ask "what's in the sample playbook?"`
Expected:
- Reads TOC
- Identifies the playbook as relevant
- Fetches the document
- Returns answer with citation and author

- [ ] **Step 7: Test `/ci-browse`**

Run: `/ci-browse`
Expected: Folder overview with file counts.

Run: `/ci-browse "Talk Tracks"`
Expected: List of files in Talk Tracks folder.

- [ ] **Step 8: Test `/ci-expert`**

Run: `/ci-expert "the topic from the sample talk track"`
Expected: Author of the talk track listed as top expert.

- [ ] **Step 9: Test deletion detection**

Delete one of the test files from Drive. Run `/ci-refresh` again.
Expected: Report shows 1 file removed, TOC updated.

- [ ] **Step 10: Final commit**

```bash
git add -A
git commit -m "feat: complete Sharecon plugin with all skills and integration tested"
```
