export type ID = string

export type Model = {
  id: ID
  name: string
  type?: string | null
  preview_image_path?: string | null
}

export type Tag = {
  id: ID
  name: string
  category_name?: string | null
}

export type MediaItem = {
  id: ID
  title: string
  file_path: string
  file_type: string
  file_size?: number | null
  thumbnail_path?: string | null
  image_width?: number | null
  image_height?: number | null
  video_width?: number | null
  video_height?: number | null
  duration_ms?: number | null
  heat_value?: number | null
  models: Model[]
  tags: Tag[]
  created_at?: string
}
