"""Storefront price formatting and disclosed foreign-currency conversion."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import os


DEFAULT_USD_TO_TWD_RATE = "31.685"
DEFAULT_USD_RATE_AS_OF = "2026-08-30T09:25:00+08:00"
RATE_SOURCE = "臺灣銀行美金即期賣出匯率"
RATE_SOURCE_URL = "https://rate.bot.com.tw/xrt?Lang=zh-TW"


def _decimal(value) -> Decimal:
    try:
        parsed = Decimal(str(value or 0))
        return parsed if parsed.is_finite() else Decimal("0")
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def display_price(value, currency="TWD") -> str:
    amount = _decimal(value)
    currency = str(currency or "TWD").upper()
    if currency == "TWD":
        return f"NT${amount.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,}"
    if currency == "USD":
        return f"US${amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"
    return f"{currency} {amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def _usd_rate_metadata() -> dict:
    configured = os.getenv("USD_TO_TWD_RATE", DEFAULT_USD_TO_TWD_RATE)
    rate = _decimal(configured)
    if rate <= 0:
        rate = Decimal(DEFAULT_USD_TO_TWD_RATE)
    return {
        "rate": rate,
        "source": RATE_SOURCE,
        "sourceUrl": RATE_SOURCE_URL,
        "asOf": os.getenv("USD_TO_TWD_RATE_AS_OF", DEFAULT_USD_RATE_AS_OF),
    }


def price_for_frontend(value, currency="TWD") -> dict:
    """Return a display price while preserving an auditable source price.

    The conversion uses Decimal and ROUND_HALF_UP because TWD is displayed as
    a whole-dollar estimate.  The database/source value remains untouched.
    """
    original_currency = str(currency or "TWD").upper()
    if value is None or (isinstance(value, str) and not value.strip()):
        return {
            "amount": None,
            "currency": original_currency,
            "display": None,
            "converted": False,
            "note": None,
            "conversion": None,
        }
    original_amount = _decimal(value)
    if original_currency != "USD":
        return {
            "amount": float(original_amount),
            "currency": original_currency,
            "display": display_price(original_amount, original_currency),
            "converted": False,
            "note": None,
            "conversion": None,
        }

    metadata = _usd_rate_metadata()
    unrounded_twd = original_amount * metadata["rate"]
    twd_amount = unrounded_twd.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    calculation = (
        f"{display_price(original_amount, 'USD')} × {metadata['rate']} "
        f"= {display_price(twd_amount, 'TWD')}"
    )
    note = (
        f"此價格為本站依{metadata['source']}換算，並非品牌台灣官方定價；"
        f"換算公式：{calculation}。實際結帳金額請以品牌官網及發卡機構為準。"
    )
    return {
        "amount": float(twd_amount),
        "currency": "TWD",
        "display": display_price(twd_amount, "TWD"),
        "converted": True,
        "note": note,
        "conversion": {
            "originalAmount": float(original_amount),
            "originalCurrency": original_currency,
            "originalDisplay": display_price(original_amount, original_currency),
            "rateToTwd": float(metadata["rate"]),
            "rateSource": metadata["source"],
            "rateSourceUrl": metadata["sourceUrl"],
            "rateAsOf": metadata["asOf"],
            "rounding": "四捨五入至新台幣整數",
            "calculation": calculation,
            "disclaimer": note,
        },
    }
