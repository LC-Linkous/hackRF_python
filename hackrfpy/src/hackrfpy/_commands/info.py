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

    @staticmethod
    def parse_info(text):
        # hackrf_info prints "Key: value" lines: a version preamble, then one
        # block per board. We keep the preamble under "library" and each board
        # under "boards". A board starts at "Found HackRF" or, for outputs that
        # omit it, at an "Index:" line.
        result = {"library": {}, "boards": []}
        current = None
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.lower().startswith("found hackrf"):
                current = {}
                result["boards"].append(current)
                continue
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
            val = val.strip()
            if key == "index":
                if current is None or "index" in current:
                    current = {}
                    result["boards"].append(current)
                current[key] = val
            elif current is None:
                result["library"][key] = val   # version preamble
            else:
                current[key] = val
        return result
