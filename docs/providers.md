# Asking questions about an indexed repository

Run `graph-n4j repos` to find your repository ID. Choose one provider for questions.

| Provider flag | Credential | Model setting |
| --- | --- | --- |
| groq | GROQ_API_KEY | GROQ_MODEL |
| openai | OPENAI_API_KEY | OPENAI_MODEL |
| anthropic | ANTHROPIC_API_KEY | ANTHROPIC_MODEL |
| gemini | GEMINI_API_KEY | GEMINI_MODEL |
| ollama | Local server, no key | OLLAMA_MODEL |

For example, in PowerShell, set the selected provider's key and ask about a repository you indexed.

```powershell
$env:OPENAI_API_KEY = "<your key>"
graph-n4j ask "Which functions call the parser?" --provider openai --repo-id my-project
```

To use a local model, start Ollama, then run:

```powershell
ollama pull qwen2.5-coder
graph-n4j --model qwen2.5-coder ask "Where does indexing start?" --provider ollama --repo-id my-project
```

Set `OLLAMA_HOST` if your server uses an address other than `http://localhost:11434`.
Set `LLM_PROVIDER` to reuse a provider across commands. If the provider rejects the model, pass a model available to your account with `--model` before `ask`.

### Choose a chat model in PowerShell

For Groq, set `GROQ_API_KEY` first. The following command uses the key from your environment or project's `.env` file to list model IDs. Pick a text chat model your account can use.

```powershell
py -c "from dotenv import find_dotenv, load_dotenv; from groq import Groq; load_dotenv(find_dotenv(usecwd=True), override=True, encoding='utf-8-sig'); print('\n'.join(sorted(m.id for m in Groq().models.list().data)))"
$model = Read-Host "Enter a chat model ID from the list"
graph-n4j --model "$model" ask "Which functions does cJSON_Parse call directly?" --repo-id "DaveGamble/cJSON" --provider groq
```

Use the repository ID shown by `graph-n4j repos`. Place `--model` before `ask`. You can switch models and reuse the same index.

If you get HTTP 404, check the exact model ID and any custom provider endpoint. A database hit counts a query sent to Neo4j, even if it returns zero records. If final answer generation returns empty text, graph-n4j retries with a shorter prompt. If that also returns empty, try a narrower question or another chat model. For diagnostic details, put `--verbose` before `ask`.
