# LLM Graph Builder AI Agent Guidelines

This document guides AI coding agents working in the LLM Graph Builder codebase. Focus on these key aspects when making changes or additions.

## Architecture Overview

This is a FastAPI-based service that builds knowledge graphs from various document sources using LLMs. Key components:

- `src/main.py`: Core orchestration for document processing and graph building
- `src/agent/`: Intelligent routing system with classifier, mapper, and evaluator
- `src/document_sources/`: Source-specific document loaders (S3, GCS, local, Wikipedia, etc.)
- `src/services/`: Core business logic and graph operations
- `src/shared/`: Common utilities, constants, and error handling


### Data Flow
1. Documents → Chunks → Entity Extraction → Graph Construction
2. User Queries → Intent Classification → Graph Queries → Response Generation

## Development Workflow

### Environment Setup
```bash
python -m venv envGenai
source envGenai/bin/activate  # or envGenai\Scripts\activate on Windows
pip install -r requirements.txt
```

### Running the Service
1. Set required environment variables (see example.env)
2. Local development: `uvicorn score:app --reload`
3. Docker: `docker build -t llm-graph-builder . && docker run -p 8000:8000 llm-graph-builder`

### Testing
- Integration tests in `test_integrationqa.py`
- Performance tests in `Performance_test.py`
- Run tests with: `python -m pytest`

## Key Patterns

### Error Handling
Use `LLMGraphBuilderException` for domain-specific errors:
```python
from src.shared.llm_graph_builder_exception import LLMGraphBuilderException
raise LLMGraphBuilderException('Descriptive error message')
```

### Configuration
- All constants in `src/shared/constants.py`
- Environment variables loaded via dotenv in main.py
- Neo4j connection params required for graph operations

### Documentation
- API docs at `/docs` (Swagger) or `/redoc`
- Key integration points documented in `lesson_notes/`

## Integration Points

### External Services
- Neo4j Graph Database
- Cloud Storage (S3/GCS)
- LLM Services (OpenAI, VertexAI)
- Document Processing Services

### Cross-Component Communication
- Agent system uses FastAPI endpoints defined in routers/
- Graph operations coordinated through graphDB_dataAccess.py
- Document processing pipeline events logged via standard logging

## Questions or Issues?
Contact: christopher.crosbie@neo4j.com or michael.hunger@neo4j.com