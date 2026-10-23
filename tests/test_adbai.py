"""Unit tests. Nothing here touches a real device or the network."""

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adbai import actions, adb, apps, cli, doctor, keys  # noqa: E402


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
        self.assertEqual(adb.normalise_target("192.168.0.42"), "192.168.0.42:5555")

    def test_explicit_port_kept(self):
        self.assertEqual(adb.normalise_target("192.168.0.42:5037"), "192.168.0.42:5037")

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
        "192.168.0.42:5555     device product:generic_tv model:Living_Room_TV\n"
        "R58M123ABCD            offline\n"
    )

    def test_parses_devices(self):
        with mock.patch.object(adb, "run") as run:
            run.return_value = mock.Mock(stdout=self.OUTPUT, stderr="")
            found = adb.devices()
        self.assertEqual([d.serial for d in found],
                         ["192.168.0.42:5555", "R58M123ABCD"])
        self.assertEqual(found[0].model, "Living Room TV")
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


class TestEnvironmentChecks(unittest.TestCase):
    """A missing adb or an old Python must produce advice, not a traceback."""

    def test_missing_adb_explains_how_to_install(self):
        with mock.patch.object(adb.shutil, "which", return_value=None), \
             mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(adb, "_candidate_paths", return_value=[]):
            with self.assertRaises(adb.AdbError) as caught:
                adb.adb_path()
        message = str(caught.exception)
        self.assertIn("adb not found", message)
        for hint in ("pkg install android-tools", "apt install adb", "winget"):
            self.assertIn(hint, message)

    def test_old_python_is_refused_with_advice(self):
        with mock.patch.object(cli.sys, "version_info", (3, 8, 0)):
            with self.assertRaises(SystemExit) as caught:
                cli._check_python()
        self.assertIn("needs Python 3.9", str(caught.exception))

    def test_doctor_reports_missing_adb(self):
        with mock.patch.object(doctor.adb, "adb_path",
                               side_effect=adb.AdbError("adb not found")), \
             contextlib.redirect_stdout(io.StringIO()) as printed:
            code = doctor.run()
        self.assertIn("adb not found", printed.getvalue())
        self.assertIn("fix the FAIL lines", printed.getvalue())
        self.assertEqual(code, 1)


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


class TestAlarms(unittest.TestCase):
    STUB_ONLY = "  packageName=com.google.android.tv.frameworkpackagestubs\n"
    REAL = ("  packageName=com.google.android.deskclock\n"
            "  packageName=com.google.android.tv.frameworkpackagestubs\n")

    def test_parse_clock(self):
        self.assertEqual(actions.parse_clock("7"), (7, 0))
        self.assertEqual(actions.parse_clock("19:30"), (19, 30))
        self.assertEqual(actions.parse_clock("07h05"), (7, 5))
        for bad in ("25:00", "abc", "7:99"):
            with self.assertRaises(ValueError):
                actions.parse_clock(bad)

    def test_parse_duration(self):
        self.assertEqual(actions.parse_duration("90"), 90)
        self.assertEqual(actions.parse_duration("10m"), 600)
        self.assertEqual(actions.parse_duration("1h30m"), 5400)
        with self.assertRaises(ValueError):
            actions.parse_duration("soon")

    def test_tv_stub_is_not_a_clock_app(self):
        """Android TV accepts the intent and drops it - that must not read as success."""
        with mock.patch.object(actions.adb, "shell", return_value=self.STUB_ONLY):
            self.assertIsNone(actions.alarm_handler())
            with self.assertRaises(adb.AdbError) as caught:
                actions.set_alarm("7:30")
        self.assertIn("no clock app", str(caught.exception))

    def test_real_clock_app_gets_the_intent(self):
        sent = []

        def fake_shell(cmd, serial=None, timeout=30.0):
            sent.append(cmd)
            return self.REAL if "query-activities" in cmd else "Starting: Intent"

        with mock.patch.object(actions.adb, "shell", side_effect=fake_shell):
            message = actions.set_alarm("7:30", label="wake up", days="mon,fri")
        intent = sent[-1]
        self.assertIn("--ei android.intent.extra.alarm.HOUR 7", intent)
        self.assertIn("--ei android.intent.extra.alarm.MINUTES 30", intent)
        self.assertIn("--eial android.intent.extra.alarm.DAYS 2,6", intent)
        self.assertIn("07:30", message)


class TestTouch(unittest.TestCase):
    def test_tap_and_swipe_build_input_commands(self):
        with mock.patch.object(actions.adb, "shell") as shell:
            actions.tap(603, 1311, serial="x")
            actions.swipe(360, 1200, 360, 400, serial="x", duration_ms=250)
        self.assertEqual(shell.call_args_list[0][0][0], "input tap 603 1311")
        self.assertEqual(shell.call_args_list[1][0][0], "input swipe 360 1200 360 400 250")

    def test_screen_size(self):
        with mock.patch.object(actions.adb, "shell",
                               return_value="Physical size: 720x1640\n"):
            self.assertEqual(actions.screen_size(), (720, 1640))

    def test_scroll_uses_screen_size(self):
        with mock.patch.object(actions, "screen_size", return_value=(720, 1640)), \
             mock.patch.object(actions.adb, "shell") as shell:
            actions.scroll("down", serial="x")
        sent = shell.call_args[0][0]
        self.assertTrue(sent.startswith("input swipe 360 "))

    def test_scroll_rejects_nonsense(self):
        with mock.patch.object(actions, "screen_size", return_value=(720, 1640)):
            with self.assertRaises(ValueError):
                actions.scroll("sideways")


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
