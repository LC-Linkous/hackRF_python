#! /usr/bin/python3

##--------------------------------------------------------------------\
#   hackrfpy  'src/hackrfpy/_stream_ctx.py'
#   Shared context manager that guarantees a live capture/sweep generator
#   is closed (and its child process reaped) on block exit, including on
#   exception or KeyboardInterrupt. Used by capture_stream and sweep_stream.
##--------------------------------------------------------------------\


class StreamCtx:
    # Wrap a live generator so its finally-block (which interrupts + reaps the
    # hackrf_* child) runs on __exit__, even if the body raised. Iterable, so
    # `for x in rows:` works directly on the bound name.
    def __init__(self, gen):
        self._gen = gen

    def __enter__(self):
        return self._gen

    def __exit__(self, exc_type, exc, tb):
        if self._gen is not None:
            self._gen.close()
        return False  # never suppress the caller's exception
