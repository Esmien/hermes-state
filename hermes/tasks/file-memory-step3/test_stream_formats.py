import unittest
import memory_filter as f

class FormatTests(unittest.TestCase):
 def test_no_stream_interception(self):
  self.assertFalse(hasattr(f.Filter(),'stream'))
 def test_no_obsolete_deletion_warning(self):
  self.assertNotIn('первые 10',f.FULL_WARNING.lower())
