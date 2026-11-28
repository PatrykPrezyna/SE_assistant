"""Methodology agent: the greeting, the system prompt, and the tool loop."""

import json
from pathlib import Path

from .provider import complete
from .tools import activity_brief, folder_context, run_tool, stakeholder_module

GREETING = (
    "Hi, I am your SE assistant. What kind of project are you working on? "
    "Do you already have artefacts or documents you want to share, or are we "
    "at the very beginning of the product development process?"
)

MAX_TOOL_ROUNDS = 4

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "stakeholder_check",
            "description": (
                "Read the stakeholder register and report which exit rules "
                "are still open. Does not write files."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stakeholder_apply",
            "description": (
                "Write the confirmed stakeholder register and generate the "
                "SysML model. Call this only after the team has confirmed "
                "the list. Omit the arguments to regenerate from the register "
                "already saved in the model folder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "system": {
                        "type": "string",
                        "description": "UpperCamelCase name of the system of interest.",
                    },
                    "stakeholders": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "category": {
                                    "type": "string",
                                    "enum": ["customer", "internal", "regulatory"],
                                },
                                "description": {"type": "string"},
                                "needs": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "name": {"type": "string"},
                                            "text": {"type": "string"},
                                        },
                                        "required": ["id", "name", "text"],
                                    },
                                },
                            },
                            "required": ["name", "category", "needs"],
                        },
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_model_element",
            "description": (
                "Add a new model element to the SysML model following existing conventions. "
                "IMPORTANT: For people (Nurse, Patient, Doctor, etc.), use element_type='stakeholder' "
                "which creates a 'part def' (not 'actor def') - this follows the model's pattern where "
                "stakeholders are part definitions that get used as actors/subjects in use cases. "
                "Ask clarifying questions first if details are missing (e.g., what role does this person play? "
                "which use cases involve them?). Only call this after you have enough information."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "element_type": {
                        "type": "string",
                        "enum": ["stakeholder", "part", "requirement", "use_case"],
                        "description": (
                            "Type of element: 'stakeholder' for people (Nurse, Patient, etc.), "
                            "'part' for equipment/components, 'requirement' for requirements, "
                            "'use_case' for use cases."
                        ),
                    },
                    "name": {
                        "type": "string",
                        "description": "UpperCamelCase name of the element (e.g., Nurse, FluidPump, REQ-123).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Description of the element's purpose, role, or requirement text.",
                    },
                },
                "required": ["element_type", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_activity",
            "description": (
                "Change a use-case activity diagram: lanes, steps, successions, "
                "decisions, forks, and item flows. Writes standard SysML v2. "
                "Call it only when the user has named the use case and every "
                "detail the operation needs. If something is missing, ask one "
                "question and do not call the tool in that turn."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": [
                            "add-lane", "add-action", "connect", "add-decision",
                            "add-fork", "add-flow", "rename", "delete",
                            "add-subactivity", "add-activity",
                        ],
                    },
                    "owner": {
                        "type": "string",
                        "description": "Use case name, or its id from the activity list.",
                    },
                    "name": {"type": "string"},
                    "newName": {"type": "string"},
                    "lane": {
                        "type": "string",
                        "description": "Stakeholder who performs the step, such as Nurse.",
                    },
                    "after": {
                        "type": "string",
                        "description": "Step this one follows. Use start for the first step.",
                    },
                    "splice": {
                        "type": "boolean",
                        "description": "Insert between that step and whatever follows it.",
                    },
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "guard": {
                        "type": "string",
                        "description": "Condition on the yes path, one word such as stable.",
                    },
                    "yes": {"type": "string", "description": "Step when the guard is true."},
                    "no": {"type": "string", "description": "Step otherwise."},
                    "yesLane": {"type": "string"},
                    "noLane": {"type": "string"},
                    "item": {"type": "string"},
                    "actors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Stakeholders for a new activity.",
                    },
                    "branches": {
                        "type": "array",
                        "description": "Parallel steps after a fork. At least two.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "lane": {"type": "string"},
                            },
                            "required": ["name", "lane"],
                        },
                    },
                },
                "required": ["op"],
            },
        },
    },
]

_NOTES = {
    "stakeholder_check": "Checked the stakeholder register.",
    "stakeholder_apply": "Updated the model from the stakeholder register.",
    "add_model_element": "Added a new element to the model.",
    "edit_activity": "Updated the activity in the SysML model.",
}


def opening_text(model_folder):
    """The first message. An open or finished activity replaces the greeting."""
    path = Path(model_folder) / "process" / "state.yaml"
    if not path.is_file():
        return GREETING
    module = stakeholder_module()
    try:
        state = module.load_yaml_file(path)
    except module.YamlError:
        return GREETING
    if not isinstance(state, dict):
        return GREETING
    status = state.get("status")
    activity = (state.get("activity") or "the current activity").replace("-", " ")
    if status == "open":
        lines = [f"{activity} is still open."]
        for rule in state.get("exit") or []:
            if isinstance(rule, dict) and not rule.get("met"):
                if rule.get("text"):
                    lines.append(rule["text"])
                for detail in rule.get("detail") or []:
                    lines.append(str(detail))
        lines.append("We can continue from here.")
        return "\n".join(lines)
    if status == "done":
        return (
            f"{activity} is finished for this folder. "
            "Tell me if you want to review the stakeholders or change them."
        )
    return GREETING


def system_message(settings):
    methodology = Path(settings.methodology).read_text(encoding="utf-8")
    state_path = Path(settings.model_folder) / "process" / "state.yaml"
    if state_path.is_file():
        state = state_path.read_text(encoding="utf-8")[:4000]
    else:
        state = "(no process state yet)"
    documents = folder_context(Path(settings.model_folder))
    activities = activity_brief(Path(settings.model_folder))
    content = f"""You are the SE assistant for a small engineering team.
Guide them through the product-development methodology. Ask one question at a time.
The opening message is already in the transcript. Do not repeat it.

Methodology file:
{methodology}

Process state:
{state}

Files in the model folder (quote a text file when you use it; PDFs are names only):
{documents}

Activities already in the model:
{activities}

Rules:
- Do not invent stakeholders, needs, or categories the team did not state.
- Categories are only customer, internal, or regulatory.
- System, stakeholder, and need names are UpperCamelCase. Need ids look like NEED-1.
- Every stakeholder needs at least one user need before the activity is done.
- Do not write SysML yourself.
- When the folder already has .sysml files and the team asks to add a person or
  another element, use add_model_element. Do not call stakeholder_apply for that,
  and do not start a new stakeholder register.
- For a person, element_type is "stakeholder". That writes a part def (not an
  actor def) into the existing Context file, in the same shape as the people
  already there.
- Ask one or two short clarifying questions before the first add_model_element
  if the team has not yet said what the person does. Do not call the tool in
  that same turn. After they answer, call the tool. The description must use
  only their words.
- Call stakeholder_apply only after the team has confirmed the list, and only
  when they are building that register rather than editing a model that
  already has .sysml files.
- Use stakeholder_check to see which exit rules are still open.
- After a successful apply or add_model_element, tell the team the diagram
  updates on its own. The explorer is at {settings.explorer_url}
- A process step, lane, decision, fork, or item flow is an activity edit.
  Use edit_activity. Do not paste SysML in the chat.
- If the use case, who does the step, where it goes, or either outcome of a
  decision was not said, ask one short question and do not call edit_activity
  in that turn. Do not invent a step, a person, or a second outcome.
- A complete request is enough. "Add a decision after Assess Patient: if
  stable, administer anesthesia, else stabilise patient" names the step, the
  guard, and both outcomes. Call edit_activity. Put both outcomes in the same
  lane as the step they follow unless the user named someone else.
- op add-decision needs owner, after, guard, yes, no, yesLane, and noLane.
  The guard is one identifier such as stable, not a sentence.
- op add-action needs owner, name, lane, and after. Set splice to true when
  the new step should sit between that step and whatever already follows it.
- op add-fork needs owner, after, and branches (at least two, each with a
  name and a lane). The join is added for you.
- op add-lane needs owner and name (the stakeholder, such as Nurse).
- op add-flow needs owner, source, target, and optionally item.
"""
    return {"role": "system", "content": content}


def run_turn(messages, settings, complete_fn=None):
    """Append the assistant's reply to `messages`. Returns (messages, notes).

    `messages` contains only user and assistant turns. Tool traffic stays
    inside this call.
    """
    if complete_fn is None:
        def complete_fn(msgs, tools):
            return complete(msgs, settings, tools)

    working = [system_message(settings)] + [
        {"role": item["role"], "content": item["content"]} for item in messages
    ]
    notes = []
    for _ in range(MAX_TOOL_ROUNDS):
        result = complete_fn(working, TOOLS)
        calls = result.get("tool_calls") or []
        if not calls:
            text = (result.get("content") or "").strip()
            if not text:
                text = "I could not produce a reply. Please try again."
            return messages + [{"role": "assistant", "content": text}], notes
        working.append({
            "role": "assistant",
            "content": result.get("content") or "",
            "tool_calls": [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["arguments"]),
                    },
                }
                for call in calls
            ],
        })
        for call in calls:
            output = run_tool(call["name"], call["arguments"], settings)
            if output.startswith("Not written"):
                notes.append("Need a detail before changing the diagram.")
            else:
                notes.append(_NOTES.get(call["name"], f"Rejected {call['name']}."))
            working.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": output,
            })
    return messages + [{
        "role": "assistant",
        "content": (
            "I stopped after several tool calls without a final answer. "
            "Tell me how you want to continue."
        ),
    }], notes
