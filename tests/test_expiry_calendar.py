from datetime import date
import pandas as pd
import pytest

from src.engine.expiry_calendar import ExpiryCalendar


def test_standard_last_thursday_expiry():
    calendar = ExpiryCalendar()
    # October 2024: 31st is a Thursday and not a trading holiday
    expiry = calendar.get_monthly_expiry(2024, 10)
    assert expiry == date(2024, 10, 31)
    assert expiry.weekday() == 3  # Thursday


def test_holiday_backward_shift_custom_holidays(tmp_path):
    # Create a temporary CSV where Thursday 2024-10-31 is marked as a holiday
    holiday_csv = tmp_path / "mock_holidays.csv"
    holiday_csv.write_text("date,name\n2024-10-31,Mock Holiday\n")

    cal = ExpiryCalendar(holidays_csv_path=str(holiday_csv))
    expiry = cal.get_monthly_expiry(2024, 10)

    # Should shift backward to Wednesday 2024-10-30
    assert expiry == date(2024, 10, 30)
    assert expiry.weekday() == 2  # Wednesday


def test_double_holiday_shift(tmp_path):
    # Both Thursday 31st and Wednesday 30th are holidays
    holiday_csv = tmp_path / "mock_holidays.csv"
    holiday_csv.write_text("date,name\n2024-10-31,Holiday 1\n2024-10-30,Holiday 2\n")

    cal = ExpiryCalendar(holidays_csv_path=str(holiday_csv))
    expiry = cal.get_monthly_expiry(2024, 10)

    # Should shift to Tuesday 2024-10-29
    assert expiry == date(2024, 10, 29)
    assert expiry.weekday() == 1  # Tuesday


def test_yearly_expiry_schedule_length():
    calendar = ExpiryCalendar()
    schedule_2025 = calendar.get_expiry_schedule(2025)

    assert len(schedule_2025) == 12
    # Ensure all expiries are business days (Monday=0 to Friday=4)
    for exp in schedule_2025:
        assert exp.weekday() < 5, f"Expiry {exp} landed on a weekend!"


def test_get_next_expiry():
    calendar = ExpiryCalendar()

    # Mid-month date
    next_exp = calendar.get_next_expiry(date(2024, 10, 15))
    assert next_exp == date(2024, 10, 31)

    # Exact expiry day -> should return today
    same_day_exp = calendar.get_next_expiry(date(2024, 10, 31))
    assert same_day_exp == date(2024, 10, 31)

    # Day after expiry -> shifts to November expiry (Nov 28, 2024)
    post_exp = calendar.get_next_expiry(date(2024, 11, 1))
    assert post_exp == date(2024, 11, 28)


def test_add_dte_column_to_dataframe():
    calendar = ExpiryCalendar()

    # Generate dates across October 2024 (Expiry is 2024-10-31)
    dates = pd.date_range("2024-10-25", "2024-10-31", freq="D")
    df = pd.DataFrame(
        {
            "open": [100.0] * len(dates),
            "high": [105.0] * len(dates),
            "low": [98.0] * len(dates),
            "close": [103.0] * len(dates),
            "volume": [1000] * len(dates),
        },
        index=dates,
    )

    df_with_dte = calendar.add_dte_column(df)

    assert "days_to_expiry" in df_with_dte.columns
    # 2024-10-31 is expiry day -> DTE must be 0
    assert df_with_dte.loc["2024-10-31", "days_to_expiry"] == 0
    # 2024-10-30 is 1 day before -> DTE must be 1
    assert df_with_dte.loc["2024-10-30", "days_to_expiry"] == 1
    # 2024-10-25 is 6 days before -> DTE must be 6
    assert df_with_dte.loc["2024-10-25", "days_to_expiry"] == 6


def test_empty_dataframe_dte():
    calendar = ExpiryCalendar()
    empty_df = pd.DataFrame()
    res = calendar.add_dte_column(empty_df)
    assert "days_to_expiry" in res.columns
    assert len(res) == 0
