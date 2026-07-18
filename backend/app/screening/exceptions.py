"""Stable screening-agent errors."""


class ScreeningError(Exception):
    code = "SCREENING_ERROR"


class ScreeningDataError(ScreeningError):
    code = "SCREENING_DATA_ERROR"
