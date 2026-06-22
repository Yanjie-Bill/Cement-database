# Cement Review Database Site

这个本地网站把 `annotation/*.xlsx` 中 20 篇人工确认数据导入 SQLite，并提供一个参与者审核界面。

## 运行

```bash
/Users/yanjie/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 review_site/import_data.py
/Users/yanjie/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 review_site/app.py --host 127.0.0.1 --port 8765
```

打开：

```text
http://127.0.0.1:8765
```

## 数据更新方式

- 把新的人工确认或 LLM 预抽取 Excel 放入 `annotation/`，然后点击网页右上角“重新导入 Excel”。
- 参与者在 Review Queue 中提交的回答会写入 `review_site/cement_review.db` 的 `answers` 表，并同步更新 `review_queue.status`。
- 原始 Excel 不会被网页修改。

## 主要导出

- `/api/export/answers`
- `/api/export/review_queue`
- `/api/export/records`
- `/api/export/papers`
