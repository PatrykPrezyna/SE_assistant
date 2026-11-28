# ADR 0002: Guided Method Across Multiple Activities

## Status

Accepted

## Context

The SE assistant could take two strategic directions:

1. **Breadth**: Implement guidance across several SE activities (stakeholder analysis, requirements, context diagrams, use cases, design decomposition, verification)
2. **Depth**: Build sophisticated AI capabilities for a single activity (e.g., copilot-level stakeholder analysis with document ingestion, natural language dialogue, automated validation)

## Decision

Pursue **breadth over depth**: implement guided method support across several SE activities with pragmatic AI assistance at each step, rather than copilot-level depth on one activity.

## Rationale

### Thesis Contribution

The master's thesis investigates **how MBSE can improve product development for small and mid-size organizations**. The core research question is about the **methodology** (which activities to do, in what order, with what exit criteria), not AI sophistication.

The Activity Repository pattern (`methodology/product-development.yaml`) is the central contribution. Proving it scales across multiple activities is more valuable than demonstrating advanced AI on one activity.

### Market Positioning

The [architecture review](../../uploads/report_4d53.md) identifies the target market quadrant as **"open + guided method"**, which is currently vacant:

- Capella has method (Arcadia) but is heavyweight
- SysON is open but has no method
- Dalus has AI copilot but is closed
- Flow has AI agents but is commercial

Competing on AI depth would pit SE_assistant against well-funded commercial tools (Dalus copilot, Flow's agent drafts ICDs, SysModeler's document ingestion). **The defensible position is comprehensive methodology coverage**, not AI sophistication.

### Practical Resource Constraints

As a thesis project with one developer and limited timeline:

- Breadth is achievable: each activity needs `check`/`apply` tools (~500-1000 LOC each, following the stakeholder analysis template)
- Depth requires: document parsers, context management, dialogue systems, domain-specific validation—order of magnitude more work

### Validation of the Approach

The existing stakeholder analysis demonstrates the pattern works:
- Clear exit rules
- Deterministic SysML generation from YAML register
- Separation between register (human edits) and model (tool writes)
- Reusable tool structure (`methodology/stakeholder_analysis.py`)

Replicating this pattern 5–6 more times proves the methodology scales. Building a sophisticated AI for stakeholders only would not.

## Consequences

### Positive

- Thesis contribution is clearer: **the Activity Repository is the innovation**, not AI technology
- Achievable scope for thesis timeline
- Differentiates from commercial tools (methodology vs. copilot capabilities)
- Serves the target user: resource-constrained teams need **guidance on what to do**, not necessarily the most advanced AI
- Demonstrates system-level thinking across the SE lifecycle

### Negative

- Each activity's AI assistance remains basic (chat-based prompting, not autonomous generation)
- May feel less impressive in demos compared to copilot-level document ingestion
- Competitive pressure from tools like Dalus and Flow on AI sophistication
- Users may expect more AI magic given "AI assistant" framing

### Implementation Path

Starting with stakeholder analysis (✅ complete), then system context and use cases (see ADRs 0003, 0004). Additional activities will be determined as the methodology evolves, following the pattern: register file → `check` command → `apply` writes SysML.

### Future Evolution

This decision does not preclude depth later. After breadth is achieved:

- Document ingestion for stakeholder/requirement extraction
- Semantic validation beyond syntax
- Dialogue-based model refinement
- Integration with LLM-based requirements authoring

But these are **post-thesis enhancements**, not the research contribution.

## Notes

The term "AI assistant" in the project name refers to conversational guidance through the methodology, not copilot-level autonomous model authoring. This distinction should be clarified in documentation to manage user expectations.
