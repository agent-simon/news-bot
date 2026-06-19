from newsbot.dedup import normalize


def test_normalize_lowercases_scheme_and_host():
    assert normalize("HTTPS://Example.COM/Path") == "https://example.com/Path"


def test_normalize_strips_www_and_trailing_slash():
    assert normalize("https://www.example.com/a/") == "https://example.com/a"


def test_normalize_drops_fragment():
    assert normalize("https://example.com/a#section") == "https://example.com/a"


def test_normalize_drops_tracking_params_keeps_real_ones():
    assert normalize(
        "https://example.com/a?id=7&utm_source=x&fbclid=y"
    ) == "https://example.com/a?id=7"


def test_normalize_equates_tracking_variants():
    assert normalize("https://example.com/a?utm_campaign=z") == normalize("https://example.com/a")
