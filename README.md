# AI Diary CLI

Minimal local diary app with JSON storage and Ollama-backed AI features.

## Features

- Daily journal entries saved by date
- Guided reflection prompts
- Mood tracking
- Todo list with add/list/done/delete
- AI reflection for each entry
- AI task extraction from journal text
- Ask-your-diary questions over recent entries
- Daily insight from the last 7 entries

## Requirements

- Python 3.10+
- Ollama running locally
- `llama3.1:8b` installed

## Start Ollama

```bash
ollama serve
ollama list
```

You should see `llama3.1:8b` in the model list.

## Usage

```bash
python3 main.py write
python3 main.py read --date 2026-03-15
python3 main.py history
python3 main.py prompts
python3 main.py prompts --with-answers
python3 main.py mood --days 7
python3 main.py todo add "Finish resume"
python3 main.py todo list --pending-only
python3 main.py todo done 1
python3 main.py todo delete 1
python3 main.py ask "What did I work on last week?"
python3 main.py insight
```

## Data files

Generated automatically in [`data/`](/Users/tanmaybhuskute/Documents/ai-diary/data):

- `entries.json`
- `todos.json`
