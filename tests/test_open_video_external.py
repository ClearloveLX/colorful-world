import os
import tempfile
import unittest
from unittest.mock import patch

from main import open_file_externally


class OpenFileExternallyTests(unittest.TestCase):
    def setUp(self):
        fd, self.tmp_path = tempfile.mkstemp(suffix='.mp4')
        os.close(fd)

    def tearDown(self):
        try:
            os.remove(self.tmp_path)
        except OSError:
            pass

    def test_shell_execute_success(self):
        with patch('main.ctypes.windll.shell32.ShellExecuteW', return_value=42) as se, \
             patch('main.os.startfile') as sf, \
             patch('main.subprocess.Popen') as po:
            self.assertTrue(open_file_externally(self.tmp_path))
        se.assert_called_once()
        sf.assert_not_called()
        po.assert_not_called()

    def test_fallback_to_startfile(self):
        with patch('main.ctypes.windll.shell32.ShellExecuteW', side_effect=OSError('boom')) as se, \
             patch('main.os.startfile') as sf, \
             patch('main.subprocess.Popen') as po:
            self.assertTrue(open_file_externally(self.tmp_path))
        se.assert_called_once()
        sf.assert_called_once_with(self.tmp_path)
        po.assert_not_called()

    def test_fallback_to_rundll32(self):
        with patch('main.ctypes.windll.shell32.ShellExecuteW', side_effect=OSError('boom')), \
             patch('main.os.startfile', side_effect=OSError('boom')), \
             patch('main.subprocess.Popen') as po:
            self.assertTrue(open_file_externally(self.tmp_path))
        po.assert_called_once_with(['rundll32.exe', 'url.dll,FileProtocolHandler', self.tmp_path])

    def test_missing_file_returns_false(self):
        with patch('main.ctypes.windll.shell32.ShellExecuteW') as se, \
             patch('main.os.startfile') as sf, \
             patch('main.subprocess.Popen') as po:
            self.assertFalse(open_file_externally(os.path.join(self.tmp_path, 'nope', 'x.mp4')))
        se.assert_not_called()
        sf.assert_not_called()
        po.assert_not_called()

    def test_empty_path_returns_false(self):
        self.assertFalse(open_file_externally(''))

    def test_all_methods_fail_returns_false(self):
        with patch('main.ctypes.windll.shell32.ShellExecuteW', side_effect=OSError('boom')), \
             patch('main.os.startfile', side_effect=OSError('boom')), \
             patch('main.subprocess.Popen', side_effect=OSError('boom')):
            self.assertFalse(open_file_externally(self.tmp_path))


if __name__ == '__main__':
    unittest.main()
