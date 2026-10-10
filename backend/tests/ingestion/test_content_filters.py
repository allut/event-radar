

def test_content_flags_scans_extra_texts_and_localized_values():
    from app.ingestion.content_filters import content_flags, localized_text_values

    assert content_flags("Concert", None, None, None) == (False, False)
    extras = localized_text_values({"en": "ok"}, None, {"ru": "xxx porn"})
    assert extras == ["ok", "xxx porn"]
    assert content_flags("Concert", None, None, None, extras)[0] is True
