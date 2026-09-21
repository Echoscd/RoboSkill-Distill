"""JSON-lines driver runner; device adapters own actions and resource cleanup."""

import contextlib
import json
import os
import signal
import threading
import sys


@contextlib.contextmanager
def protocol_output():
    # In-memory streams also support testing adapters without opening hardware.
    original = sys.stdout
    try:
        descriptor = original.fileno()
    except (AttributeError, OSError):
        with contextlib.redirect_stdout(sys.stderr):
            yield original
        return
    original.flush()
    with os.fdopen(os.dup(descriptor), "w") as output:
        os.dup2(sys.stderr.fileno(), descriptor)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                yield output
        finally:
            os.dup2(output.fileno(), descriptor)


def release(*actions):
    """Attempt every cleanup stage and report all failures."""
    errors = []
    for action in actions:
        try:
            action()
        except Exception as error:
            errors.append(error)
    if errors:
        raise ExceptionGroup("cleanup failed: " + "; ".join(map(str, errors)), errors)


@contextlib.contextmanager
def termination():
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    def stop(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise SystemExit(128 + signum)
    previous = signal.signal(signal.SIGTERM, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def run(dispatch, cleanup, *, serving=None):
    """Isolate SDK output; cleanup must release owned resources idempotently.

    Persistent operations require load. One-shot adapters acquire temporary
    clients per operation; their cleanup must not cancel accepted commands.
    """
    persistent = "--serve" in sys.argv if serving is None else serving
    ready = False
    with protocol_output() as output, termination():
        def respond(action, args):
            nonlocal ready
            if action in {"load", "unload", "status"} and args:
                return {"ok": False, "error": f"{action} accepts no arguments"}
            if persistent and not ready and action not in {"load", "unload", "status"}:
                return {"ok": False, "error": "device is inactive; load it before operations"}
            result = dispatch(action, args)
            if action == "load":
                ready = result.get("ok") is True
                if not ready:
                    try:
                        cleanup()
                    except Exception as error:
                        result["error"] = f"{result.get('error', 'load failed')}; {error}"
            if action == "unload":
                ready = False
            return result
        try:
            if persistent:
                for line in sys.stdin:
                    request = json.loads(line)
                    result = respond(request["action"], request.get("args", {}))
                    output.write(json.dumps(result, allow_nan=False) + "\n")
                    output.flush()
                return
            action = sys.argv[1] if len(sys.argv) > 1 else "read"
            args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
            output.write(json.dumps(respond(action, args), allow_nan=False) + "\n")
            output.flush()
        finally:
            cleanup()
