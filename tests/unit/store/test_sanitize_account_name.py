"""Tests for finstore.storage.paths.sanitize_account_name."""
import pytest

from finstore.storage.paths import sanitize_account_name


class TestSanitizeAccountName:
    @pytest.mark.parametrize("name,expected", [
        # Basic dedup: digits outside parens removed
        ("Investor Checking ...882 (882)", "Investor_Checking_882"),
        ("WELLSTRADE ...8581 (8581)", "WELLSTRADE_8581"),
        ("EVERYDAY CHECKING ...1817 (1817)", "EVERYDAY_CHECKING_1817"),
        # No dedup needed: digits only in parens
        ("Schwab Investor Card (1008)", "Schwab_Investor_Card_1008"),
        ("High Yield Savings Account (5358)", "High_Yield_Savings_Account_5358"),
        # Exactly 40 chars without truncation
        ("Amazon Prime Rewards Visa Signature (4825)", "Amazon_Prime_Rewards_Visa_Signature_4825"),
        # Emoji stripped
        ("VISA SIGNATURE\U0001f3c4 CARD ...1605 (1605)", "VISA_SIGNATURE_CARD_1605"),
        # Truncation with __ midpoint (len > 40)
        (
            "Steven X Li - Rollover IRA Brokerage Account (4313)",
            "Steven_X_Li_Rollove__kerage_Account_4313",
        ),
        # Uniqueness between two WF accounts with same last-4
        ("WELLSTRADE BUSINESS ...1817 (1817)", "WELLSTRADE_BUSINESS_1817"),
        # Long Vanguard trust name
        (
            "Steven X Li, UA 10-24-2008 Steven Li Living Trust - Cash Plus Account (7231)",
            "Steven_X_Li_UA_10_2__h_Plus_Account_7231",
        ),
    ])
    def test_sanitize(self, name: str, expected: str) -> None:
        assert sanitize_account_name(name) == expected
