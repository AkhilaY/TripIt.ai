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


def test_cuisine_from_name_summary_and_dishes():
    from app.cuisine import cuisine_of
    assert cuisine_of("food", "Dhamaka", "Bold regional Indian cooking", ["goat neck biryani"]) == "indian"
    assert cuisine_of("food", "Joe's Pizza", "The classic New York slice") == "pizza"
    assert cuisine_of("food", "Los Tacos No. 1", "Adobada tacos in Chelsea Market") == "mexican"
    assert cuisine_of("food", "Via Carota", "West Village trattoria", ["cacio e pepe"]) == "italian"
    assert cuisine_of("food", "Somewhere", "A lovely spot") is None
    assert cuisine_of("cafe", "Pizza Cafe", "coffee") is None  # only restaurants get a cuisine


def test_tiktok_short_link_retries_when_sent_to_home_page(monkeypatch):
    import httpx
    from app import tiktok
    answers = iter([("https://www.tiktok.com/?_r=1", 302),
                    ("https://www.tiktok.com/@someone/photo/7695188109977226518?_r=1&_t=x", 301)])

    def handler(request):
        location, status = next(answers)
        return httpx.Response(status, headers={"location": location})

    real = httpx.Client
    monkeypatch.setattr(tiktok.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(tiktok, "RESOLVE_PAUSE", 0)
    assert tiktok.resolve("https://www.tiktok.com/t/ZPNrrb5w7/") == "https://www.tiktok.com/@someone/photo/7695188109977226518"


def test_tiktok_short_link_kept_when_it_never_reaches_the_post(monkeypatch):
    import httpx
    from app import tiktok
    real = httpx.Client
    handler = lambda request: httpx.Response(302, headers={"location": "https://www.tiktok.com/?_r=1"})
    monkeypatch.setattr(tiktok.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(tiktok, "RESOLVE_PAUSE", 0)
    assert tiktok.resolve("https://www.tiktok.com/t/ZPNrrb5w7/") == "https://www.tiktok.com/t/ZPNrrb5w7/"


def test_edit_cover_prefers_a_saved_places_photo_over_an_expiring_google_link():
    from app.concierge import Curator
    from app.db import Database
    from app.models import EditItem, PlacePhoto
    curator = Curator(Database(":memory:"), None, photo_url=lambda ref: f"/v1/discover/photo?ref={ref}&sig=x")
    saved = PlacePhoto(source="google", url="/v1/places/p1/photos/0?sig=y")
    reel = PlacePhoto(source="reel", url="/v1/places/p2/photos/0?sig=z")
    pick = PlacePhoto(source="google", url="/v1/discover/photo?ref=places/a&sig=x")
    items = [EditItem(id="i1", name="Press pick", category="food", city="NYC", photo=pick),
             EditItem(id="i2", place_id="p2", saved=True, name="Reel place", category="food", city="NYC", photo=reel),
             EditItem(id="i3", place_id="p1", saved=True, name="Saved", category="food", city="NYC", photo=saved)]
    assert curator._pick_cover({"ref": "places/a"}, items) == saved  # Claude's Google pick loses to a saved photo
    assert curator._pick_cover(None, items[:1]) == pick  # nothing saved: the pick is all there is
    assert curator._pick_cover(None, []) is None


def test_instagram_photo_post_embed_is_read():
    import json as _json
    from app import instagram

    assert instagram.shortcode("https://www.instagram.com/p/ABC123/?img_index=1") == "ABC123"
    assert instagram.shortcode("https://instagram.com/reel/XYZ/") == "XYZ"
    media = {"owner": {"username": "eats.nyc"},
             "edge_media_to_caption": {"edges": [{"node": {"text": "3 cafés: Sey, Devoción, Abraço"}}]},
             "edge_sidecar_to_children": {"edges": [
                 {"node": {"is_video": False, "display_url": "https://cdn/1.jpg"}},
                 {"node": {"is_video": True, "display_url": "https://cdn/v.jpg"}},
                 {"node": {"is_video": False, "display_url": "https://cdn/2.jpg"}}]}}
    page = 'x "contextJSON":' + _json.dumps(_json.dumps({"gql_data": {"shortcode_media": media}})) + ', y'
    assert instagram.parse_embed(page) == (["https://cdn/1.jpg", "https://cdn/2.jpg"], "3 cafés: Sey, Devoción, Abraço", "eats.nyc")

    # The plain embed page: the first picture and the caption.
    plain = ('<img class="EmbeddedMediaImage" alt="" src="https://cdn/a.jpg?x=1&amp;y=2">'
             '<div class="Caption"><a class="CaptionUsername" href="#">eats.nyc</a><br/>Sey Coffee &amp; more'
             '<div class="CaptionComments"></div></div><span class="UsernameText">eats.nyc</span>')
    assert instagram.parse_embed(plain) == (["https://cdn/a.jpg?x=1&y=2"], "Sey Coffee & more", "eats.nyc")


def test_instagram_photo_post_downloads_slides(tmp_path):
    import httpx
    from app import instagram

    page = '<img class="EmbeddedMediaImage" src="https://cdn/a.jpg"><div class="Caption">Pizza at Lucali<div class="CaptionComments">'

    def handler(request):
        if "embed" in request.url.path:
            return httpx.Response(200, text=page)
        return httpx.Response(200, content=b"\xff\xd8jpeg", headers={"content-type": "image/jpeg"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        meta, slides = instagram.download_photo_post("https://www.instagram.com/p/ABC/", tmp_path, client)
    assert meta.caption == "Pizza at Lucali" and len(slides) == 1 and slides[0].read_bytes().startswith(b"\xff\xd8")


def test_instagram_embed_fallback_gets_reel_video_and_follows_share_links(tmp_path):
    import json as _json
    import httpx
    from app import instagram

    media = {"is_video": True, "video_url": "https://cdn/v.mp4", "display_url": "https://cdn/cover.jpg",
             "edge_media_to_caption": {"edges": [{"node": {"text": "Rooftop bars in Lisbon"}}]}}
    page = '"contextJSON":' + _json.dumps(_json.dumps({"gql_data": {"shortcode_media": media}}))

    def handler(request):
        if request.url.path.startswith("/share/"):
            return httpx.Response(302, headers={"location": "https://www.instagram.com/reel/REEL1/"})
        if request.url.path.startswith("/reel/"):
            return httpx.Response(200, text="ok")
        if "embed" in request.url.path:
            assert "/p/REEL1/" in request.url.path
            return httpx.Response(200, text=page)
        return httpx.Response(200, content=b"\x00\x00\x00 ftypmp4", headers={"content-type": "video/mp4"})

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        url = instagram.resolve("https://www.instagram.com/share/reel/BAbc/", client)
        assert url == "https://www.instagram.com/reel/REEL1/"
        meta, slides, video = instagram.download_post(url, tmp_path, client)
    assert meta.caption == "Rooftop bars in Lisbon" and slides == [] and video and video.read_bytes().endswith(b"mp4")
    assert instagram.resolve("https://www.instagram.com/p/X/") == "https://www.instagram.com/p/X/"
