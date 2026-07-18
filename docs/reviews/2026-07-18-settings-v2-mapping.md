# Settings v2 Mapping Review

> 知識庫索引：[../INDEX.md](../INDEX.md)

- root schema：`schema_version / global / profiles / selected_profile / extensions / migration`。
- `GLOBAL_SETTING_KEYS` 唯一映射到 `global.<field>`。
- `PROFILE_SETTING_KEYS` 唯一映射到 `profiles.<selected>.<field>`。
- 未知 root/profile 欄位分別保存在 `extensions` 與 profile `extensions`。
- migration 採 copy-on-write；任何 invalid v2 或 profile mapping 失敗都不覆寫原檔。
- production save 使用 pending file、flush、`fsync`、backup rotation 與 `os.replace`。
- 可執行 manifest：[full_performance_settings_manifest.py](../../tests/full_performance_settings_manifest.py)。
