from __future__ import annotations


class WclReportDataError(Exception):
    code = "wcl_report_data_error"


class InputError(WclReportDataError):
    code = "invalid_input"


class CredentialError(WclReportDataError):
    code = "credentials_unavailable"


class ApiError(WclReportDataError):
    code = "wcl_api_error"


class RateLimitError(ApiError):
    code = "wcl_rate_limit"


class RevisionChangedError(ApiError):
    code = "report_revision_changed"


class DatasetError(WclReportDataError):
    code = "dataset_error"
