"""Keystone error hierarchy (see cobol-conventions skill)."""


class KeystoneError(Exception):
    """Base class for all Keystone errors."""


class RecordError(KeystoneError):
    """A record could not be read or decoded."""


class RecordLengthError(RecordError):
    """A record does not have the length its layout requires."""


class InvalidNumericDataError(RecordError):
    """Invalid zoned or packed data (the S0C7 equivalent)."""


class FieldOverflowError(KeystoneError):
    """A result does not fit the receiving PIC (COBOL would truncate silently)."""
