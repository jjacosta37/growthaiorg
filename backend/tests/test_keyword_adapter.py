"""ApifyKeywordSource: input mapping, output mapping and failure handling, with Apify faked."""

from decimal import Decimal
from types import SimpleNamespace

from providers.keywords import ApifyKeywordSource, KeywordQuery

# Shape of one dataset item from a live run (2026-10-13), trimmed to the fields we read.
LIVE_ITEM = {"keyword": "how to run a sprint retrospective", "country": "US", "language": "en",
             "search_volume": 40, "keyword_difficulty": 19, "search_intent": "informational", "source": "database"}


class FakeApify:
    def __init__(self, items, status="SUCCEEDED", error=None, settled_cost=0.044):
        self.items, self.status, self.error, self.settled_cost = items, status, error, settled_cost
        self.calls = []

    def actor(self, actor_id):
        fake = self

        class Actor:
            def call(self, run_input, run_timeout, max_total_charge_usd=None):
                fake.calls.append((actor_id, run_input, max_total_charge_usd))
                if fake.error:
                    raise fake.error
                # The object call() returns predates the final charges, as the live one did.
                return SimpleNamespace(id="kw1", status=fake.status, usage_total_usd=0.00005, default_dataset_id="d")

        return Actor()

    def run(self, run_id):
        fake = self

        class Run:
            def get(self):
                return SimpleNamespace(id=run_id, status=fake.status, usage_total_usd=fake.settled_cost,
                                       default_dataset_id="d")

        return Run()

    def dataset(self, _):
        items = self.items

        class Dataset:
            def iterate_items(self):
                return iter(items)

        return Dataset()


def source(client):
    return ApifyKeywordSource("tok", client=client, max_charge_usd=Decimal("0.50"))


def test_input_is_normalised_deduped_and_within_limits():
    client = FakeApify([])
    source(client).lookup(KeywordQuery(
        keywords=["Sprint  Retro", "sprint retro", "x" * 81, " ".join(["w"] * 11), "", "kanban"],
        country="GB", language="en"))
    actor_id, run_input, cap = client.calls[0]
    assert actor_id == "keywordlab/keyword-search-volume"
    assert run_input == {"keywords": ["sprint retro", "kanban"], "country": "GB", "language": "en",
                         "liveLookupForMissing": False}
    assert cap == Decimal("0.50")


def test_maps_metrics_settled_cost_and_keywords_without_data():
    client = FakeApify([LIVE_ITEM, {**LIVE_ITEM, "keyword": "Kanban", "search_volume": 5400,
                                    "keyword_difficulty": None}])
    r = source(client).lookup(KeywordQuery(keywords=["how to run a sprint retrospective", "kanban", "rare phrase"]))
    assert r.ok and r.status == "SUCCEEDED" and r.external_run_id == "kw1" and r.items_raw == 2
    assert (r.metrics["how to run a sprint retrospective"].volume, r.metrics["kanban"].difficulty) == (40, None)
    assert r.without_data == ["rare phrase"]
    assert r.cost_usd == Decimal("0.044")  # re-read once finished, not the stale figure


def test_failed_run_reports_no_without_data():
    r = source(FakeApify([LIVE_ITEM], status="FAILED")).lookup(KeywordQuery(keywords=[LIVE_ITEM["keyword"], "x y"]))
    assert not r.ok and "FAILED" in r.error
    assert r.without_data == []  # a failed run's gaps are unknown, not "no data"


def test_exception_degrades_to_an_error():
    r = source(FakeApify([], error=RuntimeError("boom"))).lookup(KeywordQuery(keywords=["kanban"]))
    assert r.error == "RuntimeError: boom" and r.metrics == {}


def test_nothing_to_look_up_makes_no_call():
    client = FakeApify([])
    r = source(client).lookup(KeywordQuery(keywords=["", "x" * 200]))
    assert client.calls == [] and r.ok and r.metrics == {}
