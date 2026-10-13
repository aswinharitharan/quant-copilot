import calendar
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Set, Tuple, Union
import pandas as pd


class ExpiryCalendar:
    """
    NSE Derivative Expiry Calendar.
    
    Computes monthly equity & stock futures expiry dates according to
    National Stock Exchange (NSE) rules:
    - Default: Last Thursday of the expiry month.
    - Holiday Adjustment: If the last Thursday is a market trading holiday
      or weekend, the expiry date shifts backward to the immediately preceding
      trading day.
    """

    THURSDAY = 3  # datetime.date.weekday() convention: Monday=0 ... Sunday=6

    def __init__(self, holidays_csv_path: Optional[str] = None):
        """
        Initialize the calendar.
        
        Args:
            holidays_csv_path: Optional path to NSE holidays CSV. If omitted,
                defaults to 'config/nse_holidays.csv' relative to the project root.
        """
        if holidays_csv_path is None:
            # Locate config/nse_holidays.csv relative to this file's root
            project_root = Path(__file__).resolve().parent.parent.parent
            default_path = project_root / "config" / "nse_holidays.csv"
            holidays_csv_path = str(default_path)
        
        self.holidays: Set[date] = self._load_holidays(holidays_csv_path)

    @staticmethod
    def _load_holidays(csv_path: str) -> Set[date]:
        """Load holiday dates from CSV."""
        path = Path(csv_path)
        if not path.exists():
            return set()
        
        df = pd.read_csv(path)
        if "date" not in df.columns:
            return set()
        
        dates = pd.to_datetime(df["date"]).dt.date
        return set(dates)

    def get_monthly_expiry(self, year: int, month: int) -> date:
        """
        Return the exact NSE monthly stock futures expiry date for a given year and month.
        
        Args:
            year: Four-digit year (e.g., 2024)
            month: Month integer 1-12
            
        Returns:
            datetime.date representing the final trading day of the contract.
        """
        if not (1 <= month <= 12):
            raise ValueError(f"Invalid month: {month}. Must be between 1 and 12.")

        # 1. Find the last Thursday of the month
        last_day_num = calendar.monthrange(year, month)[1]
        last_date = date(year, month, last_day_num)
        offset = (last_date.weekday() - self.THURSDAY) % 7
        raw_expiry = last_date - timedelta(days=offset)

        # 2. Adjust backward if it lands on a holiday or weekend
        return self._adjust_for_holidays(raw_expiry)

    def _adjust_for_holidays(self, d: date) -> date:
        """Step backward until a non-holiday, non-weekend trading day is found."""
        while d in self.holidays or d.weekday() >= 5:  # 5=Saturday, 6=Sunday
            d -= timedelta(days=1)
        return d

    def get_expiry_schedule(self, year: int) -> List[date]:
        """Return all 12 monthly expiry dates for a specific year in chronological order."""
        return [self.get_monthly_expiry(year, month) for month in range(1, 13)]

    def get_next_expiry(self, current_date: Union[date, datetime]) -> date:
        """
        Given any current date, returns the next upcoming monthly expiry date
        (or today's date if today is the expiry date).
        """
        if isinstance(current_date, datetime):
            current_date = current_date.date()

        # Check current month expiry
        this_month_exp = self.get_monthly_expiry(current_date.year, current_date.month)
        if this_month_exp >= current_date:
            return this_month_exp

        # Otherwise, expiry is next month
        next_month = current_date.month + 1
        next_year = current_date.year
        if next_month > 12:
            next_month = 1
            next_year += 1

        return self.get_monthly_expiry(next_year, next_month)

    def add_dte_column(
        self,
        df: pd.DataFrame,
        year_range: Tuple[int, int] = (2020, 2027),
    ) -> pd.DataFrame:
        """
        Add a 'days_to_expiry' (DTE) integer column to an OHLCV DataFrame.
        
        Assumes the DataFrame index is a DatetimeIndex (or contains timestamp values).
        DTE = calendar days remaining until the contract's monthly expiry date:
          - DTE = 0 on the expiry day itself.
          - DTE = 1 on the day immediately preceding expiry.
        """
        if df.empty:
            df_out = df.copy()
            df_out["days_to_expiry"] = pd.Series(dtype="int64")
            return df_out

        # Pre-compute all expiries across the specified year range
        all_expiries: List[date] = []
        for y in range(year_range[0], year_range[1] + 1):
            all_expiries.extend(self.get_expiry_schedule(y))
        all_expiries.sort()

        def _calculate_dte(ts) -> int:
            d = ts.date() if hasattr(ts, "date") else pd.to_datetime(ts).date()
            for exp in all_expiries:
                if exp >= d:
                    return (exp - d).days
            # Fallback if beyond range
            return (self.get_next_expiry(d) - d).days

        df_out = df.copy()
        df_out["days_to_expiry"] = [_calculate_dte(idx) for idx in df_out.index]
        return df_out
