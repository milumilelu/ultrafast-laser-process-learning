from ultrafast_shared.units import convert, normalize_unit


def test_normalize_unit_accepts_scientific_unicode_spellings() -> None:
    assert normalize_unit("J / cm²") == ("J/m2", 1e4)
    assert normalize_unit("μm") == ("m", 1e-6)


def test_convert_rejects_incompatible_dimensions() -> None:
    assert convert(20, "percent", "W") is None


def test_convert_between_equivalent_units() -> None:
    assert convert(3, "J/cm²", "J/m2") == 30000
    assert convert(50, "kJ/cm²", "J/m2") == 500_000_000
