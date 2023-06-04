import unittest
from pydub import AudioSegment
from llm_from_here.plugins.applause import generate_applause

class TestGenerateApplause(unittest.TestCase):
    def test_duration(self):
        applause = generate_applause(5000, 1000, 2000, 100)
        self.assertEqual(len(applause), 5000)

if __name__ == "__main__":
    unittest.main()
