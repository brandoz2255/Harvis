# n8n Workflow Embedding System

This module provides tools for processing n8n workflow JSON files from local repositories, generating embeddings using sentence transformers, and storing them in a pgvector-enabled PostgreSQL database for semantic search and retrieval-augmented generation (RAG).

## Features

- **Local Workflow Processing**: Processes n8n workflows from local git repositories
- **Smart Content Extraction**: Extracts meaningful content from workflow JSON files including:
  - Workflow names, descriptions, and tags
  - Node types and configurations  
  - Workflow connections and flow
  - Parameters and settings
- **Embedding Generation**: Uses HuggingFace sentence transformers for semantic embeddings
- **Vector Database Storage**: Stores embeddings in pgvector-enabled PostgreSQL
- **Semantic Search**: Query workflows by meaning rather than exact keywords
- **Batch Processing**: Efficient processing of thousands of workflows
- **Comprehensive Metadata**: Rich metadata for filtering and analysis

## Quick Start (Docker)

### 1. Build and Test

```bash
cd /home/guruai/compose/aidev/embedding

# Build the Docker image
./run-embedding.sh build

# Test the system
./run-embedding.sh test
```

### 2. Process and Embed Workflows

```bash
# Embed all workflow repositories
./run-embedding.sh embed-all

# Embed only n8n-workflows repository
./run-embedding.sh embed-n8n

# View statistics
./run-embedding.sh stats
```

### 3. Search Workflows

```bash
# Search for email automation workflows
./run-embedding.sh search "email automation with gmail"

# Search for slack integration
./run-embedding.sh search "slack integration"

# Search for webhook triggers
./run-embedding.sh search "webhook trigger automation"
```

### 4. Interactive Development

```bash
# Open shell in container for development
./run-embedding.sh shell

# View logs
./run-embedding.sh logs

# Clean up Docker resources
./run-embedding.sh clean
```

## Architecture

### Components

1. **WorkflowProcessor**: Extracts meaningful content from n8n workflow JSON files
2. **EmbeddingManager**: Handles embedding generation and vector database operations
3. **EmbeddingConfig**: Configuration management with environment variable support

### Data Flow

```
Local Workflow Files → WorkflowProcessor → EmbeddingManager → pgvector Database
                                          ↓
                      Search Query → Semantic Search → Relevant Workflows
```

### Workflow Content Extraction

For each n8n workflow JSON file, the system extracts:

- **Basic Info**: Name, description, tags, workflow ID
- **Nodes**: Node types, parameters, configurations, notes
- **Flow**: Connection patterns and workflow logic
- **Metadata**: File paths, source repository, statistics

### Embedding Strategy

- **Model**: sentence-transformers/all-MiniLM-L6-v2 (384 dimensions)
- **Chunking**: Large workflows split into manageable chunks with overlap
- **Normalization**: Embeddings are normalized for cosine similarity
- **Metadata**: Rich metadata preserved for filtering and analysis

## Configuration

### Default Paths

```python
# Workflow directories (from git clones)
n8n_workflows_path = "/home/guruai/compose/rag-info/n8n-workflows/workflows" 
test_workflows_path = "/home/guruai/compose/rag-info/test-workflows"

# Database connection (Docker network)
database_url = "postgresql://pguser:pgpassword@pgsql:5432/database"
collection_name = "n8n_workflows"
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VECTOR_DATABASE_URL` | `postgresql://pguser:pgpassword@pgsql:5432/database` | PostgreSQL connection URL |
| `VECTOR_COLLECTION_NAME` | `n8n_workflows` | Collection name in vector database |
| `N8N_WORKFLOWS_PATH` | `/home/guruai/compose/rag-info/n8n-workflows/workflows` | Path to n8n-workflows repository |
| `TEST_WORKFLOWS_PATH` | `/home/guruai/compose/rag-info/test-workflows` | Path to test-workflows repository |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | HuggingFace model for embeddings |
| `CHUNK_SIZE` | `1000` | Maximum characters per document chunk |
| `MAX_WORKFLOWS` | None | Limit number of workflows to process |

## Usage Examples

### Python API

```python
from embedding import EmbeddingConfig, EmbeddingManager

# Initialize with default config
config = EmbeddingConfig.from_env()
manager = EmbeddingManager(config)

# Setup database and embeddings
manager.setup_database()
manager.initialize_vector_store()

# Process workflows from directory
result = manager.add_workflows_from_directory(
    "/path/to/workflows", 
    source_repo="my_workflows"
)

# Search for similar workflows
results = manager.search_workflows("email automation", k=5)
for doc in results:
    print(f"Workflow: {doc.metadata['name']}")
    print(f"Description: {doc.metadata['description']}")
```

### Command Line Interface

```bash
# Available commands
python main.py --help

# Embed workflows
python main.py embed --all                    # All repositories
python main.py embed --repo n8n_workflows     # Specific repository

# Search workflows
python main.py search "email automation"      # Basic search
python main.py search "webhook triggers" -k 10  # Top 10 results

# Collection management
python main.py stats                          # Show statistics
python main.py delete --confirm               # Delete collection
python main.py test                           # Test system
```

## Database Schema

The system creates a pgvector table with the following structure:

- **embedding**: Vector embedding (384 dimensions)
- **document**: Original workflow content
- **cmetadata**: JSONB metadata including:
  - `filename`: Original JSON filename
  - `workflow_id`: n8n workflow ID
  - `name`: Workflow name
  - `description`: Workflow description
  - `tags`: Workflow tags
  - `node_types`: List of node types used
  - `trigger_types`: List of trigger types
  - `source_repo`: Source repository name
  - `node_count`: Number of nodes in workflow

## Troubleshooting

### Common Issues

1. **Database Connection**: Ensure pgvector extension is installed and database is accessible
2. **Memory Issues**: Reduce batch size or use smaller embedding model
3. **File Access**: Check file paths and permissions for workflow directories

### Debug Mode

```bash
# Enable debug logging
export PYTHONPATH=/home/guruai/compose/aidev/embedding
python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from main import setup_embedding_manager
manager = setup_embedding_manager()
print(manager.test_embedding_pipeline())
"
```

### Validation

```bash
# Test workflow processing
python main.py test

# Check workflow statistics
python -c "
from workflow_processor import WorkflowProcessor
processor = WorkflowProcessor()
stats = processor.get_workflow_statistics('/home/guruai/compose/rag-info/n8n-workflows/workflows')
print(stats)
"
```

## Integration with Jarvis AI

This embedding system is designed to integrate with the Jarvis AI system's RAG pipeline:

1. **Workflow Knowledge Base**: Provides semantic search over thousands of n8n workflows
2. **Automation Suggestions**: AI can suggest relevant workflows based on user queries
3. **Code Generation**: Use similar workflows as context for generating new automations
4. **Learning from Examples**: AI learns patterns from real-world workflow implementations

### Integration Points

- **Research Module**: Use for workflow-specific queries
- **n8n Integration**: Enhance automation suggestions with similar workflow examples
- **Chat Interface**: Provide workflow recommendations in conversations
- **Voice Commands**: "Show me workflows for email automation"

## Performance

### Typical Performance Metrics

- **Processing Speed**: ~100-200 workflows per minute
- **Embedding Generation**: ~50ms per workflow
- **Search Speed**: <100ms for semantic queries
- **Memory Usage**: ~2GB for full n8n-workflows repository

### Optimization Tips

1. **Batch Processing**: Use larger batch sizes for better throughput
2. **GPU Acceleration**: Set device='cuda' for faster embedding generation
3. **Chunking Strategy**: Adjust chunk size based on average workflow complexity
4. **Indexing**: pgvector provides efficient similarity search at scale