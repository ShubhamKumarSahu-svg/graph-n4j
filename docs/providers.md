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
