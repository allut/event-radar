"""Estonian registry code (Äriregistri kood) validation. Pure: no DB, no clock."""

from app.constants.promotions import PROMOTION_REGISTRY_CODE_RE

# The check digit is the 8th digit. It is the mod-11 of the first seven digits
# weighted 1..7; a remainder of 10 retries with weights 3..9, and a second 10
# means the check digit is 0 (the same scheme as the personal identity code).
_FIRST_PASS_WEIGHTS = (1, 2, 3, 4, 5, 6, 7)
_SECOND_PASS_WEIGHTS = (3, 4, 5, 6, 7, 8, 9)
_MODULUS = 11
_REMAINDER_RETRY = 10


def registry_code_check_digit(first_seven: str) -> int:
    digits = [int(c) for c in first_seven]
    remainder = sum(w * d for w, d in zip(_FIRST_PASS_WEIGHTS, digits, strict=True)) % _MODULUS
    if remainder == _REMAINDER_RETRY:
        remainder = sum(w * d for w, d in zip(_SECOND_PASS_WEIGHTS, digits, strict=True)) % _MODULUS
        if remainder == _REMAINDER_RETRY:
            return 0
    return remainder


def is_valid_registry_checksum(code: str) -> bool:
    """True for 8 digits whose last digit is the correct check digit."""
    if not PROMOTION_REGISTRY_CODE_RE.fullmatch(code):
        return False
    return registry_code_check_digit(code[:7]) == int(code[7])
