"""Shared file helpers for LedgerLogic."""


from __future__ import annotations # Enable forward references for type hints in Python 3.7+

import csv # Import the CSV module for reading and writing spreadsheet-style files
import json # Import the JSON module for handling configuration and data interchange formats
import os # Import the OS module for interacting with the operating system (environment variables, file replacement)
import uuid # Import the UUID module to generate unique identifiers for temporary file names
import warnings # Import the warnings module to issue non-fatal alerts during runtime
from collections.abc import Callable, Sequence # Import abstract base classes for function and list-like type hinting
from pathlib import Path # Import Path for object-oriented filesystem path manipulation
from typing import Any, cast # Import Any for flexible typing and cast for explicit type overriding

try:  # Attempt a block for package-relative imports
    from .parsing import parse_amount # Try to import currency parsing logic from a local sibling module
    from .schemas import CategorizedRecord # Try to import the transaction data structure from a local sibling module
except ImportError:  # Execute this block if the code is run as a standalone script rather than a package
    from parsing import parse_amount # Import currency parsing from the same directory level
    from schemas import CategorizedRecord # Import data schemas from the same directory level

CATEGORIZED_FIELDS = [ # Define the standard list of column headers used for transaction CSV files
    "date", # Transaction date column name
    "merchant", # Merchant/Vendor name column name
    "amount", # Monetary value column name
    "category", # High-level budget category column name
    "subcategory", # Specific budget sub-category column name
    "confidence", # Matching algorithm certainty score column name
    "match_type", # Type of match (exact, fuzzy, unknown) column name
] # End of CSV field definition list


def _atomic_write_file(path: Path, write: Callable[[Path], None]) -> None: # Define a function to safely write files by using a temporary copy
    """Write to a unique temp file in the same directory, then replace ``path``.""" # Explain the "atomic" write pattern to prevent data corruption
    path.parent.mkdir(parents=True, exist_ok=True) # Ensure the destination directory exists before attempting to write
    tmp = path.parent / f".{path.name}.tmp.{uuid.uuid4().hex}" # Create a hidden, unique temporary file path in the same folder
    try: # Start a block to attempt the actual file writing process
        write(tmp) # Execute the provided callback function to write data into the temporary file
    except Exception: # Catch any error that occurs during the writing process
        tmp.unlink(missing_ok=True) # Delete the failed temporary file to keep the folder clean
        raise # Re-raise the exception to inform the caller that the save failed
    try: # Start a block to finalize the file save
        os.replace(tmp, path) # Move the temporary file to the final destination, overwriting the old one if it exists
    except OSError: # Catch errors specifically related to operating system file moves
        tmp.unlink(missing_ok=True) # Delete the temporary file if the move operation failed
        raise # Re-raise the error for further handling


def get_data_dir(base_dir: str | Path | None = None) -> Path: # Define a function to locate or initialize the application data storage folder
    """Return the data directory and create it if needed.

    If ``base_dir`` is omitted, uses the ``LEDGERLOGIC_DATA_DIR`` environment
    variable when set; otherwise ``./ledgerlogic_data`` under the current
    working directory.
    """ # Explain the hierarchy used to determine where data is stored
    if base_dir is not None: # Check if a specific directory was passed as an argument
        root = Path(base_dir) # Use the provided path if available
    else: # Fall back to environment variables or defaults if no path was provided
        env = (os.environ.get("LEDGERLOGIC_DATA_DIR") or "").strip() # Retrieve a custom path from the OS environment variables
        if env: # If the environment variable was found and is not empty
            root = Path(env).expanduser() # Resolve the path and handle shorthand like the '~' user directory
        else: # If no custom path is set anywhere
            root = Path.cwd() / "ledgerlogic_data" # Default to a folder named 'ledgerlogic_data' in the current location
    root.mkdir(parents=True, exist_ok=True) # Physically create the folder on the drive if it doesn't already exist
    return root # Return the finalized path object for use in other functions


def get_categorized_path(base_dir: str | Path | None = None) -> Path: # Define a helper to find the CSV file path
    return get_data_dir(base_dir) / "categorized_transactions.csv" # Combine the data folder with the specific CSV file name


def get_budget_profile_path(base_dir: str | Path | None = None) -> Path: # Define a helper to find the budget configuration path
    return get_data_dir(base_dir) / "budget_profile.json" # Combine the data folder with the specific budget JSON file name


def get_investment_profile_path(base_dir: str | Path | None = None) -> Path: # Define a helper to find the investment settings path
    return get_data_dir(base_dir) / "investment_scenarios.json" # Combine the data folder with the investment JSON file name


def get_report_path(base_dir: str | Path | None = None) -> Path: # Define a helper to find the final text report path
    return get_data_dir(base_dir) / "ledgerlogic_report.txt" # Combine the data folder with the default report file name


def format_money(amount: float) -> str: # Define a function to turn numbers into readable currency strings
    """Format a number as dollars.""" # Brief explanation of formatting goal
    return f"${amount:,.2f}" # Return a string with a dollar sign, comma separators, and two decimal places


def save_categorized_transactions( # Define a function to export transaction records to a CSV file
    records: Sequence[CategorizedRecord], # Accept a list or tuple of transaction data objects
    path: str | Path | None = None, # Accept an optional custom file path for saving
) -> Path: # Indicate that the function returns the path where data was actually saved
    """Write categorized transactions to CSV.""" # Summarize the function's purpose
    output_path = Path(path) if path else get_categorized_path() # Decide between a custom path or the default storage location

    def write_csv(tmp: Path) -> None: # Define an internal helper to handle the actual CSV formatting
        with tmp.open("w", newline="", encoding="utf-8") as handle: # Open the temporary file for writing text with UTF-8 encoding
            writer = csv.DictWriter(handle, fieldnames=CATEGORIZED_FIELDS) # Initialize a CSV writer that maps dictionaries to columns
            writer.writeheader() # Write the top row of column headers to the file
            for record in records: # Loop through every transaction record provided
                row: dict[str, Any] = {} # Initialize an empty dictionary for the current row
                for field in CATEGORIZED_FIELDS: # Ensure only the specified columns are included in the output
                    row[field] = record.get(field, "") # Extract the field value or use an empty string if missing
                writer.writerow(row) # Write the prepared dictionary as a new line in the CSV

    _atomic_write_file(output_path, write_csv) # Execute the safe atomic write process using the internal helper
    return output_path # Return the final path where the file was saved


def load_categorized_transactions(path: str | Path | None = None) -> tuple[list[dict[str, Any]], list[str]]: # Define a function to read CSV data back into Python
    """Read categorized transactions back from CSV.

    Returns ``(records, warnings)``. Warnings describe rows where numeric
    fields could not be parsed (values default to ``0.0``). Amounts use the
    same rules as :func:`ledgerlogic.parsing.parse_amount`.
    """ # Explain the return structure and the error handling logic
    input_path = Path(path) if path else get_categorized_path() # Determine which file to read from
    if not input_path.exists(): # Check if the file actually exists on the drive
        return [], [] # Return empty lists if there is no data to load

    records: list[dict[str, Any]] = [] # Initialize a list to hold successfully parsed transactions
    load_warnings: list[str] = [] # Initialize a list to collect notes about malformed data
    with input_path.open("r", newline="", encoding="utf-8-sig") as handle: # Open the file for reading, handling potential Byte Order Marks
        reader = csv.DictReader(handle) # Initialize a reader that turns CSV rows into Python dictionaries
        for row_index, row in enumerate(reader, start=2): # Iterate through rows, keeping track of the line number for warnings
            if not row: # Skip any row that is completely empty
                continue # Move to the next line
            if not any((v or "").strip() for v in row.values()): # Skip rows that contain only whitespace or empty cells
                continue # Move to the next line
            amount_cell = (row.get("amount") or "").strip() # Extract and clean the text from the 'amount' column
            if not amount_cell: # Check if the amount field is blank
                amount = 0.0 # Default to zero if no value was provided
            else: # Attempt to parse the text into a number
                try: # Start a block to catch potential parsing errors
                    amount = parse_amount(amount_cell) # Use the custom parsing logic to convert the currency string
                except ValueError: # Catch errors if the amount text is not a valid currency format
                    load_warnings.append( # Record a warning so the user knows this row had a problem
                        f"CSV row {row_index}: could not parse amount {amount_cell!r}; using 0.00." # Descriptive error message
                    ) # End of warning addition
                    amount = 0.0 # Default to zero if the text was unreadable
            confidence_text = row.get("confidence", "") or "0" # Extract the confidence score text, defaulting to '0' if empty
            try: # Start a block to catch floating-point conversion errors
                confidence = float(confidence_text) # Convert the confidence string into a decimal number
            except ValueError: # Catch errors if the confidence text is not a valid number
                load_warnings.append( # Record a warning for the malformed confidence value
                    f"CSV row {row_index}: could not parse confidence {confidence_text!r}; using 0.0." # Descriptive error message
                ) # End of warning addition
                confidence = 0.0 # Default to zero for unreadable confidence scores

            records.append( # Add a standardized dictionary to the list of loaded records
                { # Start of the record dictionary
                    "date": row.get("date", ""), # Map the 'date' column
                    "merchant": row.get("merchant", ""), # Map the 'merchant' column
                    "amount": amount, # Map the successfully parsed amount
                    "category": row.get("category", "Unknown"), # Map the 'category' or use a placeholder
                    "subcategory": row.get("subcategory", "Unknown"), # Map the 'subcategory' or use a placeholder
                    "confidence": confidence, # Map the successfully parsed confidence score
                    "match_type": row.get("match_type", "unknown"), # Map the 'match_type' or use a placeholder
                } # End of the record dictionary
            ) # End of the list addition
    return records, load_warnings # Return the final list of transactions and any notes about data errors


def save_json(data: dict[str, Any], path: str | Path) -> Path: # Define a function to save configuration data as a JSON file
    """Save JSON data with readable indentation.""" # Summarize the save behavior
    output_path = Path(path) # Ensure the path is a Path object

    def write_json(tmp: Path) -> None: # Define an internal helper for the JSON writing logic
        with tmp.open("w", encoding="utf-8") as handle: # Open the temporary file for text writing
            json.dump(data, handle, indent=2) # Convert the dictionary to JSON text with a 2-space indent for readability

    _atomic_write_file(output_path, write_json) # Perform the safe atomic save using the helper
    return output_path # Return the path where the JSON was stored


def load_json(path: str | Path, default: dict[str, Any] | None = None) -> dict[str, Any]: # Define a function to safely load JSON data
    """Load JSON object data or return a default if missing, invalid, or not a JSON object.""" # Explain the robust fallback logic
    input_path = Path(path) # Ensure the path is a Path object
    if not input_path.exists(): # Check if the configuration file is missing
        return {} if default is None else default # Return an empty dictionary or the provided default if the file doesn't exist
    fallback = {} if default is None else default # Prepare a backup value for cases where the JSON is corrupted
    try: # Start a block to handle file reading and JSON parsing
        with input_path.open("r", encoding="utf-8") as handle: # Open the JSON file for reading
            raw = json.load(handle) # Parse the file contents into a Python structure
    except json.JSONDecodeError as exc: # Catch errors if the file content is not valid JSON
        warnings.warn(f"Invalid JSON in {input_path}: {exc}; using default.", stacklevel=2) # Warn the user that the file is corrupted
        return fallback.copy() # Return a copy of the default value
    if not isinstance(raw, dict): # Ensure the file contains a JSON object (dictionary) and not a list or single value
        warnings.warn( # Issue a warning if the data structure is not what the app expects
            f"JSON in {input_path} is not an object (got {type(raw).__name__}); using default.", # Informative warning message
            stacklevel=2, # Ensure the warning points to the caller of this function
        ) # End of warning
        return fallback.copy() # Return the default value since the structure was wrong
    return cast(dict[str, Any], raw) # Return the successfully loaded dictionary


def write_text_report(text: str, path: str | Path | None = None) -> Path: # Define a function to save a simple text file
    """Persist a text report to disk.""" # Summarize the function's purpose
    output_path = Path(path) if path else get_report_path() # Determine if using a custom name or the default report name

    def write_txt(tmp: Path) -> None: # Define an internal helper for writing plain text
        tmp.write_text(text, encoding="utf-8") # Write the entire string to the temporary file

    _atomic_write_file(output_path, write_txt) # Perform the safe atomic save process
    return output_path # Return the path where the report was saved