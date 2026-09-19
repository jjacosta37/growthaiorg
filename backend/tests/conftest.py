import pytest

from llm import client as llm_client


@pytest.fixture
def fake_anthropic():
    """Install a FakeAnthropic: `fake = fake_anthropic(msg1, msg2, ...)`."""
    from tests.fakes import FakeAnthropic

    installed = []

    def install(*responses, responder=None):
        fake = FakeAnthropic(*responses, responder=responder)
        llm_client.set_client(fake)
        installed.append(fake)
        return fake

    yield install
    llm_client.set_client(None)


@pytest.fixture
def prompts_tmp(tmp_path, settings):
    """Point PROMPTS_DIR at a temp dir holding a copy of the guardrails file."""
    from pathlib import Path

    from llm.prompts import guardrails_template

    (tmp_path / "_system").mkdir()
    src = Path(settings.BASE_DIR) / "prompts" / "_system" / "guardrails.md"
    (tmp_path / "_system" / "guardrails.md").write_text(src.read_text())
    settings.PROMPTS_DIR = tmp_path
    guardrails_template.cache_clear()
    yield tmp_path
    guardrails_template.cache_clear()


def write_prompt(root, task, version, frontmatter, system, user):
    d = root.joinpath(*task.split("."))
    d.mkdir(parents=True, exist_ok=True)
    body = f"---\n{frontmatter.strip()}\n---\n=== system ===\n{system}\n=== user ===\n{user}\n"
    (d / f"{version}.md").write_text(body)
