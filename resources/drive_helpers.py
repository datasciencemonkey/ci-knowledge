#!/usr/bin/env python3
"""
Drive API helper for Sharecon TOC operations.

Provides functions for listing files, reading content, and managing
_TOC.json files in Google Drive folders. Used by Claude Code skills
to surface team knowledge from shared Drive folders.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Import shared Google auth utilities
# ---------------------------------------------------------------------------

_AUTH_MODULE_PATH = os.path.expanduser(
    "~/.claude/plugins/cache/fe-vibe/fe-google-tools/1.4.0/skills/google-auth/resources"
)
if _AUTH_MODULE_PATH not in sys.path:
    sys.path.insert(0, _AUTH_MODULE_PATH)

from google_api_utils import api_call_with_retry, QUOTA_PROJECT  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
UPLOAD_API_BASE = "https://www.googleapis.com/upload/drive/v3"

# Google Workspace MIME type -> export format
EXPORT_MIME_MAP = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

TOC_FILENAME = "_TOC.json"


# ---------------------------------------------------------------------------
# Helper: raw GET that returns text (for file content downloads / exports)
# ---------------------------------------------------------------------------

def _raw_get(url: str, params: dict = None, timeout: int = 30) -> str:
    """
    Perform an authenticated GET that returns raw text instead of parsed JSON.

    The shared api_call_with_retry always tries to parse JSON, but file export
    endpoints return plain text / CSV. This thin wrapper handles that case.
    """
    from google_api_utils import get_access_token

    if params:
        query_string = urllib.parse.urlencode(params)
        url = f"{url}?{query_string}"

    headers = {
        "Authorization": f"Bearer {get_access_token()}",
        "x-goog-user-project": QUOTA_PROJECT,
    }

    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


# ---------------------------------------------------------------------------
# Helper: multipart upload (for creating files with metadata + content)
# ---------------------------------------------------------------------------

def _multipart_upload(metadata: dict, content_bytes: bytes, content_type: str) -> dict:
    """
    Create a file on Drive using multipart upload (metadata + media).

    Returns the parsed JSON response from the Drive API.
    """
    from google_api_utils import get_access_token

    boundary = "sharecon_boundary_2024"
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + content_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    url = f"{UPLOAD_API_BASE}/files?uploadType=multipart"
    headers = {
        "Authorization": f"Bearer {get_access_token()}",
        "x-goog-user-project": QUOTA_PROJECT,
        "Content-Type": f"multipart/related; boundary={boundary}",
        "Content-Length": str(len(body)),
    }

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ===========================================================================
# Public API
# ===========================================================================


def list_files(folder_id: str, path_prefix: str = "") -> list:
    """
    Recursively list all files in a Google Drive folder.

    Args:
        folder_id:    The Drive folder ID to enumerate.
        path_prefix:  Prefix prepended to file paths (used during recursion).

    Returns:
        List of dicts, each with keys:
            id, name, path, folder, mime_type, last_modified, author
    """
    results = []
    page_token = None

    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,owners)",
            "pageSize": "1000",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token

        resp = api_call_with_retry("GET", f"{DRIVE_API_BASE}/files", params=params)
        files = resp.get("files", [])

        for f in files:
            is_folder = f["mimeType"] == "application/vnd.google-apps.folder"
            file_path = f"{path_prefix}/{f['name']}" if path_prefix else f["name"]

            owners = f.get("owners", [])
            author = owners[0].get("emailAddress", "") if owners else ""

            entry = {
                "id": f["id"],
                "name": f["name"],
                "path": file_path,
                "folder": is_folder,
                "mime_type": f["mimeType"],
                "last_modified": f.get("modifiedTime", ""),
                "author": author,
            }
            results.append(entry)

            # Recurse into sub-folders
            if is_folder:
                results.extend(list_files(f["id"], path_prefix=file_path))

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return results


def read_file(file_id: str, mime_type: str, max_chars: int = 10000) -> str:
    """
    Read file content from Google Drive.

    Google Workspace files (Docs, Sheets, Slides) are exported as text.
    Binary / non-Workspace files are downloaded directly.

    Args:
        file_id:    The Drive file ID.
        mime_type:  The file's MIME type (used to decide export vs download).
        max_chars:  Maximum characters to return (default 10 000).

    Returns:
        The file content as a string, truncated to max_chars.
    """
    export_as = EXPORT_MIME_MAP.get(mime_type)

    if export_as:
        # Google Workspace file -> export
        url = f"{DRIVE_API_BASE}/files/{file_id}/export"
        content = _raw_get(url, params={"mimeType": export_as})
    else:
        # Regular file -> download
        url = f"{DRIVE_API_BASE}/files/{file_id}"
        content = _raw_get(url, params={"alt": "media"})

    return content[:max_chars]


def find_toc_file(folder_id: str) -> str | None:
    """
    Find _TOC.json in a Drive folder.

    Args:
        folder_id: The Drive folder ID to search.

    Returns:
        The file ID of _TOC.json, or None if not found.
    """
    params = {
        "q": f"'{folder_id}' in parents and name = '{TOC_FILENAME}' and trashed = false",
        "fields": "files(id,name)",
        "pageSize": "1",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    resp = api_call_with_retry("GET", f"{DRIVE_API_BASE}/files", params=params)
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def read_toc(folder_id: str) -> dict | None:
    """
    Read _TOC.json from a Drive folder and return parsed JSON.

    Args:
        folder_id: The Drive folder ID containing _TOC.json.

    Returns:
        Parsed JSON dict/list, or None if _TOC.json does not exist.
    """
    toc_id = find_toc_file(folder_id)
    if not toc_id:
        return None

    content = read_file(toc_id, "application/json")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print(f"Warning: _TOC.json (id={toc_id}) is not valid JSON.", file=sys.stderr)
        return None


def write_toc(folder_id: str, toc_data) -> dict:
    """
    Write _TOC.json to a Drive folder (create or update).

    Args:
        folder_id: The Drive folder ID where _TOC.json should live.
        toc_data:  The data to serialize as JSON into _TOC.json.

    Returns:
        Drive API response dict for the created/updated file.
    """
    from google_api_utils import get_access_token

    content_bytes = json.dumps(toc_data, indent=2, ensure_ascii=False).encode("utf-8")
    toc_id = find_toc_file(folder_id)

    if toc_id:
        # Update existing _TOC.json via PATCH to upload endpoint
        url = f"{UPLOAD_API_BASE}/files/{toc_id}?uploadType=media"
        headers = {
            "Authorization": f"Bearer {get_access_token()}",
            "x-goog-user-project": QUOTA_PROJECT,
            "Content-Type": "application/json",
            "Content-Length": str(len(content_bytes)),
        }
        req = urllib.request.Request(url, data=content_bytes, headers=headers, method="PATCH")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    else:
        # Create new _TOC.json via multipart upload
        metadata = {
            "name": TOC_FILENAME,
            "parents": [folder_id],
            "mimeType": "application/json",
        }
        return _multipart_upload(metadata, content_bytes, "application/json")


# ===========================================================================
# CLI interface
# ===========================================================================


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Google Drive helpers for Sharecon TOC operations.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- list-files ---
    p_list = subparsers.add_parser("list-files", help="Recursively list files in a Drive folder.")
    p_list.add_argument("folder_id", help="Google Drive folder ID.")

    # --- read-file ---
    p_read = subparsers.add_parser("read-file", help="Read content of a Drive file.")
    p_read.add_argument("file_id", help="Google Drive file ID.")
    p_read.add_argument("--mime-type", default="application/octet-stream",
                        help="MIME type of the file (default: application/octet-stream).")
    p_read.add_argument("--max-chars", type=int, default=10000,
                        help="Maximum characters to return (default: 10000).")

    # --- read-toc ---
    p_rtoc = subparsers.add_parser("read-toc", help="Read _TOC.json from a Drive folder.")
    p_rtoc.add_argument("folder_id", help="Google Drive folder ID containing _TOC.json.")

    # --- write-toc ---
    p_wtoc = subparsers.add_parser("write-toc", help="Write _TOC.json to a Drive folder.")
    p_wtoc.add_argument("folder_id", help="Google Drive folder ID for _TOC.json.")
    p_wtoc.add_argument("json_file", help="Path to local JSON file with TOC data (use - for stdin).")

    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "list-files":
            files = list_files(args.folder_id)
            print(json.dumps(files, indent=2))

        elif args.command == "read-file":
            content = read_file(args.file_id, args.mime_type, args.max_chars)
            print(content)

        elif args.command == "read-toc":
            toc = read_toc(args.folder_id)
            if toc is None:
                print("No _TOC.json found in folder.", file=sys.stderr)
                sys.exit(1)
            print(json.dumps(toc, indent=2))

        elif args.command == "write-toc":
            if args.json_file == "-":
                toc_data = json.load(sys.stdin)
            else:
                with open(args.json_file, "r") as f:
                    toc_data = json.load(f)
            result = write_toc(args.folder_id, toc_data)
            print(json.dumps(result, indent=2))

    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
