"""Local agreement, silence gating and hallucination gating (pure logic)."""
import numpy as np
import pytest

import streaming
from streaming import StreamingTranscriber, SAMPLE_RATE


def speech(seconds=1.0):
    return np.full(int(SAMPLE_RATE * seconds), 0.1, dtype="float32")


class FakeBackend:
    """Returns scripted transcripts, repeating the last one forever."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def transcribe(self, audio, language, prompt):
        text = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return text


def make(script, **kw):
    got = []
    st = StreamingTranscriber(FakeBackend(script), on_words=got.append, **kw)
    st.add_audio(speech())
    return st, got


def flat(got):
    return [w for chunk in got for w in chunk]


# ------------------------------------------------------------ local agreement
def test_nothing_emitted_after_single_pass():
    st, got = make(["hello world"])
    st._flush(False)
    assert got == []


def test_words_emitted_only_after_two_agreeing_passes():
    st, got = make(["hello", "hello world", "hello world how"])
    st._flush(False)
    assert got == []
    st._flush(False)               # "hello" now agreed by passes 1 and 2
    assert got == [["hello"]]
    st._flush(False)               # "world" agreed by passes 2 and 3
    assert got == [["hello"], ["world"]]


def test_agreement_ignores_case_and_punctuation():
    st, got = make(["Hello,", "hello world"])
    st._flush(False)
    st._flush(False)
    assert len(flat(got)) == 1


def test_emitted_text_is_never_retracted():
    st, got = make(["one two three", "one two three four", "uno dos tres four five"])
    for _ in range(3):
        st._flush(False)
    emitted = flat(got)
    assert emitted == ["one", "two", "three"]   # later disagreement rewrites nothing
    assert st._all[:3] == ["one", "two", "three"]


def test_emission_is_append_only_prefix_of_final():
    st, got = make(["a b", "a b c", "a b c d", "a b c d e"])
    seen = []
    for _ in range(4):
        st._flush(False)
        assert flat(got)[:len(seen)] == seen
        seen = flat(got)


def test_final_pass_commits_the_rest():
    st, got = make(["hello world", "hello world again"])
    st._flush(False)
    st._flush(True)
    assert flat(got) == ["hello", "world", "again"]


def test_finish_returns_joined_text():
    st, got = make(["hello world", "hello world"])
    st._flush(False)
    assert st.finish() == "hello world"


# ------------------------------------------------------------------- gating
def test_silence_never_reaches_the_model():
    be = FakeBackend(["hello"])
    st = StreamingTranscriber(be)
    st.add_audio(np.zeros(SAMPLE_RATE * 2, dtype="float32"))
    st._flush(False)
    st._flush(True)
    assert be.calls == 0


def test_too_short_audio_not_transcribed():
    be = FakeBackend(["hello"])
    st = StreamingTranscriber(be)
    st.add_audio(speech(0.2))
    st._flush(True)
    assert be.calls == 0


@pytest.mark.parametrize("junk", [
    "you", "You", " you ", "Thank you.", "thank you", "Thanks for watching!",
    "...", ".", "", "  ", ", .", "Bye.", "Subtitles by the Amara.org community",
])
def test_hallucinations_dropped(junk):
    st, got = make([junk])
    for _ in range(3):
        st._flush(False)
    st._flush(True)
    assert got == []


@pytest.mark.parametrize("real", [
    "Thank you for coming",
    "I love you.",
    "you know what I mean",
    "and the answer is yes",
    "Thank you. Now on to item two.",
    "so it goes",
])
def test_genuine_sentences_containing_hallucination_words_survive(real):
    st, got = make([real])
    st._flush(False)
    st._flush(False)
    assert flat(got) == real.split()


def test_hallucination_check_is_whole_pass_not_substring():
    assert not streaming._is_hallucination("Thank you for watching my cat")
    assert streaming._is_hallucination("Thank you.")
    assert streaming._is_hallucination("   ")


# ------------------------------------------------------------ buffer rollover
def test_rollover_commits_leftover_and_clears_buffer():
    st, got = make(["a b c"], max_buffer_s=0.5)
    st._flush(False)                 # buffer (1s) exceeds 0.5s: commit everything
    assert flat(got) == ["a", "b", "c"]
    assert len(st._buf) == 0
    assert st._prev == [] and st._committed_in_buf == 0


def test_rollover_does_not_drop_audio_that_arrived_during_the_pass():
    """Transcription takes seconds while the mic keeps streaming. Audio added
    after the buffer snapshot must survive the rollover reset."""
    class Backend(FakeBackend):
        def transcribe(self, audio, language, prompt):
            st.add_audio(speech(0.5))       # mic keeps delivering mid-pass
            return super().transcribe(audio, language, prompt)

    be = Backend(["a b c"])
    st = StreamingTranscriber(be, max_buffer_s=0.5)
    st.add_audio(speech(1.0))
    st._flush(False)                        # 1.0s > 0.5s -> rollover
    assert len(st._buf) == int(SAMPLE_RATE * 0.5), "audio recorded during the pass was discarded"
