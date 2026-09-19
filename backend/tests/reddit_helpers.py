import json
from datetime import UTC, datetime, timedelta

from apps.agents.models import AgentConfig
from apps.core.models import Project
from providers.reddit import FakeRedditSource, RedditPostData
from tests.fakes import message, schema_title

# Score by a marker in the title: "[90 yes]" → score 90, reply_worthwhile True.
SCORES = {"hi-yes": (90, True), "hi-no": (85, False), "mid": (60, True), "lo": (10, False)}


def post(pid, marker, sub="Bogleheads"):
    return RedditPostData(
        reddit_id=pid, subreddit=sub, title=f"{marker}: question {pid}", body=f"Body of {pid}",
        url=f"https://www.reddit.com/r/{sub}/comments/{pid}/q/", author="u", upvotes=5, num_comments=2,
        posted_at=datetime.now(UTC) - timedelta(hours=2),
    )


def reddit_responder(comment_body="Rebalancing once a year is common. Here's how to think about it...",
                     lint_flags=None):
    def respond(params):
        title = schema_title(params)
        user = params["messages"][0]["content"]
        if title == "RelevanceScore":
            marker = next(m for m in SCORES if f"{m}:" in user)
            score, worth = SCORES[marker]
            return message(json.dumps({"score": score, "reason": f"because {marker}", "reply_worthwhile": worth}))
        if title == "RedditComment":
            return message(json.dumps({"body": comment_body, "mentions_product": "Acme" in comment_body}))
        if title == "ComplianceLint":
            return message(json.dumps({"flags": lint_flags or []}))
        raise AssertionError(f"unexpected request {title}")

    return respond


def configure(project=None, **overrides):
    project = project or Project.current()
    if project.name == Project.DEFAULT_NAME:
        project.name = "Acme"
        project.save()
    cfg = AgentConfig.for_project(project, "reddit")
    cfg.config = {"subreddits": ["Bogleheads"], "keywords": ["rebalancing"], "relevance_threshold": 70,
                  **overrides}
    cfg.save()
    return cfg


def install_source(monkeypatch, posts):
    source = FakeRedditSource(posts)
    monkeypatch.setattr("apps.reddit.pipeline.get_source", lambda: source)
    return source
