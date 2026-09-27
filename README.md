# graph-n4j

Bridge LLM agents with code repositories via Neo4j graph databases. Based on the CodexGraph NAACL 2025 paper.

`graph-n4j` builds a highly structured code graph (AST, inheritance, composition, calls) into Neo4j and uses a dual-agent LLM pipeline to let you chat with your entire codebase with perfect accuracy and drastically reduced token consumption.

## Prerequisites

To use `graph-n4j`, you need two things running/available:

1. **Neo4j Database**: You need a running Neo4j instance. 
   - *Quickest way (Docker)*: `docker run -d -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:latest`
   - *Cloud option*: You can also use a free Neo4j AuraDB instance.

2. **Groq API Key**: You need an API key from [Groq](https://console.groq.com/) to power the LLM agents.

## Installation

```bash
pip install graph-n4j
```

## Setup & Configuration

Configure the package using environment variables. You can set them in your terminal or create a `.env` file in the directory where you run your commands:

```env
# Required: Groq API Key
GROQ_API_KEY=gsk_your_api_key_here

# Optional: Set the model (Defaults to llama-3.3-70b-versatile)
GROQ_MODEL=llama-3.3-70b-versatile
# B5 optimization: Use a cheaper/faster model for translation to save costs
GROQ_MODEL_TRANSLATION=llama-3.1-8b-instant

# Neo4j connection (These are the defaults)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

## CLI Usage

The package installs a handy command-line tool `graph-n4j`:

```bash
# 1. Index a local Python repository
graph-n4j index /path/to/your/python/repo

# OR Clone and index a GitHub repository directly
graph-n4j index-github pallets/click

# 2. Chat with your indexed codebase!
graph-n4j ask "How does the command line parsing work in this repo?"

# Check graph statistics
graph-n4j stats

# List all indexed repos
graph-n4j repos
```

## Python API Usage

You can also use it programmatically in your own apps:

```python
import os
from graph_n4j import GraphN4J

# Set up environment or let it load from .env
os.environ["GROQ_API_KEY"] = "gsk_your_api_key_here"

# Initialize the API
g = GraphN4J.from_env()

# Index a repository
g.index("./my-project")

# Chat with the codebase
result = g.ask("What does the UserManager class do and what does it inherit from?")
print(result.answer)
```

## Features
- **B1-B7 Token Efficiency**: Implements all 7 token optimizations from the CodexGraph paper (Skeleton caching, Context pruning, Early-stopping, etc.)
- **Multi-repo support**: Seamlessly index and query across multiple isolated repositories.
- **AST Parsing**: Highly accurate edge extraction for classes, functions, globals, fields, and inheritance.
