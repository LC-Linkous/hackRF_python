#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy
#   'src/hackrfpy/_commands/info.py'
#
#   InfoMixin: hackrf_info wrapper. The clean request/response case -- run the
#   binary, capture stdout text, parse to a dict. Mixin only; assumes the host
#   HackRF class provides _run, print_message, and mode state.
#
#   Author(s): <you>
##--------------------------------------------------------------------\

import re


class InfoMixin:
    def info(self, raw=False, print_cmd=False):
        # Returns a parsed dict by default, or the raw text if raw=True.
        if print_cmd:
            self._run(["info"], mode="blocking", print_cmd=True)
            return None
        out, err, rc = self._run(["info"], mode="blocking", text=True)
        self.print_message(f"[*] mode: {self.mode}")
        if raw:
            return out
        return self.parse_info(out)

    def get_info(self):
        # alias
        return self.info()

    def detect(self):
        # Hardware autodetection + identification, the HackRF analog of a
        # serial-port scan. The HackRF is NOT a serial device -- there are no
        # COM ports to walk -- so "detection" means: run hackrf_info, confirm
        # each enumerated board is actually a HackRF, and report identity +
        # firmware. Never raises for "no board"; that is a normal result the
        # caller inspects. Raises HackRFDeviceError only if hackrf_info itself
        # cannot run (missing binary).
        #
        # Returns a dict:
        #   {
        #     "found": bool,         # at least one board enumerated
        #     "ready": bool,         # >=1 CONFIRMED HackRF + usable tooling
        #     "count": int,
        #     "boards": [ {index, serial, name, firmware, is_hackrf,
        #                  firmware_stale}, ... ],
        #     "tools_version": str|None,
        #     "libhackrf_version": str|None,
        #     "multiple": bool,      # >1 board -> disambiguate with serial=
        #     "problem": str|None,
        #   }
        from ..exceptions import HackRFDeviceError
        result = {"found": False, "ready": False, "count": 0, "boards": [],
                  "tools_version": None, "libhackrf_version": None,
                  "multiple": False, "warnings": [], "problem": None}
        try:
            out, _, _ = self._run(["info"], mode="blocking", text=True)
        except HackRFDeviceError as e:
            # hackrf_info couldn't run at all (binary missing). Surface it as a
            # problem rather than raising, so detect() is always safe to call.
            result["problem"] = str(e)
            return result

        parsed = self.parse_info(out)
        lib = parsed.get("library", {})
        result["tools_version"] = lib.get("hackrf_info_version")
        result["libhackrf_version"] = lib.get("libhackrf_version")
        # device-emitted free-text warnings, e.g. "There are N other devices
        # on the same USB bus. You may have problems at high sample rates."
        result["warnings"] = parsed.get("warnings", [])

        boards = parsed.get("boards", [])
        result["count"] = len(boards)
        result["found"] = len(boards) > 0
        result["multiple"] = len(boards) > 1

        for b in boards:
            board_id = b.get("board_id_number", "")
            # "Board ID Number: 2 (HackRF One)" -> confirm it's a HackRF
            is_hackrf = "hackrf" in board_id.lower()
            fw = b.get("firmware_version", "")
            m = re.match(r"(\d{4})", fw or "")
            stale = bool(m and int(m.group(1)) < 2021)
            result["boards"].append({
                "index": b.get("index"),
                "serial": b.get("serial_number"),
                "name": board_id or None,
                "firmware": fw or None,
                "is_hackrf": is_hackrf,
                "firmware_stale": stale,
            })

        # ready = at least one confirmed HackRF present
        result["ready"] = any(bd["is_hackrf"] for bd in result["boards"])
        if result["found"] and not result["ready"]:
            result["problem"] = ("a USB device was enumerated but did not "
                                 "identify as a HackRF")
        elif not result["found"]:
            result["problem"] = "no HackRF board detected (check USB / drivers)"
        return result

    def identify(self, serial=None):
        # Return the identity of a single board: the one matching `serial`, or
        # the first detected board if serial is None. Returns the board dict
        # from detect()["boards"], or None if not found. Convenience for "what
        # am I about to talk to?" before a capture/transmit.
        det = self.detect()
        if not det["boards"]:
            return None
        if serial is None:
            return det["boards"][0]
        for b in det["boards"]:
            if b["serial"] and serial in b["serial"]:
                return b
        return None

    @staticmethod
    def parse_info(text):
        # hackrf_info prints "Key: value" lines: a version preamble, then one
        # block per board. We keep the preamble under "library" and each board
        # under "boards". A board starts at "Found HackRF" or, for outputs that
        # omit it, at an "Index:" line.
        #
        # Real-hardware quirks this handles:
        #   - "Hardware supported by installed firmware:" puts its value on the
        #     NEXT, indented line (e.g. "    HackRF One") rather than after the
        #     colon -- so an empty value followed by an indented line is a
        #     continuation, not a blank.
        #   - Trailing free-text warnings with no colon (e.g. "There are 2
        #     other devices on the same USB bus. You may have problems at high
        #     sample rates.") are collected under result["warnings"] instead of
        #     being silently dropped.
        result = {"library": {}, "boards": [], "warnings": []}
        current = None
        last_target = None      # dict the last key was written to
        last_key = None         # the last key, for continuation lines
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.lower().startswith("found hackrf"):
                current = {}
                result["boards"].append(current)
                last_target = last_key = None
                continue
            if ":" not in line:
                # No colon. Either a continuation of the previous key whose
                # value was on this indented line, or a free-text warning.
                if (last_target is not None and last_key is not None
                        and raw[:1].isspace() and not last_target.get(last_key)):
                    last_target[last_key] = line   # fill the empty continuation
                else:
                    result["warnings"].append(line)
                continue
            key, _, val = line.partition(":")
            key = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
            val = val.strip()
            if key == "index":
                if current is None or "index" in current:
                    current = {}
                    result["boards"].append(current)
                current[key] = val
                last_target, last_key = current, key
            elif current is None:
                result["library"][key] = val   # version preamble
                last_target, last_key = result["library"], key
            else:
                current[key] = val
                last_target, last_key = current, key
        return result
