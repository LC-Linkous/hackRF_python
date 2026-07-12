# Security Policy

## Supported versions

This is an unofficial, community-maintained project under active development.
Security-relevant fixes are applied to the latest release on the `main` branch
only. There is no back-porting to older versions.

| Version | Supported          |
| ------- | ------------------ |
| latest (`main` / newest release) | :white_check_mark: |
| older releases | :x: |

## Reporting a vulnerability

Please **do not open a public issue** for security-sensitive reports.

Use GitHub's private vulnerability reporting:
**Security → Report a vulnerability** on the repository, or the "Report a
vulnerability" button under the Security tab. This opens a private advisory
visible only to the maintainers.

When reporting, please include:

- A description of the issue and its impact
- Steps to reproduce (OS, Python version, `hackrf-tools` version)
- Any relevant logs or a minimal proof of concept

You can expect an initial acknowledgment within a reasonable window. Once a fix
is available, we will coordinate disclosure and credit the reporter unless
anonymity is requested.

## Scope

In-scope examples:

- Command injection or unsafe argument handling in how the library builds and
  runs `hackrf-tools` invocations
- Path handling issues in file read/write helpers (IQ files, SigMF sidecars,
  firmware dumps)
- Unsafe handling of subprocess input/output that could affect the host

Out of scope:

- Vulnerabilities in `hackrf-tools`, `libhackrf`, or HackRF firmware — report
  those upstream at https://github.com/greatscottgadgets/hackrf
- **RF safety and legality.** Transmitting is regulated. Operating outside your
  legal authorization, damaging equipment, or interfering with licensed
  services is a user responsibility, not a software vulnerability. The transmit
  gate and gain ceiling are guardrails, not guarantees.
