"""Unit tests. Nothing here touches a real device or the network."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adbctl import actions, adb, apps, keys  # noqa: E402


class TestKeys(unittest.TestCase):
    def test_friendly_names(self):
        self.assertEqual(keys.resolve("home"), "KEYCODE_HOME")
        self.assertEqual(keys.resolve("OK"), "KEYCODE_DPAD_CENTER")
        self.assertEqual(keys.resolve("play-pause"), "KEYCODE_MEDIA_PLAY_PAUSE")

    def test_raw_keycodes_pass_through(self):
        self.assertEqual(keys.resolve("KEYCODE_SOFT_LEFT"), "KEYCODE_SOFT_LEFT")
        self.assertEqual(keys.resolve("keycode_tv_input"), "KEYCODE_TV_INPUT")

    def test_unknown_key_raises(self):
        with self.assertRaises(KeyError):
            keys.resolve("nope")


class TestTargetNormalisation(unittest.TestCase):
    def test_ip_gets_default_port(self):
        self.assertEqual(adb.normalise_target("192.168.0.102"), "192.168.0.102:5555")

    def test_explicit_port_kept(self):
        self.assertEqual(adb.normalise_target("192.168.0.102:5037"), "192.168.0.102:5037")

    def test_usb_serial_untouched(self):
        self.assertEqual(adb.normalise_target("R58M123ABCD"), "R58M123ABCD")


class TestScreencap(unittest.TestCase):
    """Some devices print driver noise before the PNG; it must be trimmed."""

    NOISE = b"Init wrapper sys mutex successful. Pid:1234\nopen mma dev failed\n"
    IMAGE = adb.PNG_MAGIC + b"\x00\x00\x00\rIHDRfake-image-body"

    def test_strips_leading_garbage(self):
        with mock.patch.object(adb, "run") as run:
            run.return_value = mock.Mock(stdout=self.NOISE + self.IMAGE, stderr="")
            self.assertEqual(adb.screencap(), self.IMAGE)

    def test_clean_output_unchanged(self):
        with mock.patch.object(adb, "run") as run:
            run.return_value = mock.Mock(stdout=self.IMAGE, stderr="")
            self.assertEqual(adb.screencap(), self.IMAGE)

    def test_no_png_raises(self):
        with mock.patch.object(adb, "run") as run:
            run.return_value = mock.Mock(stdout=b"error: device offline", stderr="")
            with self.assertRaises(adb.AdbError):
                adb.screencap()


class TestDeviceListing(unittest.TestCase):
    OUTPUT = (
        "List of devices attached\n"
        "192.168.0.102:5555     device product:PH0M_LT_T32 model:Philips_TV\n"
        "R58M123ABCD            offline\n"
    )

    def test_parses_devices(self):
        with mock.patch.object(adb, "run") as run:
            run.return_value = mock.Mock(stdout=self.OUTPUT, stderr="")
            found = adb.devices()
        self.assertEqual([d.serial for d in found],
                         ["192.168.0.102:5555", "R58M123ABCD"])
        self.assertEqual(found[0].model, "Philips TV")
        self.assertTrue(found[0].online and found[0].is_network)
        self.assertFalse(found[1].online or found[1].is_network)


class TestAppResolution(unittest.TestCase):
    PACKAGES = [
        "com.netflix.ninja",
        "com.google.android.youtube.tv",
        "com.world.youcinetv",
        "com.example.player",
    ]

    def resolve(self, name):
        with mock.patch.object(apps, "installed", return_value=sorted(self.PACKAGES)):
            return apps.resolve(name)

    def test_alias(self):
        self.assertEqual(self.resolve("netflix"), "com.netflix.ninja")

    def test_alias_prefers_tv_build(self):
        self.assertEqual(self.resolve("youtube"), "com.google.android.youtube.tv")

    def test_full_package(self):
        self.assertEqual(self.resolve("com.world.youcinetv"), "com.world.youcinetv")

    def test_fragment(self):
        self.assertEqual(self.resolve("youcine"), "com.world.youcinetv")

    def test_unknown(self):
        with self.assertRaises(LookupError):
            self.resolve("hbogo")


class TestShellQuoting(unittest.TestCase):
    def test_spaces_and_quotes_survive(self):
        with mock.patch.object(actions.adb, "shell") as shell:
            actions.type_text("it's a test", serial="x")
        sent = shell.call_args[0][0]
        self.assertIn("%s", sent)              # spaces encoded for `input text`
        self.assertIn("'\\''", sent)           # apostrophe escaped for the shell

    def test_url_is_quoted(self):
        with mock.patch.object(actions.adb, "shell") as shell:
            actions.open_url("https://x.dev/a?b=1&c=2", serial="x")
        self.assertIn("'https://x.dev/a?b=1&c=2'", shell.call_args[0][0])


class TestStateParsing(unittest.TestCase):
    def test_current_app(self):
        dump = "  mCurrentFocus=Window{abc u0 com.netflix.ninja/com.netflix.Main}\n"
        with mock.patch.object(actions.adb, "shell", return_value=dump):
            self.assertEqual(actions.current_app(),
                             "com.netflix.ninja/com.netflix.Main")

    def test_current_app_null_during_transition(self):
        with mock.patch.object(actions.adb, "shell", return_value="mCurrentFocus=null\n"):
            self.assertIsNone(actions.current_app())

    def test_playback_playing(self):
        dump = "state=PlaybackState {state=3, position=12}"
        with mock.patch.object(actions.adb, "shell", return_value=dump):
            self.assertEqual(actions.playback()["label"], "playing")

    def test_playback_without_session(self):
        with mock.patch.object(actions.adb, "shell", return_value="nothing here"):
            self.assertIsNone(actions.playback()["state"])


if __name__ == "__main__":
    unittest.main()
