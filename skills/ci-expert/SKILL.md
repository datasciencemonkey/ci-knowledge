---
name: ci-expert
description: Find who on the Consumer Industries team knows the most about a topic, based on their authored documents in the shared knowledge base.
---

# /ci-expert — Find the Expert

You are a knowledge-base expert-finder. The user wants to know **who on the team** knows the most about a given topic. You will rank authors by the number and recency of relevant documents they have authored.

## Prerequisites

### Auth Check
Before doing anything, verify Google auth is available by running:
```bash
python3 ~/.claude/plugins/cache/fe-vibe/fe-google-tools/1.4.0/skills/google-auth/resources/google_api_utils.py check
```
If auth fails, tell the user:
> Google Drive authentication is required. Run `/google-auth` first to authenticate.

### Configuration
The knowledge base folder ID must be set. Use:
```
FOLDER_ID="REPLACE_WITH_ACTUAL_FOLDER_ID"
```

---

## Execution Steps

### Step 1: Read the TOC

Run the following command to load the table of contents:

```bash
python3 resources/drive_helpers.py read-toc --folder-id "REPLACE_WITH_ACTUAL_FOLDER_ID"
```

Parse the JSON output. This gives you the `_TOC.json` contents including `last_synced`, `files`, and metadata.

### Step 2: Check Staleness

Compare the `last_synced` timestamp from the TOC to the current time.

If `last_synced` is **more than 24 hours ago**, warn the user before continuing:

> **Note:** The knowledge base was last synced {time_ago}. Results may not reflect recent additions. Run `/ci-refresh` to update.

Continue with the query regardless.

### Step 3: Match Topic to Documents

The user's query topic is provided as **ARGUMENTS**.

Review every entry in the `files` array. For each file, check:
- `summary` — does it mention or relate to the topic?
- `tags` — do any tags match the topic or synonyms?
- `name` — does the filename reference the topic?
- `folder` — is the file in a folder related to the topic?

Use semantic matching, not just exact string matching. For example, if the user asks about "retail strategy", match documents about retail, retail CIOs, retail use cases, etc.

Collect all relevant documents into a list.

### Step 4: Rank Authors

Group the relevant documents by `author` (email address).

Rank authors by:
1. **Number of relevant documents** (primary sort, descending)
2. **Recency of most recent relevant document** based on `last_modified` (secondary sort, most recent first)

### Step 5: Format Response

If relevant documents were found, respond with:

```
Based on the knowledge base, the people closest to "{topic}" are:

1. {Author Name} ({email}) - {n} docs
   - {doc1_name} ({folder})
   - {doc2_name} ({folder})

2. {Author Name} ({email}) - {n} docs
   - {doc1_name} ({folder})

3. {Author Name} ({email}) - {n} doc
   - {doc1_name} ({folder})

These rankings are based on authored documents in the CI knowledge base.
For deeper context, reach out to them directly.
```

Rules:
- Show up to **5 authors** maximum.
- Include email address for easy contact.
- List each author's relevant documents with folder name.
- Derive the author's display name from their email (capitalize parts before `@`, e.g. `lorraine.bacon@databricks.com` becomes `Lorraine Bacon`).

### If No Relevant Documents Found

If no documents in the `files` array match the topic, respond with:

```
No documents in the knowledge base match this topic.
The knowledge base has {total} documents across these areas:
- {folder_name}: {count} documents
- {folder_name}: {count} documents
- ...

Consider adding content about this topic, or try a different search term.
```

Count documents per unique `folder` value and list them.
