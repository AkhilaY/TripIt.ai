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


def test_whisper_falls_back_when_the_cpu_refuses_int8(monkeypatch):
    import sys
    import types
    from app import transcribe
    from app.config import Settings

    tried = []

    class FakeModel:
        def __init__(self, name, device, compute_type, local_files_only):
            tried.append((compute_type, local_files_only))
            if compute_type != "float32":
                raise ValueError("Requested int8 compute type, but the target device or backend do not support efficient int8 computation.")

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    monkeypatch.setattr(transcribe, "_model", None)
    model = transcribe._get_model(Settings(anthropic_api_key="x"))
    assert isinstance(model, FakeModel)
    assert tried == [("int8", True), ("int8_float32", True), ("float32", True)]  # the copy in the image, no download
    assert transcribe.load_error is None
    monkeypatch.setattr(transcribe, "_model", None)


def test_transcribe_reads_the_audio_itself(tmp_path, monkeypatch):
    """faster-whisper's own decoder breaks on newer PyAV (an option it passes was removed), so the samples are
    read from the WAV and handed over as an array."""
    import subprocess

    import numpy as np

    from app import transcribe
    from app.config import Settings
    from app.media import extract_audio

    video = tmp_path / "reel.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=1",
                    "-ac", "2", str(video)], check=True)
    audio = extract_audio(video, tmp_path)
    got = []

    class Segment:
        start, text = 0.0, " Go to Joe's Pizza "

    class FakeModel:
        def transcribe(self, samples, **kwargs):
            got.append(samples)
            return [Segment()], type("Info", (), {"language": "en"})()

    monkeypatch.setattr(transcribe, "_model", FakeModel())
    assert transcribe.transcribe(audio, Settings(anthropic_api_key="x")) == "[  0.0s] Go to Joe's Pizza"
    assert isinstance(got[0], np.ndarray) and got[0].dtype == np.float32 and 15000 < len(got[0]) < 17000
    assert 0 < float(np.abs(got[0]).max()) <= 1
    monkeypatch.setattr(transcribe, "_model", None)


def test_tiktok_slides_found_in_any_page_shape():
    import json
    from app.tiktok import embed_caption, embed_slides, parse_item

    # The post data under a renamed part of the page.
    item = {"id": "7431", "desc": "10 cafés in Paris", "imagePost": {"images": [{"imageURL": {"urlList": ["https://p16-sign.tiktokcdn-us.com/a~tplv-photomode-image.jpeg"]}}]}}
    page = '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">' + json.dumps(
        {"__DEFAULT_SCOPE__": {"webapp.app-context": {}, "webapp.photo-detail": {"itemInfo": {"itemStruct": item}}}}) + "</script>"
    assert parse_item(page)["desc"] == "10 cafés in Paris"
    # The embed page: slides by their address (escaped as TikTok writes them), each once, nothing from other hosts.
    embed = ('<script>{"desc":"Best croissants \\u00e9 Paris","images":["https:\\u002F\\u002Fp16-sign.tiktokcdn.com\\u002Ftos-photomode\\u002Fabc~tplv-photomode-image.jpeg?x=1",'
             '"https:\\u002F\\u002Fp16-sign.tiktokcdn.com\\u002Ftos-photomode\\u002Fabc~tplv-photomode-small.jpeg",'
             '"https:\\u002F\\u002Fp16-sign.tiktokcdn.com\\u002Ftos-photomode\\u002Fdef~tplv-photomode-image.jpeg",'
             '"https:\\u002F\\u002Fevil.example\\u002Fphotomode.jpg"]}</script>')
    slides = embed_slides(embed)
    assert [s.split("/")[-1].split("~")[0] for s in slides] == ["abc", "def"]
    assert embed_caption(embed) == "Best croissants é Paris"


def test_tiktok_cookies_from_a_cookies_file(tmp_path):
    from app.tiktok import cookies_for_tiktok
    f = tmp_path / "cookies.txt"
    f.write_text("# Netscape HTTP Cookie File\n.tiktok.com\tTRUE\t/\tTRUE\t0\tsessionid\tabc\n#HttpOnly_.tiktok.com\tTRUE\t/\tTRUE\t0\tmsToken\txyz\n"
                 ".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tnope\n")
    assert cookies_for_tiktok(str(f)) == {"sessionid": "abc", "msToken": "xyz"}


def _rehydration(item):
    import json
    return ('<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
            + json.dumps({"__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": item}}}}) + "</script>")


def _embed(post_id, caption, urls):
    import json
    state = {"source": {"data": {f"/embed/v2/{post_id}": {"videoData": {
        "itemInfos": {"id": post_id, "text": caption}, "authorInfos": {"uniqueId": "londontodolife"},
        "imagePostInfo": {"displayImages": [{"urlList": [u]} for u in urls]}}}}}}
    return f'<script id="__FRONTITY_CONNECT_STATE__" type="application/json">{json.dumps(state)}</script>'


def test_tiktok_embed_post_reads_the_page_data():
    from app.tiktok import embed_post

    page = _embed("7695", "Insta highlights #london ", [
        "https://p16-common-sign.tiktokcdn.com/tos-no1a-i-photomode-no/a~tplv-photomode-image.jpeg?x=1",
        "https://evil.example/tos-no1a-i-photomode-no/b.jpeg",
        "https://p19-common-sign.tiktokcdn.com/tos-no1a-i-photomode-no/c~tplv-photomode-image.jpeg"])
    metadata, slides = embed_post(page, "https://www.tiktok.com/@londontodolife/photo/7695")
    assert metadata.caption == "Insta highlights #london" and metadata.uploader == "londontodolife"
    assert [s.split("/")[-1].split("~")[0] for s in slides] == ["a", "c"]


def test_tiktok_same_slide_from_two_hosts_counts_once():
    from app.tiktok import embed_slides

    page = ('"https://p16-common-sign.tiktokcdn.com/tos-no1a-i-photomode-no/abc~tplv-photomode-image.jpeg" '
            '"https://p19-common-sign.tiktokcdn-us.com/tos-no1a-i-photomode-no/abc~tplv-photomode-image.jpeg"')
    assert len(embed_slides(page)) == 1


def test_tiktok_photo_post_tries_other_browsers_then_the_embed(monkeypatch):
    from app import tiktok

    url = "https://www.tiktok.com/@londontodolife/photo/7695"
    item = {"id": "7695", "desc": "Insta highlights", "author": {"uniqueId": "londontodolife"},
            "imagePost": {"images": [{"imageURL": {"urlList": ["https://p16-sign.tiktokcdn.com/s1~tplv-photomode-image.jpeg"]}}]}}
    calls = []

    # The first browser gets TikTok's 1.5 KB page without the post; the next one gets the post.
    def video_page(page, cookies=None, profile=tiktok.PROFILES[0]):
        calls.append((page.split("/")[-2], profile))
        return _rehydration(item) if profile == tiktok.PROFILES[1] else "<html>blocked</html>"

    monkeypatch.setattr(tiktok, "_get_page", video_page)
    metadata, slides = tiktok.find_photo_post(url)
    assert calls == [("video", tiktok.PROFILES[0]), ("video", tiktok.PROFILES[1])]
    assert metadata.caption == "Insta highlights" and len(slides) == 1

    # No video page at all: the embed page, after one 503.
    calls.clear()
    monkeypatch.setattr(tiktok, "EMBED_PAUSE", 0)
    answers = iter([None, _embed("7695", "From the embed", ["https://p16-common-sign.tiktokcdn.com/tos-photomode/x~tplv-photomode-image.jpeg"])])

    def embed_only(page, cookies=None, profile=tiktok.PROFILES[0]):
        calls.append((page.split("/")[-2], profile))
        return next(answers) if "/embed/v2/" in page else None

    monkeypatch.setattr(tiktok, "_get_page", embed_only)
    metadata, slides = tiktok.find_photo_post(url)
    assert metadata.caption == "From the embed" and len(slides) == 1
    assert calls[-2:] == [("v2", tiktok.PROFILES[0]), ("v2", tiktok.PROFILES[1])]

    # Nothing served anywhere.
    monkeypatch.setattr(tiktok, "_get_page", lambda page, cookies=None, profile=None: None)
    assert tiktok.find_photo_post(url) is None
