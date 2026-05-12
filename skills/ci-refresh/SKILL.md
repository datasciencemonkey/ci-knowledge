---
name: ci-refresh
description: Sync the CI Knowledge Base TOC with Google Drive. Scans for new, modified, and deleted files, generates summaries for changes, and writes updated _TOC.json back to Drive.
---

# /ci-refresh — Knowledge Base Sync

Synchronize the CI Knowledge knowledge base table of contents (`_TOC.json`) with the contents of a shared Google Drive folder. This skill scans for new, modified, and deleted files, generates short summaries and topic tags for changes, and writes the updated TOC back to Drive.

## Configuration

The Drive folder ID must be set before running this skill. Replace the placeholder below with the actual Google Drive folder ID for your team's knowledge base.

```
FOLDER_ID = "REPLACE_WITH_ACTUAL_FOLDER_ID"
```

## Authentication

This skill requires an active Google OAuth session. If any Drive API call fails with an authentication error, stop and tell the user:

> You are not authenticated with Google. Please run `/google-auth` first, then retry `/ci-refresh`.

## Execution Steps

Follow every step in order. Run all `python3` commands from the plugin root directory so that `resources/drive_helpers.py` resolves correctly.

### Step 1 — Read the existing TOC

Run:

```bash
python3 resources/drive_helpers.py read-toc "FOLDER_ID"
```

- If the command succeeds, parse the JSON output as the current TOC.
- If it exits with a "No _TOC.json found" message (exit code 1), start with an empty TOC structure:

```json
{
  "last_synced": null,
  "synced_by": null,
  "source": {
    "type": "google_drive",
    "folder_id": "FOLDER_ID"
  },
  "files": []
}
```

### Step 2 — List ALL files in Drive

Run:

```bash
python3 resources/drive_helpers.py list-files "FOLDER_ID"
```

Parse the JSON output. This is the complete Drive manifest and serves as the source of truth for what exists in the folder.

### Step 3 — Diff Drive manifest against TOC

Compare every file by its `id` field. Classify each file into one of four buckets:

| Category     | Condition                                                        | Action         |
|--------------|------------------------------------------------------------------|----------------|
| **Unchanged**| File `id` exists in both TOC and Drive, and `last_modified` matches | Skip           |
| **New**      | File `id` is in the Drive manifest but NOT in the TOC            | Needs summary  |
| **Modified** | File `id` exists in both, but Drive's `last_modified` is newer   | Needs re-summary |
| **Deleted**  | File `id` is in the TOC but NOT in the Drive manifest            | Remove from TOC|

Exclude folders (entries where `folder` is `true`) from the diff — only track actual files.

### Step 4 — Mass deletion protection

Before applying deletions, check whether the number of deleted files exceeds **50%** of the total entries currently in the TOC.

If it does, **STOP** and warn the user:

> ⚠️ Mass deletion detected: {n} of {total} files would be removed ({pct}%). This may indicate a permissions change or folder move rather than intentional deletions. Proceed? (yes/no)

Wait for explicit user confirmation before continuing. If the user declines, abort the sync.

### Step 5 — Generate summaries for new and modified files

For each file that needs a summary (new or modified):

1. **Skip binary files.** If the `mime_type` is not a Google Workspace type and is not a text-based format (e.g., `application/pdf`, `image/*`, `video/*`, `application/zip`), add the file to the TOC with an empty `summary` (`""`) and empty `tags` (`[]`). Do not attempt to read it.

2. **Read file content.** For readable files, run:

   ```bash
   python3 resources/drive_helpers.py read-file "FILE_ID" --mime-type "MIME_TYPE" --max-chars 10000
   ```

   If the read fails (permission error, timeout, or any other error), **skip** the file, log a warning to the user (e.g., "Warning: could not read {name}, skipping"), and add it to the TOC with empty `summary` and `tags`.

3. **Generate summary and tags.** Using the file content, produce:
   - A **2–3 line summary** describing what the file contains and why it matters.
   - **3–7 lowercase topic tags** (e.g., `["onboarding", "engineering", "runbook"]`).

4. **Build the TOC entry** with these fields:

   ```json
   {
     "id": "<file id>",
     "name": "<file name>",
     "path": "<full path from Drive listing>",
     "folder": false,
     "author": "<owner email from Drive listing>",
     "last_modified": "<modifiedTime from Drive listing>",
     "mime_type": "<mime type from Drive listing>",
     "summary": "<generated 2-3 line summary>",
     "tags": ["tag1", "tag2", "tag3"],
     "summary_generated": "<current ISO 8601 timestamp>"
   }
   ```

For **unchanged** files, keep their existing TOC entry as-is (preserve the previous summary and tags).

### Step 6 — Write the updated TOC

1. Assemble the final TOC object:
   - Set `last_synced` to the current ISO 8601 timestamp (e.g., `2026-05-11T15:30:00Z`).
   - Set `synced_by` to the authenticated user's email (if known from the Drive file owner metadata, otherwise leave as the previous value).
   - Set `source.type` to `"google_drive"` and `source.folder_id` to `FOLDER_ID`.
   - Set `files` to the merged list of all unchanged + new + modified entries (with deleted entries removed).

2. Write the TOC JSON to a temporary file:

   ```bash
   cat > /tmp/ci_knowledge_toc.json << 'TOCEOF'
   <pretty-printed JSON>
   TOCEOF
   ```

3. Upload it to Drive:

   ```bash
   python3 resources/drive_helpers.py write-toc "FOLDER_ID" /tmp/ci_knowledge_toc.json
   ```

4. Clean up the temp file:

   ```bash
   rm -f /tmp/ci_knowledge_toc.json
   ```

### Step 7 — Report results

Print a summary to the user:

```
Knowledge base synced:
  {n} new files indexed
  {n} files updated
  {n} files removed
  {total} total documents
```

If there are new additions, list them with their path and author:

```
New additions:
  - {path} (by {author})
  - {path} (by {author})
```

If any files were skipped due to errors, list those as well:

```
Skipped (errors):
  - {name}: {reason}
```
