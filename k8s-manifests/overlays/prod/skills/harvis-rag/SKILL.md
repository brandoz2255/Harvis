# Harvis RAG Skill

Provides RAG (Retrieval-Augmented Generation) search across the Harvis vector database.

## Tools

### search_rag(query, collection, top_k)
Search the vector database for relevant documents.

**Parameters:**
- query: Search query string
- collection: "code" (code docs) or "docs" (general docs) or "all" (both)
- top_k: Number of results to return (default: 5)

**Returns:** Array of relevant documents with content and source

### list_rag_sources()
List all available document sources in the RAG database with document counts.

## Example

```
search_rag("how to configure kubernetes deployment", "code", 3)
```

This searches the code documentation collection for relevant content about Kubernetes deployments.
