1. Start with a Full Inventory
Give Claude your entire project tree and ask it to map dependencies before touching anything. A command like find . -type f | head -200 piped into the conversation lets Claude understand what you're working with before suggesting changes.
2. Refactor in Layers, Not All at Once
Break restructuring into phases:
Phase 1 — Analysis. Have Claude read your codebase and identify coupling, circular dependencies, dead code, and naming inconsistencies.
Phase 2 — Plan. Ask Claude to propose a target structure with clear reasoning for each move (e.g., "move all DB logic into storage/ because three modules import the same query helpers").
Phase 3 — Execute. Let Claude generate the actual file moves, import rewrites, and config updates one module at a time, testing between each batch.
3. Use Claude as a "Second Brain" for Naming Conventions
Paste your current folder/file names and ask Claude to propose a consistent naming scheme. Inconsistent naming (utils.py, helpers.js, common/, shared/) is often the root cause of messy structure.
4. Extract Before You Reorganize
Before moving files around, have Claude identify code that should be extracted into its own module first. Moving tangled code just creates tangled code in a new folder. Ask Claude to find functions that are called from 3+ files — those are extraction candidates.
5. Generate Migration Scripts
Rather than manually renaming and moving, ask Claude to write a shell script or Python script that performs all the moves, updates all imports, and can be reverted. This makes restructuring reproducible and reviewable in a PR.
6. Leverage Claude's Context Window for Cross-File Analysis
Feed Claude groups of related files simultaneously so it can spot duplication across files, suggest shared abstractions, and identify where interfaces should exist. This is something that's hard to do manually across a large codebase.
7. Test Coverage as a Safety Net
Before any restructuring, ask Claude to generate a lightweight test suite that captures current behavior. After restructuring, run the same tests. Claude can write these quickly even for legacy code with no existing tests.
8. Document the "Why" as You Go
Ask Claude to generate a short ADR (Architecture Decision Record) for each structural change explaining what moved, why, and what the tradeoffs were. Future contributors will thank you.
The key principle across all of these: treat restructuring as a conversation, not a single prompt. Give Claude context incrementally, validate each step, and let it build on its own previous analysis. Claude works best when it can reason about your specific codebase rather than applying generic patterns.