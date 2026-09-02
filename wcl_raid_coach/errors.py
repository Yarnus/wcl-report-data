from __future__ import annotations


class WclRaidCoachError(Exception):
    code = "wcl_raid_coach_error"


class InputError(WclRaidCoachError):
    code = "invalid_input"


class CredentialError(WclRaidCoachError):
    code = "credentials_unavailable"


class ApiError(WclRaidCoachError):
    code = "wcl_api_error"


class RateLimitError(ApiError):
    code = "wcl_rate_limit"


class RevisionChangedError(ApiError):
    code = "report_revision_changed"


class DatasetError(WclRaidCoachError):
    code = "dataset_error"
