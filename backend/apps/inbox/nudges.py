"""Regenerate nudges: presets plus a custom instruction."""

NUDGES = {
    "shorter": "Make it noticeably shorter and tighter. Keep only what matters most.",
    "more_casual": "Make it more casual and conversational, like a knowledgeable peer, not a brand.",
    "no_mention": "Don't mention {project_name} at all. Be purely helpful.",
    "custom": "",
}


def nudge_instruction(nudge: str, instruction: str, project_name: str) -> str:
    """The text given to the model for a regeneration."""
    parts = []
    if nudge and nudge != "custom":
        parts.append(NUDGES[nudge].format(project_name=project_name))
    if instruction.strip():
        parts.append(instruction.strip())
    return " ".join(parts)
