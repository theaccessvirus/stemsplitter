import importlib.util
import pathlib
import sys
import unittest
import numpy as np

# server.py imports its sibling fetch.py.
sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / 'cloud'))
spec = importlib.util.spec_from_file_location('stream', pathlib.Path(__file__).parents[1] / 'cloud/server.py')
stream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stream)


class StreamTests(unittest.TestCase):
    def test_overlap_preserves_timeline_and_channels(self):
        signal = np.arange((stream.WINDOW + stream.STRIDE) * 8, dtype='float32').reshape(-1, 8) / 1e7
        ola = stream.Overlap()
        a = ola.commit(signal[:stream.WINDOW])
        b = ola.commit(signal[stream.STRIDE:stream.STRIDE + stream.WINDOW])
        np.testing.assert_allclose(np.concatenate([a, b]), signal[:2 * stream.STRIDE], rtol=1e-6)

    def test_wire_format(self):
        audio = np.arange(80, dtype='float32').reshape(10, 8)
        data = stream.packet(12345, audio)
        self.assertEqual(stream.HEADER.unpack(data[:16]), (b'OS01', 12345, 10))
        np.testing.assert_array_equal(np.frombuffer(data[16:], dtype='<f4').reshape(10, 8), audio)


if __name__ == '__main__':
    unittest.main()
