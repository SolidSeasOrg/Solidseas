"""Values as a drawing shows them, tolerances, the rounding guard and unit guessing
(docs/DRAWINGS.md 10.8, 6.2, Q3)."""

import math
from fractions import Fraction

import pytest

from solidseas.drawing import numbers as N
from solidseas.drawing import standards

IN = 0.0254


def tol(kind, upper=0, lower=0, places=None):
    return N.Tolerance(kind, Fraction(upper), Fraction(lower), places)


def test_inch_values_have_no_leading_zero_and_keep_their_places():
    assert N.show(0.5 * IN, "in", 3).text() == ".500"
    assert N.show(1.25 * IN, "in", 2).text() == "1.25"
    assert N.show(2 * IN, "in", 3).text() == "2.000"
    assert N.number(-0.25, 3, "in") == "-.250"


def test_millimetre_values_keep_a_leading_zero_and_the_block_places():
    assert N.show(0.0005, "mm", 1).text() == "0.5"
    assert N.show(0.032, "mm", 0).text() == "32"
    assert N.show(0.032, "mm", 1).text() == "32.0"  # the trailing zero selects the X.X row
    assert N.show(0.03215, "mm", 2).text() == "32.15"


def test_rounding_is_half_away_from_zero_on_the_decimal_value():
    assert N.number(0.0125, 3, "in") == ".013"
    assert N.number(-0.0125, 3, "in") == "-.013"
    assert N.number(2.5, 0, "mm") == "3"
    # 1 in = 25.4 mm exactly: 0.0127 m is .500 in, not .49999...
    assert N.nominal(0.0127, "in", 3) == ".500"


def test_a_value_that_rounds_to_zero_has_no_sign():
    assert N.number(-0.0001, 2, "mm") == "0.00"
    assert N.number(-0.0001, 3, "in") == ".000"


def test_exact_nominals_show_the_places_they_need():
    assert N.nominal(0.0125, "mm", 0, exact=True) == "12.5"
    assert N.nominal(0.040, "mm", 1, exact=True) == "40.0"
    assert N.nominal(0.040, "mm", 0, exact=True) == "40"
    assert N.nominal(1 / 3 * IN, "in", 0, exact=True) == ".3333"  # capped at four places


def test_inch_deviations_carry_the_value_places_and_a_signed_zero():
    shown = N.show(0.5 * IN, "in", 3, tol("deviations", Fraction(5, 1000), 0))
    assert (shown.value, shown.upper, shown.lower) == (".500", "+.005", "-.000")
    shown = N.show(0.5 * IN, "in", 3, tol("deviations", 0, Fraction(-5, 1000)))
    assert (shown.upper, shown.lower) == ("+.000", "-.005")


def test_millimetre_zero_deviation_is_a_lone_zero():
    shown = N.show(0.032, "mm", 0, tol("deviations", 0, Fraction(-2, 100)))
    assert (shown.value, shown.upper, shown.lower) == ("32", "0", "-0.02")
    shown = N.show(0.032, "mm", 0, tol("deviations", Fraction(25, 100), Fraction(-1, 10)))
    assert (shown.upper, shown.lower) == ("+0.25", "-0.10")  # both deviations to the same places


def test_symmetric_limits_max_min_basic_and_reference():
    assert N.show(0.5 * IN, "in", 3, tol("symmetric", Fraction(5, 1000))).text() == ".500 ±.005"
    assert N.show(0.032, "mm", 1, tol("symmetric", Fraction(5, 100))).text() == "32.0 ±0.05"
    limits = N.show(0.5 * IN, "in", 3, tol("limits", Fraction(5, 1000), 0))
    assert (limits.value, limits.upper, limits.lower) == ("", ".505", ".500")
    assert N.show(0.5 * IN, "in", 3, tol("max")).text() == ".500 MAX"
    assert N.show(0.5 * IN, "in", 3, tol("min")).text() == ".500 MIN"
    basic = N.show(0.040, "mm", 2, tol("basic"))
    assert basic.boxed and basic.value == "40" and not basic.upper  # basic: no tolerance, places it needs
    assert N.show(1.25 * IN, "in", 3, tol("reference")).text() == "(1.250)"


def test_a_prefix_stays_apart_from_the_value():
    shown = N.show(0.266 * IN, "in", 3, prefix="4X Ø")
    assert shown.value == ".266" and shown.prefix == "4X Ø"
    assert shown.text() == "4X Ø.266"


def test_angles_carry_the_degree_sign_on_value_and_tolerance():
    assert N.show_angle(math.radians(15)).text() == "15°"
    assert N.show_angle(math.radians(90), 0, tol("symmetric", Fraction(1, 2))).text() == "90° ±0.5°"
    assert N.show_angle(math.radians(82), 0, tol("basic")).text() == "[82°]"
    assert N.minutes_text(90) == "1°30'"
    assert N.minutes_text(60) == "1°"


def test_the_block_selects_the_tolerance_by_places():
    assert N.block_plus_minus("in", 2) == Fraction(10, 1000)
    assert N.block_plus_minus("in", 3) == Fraction(5, 1000)
    assert N.block_plus_minus("in", 4) is None  # more places than the block's last row: explicit (R3.block)
    assert N.block_plus_minus("mm", 0) == Fraction(1, 2)
    assert N.block_plus_minus("mm", 2) == Fraction(5, 100)


def test_the_rounding_guard_flags_a_value_off_by_more_than_a_tenth_of_its_band():
    # 12.345 mm shown as 12.3 under +/-0.2: off by 0.045 of a 0.4 band, 11 %
    assert N.rounding_flagged(0.012345, "mm", 1, Fraction(4, 10))
    assert not N.rounding_flagged(0.01231, "mm", 1, Fraction(4, 10))
    # a millimetre model drawn in inches: 10 mm is .3937 in, shown .394 under +/-.005
    assert not N.rounding_flagged(0.010, "in", 3, Fraction(10, 1000))
    assert N.rounding_share(0.010, "in", 3, None) == 0


def test_bands_are_counted_for_the_wizard():
    assert N.band_text(Fraction(1, 100), "in") == "±.010"
    assert N.band_text(Fraction(5, 100), "mm") == "±0.05"
    text = N.band_summary(["±.010"] * 23 + ["±.005"] * 14)
    assert text == "23 at ±.010, 14 at ±.005"


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_value_that_is_not_finite_is_refused(bad):
    with pytest.raises(ValueError):
        N.number(bad, 2, "mm")


def test_bad_arguments_are_refused():
    with pytest.raises(ValueError):
        N.number(1.0, 2, "cm")
    with pytest.raises(ValueError):
        N.number(1.0, 9, "mm")
    with pytest.raises(ValueError):
        N.Tolerance("loose")
    with pytest.raises(ValueError):
        N.Tolerance("symmetric", Fraction(0))
    with pytest.raises(ValueError):
        N.Tolerance("deviations", Fraction(-1), Fraction(1))


def test_an_inch_part_is_guessed_inch():
    sizes = [x * IN for x in (0.5, 1.0, 0.125, 0.375, 2.0, 0.875, 0.312, 3.25)]
    g = N.guess_units(sizes)
    assert g.unit == "in" and g.decided
    assert g.inch == len(sizes) and g.inch_only >= 3


def test_a_millimetre_part_is_guessed_millimetre():
    g = N.guess_units([0.010, 0.025, 0.0035, 0.0066, 0.012, 0.0045])
    assert g.unit == "mm" and g.decided and g.mm_only == 6
    assert g.to_dict()["sizes"] == 6


def test_when_the_sizes_prove_nothing_the_guess_is_inch_and_undecided():
    # multiples of a quarter inch are whole hundredths of a millimetre too
    g = N.guess_units([x * IN for x in (0.25, 0.5, 1.0, 1.5)])
    assert g.unit == "in" and not g.decided
    g = N.guess_units([0.0123456789, 0.0])
    assert not g.decided and g.sizes == 1


def test_units_convert_exactly():
    assert N.in_unit(0.0254, "in") == pytest.approx(1.0, abs=1e-15)
    assert N.from_unit(1.0, "in") == standards.INCH
    assert N.in_unit(0.001, "mm") == 1.0


def test_floats_are_added_left_to_right_on_every_python_version():
    """sum() compensates for rounding from Python 3.12, so a drawing's geometry came out
    in other last bits there than on 3.11, and a number rounded at its last place on the
    sheet with them (the goldens, recorded on 3.11, failed on 3.12). plain_sum adds as
    3.11's sum() did, whatever the version."""
    values = [1e16, 1.0, -1e16]
    assert N.plain_sum(values) == 0.0  # 1.0 is lost in the first addition, as 3.11 lost it
    expected = 0.0
    for _ in range(10):
        expected += 0.1
    assert N.plain_sum([0.1] * 10) == expected
    assert N.plain_sum([]) == 0 and isinstance(N.plain_sum([]), int)
    assert N.plain_sum([1, 2, 3]) == 6 and isinstance(N.plain_sum([1, 2, 3]), int)
    assert N.plain_sum((x for x in (0.5, 0.25)), 1.0) == 1.75
