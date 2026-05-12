---
name: ci-ask
description: Query the Consumer Industries shared knowledge base. Searches the TOC, fetches relevant documents from Google Drive, and synthesizes an answer with citations and expert attribution.
---

# /ci-ask — Query the CI Knowledge Base

You are answering a question from the user by searching the Consumer Industries shared knowledge base stored in Google Drive.

The user's question is provided as **ARGUMENTS** to this skill.

## Configuration

The Drive folder ID is read from `config.json` in the plugin root directory.

```bash
FOLDER_ID=$(python3 -c "import json; print(json.load(open('config.json'))['drive_folder_id'])")
```

All commands below use `resources/drive_helpers.py` relative to the plugin directory.

## Step 0: Check Authentication

Before proceeding, verify that Google API authentication is available. If any command below fails with an authentication error, inform the user:

```
Google Drive authentication is not configured.
Please run the google-auth setup first to enable Drive API access.
```

Then stop.

## Step 1: Read the TOC

Run:

```bash
python3 resources/drive_helpers.py read-toc FOLDER_ID
```

This returns the `_TOC.json` file from the shared Drive folder. It contains metadata about all documents including `files`, `last_synced`, and per-file fields like `id`, `name`, `path`, `folder`, `mime_type`, `author`, `summary`, and `tags`.

If no TOC is found, inform the user:

```
No knowledge base found. Run /ci-refresh to initialize the TOC from the shared Drive folder.
```

Then stop.

## Step 2: Check Staleness

Examine the `last_synced` timestamp in the TOC response.

If `last_synced` is more than 24 hours old, print this notice **before** continuing:

```
Note: Knowledge base was last synced {time_ago}. Run /ci-refresh to pick up recent changes.
```

**Do NOT block** -- continue with the query using the available data.

## Step 3: Search the TOC

Review the `files` array from the TOC. For each file entry, examine:

- `summary` -- the AI-generated summary of the document
- `tags` -- keyword tags associated with the document
- `folder` -- the folder path (indicates topic area)
- `name` -- the document name

Compare these fields against the user's question. Select the **top 3-5 most relevant documents** based on semantic relevance to the question.

## Step 4: Fetch Relevant Documents

For each relevant document identified in Step 3, fetch its full content:

```bash
python3 resources/drive_helpers.py read-file FILE_ID --mime-type "MIME_TYPE" --max-chars 10000
```

Replace `FILE_ID` with the document's `id` and `MIME_TYPE` with its `mime_type` from the TOC entry.

## Step 5: Synthesize Answer

Using the fetched document content, generate an answer that:

1. **Directly answers** the user's question
2. **Draws from specific details** found in the documents -- quote or paraphrase relevant passages
3. **Cites sources** by document name and author inline where information is referenced

## Step 6: Format Response

Present the answer in this format:

```
[Synthesized answer citing specific documents inline, e.g. "According to {doc_name} ({author}), ..."]

**Sources:**
- {path/to/doc1} ({author1})
- {path/to/doc2} ({author2})

**People closest to this topic:**
- {author1} ({N} docs) -- may have additional context
- {author2} ({N} docs)
```

The **"People closest to this topic"** section ranks authors by how many of the relevant documents they authored. This helps the user know who to reach out to for deeper knowledge.

## If No Relevant Documents Found

If no documents in the TOC are relevant to the user's question, respond with:

```
No matching knowledge found in the CI knowledge base for this topic.
Consider adding a document about this to the Google Drive folder,
or try rephrasing your question.
```
