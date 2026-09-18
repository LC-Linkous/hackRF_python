#! /usr/bin/python3

##--------------------------------------------------------------------\\
#   hackrfpy  'tests/test_docstrings.py'
#   Regression gate for plan:#1 -- every PUBLIC callable must carry a
#   real docstring. The API documentation used to live entirely in
#   comments, invisible to help(), IDE tooltips, and doc generators;
#   this test is what stops it from drifting back.
#
#
#   Author(s): Lauren Linkous
##--------------------------------------------------------------------\\

import hackrfpy
from hackrfpy import HackRF
from hackrfpy._receiver import PersistentReceiver


def _public_callables(obj):
    for name in dir(obj):
        if name.startswith("_"):
            continue
        member = getattr(obj, name)
        if callable(member):
            yield name, member


def _assert_documented(owner, name, member):
    doc = (getattr(member, "__doc__", None) or "").strip()
    assert len(doc) >= 15, (
        f"{owner}.{name} has no (or a trivial) docstring -- public API must "
        f"be introspectable; see plan:#1")


def test_hackrf_public_methods_have_docstrings():
    for name, member in _public_callables(HackRF):
        _assert_documented("HackRF", name, member)


def test_persistent_receiver_public_methods_have_docstrings():
    for name, member in _public_callables(PersistentReceiver):
        _assert_documented("PersistentReceiver", name, member)


def test_module_level_api_has_docstrings():
    for name in hackrfpy.__all__:
        member = getattr(hackrfpy, name)
        if callable(member):
            _assert_documented("hackrfpy", name, member)


def test_class_docstrings_present():
    for cls in (HackRF, PersistentReceiver):
        assert (cls.__doc__ or "").strip(), f"{cls.__name__} lacks a docstring"
