from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Optional

import httpx


STRIPE_API_BASE = "https://api.stripe.com/v1"
STRIPE_API_VERSION = "2024-04-10"


class StripeService:
    """
    Pure Stripe HTTP client — no DB access, no app state.

    Callers supply the secret key from the encrypted settings store.
    Never log or return the secret key.
    """

    def __init__(self, secret_key: str, mode: str = "test") -> None:
        self._secret = secret_key
        self._mode = mode

    @property
    def configured(self) -> bool:
        return bool(self._secret)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._secret}",
            "Stripe-Version": STRIPE_API_VERSION,
        }

    # ── Account ─────────────────────────────────────────────────────────────

    async def get_account(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{STRIPE_API_BASE}/account", headers=self._headers())
            r.raise_for_status()
            return r.json()

    # ── Customers ───────────────────────────────────────────────────────────

    async def create_or_get_customer(
        self,
        *,
        district_id: int,
        district_name: str,
        email: str = "",
        existing_customer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if existing_customer_id:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{STRIPE_API_BASE}/customers/{existing_customer_id}",
                    headers=self._headers(),
                )
                if r.status_code == 200:
                    return r.json()

        data: Dict[str, str] = {
            "name": district_name[:255],
            "metadata[district_id]": str(district_id),
            "metadata[mode]": self._mode,
        }
        if email:
            data["email"] = email[:255]

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{STRIPE_API_BASE}/customers",
                headers=self._headers(),
                data=data,
            )
            r.raise_for_status()
            return r.json()

    # ── Checkout ────────────────────────────────────────────────────────────

    async def create_checkout_session(
        self,
        *,
        price_id: str,
        customer_id: str,
        district_id: int,
        district_slug: str,
        success_url: str,
        cancel_url: str,
    ) -> Dict[str, Any]:
        data = {
            "mode": "subscription",
            "customer": customer_id,
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata[district_id]": str(district_id),
            "metadata[district_slug]": district_slug,
            "subscription_data[metadata][district_id]": str(district_id),
            "subscription_data[metadata][district_slug]": district_slug,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{STRIPE_API_BASE}/checkout/sessions",
                headers=self._headers(),
                data=data,
            )
            r.raise_for_status()
            return r.json()

    # ── Billing portal ───────────────────────────────────────────────────────

    async def create_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str,
    ) -> Dict[str, Any]:
        data = {"customer": customer_id, "return_url": return_url}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{STRIPE_API_BASE}/billing_portal/sessions",
                headers=self._headers(),
                data=data,
            )
            r.raise_for_status()
            return r.json()

    # ── Subscriptions ────────────────────────────────────────────────────────

    async def get_subscription(self, subscription_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{STRIPE_API_BASE}/subscriptions/{subscription_id}",
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    async def list_customer_subscriptions(
        self, customer_id: str
    ) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{STRIPE_API_BASE}/subscriptions",
                headers=self._headers(),
                params={"customer": customer_id, "limit": "10"},
            )
            r.raise_for_status()
            return r.json().get("data", [])

    # ── Webhook signature ────────────────────────────────────────────────────

    @staticmethod
    def verify_webhook(
        payload_bytes: bytes,
        signature_header: str,
        webhook_secret: str,
        tolerance: int = 300,
    ) -> Dict[str, Any]:
        """
        Verify Stripe webhook signature per
        https://stripe.com/docs/webhooks/signatures

        Returns the parsed event dict on success.
        Raises ValueError if signature is invalid or timestamp too old.
        """
        if not signature_header or not webhook_secret:
            raise ValueError("Missing Stripe-Signature header or webhook secret")

        parts: Dict[str, List[str]] = {}
        for segment in signature_header.split(","):
            k, _, v = segment.partition("=")
            parts.setdefault(k.strip(), []).append(v.strip())

        timestamp_str = parts.get("t", ["0"])[0]
        v1_sigs = parts.get("v1", [])
        if not timestamp_str or not v1_sigs:
            raise ValueError("Malformed Stripe-Signature header")

        ts = int(timestamp_str)
        now = int(time.time())
        if abs(now - ts) > tolerance:
            raise ValueError(
                f"Webhook timestamp outside tolerance window (diff={abs(now - ts)}s)"
            )

        signed_payload = timestamp_str.encode() + b"." + payload_bytes
        expected = hmac.new(
            webhook_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        if not any(hmac.compare_digest(expected, sig) for sig in v1_sigs):
            raise ValueError("Stripe webhook signature mismatch")

        return json.loads(payload_bytes)

    @staticmethod
    def billing_status_from_stripe(stripe_status: str) -> str:
        """Map Stripe subscription status → BlueBird billing_status."""
        return {
            "active": "active",
            "trialing": "trial",
            "past_due": "past_due",
            "canceled": "cancelled",
            "unpaid": "past_due",
            "incomplete": "trial",
            "incomplete_expired": "expired",
            "paused": "suspended",
        }.get(stripe_status, "trial")
