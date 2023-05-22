import unittest
from pydub import AudioSegment
import sys, os
sys.path.append('../src/plugins')
from applause import generate_applause

class TestGenerateApplause(unittest.TestCase):
    def test_duration(self):
        applause = generate_applause(5000, 1000, 2000, 100)
        self.assertEqual(len(applause), 5000)

if __name__ == "__main__":
    unittest.main()
