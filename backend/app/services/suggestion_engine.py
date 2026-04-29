"""
BlueBird Alerts — Smart Suggestion Engine

Rule-based suggestion engine with a pluggable provider architecture.
All public types are stable — a future AIProvider can be slotted in
alongside RuleBasedProvider without changing any call sites.

Usage::

    ctx = SuggestionContext(role="building_admin", prefix="/bb/school-a", ...)
    suggestions = SuggestionEngine().evaluate(ctx)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


# ── Data model ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Suggestion:
    id: str
    title: str
    description: str
    priority: str              # "high" | "medium" | "low"
    icon: str = "💡"
    action_label: str = ""
    action_url: str = ""
    dismissible: bool = True
    # Time-to-live in hours before a dismissed suggestion re-appears.
    # Use 0 for "never re-appear once dismissed".
    dismiss_ttl_hours: int = 72


@dataclass
class SuggestionContext:
    """All the state the engine uses to produce suggestions.

    Callers supply what they have; unset optional fields are treated as
    "unknown" and their corresponding rules are skipped.
    """
    role: str
    prefix: str
    user_count: int = 0
    active_user_count: int = 0
    device_count: int = 0
    apns_configured: bool = False
    fcm_configured: bool = False
    totp_enabled: bool = False
    access_code_count: int = 0
    unread_messages: int = 0
    help_requests_active: int = 0
    alert_count_7d: int = 0          # alerts (drills + live) in the last ~7 days
    district_admin_count: int = 0
    acknowledgement_rate: Optional[float] = None   # 0.0–1.0; None = not applicable
    quiet_period_active: bool = False


# ── Provider protocol ────────────────────────────────────────────────────────


@runtime_checkable
class SuggestionProvider(Protocol):
    """A strategy that produces Suggestion objects from a SuggestionContext."""

    def evaluate(self, ctx: SuggestionContext) -> list[Suggestion]:
        ...


# ── Rule-based provider ──────────────────────────────────────────────────────


class RuleBasedProvider:
    """
    Deterministic, dependency-free suggestion rules.

    Rules are grouped by concern and ordered by importance within each group.
    The engine caps the final list at 4 items and re-sorts by priority.
    """

    def evaluate(self, ctx: SuggestionContext) -> list[Suggestion]:  # noqa: C901
        out: list[Suggestion] = []
        p = ctx.prefix
        role = ctx.role.lower()

        # ── Operational urgency (always first) ───────────────────────────

        if ctx.help_requests_active > 0:
            plural = "s" if ctx.help_requests_active != 1 else ""
            out.append(Suggestion(
                id="help_requests_active",
                title=f"{ctx.help_requests_active} active help request{plural}",
                description="Staff are requesting assistance or backup — review and respond.",
                priority="high",
                icon="🙋",
                action_label="Review Requests",
                action_url=f"{p}/admin?section=dashboard#request-help",
                dismiss_ttl_hours=4,
            ))

        if ctx.unread_messages > 0:
            plural = "s" if ctx.unread_messages != 1 else ""
            out.append(Suggestion(
                id="unread_messages",
                title=f"{ctx.unread_messages} unread staff message{plural}",
                description="Staff have sent messages to the admin dashboard.",
                priority="high",
                icon="✉️",
                action_label="View Messages",
                action_url=f"{p}/admin?section=dashboard#messages",
                dismiss_ttl_hours=4,
            ))

        # ── Push infrastructure ──────────────────────────────────────────

        if not ctx.apns_configured and not ctx.fcm_configured:
            out.append(Suggestion(
                id="push_not_configured",
                title="Push notifications are not configured",
                description=(
                    "APNs (iOS) or FCM (Android) credentials are required "
                    "before alerts can reach devices."
                ),
                priority="high",
                icon="🔔",
                action_label="Open Settings",
                action_url=f"{p}/admin?section=settings",
                dismiss_ttl_hours=24,
            ))

        # ── Acknowledgement rate (live alarm signal) ─────────────────────

        if ctx.acknowledgement_rate is not None and ctx.acknowledgement_rate < 0.70:
            pct = int(ctx.acknowledgement_rate * 100)
            out.append(Suggestion(
                id="low_ack_rate",
                title=f"Alert acknowledgment rate is {pct}%",
                description=(
                    "More than 30% of alerted users haven't acknowledged. "
                    "Check device registration and connectivity."
                ),
                priority="high",
                icon="⚠️",
                action_label="Review Devices",
                action_url=f"{p}/admin?section=devices",
                dismiss_ttl_hours=24,
            ))

        # ── User / device setup ──────────────────────────────────────────

        if ctx.user_count == 0:
            out.append(Suggestion(
                id="no_users",
                title="No staff accounts created yet",
                description=(
                    "Add accounts for teachers and staff "
                    "so they can receive alerts."
                ),
                priority="high",
                icon="👤",
                action_label="Add Users",
                action_url=f"{p}/admin?section=user-management",
                dismiss_ttl_hours=48,
            ))
        elif ctx.device_count == 0 and ctx.active_user_count > 0:
            out.append(Suggestion(
                id="no_devices",
                title="No devices registered",
                description=(
                    "Staff need to install the app and register "
                    "to receive push alerts."
                ),
                priority="high",
                icon="📱",
                action_label="Generate Codes",
                action_url=f"{p}/admin?section=user-management&tab=codes",
                dismiss_ttl_hours=48,
            ))
        elif (
            ctx.active_user_count > 3
            and ctx.device_count < ctx.active_user_count * 0.5
        ):
            coverage = int(ctx.device_count / max(ctx.active_user_count, 1) * 100)
            out.append(Suggestion(
                id="low_device_coverage",
                title=f"Device coverage is low ({coverage}%)",
                description=(
                    "Fewer than half of active staff have registered devices. "
                    "Some users won't receive alerts."
                ),
                priority="medium",
                icon="📊",
                action_label="View Devices",
                action_url=f"{p}/admin?section=devices",
                dismiss_ttl_hours=72,
            ))

        if ctx.access_code_count == 0 and ctx.active_user_count > 0:
            out.append(Suggestion(
                id="no_access_codes",
                title="No access codes generated",
                description=(
                    "Access codes let staff self-register on the BlueBird app "
                    "without admin intervention."
                ),
                priority="medium",
                icon="🔑",
                action_label="Generate Codes",
                action_url=f"{p}/admin?section=user-management&tab=codes",
                dismiss_ttl_hours=72,
            ))

        # ── Drill / readiness ────────────────────────────────────────────

        if (
            ctx.alert_count_7d == 0
            and ctx.user_count > 0
            and ctx.device_count > 0
        ):
            out.append(Suggestion(
                id="no_recent_drill",
                title="No alerts in the last 7 days",
                description=(
                    "Run a training drill to verify push notifications "
                    "are reaching all registered devices."
                ),
                priority="medium",
                icon="🚨",
                action_label="Start Drill",
                action_url=f"{p}/admin?section=dashboard",
                dismiss_ttl_hours=168,  # 7 days
            ))

        # ── Security ─────────────────────────────────────────────────────

        if not ctx.totp_enabled and role in {"building_admin", "district_admin"}:
            out.append(Suggestion(
                id="no_2fa",
                title="Two-factor authentication is not enabled",
                description=(
                    "Protect this admin account from unauthorized access "
                    "with an authenticator app."
                ),
                priority="medium",
                icon="🔒",
                action_label="Set Up 2FA",
                action_url=f"{p}/admin?section=settings",
                dismiss_ttl_hours=168,
            ))

        # ── Admin structure ──────────────────────────────────────────────

        if ctx.district_admin_count == 0 and ctx.active_user_count > 5:
            out.append(Suggestion(
                id="no_district_admin",
                title="No district admin assigned",
                description=(
                    "With multiple staff accounts, consider assigning a "
                    "district admin for centralized oversight."
                ),
                priority="low",
                icon="🏛️",
                action_label="Manage Users",
                action_url=f"{p}/admin?section=user-management",
                dismiss_ttl_hours=168,
            ))

        _PRIO = {"high": 0, "medium": 1, "low": 2}
        out.sort(key=lambda s: _PRIO.get(s.priority, 99))
        return out[:4]


# ── Engine ───────────────────────────────────────────────────────────────────


class SuggestionEngine:
    """
    Orchestrates one or more SuggestionProviders and merges their output.

    Architecture:
        - ``providers`` defaults to ``[RuleBasedProvider()]``.
        - Future: add ``AIProvider`` to the list for LLM-backed suggestions.
          Results are merged, de-duplicated by ``id``, re-sorted, and capped.

    Example::

        # Rule-based only (default)
        engine = SuggestionEngine()

        # With a future AI provider appended:
        engine = SuggestionEngine(providers=[RuleBasedProvider(), AIProvider()])
    """

    def __init__(
        self,
        providers: Optional[list[SuggestionProvider]] = None,
    ) -> None:
        self._providers: list[SuggestionProvider] = (
            providers if providers is not None else [RuleBasedProvider()]
        )

    def evaluate(self, ctx: SuggestionContext) -> list[Suggestion]:
        seen: set[str] = set()
        merged: list[Suggestion] = []
        for provider in self._providers:
            for s in provider.evaluate(ctx):
                if s.id not in seen:
                    seen.add(s.id)
                    merged.append(s)
        _PRIO = {"high": 0, "medium": 1, "low": 2}
        merged.sort(key=lambda s: _PRIO.get(s.priority, 99))
        return merged[:4]
