import unittest

from main import get_video_processor_toolbar_layout


class VideoToolbarLayoutTests(unittest.TestCase):
    def test_places_action_buttons_on_second_row(self):
        top_row, bottom_row = get_video_processor_toolbar_layout()

        self.assertEqual(
            bottom_row,
            ("save", "stop", "auto_host", "status"),
        )
        self.assertNotIn("save", top_row)
        self.assertNotIn("stop", top_row)
        self.assertNotIn("auto_host", top_row)


if __name__ == "__main__":
    unittest.main()
