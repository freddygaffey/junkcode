"""EditGuard: hold while the user is active, flush when idle, never while paused."""
import time

from editguard import EditGuard


def make(idle=0.05):
    out = []
    states = []
    g = EditGuard(idle_seconds=idle, on_flush=out.append, on_state=states.append)
    return g, out, states


def test_types_immediately_when_idle():
    g, out, _ = make()
    g.submit("hello")
    assert out == ["hello"]


def test_empty_text_ignored():
    g, out, _ = make()
    g.submit("")
    g.flush()
    assert out == []


def test_holds_while_input_is_recent():
    g, out, states = make(idle=10)
    g._note_input()
    g.submit("hello")
    assert out == []
    assert states[-1] is True


def test_flush_releases_held_text_joined():
    g, out, states = make(idle=10)
    g._note_input()
    g.submit("hello")
    g.submit("world")
    g.flush()
    assert out == ["hello world"]
    assert states[-1] is False


def test_types_again_after_idle_period():
    g, out, _ = make(idle=0.05)
    g._note_input()
    g.submit("held")
    assert out == []
    time.sleep(0.08)
    assert g.safe_to_type()
    g.submit("now")
    assert out == ["now"]


def test_safe_to_type_false_while_input_recent_then_true():
    g, _, _ = make(idle=0.05)
    g._note_input()
    assert not g.safe_to_type()
    time.sleep(0.08)
    assert g.safe_to_type()


def test_paused_holds_and_is_never_safe():
    g, out, _ = make(idle=0.0)
    g.pause()
    assert g.paused
    assert not g.safe_to_type()
    g.submit("hello")
    assert out == []
    time.sleep(0.02)
    assert not g.safe_to_type()


def test_resume_flushes_and_restores_safety():
    g, out, _ = make(idle=0.0)
    g.pause()
    g.submit("hello")
    g.resume()
    assert out == ["hello"]
    assert not g.paused
    assert g.safe_to_type()


def test_own_output_is_not_mistaken_for_user_input():
    g, out, _ = make(idle=10)
    g.expect_own_output(5)
    g._note_input()                       # synthesised keystroke
    assert g._last_input == 0.0
    g.submit("a")
    assert out == ["a"]


def test_write_reserves_own_output_window():
    g, out, _ = make()
    g.submit("hello")
    g._note_input()                       # keystrokes from our own typing
    assert g.safe_to_type()


def test_flush_does_not_lose_or_duplicate_text_when_called_twice():
    g, out, _ = make(idle=10)
    g._note_input()
    g.submit("a")
    g.flush()
    g.flush()
    assert out == ["a"]


def test_flush_returns_only_after_text_has_been_written():
    """finish() calls flush() then trusts that everything held is on screen
    before the second pass may send backspaces."""
    import threading

    started, release = threading.Event(), threading.Event()
    written = []

    def slow_write(text):
        started.set()
        release.wait(2)
        written.append(text)

    g = EditGuard(idle_seconds=10, on_flush=slow_write)
    g._note_input()
    g.submit("held")
    t = threading.Thread(target=g.flush)     # e.g. the drain thread
    t.start()
    assert started.wait(1)
    done = threading.Event()
    threading.Thread(target=lambda: (g.flush(), done.set())).start()   # finish()
    finished_early = done.wait(0.3)
    release.set()
    t.join()
    assert not finished_early, "flush() returned while held text was still being typed"
