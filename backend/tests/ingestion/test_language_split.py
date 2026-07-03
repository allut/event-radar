"""Unit tests for app.ingestion.language_split."""

from app.ingestion.language_split import fill_missing_locales, split_by_language

_ET_PARAGRAPH = (
    "<p>Sel sügisel toimub Tallinnas suur muusikafestival, kuhu on oodatud "
    "kõik muusikahuvilised. Kava sisaldab kontserte, töötubasid ja vestlusringe "
    "erinevate kunstnikega üle kogu Euroopa.</p>"
)
_EN_PARAGRAPH = (
    "<p>This autumn a big music festival takes place in Tallinn, open to "
    "everyone who loves music. The program includes concerts, workshops and "
    "panel discussions with artists from all over Europe.</p>"
)
_RU_PARAGRAPH = (
    "<p>Этой осенью в Таллинне пройдёт большой музыкальный фестиваль, "
    "открытый для всех любителей музыки. В программе концерты, мастер-классы "
    "и дискуссии с артистами со всей Европы.</p>"
)


class TestSplitByLanguage:
    def test_none_returns_empty(self) -> None:
        assert split_by_language(None) == {}

    def test_empty_string_returns_empty(self) -> None:
        assert split_by_language("") == {}

    def test_clean_bilingual_paragraphs_split(self) -> None:
        html = _ET_PARAGRAPH + _EN_PARAGRAPH
        result = split_by_language(html)
        assert set(result.keys()) == {"et", "en"}
        assert "sügisel" in result["et"]
        assert "autumn" in result["en"]

    def test_three_locales_split(self) -> None:
        html = _ET_PARAGRAPH + _EN_PARAGRAPH + _RU_PARAGRAPH
        result = split_by_language(html)
        assert set(result.keys()) == {"et", "en", "ru"}

    def test_monolingual_returns_empty(self) -> None:
        html = _ET_PARAGRAPH + "<p>Veel üks eestikeelne lõik samal teemal, festivali kavast ja esinejatest.</p>"
        assert split_by_language(html) == {}

    def test_short_foreign_proper_noun_does_not_split(self) -> None:
        # A single short English venue name embedded in an otherwise-Estonian
        # description must not fragment it — too short to detect, and too
        # small a share of the text even if it were detected.
        html = (
            "<p>Sel sügisel toimub Tallinnas suur muusikafestival, kuhu on "
            "oodatud kõik muusikahuvilised.</p><p>Jazz Club</p><p>Kava "
            "sisaldab kontserte, töötubasid ja vestlusringe erinevate "
            "kunstnikega üle kogu Euroopa.</p>"
        )
        assert split_by_language(html) == {}

    def test_cyrillic_dominant_block_not_misdetected_as_latin_locale(self) -> None:
        # A Latin-script name embedded in an otherwise-Russian sentence must
        # not be detected as en/et — regression test for a real lingua
        # misdetection observed on production data (id 276/279/290/294).
        html = (
            "<p>Запись вебинара «Уход за детскими зубами»</p>"
            "<p>С детским зубным врачом Natalja Tammert из Studio Dental Care</p>"
            "<p>Поговорим о развитии молочных и постоянных зубов, а также об "
            "основных принципах ухода за детскими зубами дома.</p>"
        )
        assert split_by_language(html) == {}

    def test_minor_locale_below_share_threshold_excluded(self) -> None:
        # One real paragraph in a second language, but overwhelmed by a much
        # longer monolingual body — should not count as genuinely bilingual.
        html = ("<p>" + "Sel sügisel toimub Tallinnas suur muusikafestival. " * 40 + "</p>") + _EN_PARAGRAPH
        result = split_by_language(html)
        assert result == {}


class TestFillMissingLocales:
    def test_no_split_returns_original(self) -> None:
        assert fill_missing_locales({"et": "x"}, "too short") == {"et": "x"}
        assert fill_missing_locales(None, "too short") is None

    def test_adds_missing_locale_only(self) -> None:
        html = _ET_PARAGRAPH + _EN_PARAGRAPH
        result = fill_missing_locales({"et": "existing et text"}, html)
        assert result is not None
        assert result["et"] == "existing et text"  # never overwritten
        assert "autumn" in result["en"]

    def test_never_overwrites_any_existing_locale(self) -> None:
        html = _ET_PARAGRAPH + _EN_PARAGRAPH
        result = fill_missing_locales({"et": "existing", "en": "existing en"}, html)
        assert result == {"et": "existing", "en": "existing en"}
