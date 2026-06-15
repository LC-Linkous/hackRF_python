#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy
#   'src/hackrfpy/_commands/device.py'
#
#   DeviceMixin: the device-management commands other wrappers tend to drop
#   (clock, spiflash, operacake, cpldjtag, debug), plus the `doctor` preflight.
#   spiflash writes firmware and can BRICK the board, so it is heavily guarded:
#   it refuses unless confirm=True is passed explicitly.
#
#   Author(s): <you>
##--------------------------------------------------------------------\

import re
import shutil

from .. import constants as C
from ..exceptions import HackRFDeviceError, HackRFEnvironmentError, HackRFValueError


class DeviceMixin:
    # ---- clock ----
    def clock(self, *args, print_cmd=False):
        argv = ["clock"] + list(args)
        return self._run(argv, mode="blocking", text=True, print_cmd=print_cmd)

    # ---- operacake antenna switch ----
    def operacake(self, *args, print_cmd=False):
        argv = ["operacake"] + list(args)
        return self._run(argv, mode="blocking", text=True, print_cmd=print_cmd)

    def operacake_list(self):
        return self.operacake("-l")

    # ---- cpld jtag (CPLD firmware) ----
    def cpldjtag(self, firmware, *, confirm=False, print_cmd=False):
        if not confirm and not print_cmd:
            raise HackRFValueError(
                "cpldjtag flashes the CPLD and can brick the board. "
                "Pass confirm=True if you are certain.")
        return self._run(["cpldjtag", "-x", firmware], mode="blocking",
                         text=True, print_cmd=print_cmd)

    # ---- spiflash (firmware) ----
    def spiflash_write(self, firmware, *, confirm=False, print_cmd=False):
        # Writing firmware. The single most dangerous operation in the library.
        if not confirm and not print_cmd:
            raise HackRFValueError(
                "spiflash_write flashes device firmware and can BRICK the "
                "board if interrupted or given a bad image. Pass confirm=True "
                "only with a verified firmware .bin and stable power.")
        return self._run(["spiflash", "-w", firmware], mode="blocking",
                         text=True, print_cmd=print_cmd)

    def spiflash_read(self, out, length=None, print_cmd=False):
        argv = ["spiflash", "-r", out]
        if length is not None:
            argv += ["-l", int(length)]
        return self._run(argv, mode="blocking", text=True, print_cmd=print_cmd)

    def spiflash_reset(self, print_cmd=False):
        return self._run(["spiflash", "-R"], mode="blocking", text=True,
                         print_cmd=print_cmd)

    # ---- debug register access ----
    def debug(self, *args, print_cmd=False):
        argv = ["debug"] + list(args)
        return self._run(argv, mode="blocking", text=True, print_cmd=print_cmd)

    # =================================================================
    # preflight: environment / readiness check
    # (was 'doctor' -- kept as an alias below for the familiar CLI verb)
    # =================================================================
    def preflight(self, capture_path="."):
        # Checks tooling, board presence, free disk, and reports the active
        # mode. Returns a structured report; raises only on hard environment
        # failures the user must fix.
        report = {"tools": {}, "boards": [], "mode": self.mode,
                  "tool_version": None, "disk_free_bytes": None,
                  "features": {}, "problems": []}

        # 1. tools on PATH (or tools_dir). Only the CORE tools (info,
        #    transfer, sweep) count as problems -- a box without operacake or
        #    spiflash is perfectly capture-ready, and flagging them broke the
        #    documented `doctor && capture` exit-code pattern on minimal
        #    Windows installs that ship only the core binaries.
        for key, name in C.TOOLS.items():
            try:
                report["tools"][name] = self.resolve(key)
            except HackRFDeviceError:
                report["tools"][name] = None
                if key in C.CORE_TOOLS:
                    report["problems"].append(f"missing core binary: {name}")

        # 2. board enumeration via hackrf_info (only if present)
        if report["tools"].get(C.TOOLS["info"]):
            try:
                out, _, _ = self._run(["info"], mode="blocking", text=True)
                parsed = self.parse_info(out)
                report["boards"] = parsed.get("boards", [])
                # version skew is the main fragility of the subprocess
                # approach: '-r -' stdout and 'sweep -N' need modern tools.
                lib = parsed.get("library", {})
                report["tool_version"] = lib.get("hackrf_info_version")
                m = re.match(r"(\d{4})", report["tool_version"] or "")
                if m and int(m.group(1)) < 2021:
                    report["problems"].append(
                        f"hackrf-tools {report['tool_version']} predates "
                        f"2021; '-r -' streaming and 'sweep -N' may be "
                        f"unsupported -- please upgrade")
                if not report["boards"]:
                    report["problems"].append(
                        "no HackRF board detected (check USB / permissions)")
            except HackRFDeviceError as e:
                report["problems"].append(str(e))

        # 2b. feature probe: derive capability flags from the firmware version
        #     (reliable year) and tools version. See features().
        fw = None
        if report["boards"]:
            fw = report["boards"][0].get("firmware_version")
        report["features"] = self.features(report.get("tool_version"), fw)

        # 3. disk
        try:
            report["disk_free_bytes"] = shutil.disk_usage(capture_path).free
        except OSError as e:
            report["problems"].append(f"cannot stat disk at {capture_path}: {e}")

        self._print_preflight(report)
        return report

    # doctor: familiar alias for preflight (brew/flutter-style verb). The CLI
    # still exposes `hrf doctor`; the honest method name is preflight().
    def doctor(self, capture_path="."):
        return self.preflight(capture_path=capture_path)

    def features(self, tool_version=None, firmware_version=None):
        # Map version strings -> capability flags. The reliable year signal is
        # the FIRMWARE version (e.g. "2024.02.1"); the tools version is often a
        # git tag (e.g. "git-b1dbb47") with no parseable year. If nothing is
        # passed, probe the device once and use both. Table-driven + pure, so
        # unit-testable without hardware.
        if tool_version is None and firmware_version is None:
            try:
                parsed = self.parse_info(
                    self._run(["info"], mode="blocking", text=True)[0])
                tool_version = (parsed.get("library", {})
                                .get("hackrf_info_version"))
                boards = parsed.get("boards", [])
                if boards:
                    firmware_version = boards[0].get("firmware_version")
            except HackRFDeviceError:
                pass

        # Prefer the firmware version's year; fall back to the tools version.
        # A "git-" build is a from-source build, which is current by
        # definition -- treat it as modern rather than merely "unknown".
        def _year(v):
            m = re.match(r"(\d{4})", v or "")
            return int(m.group(1)) if m else None

        year = _year(firmware_version) or _year(tool_version)
        is_git = ((tool_version or "").startswith("git-")
                  or (firmware_version or "").startswith("git-"))
        # known if we have a real year OR it's an identifiable git build
        known = year is not None or is_git
        modern = is_git or year is None or year >= 2021
        return {
            "tool_version": tool_version,
            "firmware_version": firmware_version,
            "version_known": known,
            "is_git_build": is_git,
            "stdout_streaming": modern,                    # rx -r - / sweep
            "sweep_num_sweeps": modern,                    # sweep -N
            "bias_tee": is_git or year is None or year >= 2018,  # -p
        }

    def _print_preflight(self, r):
        print("hackrfpy preflight")
        print("-" * 40)
        for name, path in r["tools"].items():
            print(f"  {'OK ' if path else 'XX '} {name:18} "
                  f"{path or 'NOT FOUND'}")
        if r.get("tool_version"):
            print(f"  tools version   : {r['tool_version']}")
        feats = r.get("features", {})
        if feats and not feats.get("stdout_streaming", True):
            print("  ! stdout streaming (rx -r - / capture_array) unsupported "
                  "by this tools version")
        print(f"  boards detected : {len(r['boards'])}")
        for b in r["boards"]:
            sn = b.get("serial_number", b.get("serial", "?"))
            print(f"      - {sn}")
        if r["disk_free_bytes"] is not None:
            print(f"  free disk       : {r['disk_free_bytes']/1e9:.1f} GB")
        print(f"  active mode     : {r['mode']}")
        if r["problems"]:
            print("  problems:")
            for p in r["problems"]:
                print(f"      ! {p}")
        else:
            print("  no problems found")
