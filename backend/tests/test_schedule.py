"""Plans stay realistic: one meal per meal, sensible days, and clock times that add up."""

from app.models import Place, PlannedDay, PlannedStop, PlanResult, TimeOfDay
from app.schedule import balance_plan, day_times


def place(pid, category, **kw):
    return Place(id=pid, name=pid, category=category, created_at="2026-10-25T00:00:00Z", **kw)


def test_five_lunches_become_one_lunch_one_dinner_and_the_rest_move_or_drop():
    restaurants = [place(f"r{i}", "food", city="Dubai") for i in range(5)]
    sight = place("s", "attraction", city="Dubai")
    plan = PlanResult(days=[
        PlannedDay(day_number=1, title="Old Dubai", stops=[PlannedStop(place_id=p.id, time_of_day=TimeOfDay.lunch, note=None) for p in restaurants]
                   + [PlannedStop(place_id="s", time_of_day=TimeOfDay.morning, note=None)]),
        PlannedDay(day_number=2, title="Marina", stops=[]),
    ], unscheduled_place_ids=[])
    out = balance_plan(plan, restaurants + [sight], lambda p: [1, 2])
    meals = lambda day: sorted(s.time_of_day.value for s in day.stops if s.place_id.startswith("r"))
    assert meals(out.days[0]) == ["dinner", "lunch"]  # one lunch and one dinner, no more
    assert meals(out.days[1]) == ["dinner", "lunch"]  # two more moved to the next day
    assert out.unscheduled_place_ids == ["r4"]  # and the fifth waits rather than stacking up
    assert out.days[0].stops[0].place_id == "s" or out.days[0].stops[0].time_of_day == TimeOfDay.morning


def test_a_hand_built_day_keeps_its_places_but_not_two_lunches():
    a, b = place("a", "food"), place("b", "food")
    plan = PlanResult(days=[PlannedDay(day_number=1, title="", stops=[
        PlannedStop(place_id="a", time_of_day=TimeOfDay.lunch, note=None), PlannedStop(place_id="b", time_of_day=TimeOfDay.lunch, note=None)])],
        unscheduled_place_ids=[])
    out = balance_plan(plan, [a, b], lambda p: [1], move_days=False)
    assert [s.time_of_day for s in out.days[0].stops] == [TimeOfDay.lunch, TimeOfDay.dinner]


def test_times_follow_one_another_instead_of_repeating():
    day = [place("bakery", "cafe", day_number=4, day_order=0, time_of_day="morning"),
           place("market", "shopping", day_number=4, day_order=1, time_of_day="afternoon"),
           place("buns", "dessert", day_number=4, day_order=2, time_of_day="afternoon"),
           place("books", "shopping", day_number=4, day_order=3, time_of_day="afternoon"),
           place("dinner", "food", day_number=4, day_order=4, time_of_day="dinner", start_time="20:15")]
    times = [(t.place_id, t.time, t.estimated) for t in day_times(day)]
    assert times == [("bakery", "09:30", True), ("market", "14:00", True), ("buns", "15:15", True),
                     ("books", "16:00", True), ("dinner", "20:15", False)]


def test_an_edit_cover_is_the_photo_claude_picks():
    import asyncio
    from app.concierge import Curator
    from app.models import CoverPick

    class DB:
        def photo_refs(self, pid):
            return {"slide": [{"source": "google", "ref": "places/slide/photos/1"}],
                    "tower": [{"source": "reel", "ref": "x.jpg"}, {"source": "google", "ref": "places/tower/photos/1"},
                              {"source": "google", "ref": "places/tower/photos/2"}]}[pid]

    class Claude:
        seen = []
        async def _parse(self, system, content, output_type, effort=None, feature="other"):
            self.seen.append([c for c in content if c["type"] == "image"])
            return CoverPick(number=2, reason="Wide and calm")

    async def fetch(ref):
        return b"\xff\xd8 jpeg " + ref["ref"].encode()

    cur = Curator(DB(), Claude())
    cur.fetch_photo = fetch
    edits = [{"id": "e1", "title": "The Coastline Edit", "dek": "A day by the sea", "entries": [{"place_id": "slide"}, {"place_id": "tower"}]}]
    asyncio.run(cur._pick_covers(edits))
    # One photo per place first (skipping Reel frames), then second photos; Claude chose the second: the tower.
    assert len(Claude.seen[0]) == 3
    assert edits[0]["cover"] == {"place_id": "tower", "index": 1}
