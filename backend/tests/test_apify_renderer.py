from decimal import Decimal
from types import SimpleNamespace

from providers.crawl import ApifyRenderer


class FakeApify:
    def __init__(self, run, items=(), error=None):
        self.run, self.items, self.error = run, list(items), error
        self.calls, self.loggers = [], []

    def actor(self, actor_id):
        fake = self

        class Actor:
            def call(self, run_input, run_timeout, logger):
                fake.calls.append((actor_id, run_input))
                fake.loggers.append(logger)
                if fake.error:
                    raise fake.error
                return fake.run

        return Actor()

    def dataset(self, dataset_id):
        items = self.items

        class Dataset:
            def iterate_items(self):
                return iter(items)

        return Dataset()


def run(status="SUCCEEDED", cost=0.031):
    return SimpleNamespace(id="apify_run_1", status=status, usage_total_usd=cost, default_dataset_id="ds1")


def test_render_maps_items_and_cost():
    client = FakeApify(run(), [
        {"url": "https://acme.example/pricing", "markdown": "# Pricing\nOne plan.", "text": "Pricing One plan.",
         "metadata": {"title": "Pricing | OW"}},
        {"url": "https://acme.example/", "markdown": "", "text": "Home text", "metadata": {}},
        {"url": "https://acme.example/empty", "markdown": "", "text": ""},
    ])
    r = ApifyRenderer("tok", client=client).render(["https://acme.example/pricing", "https://acme.example/"])

    actor_id, run_input = client.calls[0]
    assert actor_id == "apify/website-content-crawler"
    assert run_input["maxCrawlDepth"] == 0 and run_input["maxCrawlPages"] == 2
    assert run_input["startUrls"] == [{"url": "https://acme.example/pricing"}, {"url": "https://acme.example/"}]
    assert run_input["crawlerType"].startswith("playwright")
    assert client.loggers == [None]  # the actor's own log must not reach ours (or Sentry)
    assert [(p.url, p.title, p.text) for p in r.pages] == [
        ("https://acme.example/pricing", "Pricing | OW", "# Pricing\nOne plan."),  # markdown preferred
        ("https://acme.example/", "", "Home text"),
    ]
    assert (r.external_run_id, r.cost_usd, r.error) == ("apify_run_1", Decimal("0.031"), "")


def test_render_errors_degrade_gracefully():
    r = ApifyRenderer("tok", client=FakeApify(None, error=RuntimeError("401 bad token"))).render(["https://a.example/"])
    assert r.pages == [] and "bad token" in r.error

    r = ApifyRenderer("tok", client=FakeApify(run(status="TIMED-OUT"))).render(["https://a.example/"])
    assert "TIMED-OUT" in r.error

    assert ApifyRenderer("tok", client=FakeApify(run())).render([]).pages == []
