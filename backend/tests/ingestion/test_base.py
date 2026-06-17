"""Tests for shared ingestion helpers in app.ingestion.base."""

from app.ingestion.base import address_city, is_explicit_text, is_target_city


class TestIsExplicitText:
    def test_positive_english_title(self):
        assert is_explicit_text("Striptease Night") is True

    def test_positive_mixed_case(self):
        assert is_explicit_text("PORN star live") is True

    def test_positive_russian(self):
        assert is_explicit_text("стриптиз шоу в клубе") is True

    def test_positive_estonian(self):
        assert is_explicit_text("Suur striptiis õhtu") is True

    def test_negative_sussex_does_not_match_sex(self):
        assert is_explicit_text("Sussex Quartet live concert") is False

    def test_negative_essex_street_jazz(self):
        assert is_explicit_text("Essex Street Jazz Night") is False

    def test_negative_comic_strip_does_not_match_strip(self):
        assert is_explicit_text("Comic strip workshop for kids") is False

    def test_negative_normal_nightlife_title(self):
        assert is_explicit_text("Techno night at Hall club") is False

    def test_checks_all_provided_parts(self):
        assert is_explicit_text("Friday night", None, "Brothel Bar") is True

    def test_none_parts_are_ignored(self):
        assert is_explicit_text(None, None, None) is False

    def test_empty_string_is_not_explicit(self):
        assert is_explicit_text("") is False


class TestAddressCity:
    def test_extracts_tallinn(self):
        assert address_city("Narva maantee 63, 10152 Tallinn, Harju maakond") == "Tallinn"

    def test_extracts_tartu(self):
        assert address_city("Ülikooli 18, 51003 Tartu, Tartumaa") == "Tartu"

    def test_extracts_parnu(self):
        assert address_city("Rüütli 40, 80010 Pärnu, Pärnumaa") == "Pärnu"

    def test_no_postal_code_returns_none(self):
        assert address_city("Vanaturu kael 3") is None

    def test_none_returns_none(self):
        assert address_city("") is None


class TestIsTargetCity:
    def test_tallinn_address_is_target(self):
        assert is_target_city("Narva maantee 63, 10152 Tallinn, Harju maakond") is True

    def test_tartu_address_is_not_target(self):
        assert is_target_city("Ülikooli 18, 51003 Tartu, Tartumaa") is False

    def test_parnu_address_is_not_target(self):
        assert is_target_city("Rüütli 40, 80010 Pärnu, Pärnumaa") is False

    def test_city_less_address_kept(self):
        assert is_target_city("Vanaturu kael 3") is True

    def test_none_address_kept(self):
        assert is_target_city(None) is True

    # Allowlist regression: these cities were ABSENT from the old denylist and
    # leaked through. Under the allowlist (city != Tallinn → drop) they must fail.
    def test_small_estonian_town_kardla_dropped(self):
        assert is_target_city("Posti 13, 92411 Kärdla, Hiiumaa") is False

    def test_small_estonian_town_korgessaare_dropped(self):
        assert is_target_city("Kõpu tee 1, 92201 Kõrgessaare") is False

    def test_foreign_city_angers_dropped(self):
        assert is_target_city("Rue Bressigny 1, 49000 Angers, France") is False

    def test_foreign_city_gent_dropped(self):
        assert is_target_city("Korenmarkt 1, 9000 Gent, Belgium") is False

    def test_foreign_city_dusseldorf_dropped(self):
        assert is_target_city("Königsallee 1, 40212 Düsseldorf, Germany") is False

    def test_foreign_city_warszawa_dropped(self):
        assert is_target_city("Marszałkowska 1, 00-661 Warszawa, Poland") is False
