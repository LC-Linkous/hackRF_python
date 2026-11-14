#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_encode_iq.py'
#   encode_iq is the exact inverse of decode_iq / load_iq. Runs without a
#   device. The property under test is the one hackrf-web's recorder relies
#   on: a stream decoded to complex64 and re-encoded is byte-identical.
#
#   Author(s): Lauren Linkous
##--------------------------------------------------------------------\

import os

import numpy as np
import pytest

from hackrfpy import HackRF, encode_iq, load_iq
from hackrfpy.exceptions import HackRFValueError


def test_bytes_roundtrip_on_real_fixture(fixtures_dir):
    raw = open(os.path.join(fixtures_dir, "sample_real.iq"), "rb").read()
    raw = raw[: len(raw) - (len(raw) % 2)]           # whole pairs only
    h = HackRF()
    assert encode_iq(h.decode_iq(raw)) == raw


def test_every_int8_code_survives():
    # All 256 x 256 would be 65k samples; the diagonal plus the extremes is
    # enough to prove rint/clip do not bias or saturate any code.
    codes = np.arange(-128, 128, dtype=np.int8)
    raw = np.empty(2 * codes.size, dtype=np.int8)
    raw[0::2] = codes
    raw[1::2] = codes[::-1]
    h = HackRF()
    assert encode_iq(h.decode_iq(raw.tobytes())) == raw.tobytes()


def test_complex_roundtrip_is_lossless():
    rng = np.random.default_rng(0)
    raw = rng.integers(-128, 128, size=2 * 4096, dtype=np.int8).tobytes()
    h = HackRF()
    once = h.decode_iq(raw)
    twice = h.decode_iq(encode_iq(once))
    assert np.array_equal(once, twice)


def test_layout_is_interleaved_i_then_q():
    iq = np.array([1 / 128 + 2j / 128, -3 / 128 - 4j / 128], dtype=np.complex64)
    assert encode_iq(iq) == bytes([1, 2, 0xFD, 0xFC])    # 1, 2, -3, -4


def test_rounds_to_nearest_and_clips():
    iq = np.array([0.5 + 0j,            # 64.0 exactly
                   0.5039 + 0j,         # 64.4992 -> 64
                   0.5078 + 0j,         # 64.9984 -> 65
                   1.0 + 1j,            # 128 -> clips to 127
                   -1.5 - 1.5j], dtype=np.complex64)
    out = np.frombuffer(encode_iq(iq), dtype=np.int8)
    assert out[0] == 64 and out[2] == 64 and out[4] == 65
    assert out[6] == 127 and out[7] == 127
    assert out[8] == -128 and out[9] == -128


def test_load_iq_and_encode_agree(tmp_path):
    rng = np.random.default_rng(1)
    raw = rng.integers(-128, 128, size=2 * 1000, dtype=np.int8).tobytes()
    p = tmp_path / "x.iq"
    p.write_bytes(raw)
    assert encode_iq(load_iq(str(p))) == raw


def test_class_alias_matches_module_function():
    iq = (np.arange(8) / 128).astype(np.complex64)
    assert HackRF.encode_iq(iq) == encode_iq(iq)


def test_rejects_non_1d():
    with pytest.raises(HackRFValueError):
        encode_iq(np.zeros((2, 2), dtype=np.complex64))
