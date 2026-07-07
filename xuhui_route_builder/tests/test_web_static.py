from pathlib import Path


def test_index_declares_inline_favicon_to_avoid_404() -> None:
    html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert 'rel="icon"' in html
