---
title: Retrieval — Agent Guide
feature: knowledgebase
purpose: How retrieval works end-to-end and how an agent uses the retrieval API to get chunks
---

# Retrieval — Agent Guide

Complete reference for understanding and using the retrieval pipeline. Covers direct chunk retrieval endpoints, how the chat middleware drives automatic RAG, collection naming, query parameters, response shapes, and the Cognee graph merge layer.

---

## 1. Two Ways to Use Retrieval

**Direct retrieval** — the agent calls retrieval endpoints explicitly, gets raw chunks back, and uses them however it wants. Best for tools, batch jobs, or custom RAG pipelines.

**Chat-integrated retrieval** — the agent sends a normal chat completion request with `files` or `knowledge` attached in the metadata. The middleware automatically generates queries, searches, reranks, and injects context into the prompt. The agent only sees the final LLM answer and a `sources` event. Best for conversational interfaces.

Both modes are described below.

---

## 2. Collection Naming

Every vector search targets a named collection. The collection name determines what is searched.

| What it is | Collection name format |
|---|---|
| A knowledge base | The KB's UUID (e.g. `a1b2c3d4-...`) — same as the KB's `id` field |
| A single uploaded file (standalone) | `file-<file-uuid>` |
| Files inside a KB | Also indexed under the KB's UUID; `file-<file-uuid>` sub-collections are deleted after KB ingestion |

When the `query/collection` endpoint receives a KB UUID (anything not prefixed with `file-`), it automatically expands to include all file sub-collections associated with that KB. The agent does not need to enumerate individual file IDs.

---

## 3. Direct Retrieval Endpoints

All retrieval endpoints are under `/api/v1/retrieval/`. All require a Bearer token.

### 3.1 Query a Single Collection

`POST /api/v1/retrieval/query/doc`

Searches one collection (KB or file). Chooses hybrid or pure vector mode based on the server's `ENABLE_RAG_HYBRID_SEARCH` setting and the optional `hybrid` field.

Request body:

```
{
  "collection_name": "<kb-uuid or file-<uuid>>",
  "query": "What is the refund policy?",
  "k": 5,                    // optional; defaults to server TOP_K
  "k_reranker": 3,           // optional; post-rerank cutoff
  "r": 0.0,                  // optional; min relevance score (0–1)
  "hybrid": true,            // optional; null = use server default
  "hybrid_bm25_weight": 0.5  // optional; balance BM25 vs vector
}
```

Response — the raw vector DB result:

```json
{
  "ids": [["chunk-uuid-1", "chunk-uuid-2", ...]],
  "documents": [["chunk text 1", "chunk text 2", ...]],
  "metadatas": [[
    { "source": "filename.pdf", "file_id": "uuid", "page_number": 3, ... },
    ...
  ]],
  "distances": [[0.92, 0.85, ...]]
}
```

Documents, metadatas, and distances are parallel arrays — index `i` in each array corresponds to the same chunk. Distances are similarity scores; higher is better (range 0–1 for cosine after normalization).

### 3.2 Query One or More Collections

`POST /api/v1/retrieval/query/collection`

The preferred endpoint for KB search. Accepts multiple collection names, expands KB UUIDs to their file sub-collections automatically, runs hybrid or pure vector search, and if Cognee is enabled on any KB, runs a graph search in parallel and merges the graph context into position 0 of the results.

Request body:

```
{
  "collection_names": ["<kb-uuid-1>", "<kb-uuid-2>"],
  "query": "How is the product packaged?",
  "k": 10,
  "k_reranker": 5,
  "r": 0.2,
  "hybrid": true,
  "hybrid_bm25_weight": 0.4
}
```

All parameters except `collection_names` and `query` are optional. When omitted, the server uses global config values, overridden by the KB's `meta.retrieval_config` if exactly one KB is in the list (multi-KB queries always use global config).

Response shape is identical to `query/doc`. When Cognee graph context is available, it appears as the first document with `metadata.source = "cognee-graph"` and `distance = 1.0` (synthetic max score).

### 3.3 Get Stored Chunks for a File

`GET /api/v1/retrieval/chunks/{file_id}?knowledge_id=<kb-uuid>`

Returns every chunk already stored in the vector DB for a specific file within a specific KB. Does not re-chunk or re-embed — reads the stored state directly. Use this to inspect what was indexed, validate chunking output, or build a chunk browser UI.

Query parameters:
- `file_id` — the file UUID (path param)
- `knowledge_id` — the KB UUID (query param, required)

Response:

```json
{
  "total": 42,
  "chunks": [
    { "text": "...", "source": "filename.pdf", "file_id": "uuid", "page_number": 2, ... },
    ...
  ]
}
```

Returns up to 2000 chunks. Each chunk object contains the text plus all metadata stored at ingestion time.

### 3.4 Chunk Text (Preview / Test Only)

`POST /api/v1/retrieval/chunk`

Runs the chunking pipeline on raw text and returns the chunks without embedding or storing anything. Useful for testing how a KB's chunking config will split a document before committing.

Request body:

```
{
  "content": "The full text to chunk...",
  "source": "optional display name",
  "engine": "internal | external | null",   // null = server decides
  "strategy": "A | H | E",                  // strategy letter (external only)
  "config": {                               // optional per-request overrides
    "chunk_size": 512,
    "chunk_overlap": 64,
    "text_splitter": "character | token | markdown_header"
  }
}
```

Response:

```json
{
  "engine": "internal",
  "strategy": "internal",
  "total_chunks": 18,
  "chunks": [
    { "text": "...", "source": "...", ... },
    ...
  ],
  "config_used": { "text_splitter": "character", "chunk_size": 512, "chunk_overlap": 64 }
}
```

---

## 4. Retrieval Configuration

`GET /api/v1/retrieval/config` — admin or knowledge editor only.

Returns all parameters controlling retrieval behavior. Key fields:

| Parameter | Purpose |
|---|---|
| `TOP_K` | Number of chunks to retrieve from vector DB |
| `TOP_K_RERANKER` | Number to keep after reranking (must be ≤ TOP_K) |
| `RELEVANCE_THRESHOLD` | Min score to include (0 = no filter, 1 = exact match only) |
| `ENABLE_RAG_HYBRID_SEARCH` | Enables BM25 + vector hybrid search |
| `HYBRID_BM25_WEIGHT` | BM25 weight in hybrid mode (0 = pure vector, 1 = pure BM25) |
| `RAG_FULL_CONTEXT` | When true, skips chunked retrieval and passes entire file content |
| `BYPASS_EMBEDDING_AND_RETRIEVAL` | When true, disables vector search entirely |
| `RAG_RERANKING_ENGINE` | Reranker engine: empty (none), `external` |
| `CHUNKING_STRATEGY` | `A` (fixed), `H` (HTML-aware), `E` (parent-child) |
| `CHUNK_SIZE` | Characters per chunk (strategy A) |
| `CHUNK_OVERLAP` | Overlap between chunks (strategy A) |

Update config (admin only): `POST /api/v1/retrieval/config/update` with a partial body — only fields present are updated.

---

## 5. Hybrid Search Modes

When `ENABLE_RAG_HYBRID_SEARCH` is true, the system can use two implementations:

**Native hybrid search** (Elasticsearch only): The vector DB handles BM25 and vector scoring natively in one pass. Significantly faster for large collections. Active when `ENABLE_RAG_NATIVE_HYBRID_SEARCH = true` and the vector DB supports it.

**Legacy hybrid search**: Loads all documents from the collection, scores with BM25 locally, merges with vector scores using `hybrid_bm25_weight`, then reranks. Works with any vector DB but is memory-intensive for large KBs.

The agent does not choose the implementation — it is selected automatically based on server config and available capabilities.

---

## 6. Per-KB Retrieval Config at Query Time

When querying a single KB collection, the server reads the KB's `meta.retrieval_config` and uses its values for `TOP_K`, `TOP_K_RERANKER`, `RELEVANCE_THRESHOLD`, `HYBRID_BM25_WEIGHT`, and `ENABLE_RAG_HYBRID_SEARCH`. These override global config for that specific search call.

When querying multiple KB collections in one call, the global config is always used — per-KB overrides are ignored for multi-collection queries.

The agent can also pass explicit values in the request body (`k`, `k_reranker`, `r`, `hybrid_bm25_weight`). Explicit request body values take priority over both KB overrides and global config.

---

## 7. Cognee Graph Merge in Retrieval Results

When a KB has Cognee enabled (`meta.cognee.enabled = true`) and its graph is ready (`meta.cognee.graph_ready = true`), the `query/collection` endpoint runs a `GRAPH_RETURN` Cognee search in parallel with the vector search. The result is merged into position 0 of the documents array as a single synthesized chunk containing the graph entities and relationships as JSON. Its `distance` is set to `1.0` so it always wins any score-based cutoff.

The Cognee chunk's metadata has:
- `source: "cognee-graph"`
- `name: "Cognee Knowledge Graph"`

The agent can detect and handle this chunk differently if needed (e.g. render it as a graph panel rather than inline text).

---

## 8. Chat-Integrated Retrieval (How the Middleware Drives RAG)

When an agent sends a chat completion request, the middleware intercepts it before the LLM call and injects retrieved context. Understanding this pipeline helps the agent build correct requests and interpret responses.

### 8.1 What Triggers Retrieval

Retrieval fires when the chat request body contains a `files` array in `metadata`. Each item in `files` is either an attached file or a KB reference:

**Attached file item:**
```json
{
  "id": "file-<uuid>",
  "name": "Q4 Report.pdf",
  "type": "file"
}
```

**KB collection item:**
```json
{
  "id": "<kb-uuid>",
  "name": "Product Docs",
  "type": "collection"
}
```

**Full context mode (skip chunked retrieval, use entire content):**
```json
{
  "id": "<kb-uuid>",
  "name": "Short Policy",
  "type": "collection",
  "context": "full"
}
```

Model-level knowledge (KBs attached to the model definition) is automatically merged into the files list before retrieval runs — the agent doesn't need to specify them again.

### 8.2 Pipeline Execution Order

```
Request arrives
  → Apply model/folder params
  → Pipeline inlet filters
  → Filter function inlets
  → Features: memory, web search, image generation, code interpreter
  → Tool execution (parallel with KB handler when tools are present)
  → KB/file retrieval handler (chat_completion_files_handler)
  → Unified reranking if both tool sources and KB sources exist
  → Context injection into messages
  → LLM call
  → Pipeline outlet filters
  → Response streaming
```

### 8.3 Query Generation

Before searching, the middleware calls a query generation LLM task against the current messages to produce better search queries than the raw user message. The model generates a JSON object with a `queries` array and optionally a `rerank_query` field.

If query generation returns an empty `queries` array, retrieval is intentionally skipped ("No Search" behavior). If query generation fails or is disabled, the raw last user message is used as the query.

The original messages (before any tool results are appended) are used for query generation. This prevents tool output from polluting the search decision.

### 8.4 Parallel Search Strategy

Attached files (type=`file`, no `legacy` flag) and KB collections are searched in parallel:

- **Attached file search** always uses global config parameters.
- **KB search** uses per-KB config overrides when only one KB is present; global config when multiple KBs are present.
- Cognee graph search (when applicable) runs concurrently with KB vector search.

Each group is reranked independently before merging. A top-K cutoff is applied to each group separately.

### 8.5 Context Injection

Retrieved chunks are formatted into a context string with XML-like source tags:

```
<source id="1" name="Q4 Report.pdf">...chunk text...</source>
<source id="2" name="Product Docs">...chunk text...</source>
```

The context string is structured in two labeled sections:

```
[Attached File — filename.pdf]
<source>...</source>

[Knowledge Base]
<source>...</source>
```

When attached files are present, a system message instruction is prepended: the LLM is told to prioritize the attached file and use the KB only if the file does not cover the question.

The whole context block is injected into the last user message using the server's `RAG_TEMPLATE`. The template wraps the query and context together before passing to the LLM.

### 8.6 Tool-KB Interaction

When tools and KB files are both present, the middleware runs them in parallel. If any tool sets the `file_handler` flag (a tool that handles file context itself), KB retrieval results are discarded. Otherwise both sets of sources are combined. If a reranking function is configured, tool sources and KB sources are merged and reranked together using the original user query before the final context is built.

### 8.7 Source Events

After the LLM response is streamed, the middleware emits a `sources` event over the same connection. This event contains the array of source objects used for retrieval. Each source object:

```json
{
  "source": { "name": "filename.pdf", "id": "chunk-id" },
  "document": ["chunk text 1", "chunk text 2"],
  "metadata": [{ "source": "filename.pdf", "file_id": "uuid", "page_number": 3 }],
  "distances": [0.91, 0.87]
}
```

Sources without a name or id are stripped before emission.

---

## 9. Response Shape Reference

### Vector DB result (direct endpoints)

```
{
  "ids": [["id-1", "id-2", ...]],
  "documents": [["text-1", "text-2", ...]],
  "metadatas": [[
    { "source": str, "file_id": str, "name": str, "page_number": int, "raw_text": str?, ... }
  ]],
  "distances": [[float, float, ...]]
}
```

The outer array wrapper (nested lists) is a legacy format from ChromaDB. Index `[0][i]` to get the i-th chunk in each field.

The `raw_text` metadata field, when present, contains the original HTML/structured text preserved before text normalization. The middleware uses `raw_text` in preference to `document` text for LLM context so that table structure is not lost. The agent should do the same when building its own context.

### Chunk from get_stored_chunks

```
{
  "text": str,
  "source": str,
  "file_id": str,
  "name": str,
  "page_number": int | null,
  ... (other metadata from ingestion)
}
```

### Chunk from chunk_text

```
{
  "text": str,
  "source": str,
  "start_index": int,
  "headings": [str]   // only for markdown_header splitter
}
```

---

## 10. Typical Agent Retrieval Workflows

### Search a KB for relevant chunks (direct)

1. Sign in → get token.
2. `POST /api/v1/retrieval/query/collection` with `{ "collection_names": ["<kb-id>"], "query": "..." }`.
3. Iterate `response.documents[0]` with `response.metadatas[0]` and `response.distances[0]` to process each chunk.
4. Apply your own relevance filter using the distance score if needed.

### Search multiple KBs at once

1. Collect the KB UUIDs you want to search.
2. `POST /api/v1/retrieval/query/collection` with all UUIDs in `collection_names`.
3. Note: per-KB config overrides are ignored when more than one KB is in the list; global config applies.

### Inspect what was indexed for a file

1. Know the `file_id` (UUID of the file) and `knowledge_id` (UUID of the KB it belongs to).
2. `GET /api/v1/retrieval/chunks/{file_id}?knowledge_id={kb-id}`.
3. Inspect returned chunks to verify chunking quality, page coverage, or metadata correctness.

### Preview chunking before adding a file to a KB

1. Extract text from the document client-side (or use the file content already stored in `file.data.content`).
2. `POST /api/v1/retrieval/chunk` with the text and any config overrides matching the target KB's `meta.retrieval_config`.
3. Review chunk count, size distribution, and boundary quality before committing to the KB.

### Build a chat completion request that triggers KB retrieval

Include the `files` array in the request body's `metadata`:

```json
{
  "model": "model-id",
  "messages": [{ "role": "user", "content": "What does the policy say about refunds?" }],
  "metadata": {
    "files": [
      { "id": "<kb-uuid>", "name": "Policy Docs", "type": "collection" }
    ]
  }
}
```

The middleware handles query generation, search, reranking, and context injection automatically. The agent receives the LLM's answer and a `sources` event with the chunks used.

### Force full-document context (skip chunked retrieval)

Set `"context": "full"` on any file item in the `files` array. The middleware loads the entire stored document content and injects it without retrieving chunks. All files in the request must have `context: "full"` for the full-context path to activate; otherwise hybrid retrieval runs normally.

### Attach an uploaded file directly to a chat (without a KB)

```json
{
  "metadata": {
    "files": [
      { "id": "file-<uuid>", "name": "Q4 Report.pdf", "type": "file" }
    ]
  }
}
```

The middleware searches the `file-<uuid>` collection using attached-file parameters (always global config). The retrieved chunks appear under the `[Attached File — Q4 Report.pdf]` section in the context, and the LLM is instructed to prioritize them over any KB sources also in the request.

---

## 11. Admin Utility Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/retrieval/` | Health check — returns embedding model and status |
| GET | `/api/v1/retrieval/config` | Read all retrieval/RAG config |
| POST | `/api/v1/retrieval/config/update` | Update retrieval/RAG config (admin) |
| GET | `/api/v1/retrieval/embedding` | Read embedding model config |
| POST | `/api/v1/retrieval/embedding/update` | Update embedding model (admin) |
| POST | `/api/v1/retrieval/delete` | Delete specific vectors by file_id from a collection (admin) |
| POST | `/api/v1/retrieval/drop/collection` | Drop an entire vector collection (admin) |
| POST | `/api/v1/retrieval/reset/db` | Wipe entire vector DB (admin, destructive) |
| POST | `/api/v1/retrieval/reset/uploads` | Delete all uploaded files on disk (admin, destructive) |
| POST | `/api/v1/retrieval/process/file` | Re-process a file into a collection (internal use) |
| POST | `/api/v1/retrieval/process/text` | Inline text → vector index (internal use) |
| POST | `/api/v1/retrieval/process/web` | Scrape URL → vector index |
| POST | `/api/v1/retrieval/process/web/search` | Web search → vector index |
