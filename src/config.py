from dataclasses import dataclass

TARGET_UPSIDE_THRESHOLD = 0.30
REPORT_MAX_AGE_DAYS = 90
HORIZONS = (5, 10, 20, 60)
FOLDER_ID = "13XG_Eqx1hGDeZwX9Awj7cTxT5E10dkhT"
SHEET_ID = "1VHB4WEwWt04eDWhOu8aM2bQLHCBUgEeoUrL3wUTuyew"
FOLDER_NAME = "基本面選股"


@dataclass(frozen=True)
class Config:
    folder_id: str = FOLDER_ID
    sheet_id: str = SHEET_ID
    threshold: float = TARGET_UPSIDE_THRESHOLD
    max_age_days: int = REPORT_MAX_AGE_DAYS
