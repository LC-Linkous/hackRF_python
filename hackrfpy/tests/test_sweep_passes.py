#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'tests/test_sweep_passes.py'
#   iter_sweep_passes / sweep_passes: grouping hackrf_sweep rows into whole,
#   frequency-sorted passes. Runs without a device. The boundary rule under
#   test -- segment revisit, never timestamp -- is the one real hardware
#   taught monitor_frequencies in 1.1.0.
#
#   Author(s): Lauren Linkous
##--------------------------------------------------------------------\

import os

import numpy as np

from hackrfpy._commands.sweep import SweepMixin


def _fixture_rows(fixtures_dir):
    rows = []
    with open(os.path.join(fixtures_dir, "sweep_sample_real.csv")) as fh:
        for line in fh:
            r = SweepMixin.parse_sweep_line(line)
            if r is not None:
                rows.append(r)
    assert len(rows) == 4                        # the garbled line is dropped
    return rows


def _row(low, high, db, stamp="12:00:00.000000", bw=1_000_000.0):
    return {"date": "2026-06-15", "time": stamp, "hz_low": low, "hz_high": high,
            "bin_width": bw, "num_samples": 20, "db": list(db)}


def test_real_fixture_is_one_contiguous_pass(fixtures_dir):
    passes = list(SweepMixin.iter_sweep_passes(_fixture_rows(fixtures_dir)))
    assert len(passes) == 1
    p = passes[0]
    assert (p["start"], p["stop"], p["bin_width"]) == (88_000_000, 108_000_000, 1e6)
    assert p["points"] == 20 and p["level"].shape == (20,)
    assert p["level"].dtype == np.float32
    assert p["segments"] == 4 and p["contiguous"]
    assert not np.isnan(p["level"]).any()
    # sorted by frequency even though the file is 88, 98, 93, 103
    assert p["level"][0] == np.float32(-67.19)      # 88 MHz row, first bin
    assert p["level"][5] == np.float32(-67.23)      # 93 MHz row
    assert p["level"][10] == np.float32(-59.12)     # 98 MHz row
    assert p["level"][19] == np.float32(-85.31)     # 103 MHz row, last bin


def test_pass_boundary_is_segment_revisit_not_timestamp():
    # Real hackrf_sweep stamps every row individually. Two passes of two
    # segments each, every row with a DIFFERENT timestamp: a timestamp rule
    # would yield four partial passes; the revisit rule yields two whole ones.
    rows = [_row(88e6, 93e6, [1] * 5, "12:00:00.1"),
            _row(93e6, 98e6, [2] * 5, "12:00:00.2"),
            _row(88e6, 93e6, [3] * 5, "12:00:00.3"),
            _row(93e6, 98e6, [4] * 5, "12:00:00.4")]
    passes = list(SweepMixin.iter_sweep_passes(rows))
    assert len(passes) == 2
    assert passes[0]["level"].tolist() == [1] * 5 + [2] * 5
    assert passes[1]["level"].tolist() == [3] * 5 + [4] * 5
    assert passes[0]["time"] == "12:00:00.1"        # first row of the pass


def test_shared_timestamp_does_not_merge_passes():
    # The mirror case: stubs give every row of a pass the same timestamp, and
    # two consecutive passes may share one. Revisit still splits them.
    rows = [_row(88e6, 93e6, [1] * 5), _row(93e6, 98e6, [2] * 5),
            _row(88e6, 93e6, [3] * 5), _row(93e6, 98e6, [4] * 5)]
    assert len(list(SweepMixin.iter_sweep_passes(rows))) == 2


def test_trailing_partial_pass_is_yielded_and_marked():
    rows = [_row(88e6, 93e6, [1] * 5), _row(93e6, 98e6, [2] * 5),
            _row(88e6, 93e6, [3] * 5)]                 # stream ended here
    passes = list(SweepMixin.iter_sweep_passes(rows))
    assert len(passes) == 2
    assert passes[1]["segments"] == 1 and passes[1]["points"] == 5
    assert passes[1]["contiguous"]


def test_gap_between_segments_is_nan_and_not_contiguous():
    rows = [_row(88e6, 93e6, [1] * 5), _row(98e6, 103e6, [3] * 5)]   # 93-98 missing
    p = next(SweepMixin.iter_sweep_passes(rows))
    assert p["points"] == 15 and not p["contiguous"]
    assert np.isnan(p["level"][5:10]).all()
    assert p["level"][:5].tolist() == [1] * 5 and p["level"][10:].tolist() == [3] * 5


def test_empty_input_yields_nothing():
    assert list(SweepMixin.iter_sweep_passes([])) == []


def test_sweep_passes_closes_the_row_generator(monkeypatch):
    # sweep_passes must reap hackrf_sweep when the consumer stops early: the
    # row generator's close() is how sweep() interrupts the child.
    closed = {"n": 0}

    def fake_rows():
        try:
            yield _row(88e6, 93e6, [1] * 5)
            yield _row(93e6, 98e6, [2] * 5)
            yield _row(88e6, 93e6, [3] * 5)      # revisit -> first pass emitted
            yield _row(93e6, 98e6, [4] * 5)
        finally:
            closed["n"] += 1

    class H(SweepMixin):
        def sweep(self, *a, **k):
            return fake_rows()

    gen = H().sweep_passes(88e6, 98e6)
    first = next(gen)
    assert first["level"].tolist() == [1] * 5 + [2] * 5
    gen.close()
    assert closed["n"] == 1
