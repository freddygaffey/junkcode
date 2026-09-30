"""dictate._make_controller: live emit -> finish() -> _second_pass.

Everything that touches the outside world is faked: the "screen" is a string
that receives typed text and backspaces, the recorder returns canned audio, the
transcriber returns a scripted final text, and StreamingTranscriber's timer
thread is replaced by manual _flush() calls.

The invariant under test: the second pass may only ever delete characters that
the live pass itself typed, and only if the cursor is still where it was left.
"""
import configparser
import time

import numpy as np
import pytest

import dictate
import editguard
import streaming

PREFIX = "USER TEXT: "


class Screen:
    """A text field. Typing appends at the caret (always the end); backspace deletes."""

    def __init__(self, text=PREFIX):
        self.text = text
        self.typed = 0
        self.erased = 0

    def type(self, s):
        self.text += s
        self.typed += len(s)

    def backspace(self, n):
        self.erased += n
        self.text = self.text[:max(0, len(self.text) - n)]


def make_cfg(method="type", second_pass=True, hold=True):
    cfg = configparser.ConfigParser()
    cfg.read_dict({
        "audio": {"sample_rate": "16000", "channels": "1", "max_seconds": "300"},
        "hotkey": {"key": "f9", "mode": "toggle"},
        "transcription": {"live": "true", "second_pass": str(second_pass).lower(),
                          "hold_while_editing": str(hold).lower(),
                          "edit_idle_seconds": "1.2", "live_interval": "1.4"},
        "output": {"method": method, "echo_to_stdout": "false"},
        "cleanup": {"enabled": "false"},
    })
    return cfg


class Rig:
    def __init__(self, monkeypatch, cfg, final="", pieces=(), fail_type=False):
        self.screen = Screen()
        self.final = final
        self.on_second_pass = None       # callback run while "transcribing"
        self.fail_type = fail_type
        self.streams = []
        self.guards = []
        rig = self

        class FakeTranscriber:
            backend = object()
            language = "en"
            initial_prompt = None

            def __init__(self, cfg):
                pass

            def transcribe(self, audio):
                if rig.on_second_pass:
                    rig.on_second_pass()
                return rig.final

        class FakeRecorder:
            sample_rate = 16000

            def __init__(self, *a, **k):
                self.on_chunk = None

            def start(self):
                pass

            def stop(self):
                return np.full(16000, 0.1, dtype="float32")

        class ManualStream(streaming.StreamingTranscriber):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                rig.streams.append(self)

            def start(self):                 # no timer thread; tests drive it
                pass

            def finish(self):
                return " ".join(self._all).strip()

        class ManualGuard(editguard.EditGuard):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                rig.guards.append(self)

            def start(self):                 # no pynput listeners
                return True

        def fake_emit_raw(text, cfg):
            if rig.fail_type:
                raise RuntimeError("xclip not found / no display")
            rig.screen.type(text)

        monkeypatch.setattr(dictate, "Transcriber", FakeTranscriber)
        monkeypatch.setattr(dictate, "Recorder", FakeRecorder)
        monkeypatch.setattr(dictate.streaming_mod, "StreamingTranscriber", ManualStream)
        monkeypatch.setattr(dictate.editguard_mod, "EditGuard", ManualGuard)
        monkeypatch.setattr(dictate, "emit_raw", fake_emit_raw)
        monkeypatch.setattr(dictate, "erase", lambda n: rig.screen.backspace(n) if n > 0 else None)
        monkeypatch.setattr(dictate, "_set_state", lambda s: None)   # never touch the real state file

        self.begin, self.finish, self.state, _ = dictate._make_controller(cfg)
        self.guard = self.guards[0] if self.guards else None

    def live_emit(self, *groups):
        """Push word groups through the real StreamingTranscriber emitter."""
        st = self.streams[-1]
        for g in groups:
            st._all.extend(g)
            st.on_words(list(g))


@pytest.fixture
def rig_factory(monkeypatch):
    def f(cfg=None, **kw):
        r = Rig(monkeypatch, cfg or make_cfg(), **kw)
        r.begin()
        return r
    return f


# ------------------------------------------------------ character accounting
def test_count_matches_screen_for_several_live_groups(rig_factory):
    r = rig_factory(final="Hello there, big world.")
    r.live_emit(["hello", "there"], ["big"], ["world"])
    live = r.screen.text
    assert live == PREFIX + "hello there big world"
    r.finish()
    assert r.screen.erased == len("hello there big world")
    assert r.screen.text == PREFIX + "Hello there, big world."


def test_no_change_means_no_backspaces(rig_factory):
    r = rig_factory(final="hello   there\nbig world")
    r.live_emit(["hello", "there"], ["big", "world"])
    r.finish()
    assert r.screen.erased == 0
    assert r.screen.text == PREFIX + "hello there big world"


def test_first_group_has_no_leading_space_later_groups_do(rig_factory):
    r = rig_factory(final="x")
    r.live_emit(["a"], ["b"])
    assert r.screen.text == PREFIX + "a b"


def test_second_pass_when_live_emitted_nothing_does_nothing(rig_factory):
    r = rig_factory(final="I said something")
    r.finish()
    assert r.screen.erased == 0
    assert r.screen.typed == 0
    assert r.screen.text == PREFIX


def test_second_pass_disabled(rig_factory):
    r = rig_factory(cfg=make_cfg(second_pass=False), final="different")
    r.live_emit(["hello"])
    r.finish()
    assert r.screen.erased == 0 and r.screen.text == PREFIX + "hello"


def test_empty_final_leaves_live_text(rig_factory):
    r = rig_factory(final="   ")
    r.live_emit(["hello"])
    r.finish()
    assert r.screen.text == PREFIX + "hello" and r.screen.erased == 0


def test_counter_resets_between_dictations(rig_factory):
    r = rig_factory(final="Hi")
    r.live_emit(["hi"])
    r.finish()
    r.begin()
    r.live_emit(["yo"])
    r.final = "Yo!"
    r.finish()
    # second dictation must erase only its own 2 chars, not 2 + 2
    assert r.screen.text == PREFIX + "Hi" + "Yo!"


@pytest.mark.parametrize("groups", [
    [["a"]], [["a"], ["b"]], [["hello", "world"], ["x"], ["y", "z"]],
    [["it's"], ["naïve"], ["café"]],
])
@pytest.mark.parametrize("hold", [True, False])
def test_never_erases_more_than_was_typed(rig_factory, groups, hold):
    r = rig_factory(cfg=make_cfg(hold=hold), final="Completely different words here")
    r.live_emit(*groups)
    r.finish()
    assert r.screen.text.startswith(PREFIX)
    assert r.screen.text == PREFIX + "Completely different words here"


# ------------------------------------------------- held text flushed later
def test_count_correct_when_held_pieces_are_flushed_together(rig_factory):
    """Guard holds pieces while paused; resume() flushes them in one write."""
    r = rig_factory(final="Alpha beta gamma.")
    r.guard.pause()
    r.live_emit(["alpha"], ["beta"], ["gamma"])
    assert r.screen.text == PREFIX                   # everything is held
    r.guard.resume()                                  # user finished their edit
    typed_live = r.screen.text[len(PREFIX):]
    r.finish()
    assert r.screen.erased == len(typed_live), (
        f"typed {len(typed_live)} chars ({typed_live!r}) but sent {r.screen.erased} backspaces")
    assert r.screen.text == PREFIX + "Alpha beta gamma."


def test_held_text_flushed_at_finish_is_counted(rig_factory):
    r = rig_factory(final="Hello world.")
    r.guard.pause()
    r.live_emit(["hello"])
    # paused at finish: flush() types it, but the second pass must then refuse
    r.finish()
    assert r.screen.text == PREFIX + "hello"
    assert r.screen.erased == 0


# ------------------------------------------------------ output failure modes
def test_failed_typing_is_not_counted_as_typed(rig_factory):
    """e.g. method=clipboard with xclip missing: nothing reaches the screen,
    so nothing may be erased. Backspaces would land on the user's own text."""
    r = rig_factory(cfg=make_cfg(method="clipboard", hold=False), final="Hello world.",
                    fail_type=True)
    r.live_emit(["hello", "world"])
    r.fail_type = False
    r.finish()
    assert r.screen.text.startswith(PREFIX), (
        f"second pass ate the user's text: {r.screen.text!r}")


def test_clipboard_method_uses_same_character_count(monkeypatch):
    sent = []
    monkeypatch.setattr(dictate, "_emit_clipboard", sent.append)
    dictate.emit_raw("hello world", make_cfg(method="clipboard"))
    assert sent == ["hello world"]


# ------------------------------------------ safety checks before deleting
def test_skipped_when_user_is_typing_at_finish(rig_factory):
    r = rig_factory(final="Different.")
    r.live_emit(["hello"])
    r.guard._last_input = time.monotonic()
    r.finish()
    assert r.screen.text == PREFIX + "hello" and r.screen.erased == 0


def test_skipped_when_paused_at_finish(rig_factory):
    r = rig_factory(final="Different.")
    r.live_emit(["hello"])
    r.guard.pause()
    r.finish()
    assert r.screen.erased == 0


def test_user_input_during_second_pass_transcription_cancels_erase(rig_factory):
    """Transcribing the whole recording takes seconds. The idle check happens
    BEFORE it; if the user starts typing or switches window meanwhile, the
    backspaces must not be sent."""
    r = rig_factory(final="Different.")
    r.live_emit(["hello", "world"])
    r.on_second_pass = lambda: setattr(r.guard, "_last_input", time.monotonic())
    r.finish()
    assert r.screen.erased == 0, "backspaces sent after the user had resumed typing"


def test_pause_during_second_pass_transcription_cancels_erase(rig_factory):
    r = rig_factory(final="Different.")
    r.live_emit(["hello", "world"])
    r.on_second_pass = r.guard.pause
    r.finish()
    assert r.screen.erased == 0


def test_user_text_typed_between_live_output_and_stop_is_not_erased(rig_factory):
    """The user dictates, pauses, types a few words by hand, waits longer than
    the idle window, then stops. The caret is no longer where live left it, so
    a blind erase(count) deletes their words."""
    r = rig_factory(final="Hello world.")
    r.live_emit(["hello", "world"])
    r.screen.type(" and my own words")          # user's keyboard; guard idle again
    r.guard._last_input = time.monotonic() - 5
    r.finish()
    assert "and my own words" in r.screen.text, r.screen.text


def test_no_guard_means_no_safety_check_documented(rig_factory):
    """hold_while_editing=false: nothing can veto the erase. Locks in current
    behaviour so a change is noticed."""
    r = rig_factory(cfg=make_cfg(hold=False), final="Different.")
    assert r.guard is None
    r.live_emit(["hello"])
    r.finish()
    assert r.screen.text == PREFIX + "Different."
