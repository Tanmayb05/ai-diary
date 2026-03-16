# AI Diary CLI

Minimal local diary app with JSON storage and Ollama-backed AI features.

## Requirements

- Python 3.14.3 (developed and tested on this version; 3.10+ should work)
- [Ollama](https://ollama.com) running locally with `llama3.1:8b` installed

## Setup

**1. Clone the repo**

```bash
git clone <repo-url>
cd ai-diary
```

**2. Create and activate a virtual environment**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**3. Install dependencies**

This project uses only the Python standard library — no pip install needed.

**4. Start Ollama**

```bash
ollama serve
ollama pull llama3.1:8b
```

Verify the model is available:

```bash
ollama list
```

You should see `llama3.1:8b` in the list.

**5. Run the app**

```bash
python main.py
```

This launches the interactive chat interface. Type `help` to see available commands.

## Usage

### Chat interface (default)

```bash
python main.py
python main.py chat-ui
```

Natural language examples you can type in the chat:

```
i want to write
i want to write for Jan 29 2026
read today's entry
read march 2023
read only 3 entries from march 2023
show my todos
add todo finish thesis draft
mark task 2 done
delete task 3
help
exit
```

### CLI commands

**Writing entries**

```bash
python main.py write                        # write for today
python main.py write --date 2026-01-29      # write for a specific date
python main.py write --skip-ai              # skip AI reflection
```

**Reading entries**

```bash
python main.py read                         # read today's entry
python main.py read --date 2026-01-29
python main.py history                      # list recent entry dates
python main.py history --limit 20
```

**AI features**

```bash
python main.py ask "What did I work on last week?"
python main.py insight                      # insight from last 7 entries
python main.py weekly-review
python main.py weekly-review --days 14
python main.py analyze                      # re-analyze today's entry
python main.py analyze --date 2026-01-29 --save
python main.py coach                        # coaching guidance for today
python main.py plan-next                    # next-day plan from today's entry
python main.py chat "How have I been feeling lately?"
python main.py rewrite                      # rewrite today's entry (clean mode)
python main.py rewrite --mode bullets
```

**Mood & trends**

```bash
python main.py mood                         # mood trend for last 7 days
python main.py mood --days 30
python main.py trends                       # sentiment, stress, habit trends
python main.py trends --days 60
```

**Goals & reflection**

```bash
python main.py goals
python main.py goals --recent 14
python main.py plan-tomorrow
python main.py prompts
python main.py prompts --with-answers
python main.py tags
python main.py tags --recent
python main.py tags --date 2026-01-29
```

**Surfacing past entries**

```bash
python main.py similar                      # entries similar to today
python main.py similar --date 2026-01-29
python main.py resurface --query "thesis"
python main.py resurface --similar-to 2026-01-29
python main.py contradictions               # repeated priorities without follow-through
python main.py contradictions --days 60
```

**Todos**

```bash
python main.py todo add "Finish resume"
python main.py todo list
python main.py todo list --pending-only
python main.py todo done 1
python main.py todo delete 2
```

**Debug**

```bash
python main.py timing                       # LLM call timing stats
python main.py timing --last 20
```

## Data files

Auto-generated in `data/`:

- `entries.json` — all diary entries
- `todos.json` — todo list
- `llm_timing.jsonl` — LLM call timing log

## Model

The default model is `llama3.1:8b`. Override with `--model`:

```bash
python main.py --model llama3.2:3b write
```
