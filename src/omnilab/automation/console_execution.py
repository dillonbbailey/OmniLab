"""Qt-free console execution shared by the host-Python and native-USD workers."""
import ast
import builtins
from contextlib import redirect_stdout, redirect_stderr
import io
import linecache
import os
import pydoc
import sys
import time
import traceback

OUTPUT_LIMIT = 256 * 1024


def normalize_newlines(text):
    """Use Python line endings for Qt/clipboard line and paragraph separators."""
    return text.replace('\r\n', '\n').replace('\r', '\n').replace('\u2028', '\n').replace('\u2029', '\n')


class ConsoleCancelled(KeyboardInterrupt):
    pass


class Cancellation:
    """A private marker file works even while the worker's Qt thread is occupied."""
    def __init__(self, path):
        self.path = path
        self.next_check = 0.0
        self.cancelled = False

    def check(self):
        now = time.monotonic()
        if not self.cancelled and now >= self.next_check:
            self.next_check = now + .03
            self.cancelled = bool(self.path and os.path.exists(self.path))
        if self.cancelled:
            # Do not interrupt rollback/finally handlers a second time.
            sys.settrace(None)
            raise ConsoleCancelled("Stopped by user")

    def trace(self, frame, event, arg):
        # Trace entered scripts and their functions, not protocol writes or
        # context-manager cleanup. Library/native calls finish before Stop.
        if frame.f_code.co_filename.startswith("<lunatic-console-") or frame.f_code.co_filename == "<string>":
            self.check()
            return self.trace
        return None


class Output:
    def __init__(self, emit):
        self.emit = emit
        self.stream = "stdout"
        self.pending = ""
        self.count = 0
        self.truncated = False
        self.events = 0
        self.last_flush = time.monotonic()

    def write(self, stream, text):
        if not isinstance(text, str):
            raise TypeError("write() requires text")
        size = len(text)
        if self.truncated:
            return size
        if self.stream != stream:
            self.flush()
            self.stream = stream
        available = max(0, OUTPUT_LIMIT - self.count)
        encoded = text[:available].encode("utf-8", "replace")[:available]
        accepted = encoded.decode("utf-8", "ignore")
        self.pending += accepted
        self.count += len(accepted.encode("utf-8"))
        if len(self.pending) >= 4096 or time.monotonic() - self.last_flush >= .05:
            self.flush()
        if len(accepted) < size:
            self.flush()
            self.truncated = True
            self.emit("output", stream="stderr", text="\n[Output limit reached; further output suppressed.]\n")
        return size

    def flush(self):
        if self.pending and not self.truncated:
            self.events += 1
            self.emit("output", stream=self.stream, text=self.pending)
            self.pending = ""
            if self.events >= 512:
                self.truncated = True
                self.emit("output", stream="stderr", text="\n[Output event limit reached; further output suppressed.]\n")
        self.last_flush = time.monotonic()


class Writer(io.TextIOBase):
    def __init__(self, output, stream):
        self.output, self.stream = output, stream

    @property
    def encoding(self):
        return "utf-8"

    def writable(self):
        return True

    def write(self, text):
        return self.output.write(self.stream, text)

    def flush(self):
        self.output.flush()


def no_input(*args, **kwargs):
    raise RuntimeError("Interactive input is unavailable. Set values in the input editor and execute again.")


def console_help(value=None):
    if value is None:
        print("Use help(stage), help(usd), or help(material). See PYTHON_CONSOLE.md for examples.")
    else:
        print(pydoc.render_doc(value, renderer=pydoc.plaintext))


class Executor:
    def __init__(self):
        self.namespace = {}
        self.sources = []

    def reset(self):
        self.namespace.clear()
        for name in self.sources:
            linecache.cache.pop(name, None)
        self.sources.clear()

    def run(self, code, command_id, cancel_path, emit, globals_=None):
        code = normalize_newlines(code)
        output = Output(emit)
        cancel = Cancellation(cancel_path)
        namespace = self.namespace
        namespace.update(__name__="__console__", __builtins__=dict(vars(builtins), input=no_input),
                         help=console_help)
        namespace.update(globals_ or {})
        filename = "<lunatic-console-" + command_id + ">"
        linecache.cache[filename] = (len(code), None, code.splitlines(True), filename)
        self.sources.append(filename)
        if len(self.sources) > 100:
            linecache.cache.pop(self.sources.pop(0), None)
        status = "ok"
        previous_trace = sys.gettrace()
        previous_stdin = sys.stdin
        emit("started")
        sys.stdin = io.StringIO("")
        try:
            with redirect_stdout(Writer(output, "stdout")), redirect_stderr(Writer(output, "stderr")):
                sys.settrace(cancel.trace)
                cancel.check()
                tree = ast.parse(code, filename=filename, mode="exec")
                expression = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
                # Compile together first: do not run a prefix if the final expression is invalid.
                body = compile(tree, filename, "exec")
                tail = compile(ast.Expression(expression.value), filename, "eval") if expression else None
                exec(body, namespace)
                if tail:
                    value = eval(tail, namespace)
                    if value is not None:
                        namespace["_"] = value
                        output.flush()
                        emit("result", text=repr(value)[:16384])
        except ConsoleCancelled:
            status = "cancelled"
            output.flush()
            emit("error", text="Stopped by user.\n")
        except BaseException:
            status = "error"
            output.flush()
            emit("error", text=traceback.format_exc()[-16384:])
        finally:
            sys.settrace(previous_trace)
            sys.stdin = previous_stdin
            output.flush()
        return status
