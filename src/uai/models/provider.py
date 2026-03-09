"""Provider-related enums and data models."""
from enum import Enum, auto


class BackendType(str, Enum):
    API = "api"    # Direct HTTP/SDK call to provider API
    CLI = "cli"    # Local CLI subprocess


class ProviderStatus(str, Enum):
    AVAILABLE = "available"
    RATE_LIMITED = "rate_limited"
    AUTH_ERROR = "auth_error"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"
    COOLDOWN = "cooldown"


class TaskCapability(str, Enum):
    """Task types that providers specialise in, ordered by specificity."""
    DEBUGGING = "debugging"
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    ARCHITECTURE = "architecture"
    LONG_CONTEXT = "long_context"   # Large files / whole codebases
    GENERAL_CHAT = "general_chat"
    DATA_ANALYSIS = "data_analysis"
    BATCH_PROCESSING = "batch_processing"
    PRIVACY_AUDIT = "privacy_audit"
