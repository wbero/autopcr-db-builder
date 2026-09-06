# AutoPCR Database Builder

自动从 B 站游戏接口检测当前 manifest，从 AssetBundle 提取 SQLite，恢复混淆表结构，严格校验后发布 GitHub Release。

## 功能

- 从游戏维护状态接口读取真实 `required_manifest_ver`
- 从 B 站资源服务器下载并校验 `masterdata_master.unity3d`
- 使用 UnityPy 提取 SQLite 数据库
- 使用 AutoPCR Android 的 `rainbow.json` 恢复表名和列名
- 执行 SQLite 完整性检查和关键表/列检查
- 生成包含 SHA-256、表行数和恢复统计的 `manifest.json`
- 已发布的版本自动跳过，支持手动强制重建
- 自动创建 GitHub Release，并记录 `latest-version.txt`

## 使用方法

### 触发 Workflow

- **定时触发**：每天 UTC 06:17 自动运行
- **手动触发**：在 GitHub Actions 页面点击 “Run workflow”
- **指定版本**：填写12位 manifest 版本号
- **强制重建**：启用 `force`，覆盖相同版本 Release 中的文件

> GitHub 会在公开仓库连续60天没有活动后自动禁用定时工作流。发生这种情况时，进入 Actions 的 Build Database 页面点击 “Enable workflow”。新数据库发布后，工作流会提交 `latest-version.txt`，使版本变化成为正常仓库活动。

### 获取 Database

从 Releases 页面下载生成的：
- `manifest.json` - 版本和校验信息
- `{version}.db` - SQLite 数据库文件

## Workflow 详情

```
┌─────────────────────────────────────────────────────────────┐
│  GitHub Actions                                             │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ 1. Checkout code                                    │  │
│  │ 2. Setup Python 3.11                                │  │
│  │ 3. 运行单元测试并检测游戏 manifest                  │  │
│  │ 4. Checkout AutoPCR Android 的 rainbow.json          │  │
│  │ 5. 下载、提取、解混淆并校验 SQLite                  │  │
│  │ 6. 创建 Release 并记录最新版本                       │  │
│  └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 输出文件

### manifest.json
```json
{
  "db_version": "202609021434",
  "schema_version": 4,
  "compatibility_version": 3,
  "created_at": "2026-09-06T12:00:00Z",
  "checksum_sha256": "abc123...",
  "size_bytes": 1048576,
  "restored_tables": 600,
  "table_counts": {
    "unit_data": 400,
    "unit_skill_data": 400,
    "skill_data": 5000
  }
}
```

### Database 版本

Database 版本号格式: `YYYYMMDDHHMM`（游戏资源 manifest 版本）

## 本地验证

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python .github/scripts/detect_version.py
python .github/scripts/extract_db.py \
  --version 202609021434 \
  --output-dir db \
  --rainbow ../AutoPCR-Android/app/src/main/python/data/rainbow.json
```

## App 端使用

在 App 中配置：

```kotlin
val source = PreBundledArtifactSource(
    manifestUrl = "https://github.com/wbero/autopcr-db-builder/releases/latest/download/manifest.json",
    dbDownloadUrlTemplate = "https://github.com/wbero/autopcr-db-builder/releases/download/db-v{version}/{version}.db",
    cacheDir = cacheDir
)
```
