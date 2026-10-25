"""Keep a CSV cell from being read as a spreadsheet formula.

Shared by every export (FR-47, FR-69): a cell that starts with one of these
characters is prefixed with an apostrophe so Excel and Sheets show it as text.
"""

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def text_cell(value: object) -> str:
    """A cell that a spreadsheet will not run as a formula."""
    cell = "" if value is None else str(value)
    return f"'{cell}" if cell.startswith(_FORMULA_PREFIXES) else cell
