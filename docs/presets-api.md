# Preset API

## 概览

- 媒体类型：`image`、`video`
- 数据隔离：图片与视频分别落在 `image_presets`、`video_presets`
- 标签校验：`tags` 中的标签必须存在于有效标签池，否则返回 `400`
- 排序规则：`sort_order` 始终从 `0` 开始连续递增
- 删除策略：软删除，删除后自动重排

## 数据对象

```json
{
  "preset_id": "9b16d2a0f6a74e33a6d5f8b0ce5a5c3a",
  "name": "常用标签组合",
  "sort_order": 0,
  "tags": ["tag_a", "tag_b"],
  "media_type": "image",
  "created_at": "2026-04-26T10:00:00.000000",
  "updated_at": "2026-04-26T10:00:00.000000",
  "is_deleted": 0
}
```

## POST `/api/presets/{media_type}`

创建预制。

请求体：

```json
{
  "name": "常用图片标签",
  "sort_order": 0,
  "tags": ["tag_a", "tag_b"]
}
```

响应：

```json
{
  "preset_id": "9b16d2a0f6a74e33a6d5f8b0ce5a5c3a"
}
```

## PUT `/api/presets/{media_type}/{preset_id}`

更新名称、排序或标签。字段均可选。

请求体：

```json
{
  "name": "常用图片标签-新版",
  "sort_order": 1,
  "tags": ["tag_a", "tag_c"]
}
```

响应：返回完整预制对象。

## DELETE `/api/presets/{media_type}/{preset_id}`

软删除预制并自动重排。

响应：

```json
{
  "ok": true
}
```

## GET `/api/presets/{media_type}`

按 `sort_order` 升序返回列表。

响应：

```json
[
  {
    "preset_id": "9b16d2a0f6a74e33a6d5f8b0ce5a5c3a",
    "name": "常用图片标签",
    "sort_order": 0,
    "tags": ["tag_a", "tag_b"],
    "media_type": "image",
    "created_at": "2026-04-26T10:00:00.000000",
    "updated_at": "2026-04-26T10:00:00.000000",
    "is_deleted": 0
  }
]
```

## GET `/api/presets/{media_type}/{preset_id}`

获取单条预制，用于一键带出标签。

## 错误码

- `400`：`media_type` 非法、标签不存在、名称为空、名称过长、名称冲突
- `404`：预制不存在或已删除
