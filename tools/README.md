# 發音包產生與檢查工具

`audio/` 裡的內建發音包是用這些腳本產生的。App 本身不需要它們。

需要 Python 3（無第三方套件）與一把 Gemini API Key。**金鑰一律從命令列傳入，不要寫進檔案。**

## 產生

```
python -u tools/gen_pack.py <KEY1[,KEY2]> <每批字數> <做幾課> [起始課]
python -u tools/gen_sent.py <KEY1[,KEY2]> <每批句數> <做到第幾課>
python -u tools/gen_one.py  <KEY1[,KEY2]> <字1> <字2> ...
python -u tools/resplit.py
```

- `gen_pack.py` 產生單字發音，`gen_sent.py` 產生例句發音。兩者都會跳過 `audio/index.json` 已有的項目。
- `gen_one.py` 一次請求只念一個字、完全不切割，用在批次切不開的短字。
- `resplit.py` 把切割失敗時存在 `tools/raw/` 的原始音訊拿出來離線重切，不消耗額度。

**批次大小**：例句用 5，單字用 5–10。例句 10 句一批約三分之一會切壞。

## 檢查（都不需要金鑰）

```
python -u tools/qc_audio.py     # 全靜音、格式、頭尾被切、太短太長、單字檔含兩字
python -u tools/qc_align.py     # 長度回歸，找離群檔
python -u tools/bench_split.py  # 新舊切割演算法的合成測試比較
```

產完一批就跑 `qc_audio.py`，有離群再用 `qc_align.py` 細看。

## 免費層的兩個額度上限

錯誤訊息裡的 `quotaId` 才分得出來，混為一談會白白丟掉當天額度：

| quotaId | 上限 | 處理 |
|---|---|---|
| `GenerateRequestsPerMinutePerProjectPerModel-FreeTier` | 3 次/分鐘 | 等一下重送同一個請求 |
| `GenerateRequestsPerDayPerProjectPerModel-FreeTier` | 10 次/天 | 停用該金鑰 |

每把金鑰的每日額度是分開的。腳本成功後固定間隔 21 秒，避免撞到每分鐘上限。

偶發的 `400 INVALID_ARGUMENT`（訊息無細節）是伺服器端不穩，重送就會成功。

## 音檔格式

16 kHz、8-bit µ-law WAV（`fmt` 格式碼 7）。API 回傳 24 kHz 16-bit PCM，降取樣後編碼，約為原本的 1/3 大小。`audio/index.json` 是「文字 → 檔名」的對照表：單字用字本身當檔名，例句用 `s_<md5前12碼>.wav`。

## 已知會失敗的字

`pause` 這個字，API 會回 HTTP 200 但 `candidates` 是空的（沒有音訊）。試過三種提示詞、
單獨念與夾在其他字中間，結果一樣。推測是模型把它當成指令。目前讓它退回裝置語音。

`model / motivation / note / obstacle / organize` 放在同一批時，模型固定只念 4 個字。
這種情況改用 `gen_one.py` 一次一字。

## 提示詞注意事項

指令要寫明「不要演、不要加音效」。曾經發生 `laugh` 被念成笑聲（1.90 秒、7 次重複脈衝）而不是念這個字。
