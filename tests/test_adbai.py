"""Unit tests. Nothing here touches a real device or the network."""

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adbai import (actions, adb, apps, cli, doctor, images, keys,  # noqa: E402
                   mcp_server, mirror, pairing, qr, target)


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


class TestShellGate(unittest.TestCase):
    """Shell is on by default; the operator can take it away."""

    def test_on_by_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(mcp_server._shell_enabled())

    def test_explicit_off_switches(self):
        for env in ({"ADBAI_NO_SHELL": "1"}, {"ADBAI_ALLOW_SHELL": "0"},
                    {"ADBAI_ALLOW_SHELL": "false"}, {"ADBAI_ALLOW_SHELL": "off"}):
            with mock.patch.dict("os.environ", env, clear=True):
                self.assertFalse(mcp_server._shell_enabled(), env)

    def test_truthy_values_keep_it_on(self):
        for env in ({"ADBAI_ALLOW_SHELL": "1"}, {"ADBAI_ALLOW_SHELL": "yes"},
                    {"ADBAI_NO_SHELL": "0"}):
            with mock.patch.dict("os.environ", env, clear=True):
                self.assertTrue(mcp_server._shell_enabled(), env)

    def test_disabled_tool_explains_itself_instead_of_running(self):
        with mock.patch.dict("os.environ", {"ADBAI_NO_SHELL": "1"}, clear=True), \
             mock.patch.object(mcp_server.adb, "shell") as shell:
            result = mcp_server.tool_shell({"command": "rm -rf /"})
        shell.assert_not_called()
        self.assertIn("switched off", result["content"][0]["text"])


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


MODERN_HELP = """
    --no-control
    --no-playback
    --no-window
    --max-fps value
    --video-bit-rate value
    --no-audio
    --time-limit seconds
    --window-title text
"""

# scrcpy 1.x: before the renames, and before audio existed at all.
OLD_HELP = """
    --no-control
    --no-display
    --bit-rate value
    --window-title text
"""


class TestMirror(unittest.TestCase):
    """scrcpy is optional, and its flags have been renamed over the years."""

    def _with(self, help_text):
        return mock.patch.multiple(
            mirror,
            scrcpy_path=mock.Mock(return_value="/usr/bin/scrcpy"),
            help_text=mock.Mock(return_value=help_text),
        )

    def test_builds_the_options_we_advertise(self):
        with self._with(MODERN_HELP):
            cmd = mirror.build_command("tv:5555", view_only=True, max_size=1024,
                                       fps=30, bitrate="4M", audio=False,
                                       title="adb-ai tv")
        self.assertEqual(cmd[:3], ["/usr/bin/scrcpy", "-s", "tv:5555"])
        for flag in ("--no-control", "--max-fps", "--video-bit-rate=4M", "--no-audio",
                     "--window-title=adb-ai tv"):
            self.assertIn(flag, cmd)
        self.assertIn("1024", cmd)

    def test_recording_without_a_window_uses_the_current_flag(self):
        with self._with(MODERN_HELP):
            cmd = mirror.build_command(None, window=False, record="out.mp4")
        self.assertIn("--record=out.mp4", cmd)
        self.assertIn("--no-playback", cmd)
        self.assertIn("--no-window", cmd)

    def test_recording_falls_back_to_the_old_flag_name(self):
        with self._with(OLD_HELP):
            cmd = mirror.build_command(None, window=False, record="out.mp4")
        self.assertIn("--no-display", cmd)
        self.assertNotIn("--no-playback", cmd)
        self.assertNotIn("--no-window", cmd)

    def test_flags_an_old_scrcpy_lacks_are_left_out(self):
        with self._with(OLD_HELP):
            cmd = mirror.build_command(None, fps=30, bitrate="4M", audio=False,
                                       time_limit=60)
        self.assertIn("--bit-rate=4M", cmd)
        for absent in ("--max-fps", "--no-audio", "--time-limit"):
            self.assertNotIn(absent, cmd)

    def test_no_window_and_no_recording_is_a_mistake(self):
        with self._with(MODERN_HELP):
            with self.assertRaises(ValueError):
                mirror.build_command(None, window=False)

    def test_termux_is_refused_with_a_reason_not_an_sdl_error(self):
        with mock.patch.object(mirror.adb, "current_system", return_value="Termux"), \
             mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(adb.AdbError) as caught:
                mirror.preflight()
        message = str(caught.exception)
        self.assertIn("does not work from Termux", message)
        self.assertIn("adb-ai shot", message)  # tell them what to use instead

    def test_termux_can_still_be_overridden_by_someone_who_got_it_working(self):
        with mock.patch.object(mirror.adb, "current_system", return_value="Termux"), \
             mock.patch.dict("os.environ", {"ADBAI_SCRCPY": __file__}), \
             mock.patch.object(mirror, "headless", return_value=False):
            self.assertEqual(mirror.preflight(), __file__)

    def test_a_window_needs_a_display_on_linux(self):
        with mock.patch.object(mirror.sys, "platform", "linux"), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(mirror.headless())
        with mock.patch.object(mirror.sys, "platform", "linux"), \
             mock.patch.dict("os.environ", {"DISPLAY": ":0"}, clear=True):
            self.assertFalse(mirror.headless())
        with mock.patch.object(mirror.sys, "platform", "darwin"), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(mirror.headless())

    def test_mcp_status_with_nothing_running(self):
        with mock.patch.dict(mirror._running, {}, clear=True):
            result = mcp_server.tool_mirror({"action": "status"})
        self.assertIn("no mirror running", result["content"][0]["text"])

    def test_mcp_start_tells_the_model_it_cannot_see_the_window(self):
        fake = mock.Mock(pid=4321)
        with mock.patch.object(mirror, "preflight"), \
             mock.patch.object(mirror, "start", return_value=fake), \
             mock.patch.object(mcp_server, "_device", return_value="tv:5555"):
            text = mcp_server.tool_mirror({})["content"][0]["text"]
        self.assertIn("You cannot see it", text)
        self.assertIn("adb_screenshot", text)

    def test_one_mirror_per_device(self):
        alive = mock.Mock(**{"poll.return_value": None}, pid=99)
        with mock.patch.dict(mirror._running, {"tv:5555": alive}, clear=True), \
             mock.patch.object(mirror, "preflight") as preflight, \
             mock.patch("subprocess.Popen") as popen:
            self.assertIs(mirror.start("tv:5555"), alive)
        popen.assert_not_called()
        preflight.assert_not_called()

    def test_stopping_something_that_is_not_running(self):
        with mock.patch.dict(mirror._running, {}, clear=True):
            self.assertFalse(mirror.stop("tv:5555"))


class TestCaching(unittest.TestCase):
    """The same answer twice in a row should not cost two adb calls."""

    def setUp(self):
        adb.forget_devices()
        apps.forget_packages()
        actions.forget_sizes()

    def test_device_list_is_reused_then_dropped(self):
        listing = mock.Mock(stdout="List of devices attached\n", stderr="")
        with mock.patch.object(adb, "run", return_value=listing) as run:
            adb.devices()
            adb.devices()
            self.assertEqual(run.call_count, 1)
            adb.devices(fresh=True)
            self.assertEqual(run.call_count, 2)
            adb.forget_devices()
            adb.devices()
            self.assertEqual(run.call_count, 3)

    def test_connecting_invalidates_the_device_list(self):
        listing = mock.Mock(stdout="List of devices attached\n", stderr="")
        with mock.patch.object(adb, "run", return_value=listing):
            adb.devices()
        self.assertIsNotNone(adb._devices_cache)
        with mock.patch.object(adb, "run",
                               return_value=mock.Mock(stdout="connected to x", stderr="")):
            adb.connect("192.168.0.42")
        # The cache was dropped before the connect, so the next read is honest.
        with mock.patch.object(adb, "run", return_value=listing) as run:
            adb.devices()
        run.assert_called_once()

    def test_package_list_is_reused_per_device(self):
        out = "package:com.netflix.ninja\npackage:com.spotify.tv.android\n"
        with mock.patch.object(apps.adb, "shell", return_value=out) as shell:
            first = apps.installed("tv:5555")
            second = apps.installed("tv:5555")
            self.assertEqual(first, second)
            shell.assert_called_once()
            apps.installed("phone:5555")  # a different device is a different answer
            self.assertEqual(shell.call_count, 2)

    def test_screen_size_is_reused(self):
        with mock.patch.object(actions.adb, "shell",
                               return_value="Physical size: 1080x2400\n") as shell:
            self.assertEqual(actions.screen_size("phone"), (1080, 2400))
            self.assertEqual(actions.screen_size("phone"), (1080, 2400))
            shell.assert_called_once()


class TestFewerRoundtrips(unittest.TestCase):
    """Latency is roundtrips: every adb call is ~50ms before the network."""

    def setUp(self):
        actions._probe_works.clear()

    PROBE_OK = ("@@ADBAIP\n  mWakefulness=Awake\n"
                "@@ADBAIW\n  mCurrentFocus=Window{a u0 com.netflix.ninja/.Main}\n"
                "@@ADBAIM\n      state=PlaybackState {state=3, position=9}\n"
                "@@ADBAIEND\n")
    # A device whose grep is missing: the sections come back empty.
    PROBE_EMPTY = "@@ADBAIP\n@@ADBAIW\n@@ADBAIM\n@@ADBAIEND\n"

    def test_state_is_one_call_when_the_device_can_filter(self):
        with mock.patch.object(actions.adb, "shell", return_value=self.PROBE_OK) as shell:
            snapshot = actions.state("tv:5555")
        shell.assert_called_once()
        self.assertEqual(snapshot["screen"], "Awake")
        self.assertEqual(snapshot["foreground"], "com.netflix.ninja/.Main")
        self.assertEqual(snapshot["playback"]["label"], "playing")

    def test_state_falls_back_to_full_dumps_and_remembers(self):
        def answer(cmd, serial=None, timeout=30.0):
            if "@@ADBAI" in cmd:
                return self.PROBE_EMPTY
            if "dumpsys power" in cmd:
                return "mWakefulness=Asleep\n"
            if "dumpsys window" in cmd:
                return "mCurrentFocus=null\n"
            return "no session here"

        with mock.patch.object(actions.adb, "shell", side_effect=answer) as shell:
            snapshot = actions.state("old-tv")
            self.assertEqual(shell.call_count, 4)  # the probe, then three dumps
            self.assertEqual(snapshot["screen"], "Asleep")
            self.assertIsNone(snapshot["foreground"])
            shell.reset_mock()
            actions.state("old-tv")
            self.assertEqual(shell.call_count, 3)  # the probe is not tried again

    def test_several_keys_go_in_one_call(self):
        with mock.patch.object(actions.adb, "shell") as shell:
            actions.press_sequence(["down", "down", "ok"], serial="tv")
        shell.assert_called_once_with(
            "input keyevent KEYCODE_DPAD_DOWN KEYCODE_DPAD_DOWN KEYCODE_DPAD_CENTER",
            serial="tv")

    def test_repeat_also_goes_in_one_call(self):
        with mock.patch.object(actions.adb, "shell") as shell:
            actions.press("volup", serial="tv", repeat=5)
        shell.assert_called_once()
        self.assertEqual(shell.call_args[0][0].count("KEYCODE_VOLUME_UP"), 5)

    def test_pacing_goes_back_to_one_call_per_key(self):
        with mock.patch.object(actions.adb, "shell") as shell, \
             mock.patch.object(actions.time, "sleep") as sleep:
            actions.press_sequence(["down", "ok"], serial="tv", pace_ms=120)
        self.assertEqual(shell.call_count, 2)
        sleep.assert_called_once_with(0.12)


class TestScreenshotSize(unittest.TestCase):
    """Shrinking is for the screens that are actually big."""

    PNG = adb.PNG_MAGIC + b"\x00" * 100

    def test_a_small_screenshot_is_left_alone(self):
        data, mime = images.shrink(self.PNG)
        self.assertIs(data, self.PNG)
        self.assertEqual(mime, "image/png")

    def test_max_size_zero_means_send_the_original(self):
        big = adb.PNG_MAGIC + b"\x00" * (images.SHRINK_ABOVE + 1)
        data, mime = images.shrink(big, max_size=0)
        self.assertIs(data, big)
        self.assertEqual(mime, "image/png")

    def test_without_ffmpeg_the_original_goes_through(self):
        big = adb.PNG_MAGIC + b"\x00" * (images.SHRINK_ABOVE + 1)
        with mock.patch.object(images, "ffmpeg_path",
                               side_effect=adb.AdbError("ffmpeg not found")):
            data, mime = images.shrink(big)
        self.assertIs(data, big)
        self.assertEqual(mime, "image/png")

    def test_ffmpeg_failing_is_not_an_error_either(self):
        big = adb.PNG_MAGIC + b"\x00" * (images.SHRINK_ABOVE + 1)
        with mock.patch.object(images, "ffmpeg_path", return_value="/usr/bin/ffmpeg"), \
             mock.patch("subprocess.run",
                        return_value=mock.Mock(returncode=1, stdout=b"")):
            data, mime = images.shrink(big)
        self.assertIs(data, big)
        self.assertEqual(mime, "image/png")

    def test_the_operator_can_set_the_default_size(self):
        with mock.patch.dict("os.environ", {"ADBAI_SHOT_MAX": "800"}, clear=True):
            self.assertEqual(mcp_server._shot_max_size({}), 800)
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(mcp_server._shot_max_size({}), images.DEFAULT_MAX_SIZE)
            self.assertEqual(mcp_server._shot_max_size({"max_size": 0}), 0)

    @unittest.skipUnless(images.available(), "ffmpeg is not installed here")
    def test_a_real_shrink_round_trip(self):
        """With ffmpeg present, a big picture really does come back smaller."""
        import subprocess
        made = subprocess.run(
            [images.ffmpeg_path(), "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc2=size=2560x1440", "-frames:v", "1",
             "-c:v", "png", "-f", "image2pipe", "pipe:1"],
            capture_output=True, timeout=60)
        if made.returncode != 0 or len(made.stdout) < images.SHRINK_ABOVE:
            self.skipTest("could not produce a big enough test image")
        self.assertTrue(made.stdout.startswith(adb.PNG_MAGIC))

        small, mime = images.shrink(made.stdout, max_size=640)
        self.assertEqual(mime, "image/jpeg")
        self.assertTrue(small.startswith(b"\xff\xd8\xff"))  # really a JPEG
        self.assertLess(len(small), len(made.stdout))

        # The PNG path must stay PNG: ffmpeg guesses JPEG for a pipe, so the
        # encoder is named explicitly.
        still_png, mime = images.shrink(made.stdout, max_size=640, jpeg=False)
        self.assertEqual(mime, "image/png")
        self.assertTrue(still_png.startswith(adb.PNG_MAGIC))


class TestWarmUp(unittest.TestCase):
    def test_initialize_warms_adb_up_in_the_background(self):
        with mock.patch.object(mcp_server.threading, "Thread") as thread:
            mcp_server._handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        thread.assert_called_once()
        self.assertIs(thread.call_args.kwargs["target"], mcp_server._warm_up)
        self.assertTrue(thread.call_args.kwargs["daemon"])

    def test_a_failing_warm_up_is_swallowed(self):
        with mock.patch.object(mcp_server.adb, "run", side_effect=OSError("boom")):
            mcp_server._warm_up()  # must not raise


class TestQrEncoder(unittest.TestCase):
    """The encoder has no device to tell it when it is wrong, so pin it down."""

    def test_error_correction_matches_the_spec_worked_example(self):
        # "HELLO WORLD" at version 1-M, from the specification's own walkthrough.
        data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
        self.assertEqual(
            qr._ec_codewords(data, 10),
            [196, 35, 39, 119, 235, 215, 231, 226, 93, 23],
        )

    def test_version_grows_with_the_payload(self):
        self.assertEqual(len(qr.encode("hi")), 21)  # version 1
        self.assertEqual(len(qr.encode("x" * 43)), 33)  # version 4
        self.assertEqual(len(qr.encode("x" * 43, ecl="L")), 29)  # version 3 at level L

    def test_finder_patterns_are_in_all_three_corners(self):
        matrix = qr.encode("WIFI:T:ADB;S:adb-ai-0000;P:secret;;")
        size = len(matrix)
        for row, col in ((0, 0), (0, size - 7), (size - 7, 0)):
            block = [r[col:col + 7] for r in matrix[row:row + 7]]
            self.assertTrue(all(block[0]), "finder's top edge is dark")
            self.assertTrue(block[2][2] and block[3][3] and block[4][4], "dark centre")
            self.assertFalse(block[1][1], "the ring inside it is light")

    def test_quiet_zone_and_colours_survive_rendering(self):
        drawn = qr.render(qr.encode("hi"))
        self.assertIn("\u2580", drawn)
        self.assertIn("\x1b[0m", drawn)  # every line resets, or the terminal stays white
        self.assertEqual(len(drawn.splitlines()), (21 + 8) // 2 + 1)

    def test_png_is_a_png(self):
        png = qr.to_png_bytes(qr.encode("hi"), scale=4)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(b"IEND", png)

    def test_a_payload_too_big_says_so(self):
        with self.assertRaises(qr.QrError):
            qr.encode("x" * 300)


class TestPairing(unittest.TestCase):
    def test_payload_is_the_shape_android_expects(self):
        credentials = pairing.Credentials(name="adb-ai-1234", password="hunter2")
        self.assertEqual(credentials.payload, "WIFI:T:ADB;S:adb-ai-1234;P:hunter2;;")

    def test_credentials_are_random_each_time(self):
        self.assertNotEqual(
            pairing.new_credentials().password, pairing.new_credentials().password
        )

    def test_names_round_trip_through_the_dns_encoding(self):
        encoded = pairing._encode_name(pairing.PAIRING_SERVICE)
        self.assertEqual(pairing._decode_name(encoded, 0)[0], pairing.PAIRING_SERVICE)

    def test_an_announcement_is_read_out_of_a_real_packet_shape(self):
        packet = _mdns_answer("adb-ai-1234", "phone.local.", "192.168.0.42", 37419)
        srv, hosts, ptrs = pairing._parse(packet)
        name = "adb-ai-1234." + pairing.PAIRING_SERVICE
        self.assertEqual(srv[name], ("phone.local.", 37419))
        self.assertEqual(hosts["phone.local."], "192.168.0.42")
        self.assertIn((pairing.PAIRING_SERVICE, name), ptrs)

    def test_a_truncated_packet_is_ignored_not_fatal(self):
        self.assertEqual(pairing._parse(b"\x00\x01\x02"), ({}, {}, []))

    def test_the_password_goes_in_on_stdin(self):
        done = mock.Mock(returncode=0, stdout="Successfully paired to 1.2.3.4:5", stderr="")
        with mock.patch.object(pairing.subprocess, "run", return_value=done) as run:
            with mock.patch.object(pairing.adb, "adb_path", return_value="adb"):
                pairing.pair("1.2.3.4:5", "secret")
        self.assertEqual(run.call_args.args[0], ["adb", "pair", "1.2.3.4:5"])
        self.assertEqual(run.call_args.kwargs["input"], "secret\n")

    def test_a_refused_pairing_raises_with_adbs_own_words(self):
        done = mock.Mock(returncode=1, stdout="", stderr="failed to pair")
        with mock.patch.object(pairing.subprocess, "run", return_value=done):
            with mock.patch.object(pairing.adb, "adb_path", return_value="adb"):
                with self.assertRaises(adb.AdbError) as caught:
                    pairing.pair("1.2.3.4:5", "secret")
        self.assertIn("failed to pair", str(caught.exception))


def _mdns_answer(instance: str, host: str, ip: str, port: int) -> bytes:
    """A PTR + SRV + A response, the way a phone answers a pairing query."""
    import socket as _socket
    import struct as _struct

    full = instance + "." + pairing.PAIRING_SERVICE
    body = b""
    ptr = pairing._encode_name(full)
    body += (pairing._encode_name(pairing.PAIRING_SERVICE)
             + _struct.pack(">HHIH", 12, 1, 120, len(ptr)) + ptr)
    srv = _struct.pack(">HHH", 0, 0, port) + pairing._encode_name(host)
    body += pairing._encode_name(full) + _struct.pack(">HHIH", 33, 1, 120, len(srv)) + srv
    addr = _socket.inet_aton(ip)
    body += pairing._encode_name(host) + _struct.pack(">HHIH", 1, 1, 120, 4) + addr
    return _struct.pack(">HHHHHH", 0, 0x8400, 0, 3, 0, 0) + body


class TestMirrorAfterConnect(unittest.TestCase):
    """--mirror turns reaching a device into watching it, in one command.

    The rule these pin down: the connection is the result, the window is the
    bonus. A machine with no scrcpy - Termux can never have one - still gets
    its pairing reported, and a zero exit code.
    """

    def _silence(self):
        return contextlib.redirect_stdout(io.StringIO())

    def _paired(self, connected="192.168.0.5:37123"):
        return mock.patch.object(
            cli.pairing, "pair_with_qr",
            return_value={"message": "paired", "connected": connected},
        )

    def test_pair_mirror_opens_scrcpy_on_the_device_it_just_reached(self):
        with self._paired(),              mock.patch.object(cli.mirror, "preflight", return_value="/usr/bin/scrcpy"),              mock.patch.object(cli.mirror, "mirror", return_value=0) as mirrored,              self._silence():
            self.assertEqual(cli.main(["pair", "--mirror"]), 0)
        mirrored.assert_called_once()
        self.assertEqual(mirrored.call_args.args[0], "192.168.0.5:37123")

    def test_pair_without_mirror_leaves_scrcpy_alone(self):
        with self._paired(),              mock.patch.object(cli.mirror, "mirror") as mirrored,              self._silence():
            self.assertEqual(cli.main(["pair"]), 0)
        mirrored.assert_not_called()

    def test_termux_reports_the_pairing_instead_of_failing_it(self):
        refuse = mock.Mock(side_effect=adb.AdbError(mirror.TERMUX_NOTE))
        out = io.StringIO()
        with self._paired(),              mock.patch.object(cli.mirror, "preflight", refuse),              mock.patch.object(cli.mirror, "mirror") as mirrored,              contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["pair", "--mirror"]), 0)
        mirrored.assert_not_called()
        self.assertIn("not mirroring", out.getvalue())
        self.assertIn("Termux", out.getvalue())

    def test_pairing_without_a_connection_has_nothing_to_mirror(self):
        out = io.StringIO()
        with self._paired(connected=None),              mock.patch.object(cli.mirror, "mirror") as mirrored,              contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["pair", "--mirror"]), 0)
        mirrored.assert_not_called()
        self.assertIn("nothing to mirror", out.getvalue())

    def test_connect_mirror_mirrors_the_normalised_serial(self):
        with mock.patch.object(cli.adb, "connect", return_value="connected"),              mock.patch.object(cli.mirror, "preflight", return_value="/usr/bin/scrcpy"),              mock.patch.object(cli.mirror, "mirror", return_value=0) as mirrored,              self._silence():
            self.assertEqual(cli.main(["connect", "192.168.0.5", "--mirror"]), 0)
        self.assertEqual(mirrored.call_args.args[0], "192.168.0.5:5555")

    def test_scan_mirror_connects_to_the_single_device_it_found(self):
        with mock.patch.object(cli.adb, "scan", return_value=["192.168.0.5:5555"]),              mock.patch.object(cli.adb, "connect", return_value="connected") as connected,              mock.patch.object(cli.mirror, "preflight", return_value="/usr/bin/scrcpy"),              mock.patch.object(cli.mirror, "mirror", return_value=0) as mirrored,              self._silence():
            self.assertEqual(cli.main(["scan", "--mirror"]), 0)
        connected.assert_called_once()
        self.assertEqual(mirrored.call_args.args[0], "192.168.0.5:5555")

    def test_scan_mirror_refuses_to_guess_between_two_devices(self):
        out = io.StringIO()
        with mock.patch.object(cli.adb, "scan",
                               return_value=["192.168.0.5:5555", "192.168.0.9:5555"]),              mock.patch.object(cli.adb, "connect") as connected,              mock.patch.object(cli.mirror, "mirror") as mirrored,              contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["scan", "--mirror"]), 1)
        connected.assert_not_called()
        mirrored.assert_not_called()
        self.assertIn("pick one", out.getvalue())


if __name__ == "__main__":
    unittest.main()
