"""
backfill_embeddings.py — generate embeddings for all existing entries.
Run once after Phase 6 migration: python backfill_embeddings.py

Requires Ollama running: ollama serve
Requires model pulled:   ollama pull nomic-embed-text
"""

from embeddings import backfill_embeddings

if __name__ == "__main__":
    print("Backfilling embeddings (this may take a few minutes)...")
    print("Make sure Ollama is running: ollama serve\n")
    n = backfill_embeddings(verbose=True)
    print(f"\nTotal embedded: {n}")
