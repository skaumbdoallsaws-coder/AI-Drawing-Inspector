import unittest
from launch import parse_args


class LaunchOptionsTests(unittest.TestCase):
    def test_default_waits_for_recording(self):
        self.assertTrue(parse_args(['--name', 'record-test', '--full']).wait_for_cue)

    def test_auto_start_requires_explicit_flag(self):
        self.assertFalse(parse_args(['--name', 'rehearsal-test', '--auto-start']).wait_for_cue)

    def test_ready_check_stays_paused(self):
        args = parse_args(['--name', 'ready-test', '--verify-ready'])
        self.assertTrue(args.wait_for_cue)
        self.assertTrue(args.verify_ready)


if __name__ == '__main__':
    unittest.main()
