# SysTemp

Reproduction of the SysTemp pipeline: a multi-agent system that turns
natural-language requirements into valid SysML v2 code.

Credit to the original SysTemp approach/repo — this is a reproduction done
as part of the literature review, run through a Jinja2-based skeleton
generator instead of hand-written templates. See the root
[README](../../README.md) for environment setup (venv, `requirements.txt`,
`OPENAI_API_KEY`) and for how to build/wire in the deterministic SysML v2
parser used by `ParserAgent`.

**My contributions on top of the original approach:** clearer docs, a
runnable end-to-end example, and rough cost estimation for the LLM calls.

## Pipeline

1. **Specification Agent** (`spec.py`) — extracts a structured requirements
   dictionary from natural language.
2. **Template Agent** (`template.py`) — generates a SysML v2 skeleton from
   that dictionary using Jinja2 templates.
3. **Writer Agent** (`writer.py`) — completes and refines the skeleton into
   a full model, incorporating parser feedback across iterations.
4. **Parser Agent** (`parser.py`) — validates the generated SysML v2 syntax
   (via the OMG Pilot Implementation jar, see the root README) and feeds
   errors back to the Writer Agent.

`orchestration.py` (`SysTempOrchestrator`) wires these four agents into a
loop: generate → validate → feed errors back to the writer → repeat, up to
`max_iterations` times or until the parser reports no errors.

`evaluation.py` (`SysTempEvaluator`) runs the ablation comparison referenced
in the lit review: pipeline **with** the Template Agent vs. going straight
from spec to Writer Agent **without** a skeleton, comparing syntax error
counts between the two.

## Running

Imports in `orchestration.py` and `evaluation.py` are package-qualified
(`from Lit_review_AI_for_SE.SysTemp.spec import ...`), so run those from the
**repository root**:

```bash
python -m Lit_review_AI_for_SE.SysTemp.orchestration
```

The `test_*.py` scripts use local imports instead (`from parser import
ParserAgent`) and are meant to be run **from this folder**:

```bash
cd Lit_review_AI_for_SE/SysTemp
python test_parser_agent.py
python test_template_agent.py
python test_writer_agent.py
python test_orchestrator.py
python test_evaluator.py
python test_spec_agent.py
```

## Notes / known gaps

- `ParserAgent(java_parser_path="./parser.jar")` expects a jar that isn't
  checked into this repo — see the "Deterministic SysML v2 parser" section
  of the root README for how to build one from the OMG Pilot Implementation
  and why the current CLI invocation in `_validate_with_java_parser` needs a
  small adjustment to work with that jar's actual entry point.
- `orchestration.py`'s `__main__` block hardcodes a placeholder API key
  (`"your-api-key"`) — pass a real one via `OPENAI_API_KEY` instead of
  editing that line.
