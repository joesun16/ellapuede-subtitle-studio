import io
import unittest
from unittest.mock import patch
import launch

class StdioTests(unittest.TestCase):
    def test_legacy_windows_codepage_is_replaced_for_chinese_ipc(self):
        input_stream=io.TextIOWrapper(io.BytesIO('中文\n'.encode('utf-8')),encoding='cp1252')
        raw=io.BytesIO();output=io.TextIOWrapper(raw,encoding='cp1252')
        with patch('sys.stdin',input_stream),patch('sys.stdout',output),patch('sys.stderr',None):
            launch.configure_stdio()
            self.assertEqual(input_stream.readline(),'中文\n')
            output.write('识别完成');output.flush()
            self.assertEqual(raw.getvalue(),'识别完成'.encode('utf-8'))
        input_stream.close();output.close()

    def test_windowed_program_without_console(self):
        with patch('sys.stdin',None),patch('sys.stdout',None),patch('sys.stderr',None):
            launch.configure_stdio()
