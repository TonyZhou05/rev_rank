import json
import multiprocessing

import pytest

from backend.app import usage
from backend.app.config import Settings


def spend_many(directory: str, times: int) -> None:
    settings = Settings(data_dir=__import__("pathlib").Path(directory))
    for _ in range(times):
        usage.spend(settings, "marketcheck")


def test_spends_from_several_processes_are_all_counted(tmp_path, monkeypatch):
    # Real file path: several local servers and scripts share one meter.
    monkeypatch.setattr(usage, "usage_path", lambda settings: settings.data_dir / "usage.json")
    workers = [multiprocessing.get_context("spawn").Process(target=spend_many, args=(str(tmp_path), 15))
               for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)
    assert all(worker.exitcode == 0 for worker in workers)
    assert usage.used(Settings(data_dir=tmp_path), "marketcheck") == 60


def test_an_unreadable_meter_refuses_calls_instead_of_restarting_at_zero(tmp_path):
    settings = Settings(data_dir=tmp_path)
    usage.usage_path(settings).write_text('{"2026-09": {"marketcheck": 49')  # A write cut off mid-way.
    with pytest.raises(usage.BudgetExceeded, match="could not be read"):
        usage.spend(settings, "marketcheck")
    assert usage.usage_path(settings).read_text() == '{"2026-09": {"marketcheck": 49'


def test_a_missing_or_empty_meter_starts_the_month(tmp_path):
    settings = Settings(data_dir=tmp_path)
    usage.spend(settings, "tavily")
    usage.usage_path(settings).write_text("")
    usage.spend(settings, "tavily")
    assert json.loads(usage.usage_path(settings).read_text())[usage.month()] == {"tavily": 2}
