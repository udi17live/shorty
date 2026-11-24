import pytest


@pytest.fixture(autouse=True)
def shortyy_home(tmp_path, monkeypatch):
    """Every test gets an empty SHORTYY_HOME and no keys from the developer's environment."""
    monkeypatch.setenv("SHORTYY_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CLIPYYY_HOME", raising=False)
    for var in (
        "OPENROUTER_API_KEY",
        "PEXELS_API_KEY",
        "BUFFER_API_KEY",
        "SHORTYY_LLM_MODEL",
        "CLIPYYY_LLM_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    return tmp_path / "home"


@pytest.fixture
def transcript():
    """Ten 6-second sentences, two words each per second."""
    words, sentences = [], []
    for i in range(10):
        start = i * 6.0
        sentence_words = [
            {"word": w, "start": start + j * 0.5, "end": start + j * 0.5 + 0.4}
            for j, w in enumerate(f"sentence {i} talks about building great products today.".split())
        ]
        words += sentence_words
        sentences.append(
            {
                "text": " ".join(w["word"] for w in sentence_words),
                "start": start,
                "end": sentence_words[-1]["end"],
            }
        )
    return {"language": "en", "words": words, "sentences": sentences}
