# 券商目標價 baseline research

## 假設與市場機制

人工蒐集的近期券商報告所含基本面資訊，可能尚未完全反映在市場價格。本專案只追蹤研究候選：目標價相對 raw close 的 upside >30%，且報告距市場日期不超過 90 個日曆天。這些門檻未經驗證；**研究結論：修改後再測**。`CANDIDATE` 不是買進建議。

## 輸入與權限

- 固定 Google Drive folder ID `13XG_Eqx1hGDeZwX9Awj7cTxT5E10dkhT`、名稱「基本面選股」，內含 Google Sheet ID `1VHB4WEwWt04eDWhOu8aM2bQLHCBUgEeoUrL3wUTuyew`。執行時重新驗證 folder ID、名稱與 MIME type；不猜測 Colab mount path。
- 試算表分頁「基本面選股」由人手輸入，至少含 `Ticker`、`名稱`、`報告日期`、`本次目標價`、`投顧`；可含 `前次目標價`、`持有`、`買進日期`、`成本均價`。程式只讀，不更改、刪除或覆寫任何報告；額外欄位會保留在每次 `report_snapshot.csv`。同股票同投顧的新報告須新增一列，不要修改舊列。相同 ticker、broker、report_date 的兩列會報錯，請明確區分日期。
- 可另建 `CorporateActions` 分頁，首列為 `ticker,effective_date,action_type,target_factor`。分股 1→2 填 `SPLIT,0.5`；反分股 2→1 填 `REVERSE_SPLIT,2`。其他價格尺度事件需人工驗證係數；股利填 `CASH_DIVIDEND,1`，不改目標價。缺少分頁可執行，但需自行核對資料是否存在尚未分類的小型事件；調整因子相鄰交易日跳動 >10% 而無分類紀錄會直接失敗。此偵測門檻只作資料品質警示，不能保證找出所有 corporate actions。
- GitHub Actions 以擁有目標 My Drive 的 Google 使用者 OAuth 執行，使用三個 repository secrets：`GOOGLE_OAUTH_CLIENT_ID`、`GOOGLE_OAUTH_CLIENT_SECRET`、`GOOGLE_OAUTH_REFRESH_TOKEN`。refresh token 必須由同一 OAuth client 以 offline access 授權 Drive 與唯讀 Sheets scopes 取得；不得寫入程式、日誌或 commit。Service account 不用於 My Drive 輸出，因其本身沒有個人 Drive 儲存配額。
- FinLab 無瀏覽器的 CI 使用 `FINLAB_REFRESH_TOKEN`、`FINLAB_SESSION_ID`、`FINLAB_API_KEY` 三個 GitHub Secrets。先在可信任的環境執行 `python -m finlab login`，再由 `python -m finlab token --env` 取得目前官方 headless 憑證；勿貼在日誌或 commit。Colab 可直接用瀏覽器 `finlab.login()`，或將三個值存於 Colab Secrets。不要用已棄用的 `finlab.login(api_token)`。

## 執行與資料流

Actions 週一至週五 UTC 00:00（台灣 08:00）執行；手動可由 GitHub 的 workflow_dispatch 或 Colab Run All 執行。核心只有 `python -m src.pipeline`。依 FinLab `price:收盤價` 的最新實際交易日期判斷 freshness。每一次 execution 都建立獨立的 `YYYYMMDD_HHMMSS_<full-git-commit>/` 完整 archive；即使 FinLab market date 未增加，也重新計算並保存完整 snapshot，標記 `run_status=DATA_NOT_UPDATED`、`state_updated=false`、`new_signals=0`。同一 market date 重跑不推進 `state.json` 的 market date，但每次成功 execution 都會重新發布 root current outputs，讓 `signal_ledger.csv`、`signal_returns.csv`、`last_screen.csv` 代表最後一次完整成功執行；signal ID 維持冪等，避免無變更重跑產生重複訊號。archive 追蹤 execution，`state.json` 只追蹤最後正式處理的 FinLab market date。初次有新資料的執行只建立當日畫面，不回填假設的歷史 crossing。

每日以 ticker × broker 選截至交易日最新報告，過期報告仍顯示 `EXPIRED`；`daily_screen.csv` 顯示所有 active、expired 與已持有股票。另產生精簡的 `candidate.csv`，只保留當次執行 `screen_status=CANDIDATE` 的股票，欄位為 ticker、name、broker、report_date、effective_target_price、raw_close、target_upside、report_age_days，並依 target_upside 由高到低排序。`candidate.csv` 是目前候選池的 presentation output，每次完整重建，不累積歷史，也不參與 signal 或回測計算。人工持有欄位不會因候選失效而刪除。`report_event` 可辨識新報告日；ledger 將 >30% candidate 分成兩種事件：`NEW_REPORT_CANDIDATE` 是新 report 第一次被系統觀察時即已 >30%；`THRESHOLD_CROSSING` 是既有 report 前一個可觀察 market state 的 upside ≤30%、本次 >30%。兩者保留於同一 `signal_ledger.csv` 並以 `signal_type` 區分。持續超標不重複；跌回 ≤30% 後再次突破可新增 `THRESHOLD_CROSSING`。首次 report ≤30% 不產生 signal。

篩選的分母是 FinLab **raw** `price:收盤價`。原始目標價不改動；`effective_target_price` 以報告日後生效的已分類尺度事件乘上 `target_factor`。outcome 另用 FinLab `etl:adj_close`：T 收盤形成訊號，O1 是下一交易日 raw open 乘當日 `adj_close/raw_close`，C5/C10/C20/C60 是訊號後第 5/10/20/60 個交易日 adjusted close；同時計算 0050 的 O1→Ck 與兩者差值。若 O1 尚無交易日，所有 outcome 為 `PENDING`；價格缺失則失敗，不做 forward fill。載入價格時 CI 會輸出 `FINLAB_FRAME_DIAGNOSTIC` / `FINLAB_UNIVERSE_DIFF`，記錄三個 dataset 的 shape、最新日期、指定 probe tickers 是否存在，以及各 dataset ticker universe 差異的數量與最多 10 個 sample；價格失敗時另輸出 `PRICE_DATASET_DIAGNOSTIC` / `PRICE_ENTRY_DIAGNOSTIC`，記錄缺值 ticker/date 是否存在、index type、columns dtype 與 exact cell 狀態。這些 diagnostics 僅用於定位 FinLab runtime/data availability 問題，不改變 PENDING、maturity 或任何研究規則。這是描述性 forward outcome，未扣成本、滑價，亦不保證開盤成交。

每次 execution 都建立 `YYYYMMDD_HHMMSS_<full-git-commit>/`，不論 market date 是否更新，都含 `daily_screen.csv`、`signal_ledger.csv`、`signal_returns.csv`、`research_summary.csv`、`run_info.txt`、`last_screen.csv`、`report_snapshot.csv`、`corporate_actions_snapshot.csv`、`report_registry.csv`、`candidate.csv`。只有 FinLab market date 晚於 `state.json.last_successful_market_date` 時才推進 `state.json` 日期；但同一 market date 的成功重跑仍會以最後一次完整執行覆寫 root current outputs。舊 archive 不覆蓋。folder 根目錄另有最新展示檔 `candidate.csv`，以及持續狀態 `state.json`、`last_screen.csv`、`signal_ledger.csv`、`signal_returns.csv`、`report_registry.csv`，用於隔日 crossing、去重與逐步成熟。每次新市場日執行前，`state.json.last_successful_market_date` 必須與 `last_screen.csv` 唯一的 `market_date` 完全一致；缺檔、空檔、多日期或日期不一致會直接失敗，避免靜默破壞 signal continuity。需保留根目錄狀態；若手動刪除或修改會破壞連續性。`report_registry.csv` 由程式自動維護，以 `ticker + broker + report_date` 為 immutable key；新報告第一次被 pipeline 讀到時自動寫入 Asia/Taipei `first_seen_at`，後續重跑不得改寫。使用者不需要修改 Google Sheet schema。每次 archive 亦保存 registry snapshot。每次 `run_info.txt` 另記 previous screen 日期/列數、既有 ledger 列數、本次新增 report 與 signal 數，請以 archive 和 commit hash 稽核。`research_summary.csv` 低於 30 筆標示 `INSUFFICIENT`，達到也只是 `DESCRIPTIVE_ONLY`。

本地測試可在既有相容環境執行 `python -m unittest discover -s tests -v`；正式依賴與 Python 3.11 見 `requirements.txt` 和 Actions。請勿將 token、憑證、資料與產生結果納入 Git。

## 研究限制與反對者觀點

這是人手挑選的報告，並非完整券商報告 universe，存在 selection bias、survivorship bias、可取得日期與報告實際公開時間不一致的 look-ahead 風險。必須補報告的發布時間與可取得時點，才能評估報告當日 crossing 的可交易性。高 upside 可能來自目標價大幅上修、股價大跌、報告過時，或市場已有新資訊。保留 `previous_target_price` 與 `target_upside` 為不同變數，不以其中一項代替另一項。

後續研究應分開檢查 `NEW_REPORT_CANDIDATE` 與 `THRESHOLD_CROSSING`，因兩者可能分別反映新券商資訊與價格變動造成的估值落差，不可只用合併績效推論兩種機制都有效。另應檢查資料探勘、交易成本、滑價、開盤流動性、漲跌停無法成交、樣本數、年份與股票集中度，以及各券商、年份、市場狀態、報告年齡和 upside 區間的穩健性。不得挑最好看的持有期宣稱有效。當前未有真實正式回測結果，不能判定這個假設有效。
