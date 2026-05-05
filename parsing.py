"""Shared parsing for dates and currency amounts used across CSV loaders.""" # Module docstring describing the purpose of the file
# PINNED SNAPSHOT — sourced from https://github.com/PrincetonAfeez/ledger-logic
# This is the original copy of parsing.py pinned at the version that passed
# the Ledger Logic evaluation. Any updates must be replicated to all repositories within Ledger Logic.

from __future__ import annotations # Enable postponed evaluation of type annotations for forward references

import datetime # Import the datetime module for date and time handling
from datetime import date, datetime # Specifically import the date and datetime classes for type hinting and parsing
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation # Import decimal utilities for high-precision currency rounding


def parse_date(date_text: str) -> date: # Define a function that converts a string into a date object
    """Parse several common CSV date formats.

    Slash-separated dates try **US month/day/year first** (``%m/%d/%Y``). When that
    fails—e.g. day is 13–31—**day/month/year** (``%d/%m/%Y``) is tried so exports like
    ``31/01/2024`` still parse. If both day and month are ≤12, the US interpretation wins
    (``01/02/2024`` → 2 January, not 1 February).
    """ # Function docstring explaining the logic and priority of date format matching
    raw = date_text.strip() # Remove leading and trailing whitespace from the input string
    patterns = [ # Initialize a list of date format patterns to attempt matching against
        "%Y-%m-%d", # ISO format: Year-Month-Day (e.g., 2026-04-07)
        "%m/%d/%Y", # US format with 4-digit year: Month/Day/Year (e.g., 04/07/2026)
        "%m/%d/%y", # US format with 2-digit year: Month/Day/Year (e.g., 04/07/26)
        "%Y/%m/%d", # Alternative format: Year/Month/Day (e.g., 2026/04/07)
        "%d/%m/%Y", # European/Global format with 4-digit year: Day/Month/Year (e.g., 07/04/2026)
        "%d/%m/%y", # European/Global format with 2-digit year: Day/Month/Year (e.g., 07/04/26)
    ] # End of the patterns list
    for pattern in patterns: # Iterate through each date pattern in the defined list
        try: # Start a block to attempt parsing with the current pattern
            return datetime.strptime(raw, pattern).date() # Attempt to parse the string and return the resulting date object
        except ValueError: # Catch the error if the string does not match the current pattern
            continue # Move to the next pattern in the list if the current one fails
    raise ValueError(f"Unsupported date format: {date_text}") # Raise an error if none of the patterns match the input string


def parse_amount(amount_text: str) -> float: # Define a function to convert currency strings into standardized float values
    """Parse a bank-style amount string into a non-negative float (two decimal places).

    Strips ``$``, commas, and common space-like separators used as grouping (ASCII and
    narrow no-break space). Parentheses or a leading minus denote debits; the result is
    always ``>= 0``. Values are rounded **half-up** to cents before converting to
    ``float``, matching :func:`ledgerlogic.change_maker.parse_amount_to_cents` style.

    Scientific notation (``1e2``) is rejected for consistency with interactive amount entry.
    """ # Function docstring outlining the cleaning, rounding, and validation logic
    original = (amount_text or "").strip() # Handle null inputs and remove surrounding whitespace
    cleaned = ( # Start a multi-step string replacement chain to sanitize the input
        original.replace("$", "") # Remove the currency symbol
        .replace(",", "") # Remove thousands-separator commas
        .replace("\xa0", "") # Remove non-breaking space characters
        .replace("\u202f", "") # Remove narrow non-breaking space characters
        .strip() # Remove any remaining whitespace after character replacement
    ) # End of the cleaning chain
    if not cleaned: # Check if the resulting string is empty
        raise ValueError("Blank amount") # Raise an error if no numeric data was found
    if "e" in cleaned.lower(): # Check if the string contains scientific notation characters
        raise ValueError( # Raise an error to maintain consistency with standard currency entry
            "Scientific notation is not supported. Use a plain amount like 12.34 or $1,234.56." # Error message providing valid examples
        ) # End of the error block

    negative = False # Initialize a flag to track if the transaction is a debit (negative)
    if cleaned.startswith("(") and cleaned.endswith(")"): # Detect accounting-style negative numbers in parentheses
        negative = True # Mark the amount as negative
        cleaned = cleaned[1:-1].strip() # Remove the parentheses from the string
    if cleaned.startswith("+"): # Detect and handle explicit positive sign prefixes
        cleaned = cleaned[1:].strip() # Remove the plus sign from the string
    if cleaned.startswith("-"): # Detect standard negative sign prefixes
        negative = True # Mark the amount as negative
        cleaned = cleaned[1:].strip() # Remove the minus sign from the string
    if not cleaned: # Re-verify that the string is not empty after removing signs/parentheses
        raise ValueError("Blank amount") # Raise an error if the string is now empty

    try: # Start a block to attempt numeric conversion
        decimal_amount = Decimal(cleaned) # Convert the sanitized string into a high-precision Decimal object
    except InvalidOperation as exc: # Catch errors caused by non-numeric characters in the string
        raise ValueError(f"Invalid amount: {amount_text!r}") from exc # Raise a ValueError while preserving the original exception context

    rounded = decimal_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) # Round the amount to exactly two decimal places using half-up logic
    amount = float(rounded) # Convert the rounded Decimal object into a standard float
    if negative: # Check the flag set earlier to determine if the value was originally negative
        amount = -amount # Re-apply the negative sign to the float value
    return abs(amount) # Return the absolute value to ensure the result is non-negative per requirements