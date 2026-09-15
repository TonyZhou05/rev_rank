"""Offline regressions for search-derived dealer flags.

The search provider and the model are replaced at their adapters, so nothing here touches a network
or spends a credit. The assertions are mostly about refusals: which hosts never reach the model,
which sentences never reach the report, and what the report says when it has nothing to show.
"""
import socket

import pytest

from backend.app import dealer, dealer_signals
from backend.app.cancel import DISCONNECTED, Cancelled, CancelToken
from backend.app.config import Settings
from backend.app.llm import LLMUnavailable
from backend.app.models import Candidate, DealerInfo, Preferences, Report
from backend.app.search import SearchError, SearchResult, search as real_search

DEALER = DealerInfo(name="Lone Star Synthetic Motors", city="Austin", state="TX", postal_code="78701")
AG = SearchResult(url="https://www.texasattorneygeneral.gov/news/releases/ag-sues-austin-dealer",
                  text="The Office of the Attorney General filed suit alleging deceptive advertising by the dealership.",
                  title="AG sues Austin used-car dealer", published="2026-04-02")
DMV = SearchResult(url="https://www.txdmv.gov/dealers/enforcement/orders/synthetic-motors",
                   text="The Motor Vehicle Division suspended the dealer licence for 30 days and imposed a civil penalty.",
                   title="Licence suspension order")
NEWS = SearchResult(url="https://www.example-news.test/austin/dealer-fees",
                    text="The dealership agreed to a settlement and refunded buyers after a county inquiry into add-on fees.",
                    title="Austin dealer refunds buyers", published="2026-05-11")
BOARD = SearchResult(url="https://www.bbb.org/us/tx/austin/profile/used-car-dealers/lone-star-synthetic-motors",
                     text="Customers filed 12 complaints with BBB about undisclosed fees at this dealership.",
                     title="Lone Star Synthetic Motors | BBB profile")
REVIEW = SearchResult(url="https://www.dealerrater.com/dealer/lone-star-synthetic-motors-review",
                      text="4.6 out of 5 stars from 300 reviews.", title="Reviews", published="2026-06-01")
UNDATED = SearchResult(url="https://www.random-directory.test/tx/austin/lone-star",
                       text="Business listing for a used car dealer in Austin.", title="Directory")


def forbidden(*args, **kwargs):
    raise AssertionError("This offline test must not perform network access")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(dealer_signals, "search", forbidden)
    monkeypatch.setattr(dealer_signals, "request_json", forbidden)


def enabled(**changes) -> Settings:
    fields = {"dealer_signals_enabled": True, "search_provider": "tavily", "search_api_key": "test",
              "llm_api_key": "test", "llm_model": "stub-model"}
    return Settings(**{**fields, **changes})


def stub_search(monkeypatch, results, error=None):
    queries = []

    def run(query, settings, timeout=8, **kwargs):
        queries.append(query)
        if error is not None:
            raise error
        return list(results)

    monkeypatch.setattr(dealer_signals, "search", run)
    return queries


def stub_model(monkeypatch, payload):
    seen = []

    def request_json(settings, system, body, token=None, timeout=25):
        seen.append(body)
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(dealer_signals, "request_json", request_json)
    return seen


def flags(green=(), red=()):
    return {"green": list(green), "red": list(red)}


# --- Which sources are read at all -----------------------------------------------------------

@pytest.mark.parametrize("host,published,expected", [
    # Public bodies: state attorney general, DMV / motor vehicle board, city and federal regulators.
    ("texasattorneygeneral.gov", None, "official"),
    ("oag.ca.gov", None, "official"),
    ("txdmv.gov", None, "official"),
    ("ftc.gov", None, "official"),
    ("dmv.ny.us", None, "official"),
    # Attributable news: dated, so the provider treated it as a published article.
    ("example-news.test", "2026-05-11", "news"),
    # Undated and not official: a directory, profile or landing page, so it is not read.
    ("random-directory.test", None, None),
    # Review and complaint platforms stay link-outs on the dealer card, even when dated.
    ("bbb.org", "2026-06-01", None),
    ("dealerrater.com", "2026-06-01", None),
    ("consumeraffairs.com", "2026-06-01", None),
    ("complaintsboard.com", "2026-06-01", None),
    ("reddit.com", "2026-06-01", None),
    ("www.yelp.com".removeprefix("www."), "2026-06-01", None),
    ("business.google.com", "2026-06-01", None),
    ("cars.com", "2026-06-01", None),
    ("facebook.com", "2026-06-01", None),
])
def test_only_official_pages_and_dated_articles_are_read(host, published, expected):
    assert dealer_signals.category_of(host, published) == expected


def test_review_and_complaint_platforms_never_reach_the_model(monkeypatch):
    stub_search(monkeypatch, [REVIEW, BOARD, UNDATED, AG])
    seen = stub_model(monkeypatch, flags())
    block = dealer_signals.for_dealer(DEALER, enabled(dealer_signal_searches=1))
    assert [signal.host for signal in block.signals] == ["texasattorneygeneral.gov"]
    excerpts = seen[0]["excerpts"]
    assert len(excerpts) == 1
    assert not any(word in excerpts[0]["excerpt"] for word in ("stars", "BBB"))


def test_searches_look_for_official_records_not_reviews():
    queries = dealer_signals.queries(DEALER, 3)
    assert len(queries) == 3
    assert all(DEALER.name in query and "Austin TX" in query for query in queries)
    assert not any(word in query.lower() for query in queries for word in ("review", "rating", "stars"))
    assert any("attorney general" in query.lower() for query in queries)


def test_excerpts_keep_the_provider_date_and_are_capped(monkeypatch):
    long_hit = SearchResult(url=AG.url, text="x" * 900, title="AG action", published="2026-04-02")
    stub_search(monkeypatch, [long_hit])
    stub_model(monkeypatch, flags())
    signal = dealer_signals.for_dealer(DEALER, enabled(dealer_signal_searches=1)).signals[0]
    assert len(signal.excerpt) == dealer_signals.EXCERPT_LIMIT
    assert (signal.published, signal.category) == ("2026-04-02", "official")


# --- Allegation against concluded action ------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("The Attorney General filed suit alleging deceptive advertising.", "allegation"),
    ("The division opened an investigation into add-on fees.", "allegation"),
    ("Customers filed complaints about undisclosed fees.", "allegation"),
    ("The dealer entered a settlement and paid restitution.", "action"),
    ("The board suspended the dealer licence for 30 days.", "action"),
    ("A consent order requires the dealer to disclose fees.", "action"),
    # A settlement resolving allegations is a concluded step, not merely a claim.
    ("The dealership settled a lawsuit alleging deceptive pricing.", "action"),
    ("The dealership opened a second location downtown.", "unclear"),
])
def test_wording_decides_allegation_action_or_unclear(text, expected):
    assert dealer_signals.nature_of(text) == expected


def test_each_signal_carries_its_nature_for_the_label(monkeypatch):
    stub_search(monkeypatch, [AG, DMV, NEWS])
    stub_model(monkeypatch, flags())
    signals = dealer_signals.for_dealer(DEALER, enabled(dealer_signal_searches=1)).signals
    assert [(s.category, s.nature) for s in signals] == [
        ("official", "allegation"), ("official", "action"), ("news", "action")]
    # Quote, source, date and URL all travel with the signal so the card can attribute it.
    assert all(s.excerpt and s.host and s.url for s in signals)
    assert (signals[0].published, signals[1].published) == ("2026-04-02", None)


# --- The citation gate -----------------------------------------------------------------------

def test_cited_flags_survive_and_uncited_ones_do_not(monkeypatch):
    stub_search(monkeypatch, [AG, DMV])
    stub_model(monkeypatch, flags(red=[
        {"text": "A state attorney general release alleges deceptive advertising.", "citations": ["D1"]},
        {"text": "This dealer is widely known for shady paperwork.", "citations": []},
        {"text": "Another site says the dealer has 40 lawsuits.", "citations": ["D9"]},
    ]))
    block = dealer_signals.for_dealer(DEALER, enabled(dealer_signal_searches=1))
    assert [claim.text for claim in block.red] == ["A state attorney general release alleges deceptive advertising."]
    assert block.red[0].citations == ["D1"]
    assert block.dropped_claims == 2
    assert block.status == "complete" and "2 unsupported statement(s) were rejected" in block.message


def test_numbers_must_come_from_the_cited_excerpt(monkeypatch):
    stub_search(monkeypatch, [DMV])
    stub_model(monkeypatch, flags(red=[{"text": "A DMV order suspended the licence for 90 days.", "citations": ["D1"]}]))
    block = dealer_signals.for_dealer(DEALER, enabled(dealer_signal_searches=1))
    assert block.red == [] and block.dropped_claims == 1
    assert "No statement about this dealer passed the citation checks" in block.message


def test_a_claim_may_repeat_the_date_the_provider_gave(monkeypatch):
    stub_search(monkeypatch, [AG])
    stub_model(monkeypatch, flags(red=[
        {"text": "A Texas Attorney General release dated 2026-04-02 describes a deceptive-advertising suit.",
         "citations": ["D1"]}]))
    block = dealer_signals.for_dealer(DEALER, enabled(dealer_signal_searches=1))
    assert len(block.red) == 1 and block.dropped_claims == 0


@pytest.mark.parametrize("text", [
    "A review page gives the dealer 4.6 stars out of 5.",
    "The excerpts show a strong rating for this dealership.",
    "This is a reputable dealer despite an attorney general suit.",
    "Buyers recommend this dealership despite the filed suit.",
])
def test_a_flag_that_reads_like_a_score_is_refused(monkeypatch, text):
    stub_search(monkeypatch, [AG])
    stub_model(monkeypatch, flags(green=[{"text": text, "citations": ["D1"]}]))
    block = dealer_signals.for_dealer(DEALER, enabled(dealer_signal_searches=1))
    assert block.green == [] and block.dropped_claims == 1


def test_no_more_than_three_flags_each_side(monkeypatch):
    stub_search(monkeypatch, [AG])
    many = [{"text": f"An attorney general release alleges deceptive advertising ({letter}).", "citations": ["D1"]}
            for letter in "abcde"]
    stub_model(monkeypatch, flags(green=many, red=many))
    block = dealer_signals.for_dealer(DEALER, enabled(dealer_signal_searches=1))
    assert len(block.green) == 3 and len(block.red) == 3 and block.dropped_claims == 4


# --- Honest empty and degraded states --------------------------------------------------------

def test_disabled_by_default():
    block = dealer_signals.for_dealer(DEALER, Settings(search_api_key="test", search_provider="tavily"))
    assert block.status == "disabled" and block.searches == 0
    assert "REVRANK_DEALER_SIGNALS_ENABLED" in block.message
    assert block.signals == [] and block.caveats == []


def test_search_provider_is_required():
    block = dealer_signals.for_dealer(DEALER, Settings(dealer_signals_enabled=True))
    assert block.status == "unavailable" and "REVRANK_SEARCH_PROVIDER" in block.message


def test_a_nameless_dealer_is_never_searched_for(monkeypatch):
    block = dealer_signals.for_dealer(DealerInfo(city="Austin", state="TX"), enabled())
    assert block.status == "unavailable" and block.searches == 0
    assert "no dealer name" in block.message


def test_nothing_found_is_not_a_clean_dealer(monkeypatch):
    stub_search(monkeypatch, [REVIEW, UNDATED])
    block = dealer_signals.for_dealer(DEALER, enabled(dealer_signal_searches=1))
    assert block.status == "unavailable"
    assert block.message.startswith("No official/news flags found")
    assert "absence of search results, not a clean dealer" in block.message
    assert "clean record" not in block.message


def test_search_failure_is_reported_not_hidden(monkeypatch):
    stub_search(monkeypatch, [], error=SearchError("monthly budget reached"))
    block = dealer_signals.for_dealer(DEALER, enabled())
    assert block.status == "unavailable" and "monthly budget reached" in block.message
    assert block.searches == 0


def test_excerpts_are_listed_without_a_model(monkeypatch):
    stub_search(monkeypatch, [AG, DMV])
    block = dealer_signals.for_dealer(DEALER, enabled(llm_api_key="", llm_model="", dealer_signal_searches=1))
    assert block.status == "partial" and len(block.signals) == 2
    assert (block.green, block.red) == ([], [])
    assert "REVRANK_LLM_MODEL" in block.message


def test_model_failure_keeps_the_excerpts_and_invents_nothing(monkeypatch):
    stub_search(monkeypatch, [AG])
    stub_model(monkeypatch, LLMUnavailable("Model response unavailable or invalid."))
    block = dealer_signals.for_dealer(DEALER, enabled(dealer_signal_searches=1))
    assert block.status == "partial" and block.signals and (block.green, block.red) == ([], [])
    assert "reading them into flags failed" in block.message


def test_a_spent_budget_skips_the_search(monkeypatch):
    token = CancelToken(timeout=1)
    block = dealer_signals.for_dealer(DEALER, enabled(), token)
    assert block.status == "unavailable" and block.searches == 0
    assert "ran out of time" in block.message


def test_caveats_state_the_limits_of_a_search_excerpt(monkeypatch):
    stub_search(monkeypatch, [AG, DMV])
    stub_model(monkeypatch, flags(red=[{"text": "A state attorney general release alleges deceptive advertising.", "citations": ["D1"]}]))
    block = dealer_signals.for_dealer(DEALER, enabled(dealer_signal_searches=1))
    joined = " ".join(block.caveats)
    assert "did not open these pages" in joined
    assert "not an identifier" in joined
    assert "allegation" in joined
    assert "not this VIN" in joined
    assert "No dealer score" in joined


def test_the_existing_search_meter_stops_the_pass(monkeypatch):
    """No separate budget: the pass goes through search(), so usage.py refuses it like any search."""
    # The real search adapter is restored here, and no network is reachable: the monthly meter has
    # to refuse the call before a request is built.
    monkeypatch.setattr(dealer_signals, "search", real_search)
    block = dealer_signals.for_dealer(DEALER, enabled(search_monthly_credits=0))
    assert block.status == "unavailable" and block.searches == 0
    assert "monthly budget" in block.message


def test_a_cancelled_request_stops_before_searching(monkeypatch):
    stub_search(monkeypatch, [AG])
    token = CancelToken(timeout=120)
    token.cancel(DISCONNECTED)
    with pytest.raises(Cancelled):
        dealer_signals.for_dealer(DEALER, enabled(), token)


def test_the_model_pass_is_given_the_request_token(monkeypatch):
    stub_search(monkeypatch, [AG])
    tokens = []

    def request_json(settings, system, payload, token=None, timeout=25):
        tokens.append(token)
        return flags()

    monkeypatch.setattr(dealer_signals, "request_json", request_json)
    token = CancelToken(timeout=120)
    dealer_signals.for_dealer(DEALER, enabled(dealer_signal_searches=1), token)
    assert tokens == [token]


def test_credits_are_counted_the_way_the_provider_prices_them(monkeypatch):
    stub_search(monkeypatch, [AG])
    stub_model(monkeypatch, flags())
    tavily = dealer_signals.for_dealer(DEALER, enabled(dealer_signal_searches=2))
    assert (tavily.searches, tavily.credits) == (2, 4)
    brave = dealer_signals.for_dealer(DEALER, enabled(search_provider="brave", dealer_signal_searches=2))
    assert (brave.searches, brave.credits) == (2, 2)


# --- Report wiring ---------------------------------------------------------------------------

def candidate(id="a", dealer_block=DEALER) -> Candidate:
    return Candidate(id=id, title="2017 BMW M2", source_kind="listing", make="BMW", model="M2",
                     year=2017, price=42500, currency="USD", dealer=dealer_block)


def report_with(*candidates) -> Report:
    return Report(id="r", created_at="2026-09-15T00:00:00Z", title="t", summary="s",
                  preferences=Preferences(), candidates=list(candidates), findings=[], metrics=[],
                  questions=[], market={"message": ""}, warnings=[])


def test_two_cars_at_one_rooftop_share_a_single_search_set(monkeypatch):
    queries = stub_search(monkeypatch, [AG])
    stub_model(monkeypatch, flags())
    report = report_with(candidate("a"), candidate("b"))
    blocks = dealer_signals.attach(report, enabled(dealer_signal_searches=1))
    assert set(blocks) == {"a", "b"} and blocks["a"] is blocks["b"]
    assert len(queries) == 1


def test_cars_without_a_dealer_get_no_block(monkeypatch):
    report = report_with(candidate("a", dealer_block=None), candidate("b", dealer_block=None))
    assert dealer_signals.attach(report, enabled()) == {}


def test_distinct_dealers_are_searched_separately(monkeypatch):
    queries = stub_search(monkeypatch, [AG])
    stub_model(monkeypatch, flags())
    other = DealerInfo(name="Second Synthetic Motors", city="Dallas", state="TX")
    blocks = dealer_signals.attach(report_with(candidate("a"), candidate("b", dealer_block=other)),
                                   enabled(dealer_signal_searches=1))
    assert blocks["a"].dealer_name == DEALER.name and blocks["b"].dealer_name == other.name
    assert len(queries) == 2


def test_the_shell_and_the_signals_stay_separate(monkeypatch):
    """Slice A identity is not touched by slice B: the dealer block keeps its constructed links."""
    stub_search(monkeypatch, [AG])
    stub_model(monkeypatch, flags())
    info = dealer.dealer_info(name=DEALER.name, city="Austin", state="TX", postal_code="78701")
    block = dealer_signals.for_dealer(info, enabled(dealer_signal_searches=1))
    assert info.maps_url.startswith("https://www.google.com/maps/search/?api=1&query=")
    assert block.dealer_name == DEALER.name
    assert all(signal.url != info.maps_url for signal in block.signals)
