from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from krita import Krita


DENIED_SCRIPT_TOKENS = (
    "subprocess",
    "os.system",
    "shutil.rmtree",
    "Path.home",
    "socket.",
    "requests.",
    "urllib.request",
    "open(",
    "__import__",
    "eval(",
    "exec(",
)


def validate_script_code(code):
    if not code.strip():
        raise RuntimeError("Script code is empty.")
    lowered = code.lower()
    for token in DENIED_SCRIPT_TOKENS:
        if token.lower() in lowered:
            raise RuntimeError("Script contains denied token: %s" % token)


def run_krita_script(code):
    validate_script_code(code)
    stdout = StringIO()
    stderr = StringIO()
    namespace = {
        "Krita": Krita,
        "app": Krita.instance(),
    }

    with redirect_stdout(stdout), redirect_stderr(stderr):
        exec(code, namespace, namespace)

    active = Krita.instance().activeDocument()
    if active is not None:
        active.refreshProjection()

    return {
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
    }
