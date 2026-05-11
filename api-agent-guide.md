---
title: Knowledge Base — Agent API Guide
feature: knowledgebase
purpose: Comprehensive reference for Claude Code to understand and use the Knowledge Base API without ambiguity
---

# Knowledge Base — Agent API Guide

Authoritative reference for building against the LloydK RAG Knowledge Base API. Covers authentication, permission model, every KB and file operation, async job tracking, and optional Cognee graph integration. No file paths or code — only contract-level facts.

---

## 1. Authentication

Every request must carry a JWT Bearer token. Obtain it by signing in via one of three flows.

### 1.1 Standard Email/Password Sign-In

`POST /api/v1/auths/signin`  
Body: `{ email, password }`  
Returns: `{ token, token_type: "Bearer", expires_at, id, email, name, role, profile_image_url, permissions }`

The `expires_at` field is a Unix timestamp (seconds). When it is null, the token never expires. If `expires_at` is set and the current time exceeds it, the server returns 401 on any authenticated call.

### 1.2 LDAP Sign-In

`POST /api/v1/auths/ldap`  
Body: `{ user, password }` — `user` is the LDAP username, not the email.  
Only available when the server has LDAP enabled. Returns the same `SessionUserResponse` shape as standard sign-in, including group membership synced from the directory.

### 1.3 Trusted Header (SSO proxy)

When the backend is deployed behind a reverse proxy configured for header-based SSO, the `X-Forwarded-Email` header (or the configured equivalent) is trusted in place of a password. Agents running in that environment do not need to sign in; the proxy injects the header automatically.

### 1.4 Using the Token

Pass the token in every subsequent request:  
`Authorization: Bearer <token>`

The server also sets an `httponly` cookie named `token` on sign-in responses. Browser-based agents can rely on that cookie; non-browser agents must carry the Bearer header explicitly.

### 1.5 Session Info

`GET /api/v1/auths/`  
Returns the full session payload (same shape as sign-in) including the `permissions` map for the current user. Use this to refresh expiry or verify the token is still valid.

### 1.6 Sign-Out

`GET /api/v1/auths/signout`  
Clears cookies server-side. If OIDC/OAuth is in use, the response may include a `redirect_url` pointing to the provider's end-session endpoint. The agent should follow that URL to complete the logout cycle.

### 1.7 API Keys

Users can generate a persistent API key at `POST /api/v1/auths/api_key` and delete it at `DELETE /api/v1/auths/api_key`. API keys are only available when the server config has `ENABLE_API_KEY = true`. When used, the API key is passed as a Bearer token in place of the JWT.

---

## 2. Permission Model

The system has three user roles: `admin`, `user`, and `pending`. A user with role `pending` cannot access any resource. The permission model has two layers.

### 2.1 Role-Level Gate

Admins bypass most access checks. Non-admin users must hold explicit permissions, which are stored in the server config under `USER_PERMISSIONS` and can vary per user via group membership.

### 2.2 Workspace Permissions

These flags control what non-admin users can do globally:

| Permission key | What it gates |
|---|---|
| `workspace.knowledge` | Create new knowledge bases |
| `sharing.public_knowledge` | Set a knowledge base to public (access_control = null) |

A user who lacks `workspace.knowledge` cannot call the create endpoint and will receive 401. A user who lacks `sharing.public_knowledge` who tries to create or update a KB with `access_control: null` will have the access control silently forced to `{}` (private, no explicit sharing) rather than receiving an error.

### 2.3 Per-KB Access Control

Each knowledge base carries an `access_control` field. When it is `null`, the KB is public and every authenticated user can read it. When it is an empty object `{}`, the KB is private to its creator. The object can also carry group IDs granting read or write to specific groups.

The permission checks for each operation are:

| Operation | Who can perform it |
|---|---|
| List (read) | Admin, or user with read access to the KB |
| List (write-capable) | Admin, or user with write access to the KB |
| Get by ID | Admin, KB creator, or user with read access |
| Update KB metadata | Admin, KB creator, or user with write access |
| Add file to KB | Admin, KB creator, or user with write access |
| Remove file from KB | Admin, KB creator, or user with write access |
| Update (re-process) file | Admin, KB creator, or user with write access |
| Delete KB | Admin, KB creator, or user with write access |
| Reset KB | Admin, KB creator, or user with write access |
| Export KB | Admin, KB creator, or user with read access |
| Reindex all KBs | Admin only |

---

## 3. Knowledge Base Lifecycle

### 3.1 Create

`POST /api/v1/knowledge/create`  
Body:

```
{
  "name": "string (required)",
  "description": "string (optional)",
  "data": {},           // leave empty or omit; backend initializes file_ids: []
  "meta": {},           // optional; used for per-KB retrieval config overrides
  "access_control": null | {}    // null = public, {} = private
}
```

Returns the created KB object. If Cognee is enabled globally, the backend asynchronously creates a Cognee dataset for the KB. This is non-blocking — the KB is returned immediately even if Cognee setup fails.

### 3.2 List All (read access)

`GET /api/v1/knowledge/`  
Returns every KB the current user can read, each with a populated `files` array of file metadata objects. Missing files (orphaned IDs) are automatically cleaned from the KB's `file_ids` list.

### 3.3 List All (write access)

`GET /api/v1/knowledge/list`  
Same shape as the read list, but filtered to KBs the user can write to. Use this when building pickers for "add a file to a KB" workflows.

### 3.4 Get Single KB

`GET /api/v1/knowledge/{id}`  
Returns the KB object plus its `files` array. The `id` is the UUID assigned at creation, also used as the vector DB collection name.

### 3.5 Update KB Metadata

`POST /api/v1/knowledge/{id}/update`  
Body is the same shape as the create body. Replaces name, description, meta, and access_control. Does not touch the file list — file changes happen through the file sub-endpoints.

### 3.6 Reset KB

`POST /api/v1/knowledge/{id}/reset`  
Clears the vector DB collection and empties the `file_ids` list. The KB record itself is kept. If Cognee is enabled and active on this KB, the Cognee dataset is also deleted and the Cognee meta fields are reset. The KB is left as an empty container ready for new files.

### 3.7 Delete KB

`DELETE /api/v1/knowledge/{id}/delete`  
Deletes the KB record, its vector DB collection, any Cognee dataset, and removes references to this KB from all AI models that were using it. Permanent — no soft delete.

### 3.8 Export KB

`GET /api/v1/knowledge/{id}/export`  
Returns a streaming ZIP file containing all raw files in the KB. The ZIP filename is `<kb-name>.zip`. Duplicate filenames within the archive are resolved by appending `_N` suffixes.

### 3.9 Reindex All KBs (admin only)

`POST /api/v1/knowledge/reindex`  
Iterates every KB, drops its vector collection, and re-runs the full text processing pipeline for each file. KBs with missing or invalid data are deleted during this process. Per-KB config overrides are respected during reindex. Returns `true` on completion.

---

## 4. File Operations

Files are two-step: first upload the raw bytes, then attach the file to a KB for processing.

### 4.1 Upload a Raw File

`POST /api/v1/files/?process=false`  
Multipart form upload. The `process=false` query parameter tells the server to store the file without immediately processing it. Returns `{ file_id, filename, ... }`.

Never send this without `process=false` if you intend to control which KB the file goes into.

### 4.2 Add File to KB (single file)

`POST /api/v1/knowledge/{id}/file/add`  
Body: `{ "file_id": "<uuid>" }`

**When Redis is available:** The server enqueues the file for background processing and returns immediately:

```
{
  "job_id": "<uuid>",
  "status": "queued",
  "file_id": "<uuid>",
  "knowledge_id": "<uuid>",
  "filename": "document.pdf"
}
```

The agent must then track the job via SSE (section 4.5) to know when processing completes. The file is not added to `file_ids` until the worker finishes successfully.

**When Redis is unavailable (fallback):** The server processes the file inline and returns the full `KnowledgeFilesResponse` object with the updated file list. No SSE is needed.

The agent cannot know in advance which mode the server is in — detect it by inspecting the response shape: if the response has a `job_id` field, it is async; if it has a `files` array, it is inline.

**Cognee side-effect:** If Cognee is enabled and active on this KB, the file is also uploaded to the Cognee dataset and a background graph construction task is started before the vector DB ingestion continues.

### 4.3 Add Files to KB (batch)

`POST /api/v1/knowledge/{id}/files/batch/add`  
Body: array of `{ "file_id": "<uuid>" }` objects.  
Runs inline (not queued through Redis). Returns `KnowledgeFilesResponse`. Only successfully processed files are added to `file_ids`. If some files fail, the response includes a `warnings` object listing which file IDs failed and why. Cognee batch upload is handled automatically if Cognee is enabled.

### 4.4 Re-process a File (update)

`POST /api/v1/knowledge/{id}/file/update`  
Body: `{ "file_id": "<uuid>" }`  
Deletes the file's existing vectors from the collection, then re-runs the full extraction and embedding pipeline. Use this after the source file has changed. Returns the updated `KnowledgeFilesResponse`. Runs inline — no job queue.

### 4.5 Remove a File from KB

`POST /api/v1/knowledge/{id}/file/remove`  
Body: `{ "file_id": "<uuid>" }`  
Optional query param: `delete_file=true` (default) or `delete_file=false`.

With `delete_file=true`: removes vectors from the collection, deletes the file's own vector collection, and permanently deletes the file record from the database.  
With `delete_file=false`: only removes the vectors associated with this KB — the file record stays and can be re-added.

If the `file_id` is not in the KB's list (e.g. it was never fully processed), the endpoint returns the current KB state as a no-op success rather than an error.

---

## 5. Async Job Tracking (SSE)

When `file/add` returns a `job_id`, subscribe to the SSE stream to track progress.

`GET /api/files/jobs/{job_id}/stream`  
Content-Type: `text/event-stream`

The stream emits data events with a JSON payload. The `status` field transitions through:

```
queued → processing → completed
                    ↘ failed
```

On `completed`, the file is now indexed in the KB and the file ID has been appended to the KB's `file_ids`. On `failed`, the file was not added. The agent should call `GET /api/v1/knowledge/{id}` after completion to refresh the full KB state.

**Reconnection:** If the page is reloaded or the SSE connection is dropped, re-subscribing to the same `job_id` stream is safe — the server replays the last known status. Jobs in `queued` or `processing` state resume normally.

**No Redis fallback:** When Redis is unavailable, the `file/add` endpoint processes inline and never emits SSE events. No stream subscription is needed or possible.

---

## 6. Per-KB Retrieval Config Override

Each KB can store a `meta.retrieval_config` object that temporarily overrides global ingestion settings only for that KB's files. This is applied at processing time and restored afterward.

Overridable settings include the content extraction engine, chunking strategy, chunk sizes, embedding engine and model, reranking engine and model, and their associated API base URLs.

Valid embedding engines: empty string (local SentenceTransformer), `ollama`, `openai`, `azure_openai`.  
Valid reranking engines: empty string (none), `external`.

When embedding or reranking engine or model is overridden, the server rebuilds the live function objects for the duration of processing. This is not just a config string change — the actual inference objects are swapped out so the correct model is used.

To apply a config override, set `meta.retrieval_config` when creating or updating the KB. Example structure (values are illustrative):

```json
{
  "meta": {
    "retrieval_config": {
      "CHUNKING_STRATEGY": "A",
      "CHUNK_SIZE": 512,
      "CHUNK_OVERLAP": 64,
      "RAG_EMBEDDING_ENGINE": "openai",
      "RAG_EMBEDDING_MODEL": "text-embedding-3-small"
    }
  }
}
```

---

## 7. Cognee Knowledge Graph (optional)

Cognee adds graph-based knowledge extraction on top of the standard vector pipeline. It is controlled at two levels: global server config (`COGNEE_ENABLED`) and per-KB toggle (`meta.cognee.enabled`).

When both are true, every file added to the KB is also uploaded to a Cognee dataset and a background "cognify" task constructs the knowledge graph. Vector DB ingestion runs in parallel — Cognee failure never blocks file indexing.

### 7.1 Toggle Graph On/Off

`POST /api/v1/knowledge/{id}/graph/toggle`  
Body: `{ "enabled": true | false }`

Toggling ON: creates the Cognee dataset if it does not exist, marks the KB as graph-enabled, and immediately starts cognifying any files already in the KB that have not yet been processed by Cognee.  
Toggling OFF: disables graph search for the KB without deleting the Cognee data.

### 7.2 Graph Status (polling or streaming)

`GET /api/v1/knowledge/{id}/graph/status`  
Add `?stream=false` for a single JSON snapshot. Default is streaming SSE.

SSE payload fields:
- `enabled` — whether graph is active
- `status` — `pending | processing | completed | failed | uploaded`
- `progress` — 0–100 percentage
- `graph_ready` — boolean; true only when the graph is fully built
- `current_step`, `current_file`, `files_processed`, `total_files` — progress details
- `entity_count`, `relationship_count` — graph statistics
- `visualization_url` — present only when `graph_ready` is true; points to the proxy visualization endpoint
- `error` — error message when status is `failed`

The SSE stream uses a 30-second keep-alive timeout and re-reads from the database on each timeout to prevent stale state.

### 7.3 Graph Visualization

`GET /api/v1/knowledge/{id}/graph/visualize`  
Returns an interactive HTML page rendered by Cognee showing the knowledge graph. Only available when `graph_ready` is true; returns 425 Too Early otherwise. The backend proxies this call to the Cognee service so the agent never needs to reach Cognee directly.

---

## 8. Response Shapes Reference

### KnowledgeResponse (KB without files)

```
id: string (UUID, also the vector collection name)
user_id: string
name: string
description: string | null
data: { file_ids: string[] }
meta: object | null
access_control: object | null
created_at: integer (Unix ms)
updated_at: integer (Unix ms)
```

### KnowledgeFilesResponse (KB with files)

Extends `KnowledgeResponse` with:

```
files: FileMetadataResponse[]
warnings?: { message: string, errors: string[] }   // batch add only, on partial failure
```

### FileMetadataResponse

```
id: string
user_id: string
filename: string
meta: { content_type, size, ... }
created_at: integer
```

### KnowledgeFileJobResponse (async job ticket)

```
job_id: string
status: "queued"
file_id: string
knowledge_id: string
filename: string
```

---

## 9. Error Handling

The API returns standard HTTP errors with a JSON `{ "detail": "..." }` body.

| HTTP code | Common cause |
|---|---|
| 400 | Bad request (missing fields, file not found, file already in KB) |
| 401 | Not authenticated or insufficient role |
| 403 | Access control check failed |
| 404 | KB or file does not exist |
| 425 | Graph not ready yet (visualization requested too early) |
| 500 | Internal error (embedding failure, storage error) |
| 502 | Cognee upstream error |
| 503 | Cognee service unavailable |

---

## 10. Typical Agent Workflows

### Create KB and upload a document

1. Sign in → get token.
2. Create KB via `POST /api/v1/knowledge/create`.
3. Upload file via `POST /api/v1/files/?process=false` → get `file_id`.
4. Add file to KB via `POST /api/v1/knowledge/{id}/file/add`.
5. If response has `job_id`: subscribe to `GET /api/files/jobs/{job_id}/stream` and wait for `status: completed`.
6. If response has `files`: done immediately.
7. Refresh KB state via `GET /api/v1/knowledge/{id}` to confirm.

### Upload multiple documents at once

1. Upload each file individually via the files endpoint, collect all `file_id` values.
2. Call `POST /api/v1/knowledge/{id}/files/batch/add` with the array of file IDs.
3. Inspect the response for `warnings.errors` to see which files (if any) failed.
4. Batch add runs inline — no SSE tracking needed.

### Re-index after config change

1. Update the KB's `meta.retrieval_config` via `POST /api/v1/knowledge/{id}/update`.
2. For each file, call `POST /api/v1/knowledge/{id}/file/update` with its `file_id`.  
   Or, if a full wipe is acceptable, call `POST /api/v1/knowledge/{id}/reset` then re-add all files.

### Enable knowledge graph

1. Ensure files are already indexed (standard vector pipeline complete).
2. Call `POST /api/v1/knowledge/{id}/graph/toggle` with `{ "enabled": true }`.
3. Poll `GET /api/v1/knowledge/{id}/graph/status?stream=false` until `graph_ready: true`.
4. Render visualization via `GET /api/v1/knowledge/{id}/graph/visualize`.

---

## 11. Admin-Only Operations

Admins can:
- Reindex all KBs: `POST /api/v1/knowledge/reindex`
- Add users directly: `POST /api/v1/auths/add` with `{ email, password, name, role }`
- Read/write server config: `GET/POST /api/v1/auths/admin/config`
- Read/write LDAP server config: `GET/POST /api/v1/auths/admin/config/ldap/server`
- Toggle LDAP on/off: `GET/POST /api/v1/auths/admin/config/ldap`
- View admin contact details (when `SHOW_ADMIN_DETAILS` is true): `GET /api/v1/auths/admin/details`

The `BYPASS_ADMIN_ACCESS_CONTROL` server flag, when set, makes admin users bypass all per-KB access control checks completely — they see and can write all KBs regardless of `access_control`.
