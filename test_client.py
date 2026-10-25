import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from client import Client, character, chord

class KeyboardTests(unittest.TestCase):
    def test_printable_ascii(self):
        for code in range(32, 127):
            modifier, key = character(chr(code))
            self.assertIn(modifier, (0, 2))
            self.assertGreaterEqual(key, 4)
            self.assertLessEqual(key, 56)
        self.assertEqual(character('/'), (0, 56))
        self.assertEqual(character('='), (0, 46))
        self.assertEqual(chord('ctrl+x'), (1, 27))
        self.assertEqual(chord('ctrl+alt+f2'), (5, 59))

    def test_invalid_text_sends_nothing(self):
        client = object.__new__(Client)
        client.key = MagicMock()
        with self.assertRaises(ValueError):
            client.text('abc\n')
        client.key.assert_not_called()

    def test_pinning_before_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'client.json'
            config.write_text(json.dumps({'token': 'test', 'fingerprint': '0'*64}))
            conn = MagicMock()
            conn.sock.getpeercert.return_value = b'fake certificate'
            with patch('client.http.client.HTTPSConnection', return_value=conn):
                with self.assertRaisesRegex(RuntimeError, 'Certificate mismatch'):
                    Client('localhost', config).status()
            conn.request.assert_not_called()
            conn.close.assert_called()

    def test_no_retry_after_ambiguous_input(self):
        client = object.__new__(Client)
        client.config = {'token': 'test'}
        client.sequence = 10
        client.connection = MagicMock()
        conn = client.connection
        conn.getresponse.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            client.key(0, 4)
        self.assertIsNone(client.sequence)
        self.assertIsNone(client.connection)
        conn.request.assert_called_once()

if __name__ == '__main__':
    unittest.main()
