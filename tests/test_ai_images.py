"""AI illustrations (core/media/ai_images.py): only where the script asks, tagged,
credited, declared to YouTube. The network is never called in tests."""
import base64
import io

from core.media import ai_images


def _jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    img = Image.new("RGB", (1920, 1088), (90, 110, 80))
    for x in range(0, 1920, 7):
        img.putpixel((x, x % 1088), (250, 250, 250))
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def test_parse():
    spec = "rode to a crack = settlers riding into a rift valley, 930; camped in booths = turf booths"
    pairs = ai_images.parse(spec)
    assert [p for _, p in pairs] == ["settlers riding into a rift valley, 930", "turf booths"]
    assert pairs[0][0].search("The people RODE TO A CRACK in the earth.")
    assert ai_images.parse("no equals sign; = no cue") == []


def test_no_credentials_means_no_call(monkeypatch, tmp_path):
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    assert ai_images.generate("anything", tmp_path / "a.jpg") is None


def test_generate_sends_the_prompt_and_saves(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "secret")
    sent = {}

    class R:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {"result": {"image": base64.b64encode(_jpeg()).decode()}}

    def fake_post(url, files=None, headers=None, timeout=None):
        sent.update(url=url, files=files, auth=headers["Authorization"])
        return R()
    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    meta = ai_images.generate("a longship at sea", tmp_path / "x.jpg")
    assert meta["source"] == "AI illustration" and "Apache 2.0" in meta["license"]
    assert (tmp_path / "x.jpg").stat().st_size > 5000
    assert sent["url"].endswith("/accounts/acct/ai/run/@cf/black-forest-labs/flux-2-klein-4b")
    assert sent["files"]["prompt"][1].startswith("a longship at sea. ")
    assert sent["files"]["width"][1] == "1920"


def test_illustration_goes_to_the_cued_line_and_is_tagged(monkeypatch, tmp_path):
    from PIL import Image

    from core.config import get_settings
    from core.media import images
    from core.schemas import Scene

    def fake_generate(prompt, dest):
        Image.new("RGB", (1920, 1088), (80, 100, 70)).save(dest)
        return {"path": str(dest), "title": f"Illustration: {prompt}", "license": ai_images.LICENSE,
                "source": "AI illustration", "url": "", "page": "", "credit": "AI", "ai": True}
    monkeypatch.setattr(ai_images, "generate", fake_generate)
    get_settings().images.provider = "pillow"        # no photo searches in tests
    scenes = [Scene(index=0, narration="In 930 they met.", visual_prompt="", duration=3),
              Scene(index=1, narration="They camped in booths of turf.", visual_prompt="", duration=3)]
    images.generate_images(scenes, tmp_path, topic="", category="history", subtitles=False,
                           illustrate="camped in booths = turf and stone booths in a valley, 930")
    assert scenes[1].tag == "ILLUSTRATION"
    assert scenes[1].source.startswith("AI illustration")
    assert scenes[0].tag == ""


def test_ai_credit_sets_the_youtube_declaration(tmp_path):
    from core.media import credits
    credits.add(tmp_path, [{"title": "Illustration: a longship", "license": ai_images.LICENSE,
                            "source": "AI illustration", "url": "", "page": "", "credit": "AI"}],
                "image")
    assert credits.has_ai(tmp_path)
    assert not credits.publish_problem(tmp_path)        # Apache 2.0 is fine to publish
    assert not credits.has_ai(tmp_path / "none")
