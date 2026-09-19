import pytest

from llm.prompts import PromptError, load_prompt
from tests.conftest import write_prompt


def test_loads_latest_version(prompts_tmp):
    write_prompt(prompts_tmp, "demo.task", "v1", "model_tier: fast", "old", "hi")
    fm = "model_tier: writer\nmax_tokens: 900\neffort: medium"
    write_prompt(prompts_tmp, "demo.task", "v2", fm, "sys {{ a }}", "user {{ b }}")
    write_prompt(prompts_tmp, "demo.task", "v10", "model_tier: fast", "newest", "hi")

    spec = load_prompt("demo.task")
    assert spec.version == "v10"  # numeric, not lexicographic

    spec = load_prompt("demo.task", "v2")
    assert (spec.model_tier, spec.max_tokens, spec.effort) == ("writer", 900, "medium")
    assert spec.render({"a": 1, "b": 2}) == ("sys 1", "user 2")
    assert len(spec.hash) == 16


def test_missing_variable_is_an_error(prompts_tmp):
    write_prompt(prompts_tmp, "demo", "v1", "model_tier: fast", "", "hello {{ name }}")
    with pytest.raises(Exception, match="name"):
        load_prompt("demo").render({})


@pytest.mark.parametrize(
    "frontmatter, match",
    [
        ("model_tier: huge", "model_tier"),
        ("model_tier: fast\nmax_tokens: 64000", "streaming"),
        ("model_tier: fast\ntools: [bash]", "unknown tools"),
    ],
)
def test_rejects_bad_frontmatter(prompts_tmp, frontmatter, match):
    write_prompt(prompts_tmp, "demo", "v1", frontmatter, "", "x")
    with pytest.raises(PromptError, match=match):
        load_prompt("demo")


def test_missing_task_and_bad_names(prompts_tmp):
    with pytest.raises(PromptError, match="No prompt files"):
        load_prompt("nope")
    with pytest.raises(PromptError, match="Invalid task name"):
        load_prompt("../etc")


def test_repo_prompts_all_parse(settings):
    """Every prompt file checked into the repo must load."""
    from pathlib import Path

    root = Path(settings.PROMPTS_DIR)
    for path in root.rglob("v*.md"):
        task = ".".join(path.parent.relative_to(root).parts)
        load_prompt(task, path.stem)
