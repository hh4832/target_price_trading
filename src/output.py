import io
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from .config import FOLDER_NAME

SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets.readonly"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


def clients():
    required = ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN")
    values = {key: os.environ.get(key) for key in required}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"Missing Google OAuth credentials: {', '.join(missing)}")
    credentials = Credentials(
        token=None,
        refresh_token=values["GOOGLE_OAUTH_REFRESH_TOKEN"],
        token_uri=TOKEN_URI,
        client_id=values["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=values["GOOGLE_OAUTH_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False), build("sheets", "v4", credentials=credentials, cache_discovery=False)


def verify_folder(drive, folder_id):
    meta = drive.files().get(fileId=folder_id, fields="id,name,mimeType,trashed", supportsAllDrives=True).execute()
    if meta["id"] != folder_id or meta["name"] != FOLDER_NAME or meta["mimeType"] != "application/vnd.google-apps.folder" or meta.get("trashed"):
        raise ValueError("Drive folder ID/name validation failed")


def sheet_values(sheets, sheet_id, tab):
    return sheets.spreadsheets().values().get(spreadsheetId=sheet_id, range=f"'{tab}'!A:AZ", valueRenderOption="FORMATTED_VALUE").execute().get("values", [])


def find_child(drive, parent, name):
    safe = name.replace("'", "\\'")
    result = drive.files().list(q=f"'{parent}' in parents and name = '{safe}' and trashed = false", fields="nextPageToken,files(id,name,mimeType)", pageSize=100, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    matches = result["files"]
    if len(matches) > 1 or result.get("nextPageToken"):
        raise ValueError(f"Ambiguous Drive child {name}")
    return matches[0] if matches else None


def read_csv(drive, folder_id, name, columns):
    item = find_child(drive, folder_id, name)
    if not item:
        return pd.DataFrame(columns=columns)
    data = drive.files().get_media(fileId=item["id"]).execute()
    return pd.read_csv(io.BytesIO(data)).reindex(columns=columns)


def read_state(drive, folder_id):
    item = find_child(drive, folder_id, "state.json")
    return json.loads(drive.files().get_media(fileId=item["id"]).execute()) if item else {}


def put_file(drive, parent, name, data, mime, *, replace=False):
    old = find_child(drive, parent, name)
    if old and not replace:
        raise FileExistsError(f"Drive output already exists: {name}")
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=False)
    if old:
        return drive.files().update(fileId=old["id"], media_body=media, fields="id").execute()["id"]
    return drive.files().create(body={"name": name, "parents": [parent]}, media_body=media, fields="id", supportsAllDrives=True).execute()["id"]


def csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8-sig")


def archive(drive, folder_id, frames, run_info, commit):
    timestamp = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d_%H%M%S")
    name = f"{timestamp}_{commit}"
    if find_child(drive, folder_id, name):
        raise FileExistsError(name)
    archive_id = drive.files().create(body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [folder_id]}, fields="id", supportsAllDrives=True).execute()["id"]
    for filename, df in frames.items():
        put_file(drive, archive_id, filename, csv_bytes(df), "text/csv")
    put_file(drive, archive_id, "run_info.txt", run_info.encode("utf-8"), "text/plain")
    # Every successful execution becomes the current official output. state.json is
    # advanced separately by the pipeline only when the FinLab market date advances.
    for filename in ("candidate.csv", "signal_ledger.csv", "signal_returns.csv", "last_screen.csv", "report_registry.csv"):
        if filename in frames:
            put_file(drive, folder_id, filename, csv_bytes(frames[filename]), "text/csv", replace=True)
    return name
