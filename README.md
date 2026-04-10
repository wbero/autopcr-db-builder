# AutoPCR Database Builder

自动从 B站 下载 AssetBundle，使用 UnityPy 提取 SQLite 数据库，并发布 GitHub Releases。

## 功能

- 从 B站 下载 `masterdata_master.unity3d`
- 使用 UnityPy 提取 SQLite 数据库
- 生成 `manifest.json` 元数据
- 自动创建 GitHub Release

## 使用方法

### 触发 Workflow

- **定时触发**: 每天 UTC 6:00 自动运行
- **手动触发**: 在 GitHub Actions 页面点击 "Run workflow"

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
│  │ 3. Install: UnityPy, requests                        │  │
│  │ 4. Run extract_db.py                                 │  │
│  │ 5. Create GitHub Release                             │  │
│  └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 输出文件

### manifest.json
```json
{
  "db_version": "202604021043",
  "schema_version": 3,
  "compatibility_version": 2,
  "created_at": "2026-04-08T12:00:00Z",
  "checksum_sha256": "abc123...",
  "size_bytes": 1048576
}
```

### Database 版本

Database 版本号格式: `YYYYMMDDHHMM`（构建时间）

## App 端使用

在 App 中配置：

```kotlin
val source = PreBundledArtifactSource(
    manifestUrl = "https://github.com/wbero/autopcr-db-builder/releases/latest/download/manifest.json",
    dbDownloadUrlTemplate = "https://github.com/wbero/autopcr-db-builder/releases/download/db-v{version}/{version}.db",
    cacheDir = cacheDir
)
```
