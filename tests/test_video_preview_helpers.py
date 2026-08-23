import unittest

from PIL import Image

from main import VideoPreviewCache, build_video_preview_images


class VideoPreviewHelperTests(unittest.TestCase):
    def test_build_video_preview_images_prepares_display_and_full_sizes(self):
        img = Image.new("RGB", (2048, 1024), "white")

        display_img, full_img = build_video_preview_images(
            img,
            display_size=(170, 110),
            full_max_width=1024,
        )

        self.assertLessEqual(display_img.width, 170)
        self.assertLessEqual(display_img.height, 110)
        self.assertLessEqual(full_img.width, 1024)
        self.assertEqual(full_img.width, 1024)

    def test_video_preview_cache_evicts_oldest_entry(self):
        cache = VideoPreviewCache(max_entries=2)

        cache.set("a", [1])
        cache.set("b", [2])
        cache.set("c", [3])

        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.get("b"), [2])
        self.assertEqual(cache.get("c"), [3])


if __name__ == "__main__":
    unittest.main()
