from decimal import Decimal, InvalidOperation

# The biggest single amount the app accepts (10 crore). Change it here if needed.
MAX_AMOUNT = Decimal("100000000.00")
MAX_TEXT_LENGTH = 30
CENT = Decimal("0.01")


def parse_money(raw):
    """Turn the text from a form into a Decimal money amount.

    Raises decimal.InvalidOperation for anything that is not a sensible amount:
    empty, not a number, NaN, infinity, more than 2 decimal places, or bigger
    than MAX_AMOUNT. Zero and negative numbers are allowed through here, because
    each view already has its own "must be greater than zero" message.
    """
    if raw is None:
        raise InvalidOperation("missing amount")
    text = str(raw).strip()
    if not text or len(text) > MAX_TEXT_LENGTH:
        raise InvalidOperation("bad length")
    amount = Decimal(text)
    if not amount.is_finite():
        raise InvalidOperation("not a finite number")
    if abs(amount) > MAX_AMOUNT:
        raise InvalidOperation("too large")
    if amount != amount.quantize(CENT):
        raise InvalidOperation("more than 2 decimal places")
    return amount
