# Memory & Context Management

## Session Start Protocol
1. Read CLAUDE.md (automatic)
2. Check docs/decisions/ if exists — understand past architectural choices
3. Check git log --oneline -10 — see recent work
4. Read latest .claude/handoff-*.md if exists — resume from last session
5. Tell user: "ბოლოს [X]-ზე ვმუშაობდით. გავაგრძელოთ?"

## Session End Protocol
Before ending (or when context is getting full):
1. Create .claude/handoff-YYYY-MM-DD.md with:
   - What was accomplished this session
   - Current project state
   - Next steps (numbered list)
   - Important decisions made
   - Unresolved issues
2. If architectural decisions made → save to docs/decisions/
3. Suggest: "გინდა checkpoint შევქმნა სანამ ვჩერდებით?"

## Architectural Decision Records (ADR)
Save to docs/decisions/NNN-title.md when:
- Choosing database, framework, or major library
- Deciding between code vs n8n
- Changing project architecture
- Security-related decisions
- Deployment strategy choices

ADR format:
```markdown
# NNN: Decision Title
## Date: YYYY-MM-DD
## Status: accepted
## Context: What problem were we solving?
## Decision: What did we decide?
## Reasoning: Why this choice?
## Consequences: Trade-offs?
```

## Context Window Management
- At 20+ exchanges: suggest /compact
- At 60% context usage: compact BEFORE reaching limit
- When compacting: preserve current task state, recent decisions, active bugs
- When compacting: discard early brainstorming, failed attempts already reverted

## What to Never Forget (Auto-Loaded via CLAUDE.md)
- Project purpose
- Tech stack
- User communication preferences
- Security rules
- Testing requirements

## Handoff Note Format
```markdown
# Session Handoff - YYYY-MM-DD

## Accomplished
- [List of things completed]

## Current State
- App status: [working / has issues / in progress]
- Branch: [current git branch]
- Last commit: [summary]

## Next Steps
1. [Most important next task]
2. [Second priority]
3. [Third priority]

## Important Context
- [Non-obvious information for next session]
- [Decisions made and why]
- [Known issues]
```
