"""Jobs that only tests give a worker pool (``WorkerPool(jobs=...)``): slow, crashing,
greedy and badly behaved ones. Nothing a request or a configuration says can reach
them; a pool built by the service never names this module."""

import os
import subprocess
import sys
import time

from solidseas import jobs as real


def echo(params):
    return {"echo": params, "pid": os.getpid()}


def pid(params):
    return {"pid": os.getpid()}


def sleep(params):
    time.sleep(params.get("seconds", 120))
    return {"slept": True}


def crash(params):
    os._exit(3)


def allocate(params):
    data = bytearray(params["mb"] << 20)
    return {"bytes": len(data)}


def big(params):
    return {"text": "x" * params["n"]}


def nan(params):
    return {"value": float("nan")}


def image(params):
    return {"bytes": params["n"]}, b"\x89PNG\r\n\x1a\n" + bytes(params["n"])


def spawn(params):
    """Start another process: refused inside the Job Object (ACTIVE_PROCESS)."""
    try:
        subprocess.run([sys.executable, "-c", "pass"], check=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {"spawned": False}
    return {"spawned": True}


def _by_name(params, fallback):
    """Misbehave for documents whose name asks for it, else do the real job."""
    name = os.path.basename(str(params.get("path", "")))
    if "slow" in name:
        time.sleep(120)
    if "crash" in name:
        os._exit(3)
    if "bomb" in name:
        allocate({"mb": 2048})
    return fallback(params)


def document_summary(params):
    return _by_name(params, real.document_summary)


def listing_entry(params):
    return _by_name(params, real.listing_entry)


def batch_document(params):
    return _by_name(params, real.batch_document)


def not_a_row(params):
    """A batch job whose answer is JSON but not a batch row."""
    return {"row": ["not", "a", "row"], "detail": {}}


def _cell(value):
    """A batch job that reads the document as usual but answers with ``value`` in one cell."""

    def job(params):
        answer = real.batch_document(params)
        answer["row"]["release"] = value
        return answer

    return job


list_cell = _cell(["SOLIDWORKS 2024"])
dict_cell = _cell({"release": "SOLIDWORKS 2024"})
bool_cell = _cell(True)


def batch_document_above(params):
    """A batch job that asks to read its document below the folder above the listed one."""
    return real.batch_document({**params, "folder": os.path.dirname(os.path.abspath(params["folder"]))})


def listing_entry_above(params):
    """A listing job that asks to read its entry below the folder above the listed one."""
    return real.listing_entry({**params, "within": os.path.dirname(os.path.abspath(params["within"]))})


def modules(params):
    """The modules this worker has imported, for the check that nothing loads SOLIDWORKS."""
    return {"modules": sorted(sys.modules)}


def error_mode(params):
    """The worker's Windows error mode (GetErrorMode), or None elsewhere."""
    if sys.platform != "win32":
        return {"error_mode": None}
    import ctypes

    return {"error_mode": ctypes.windll.kernel32.GetErrorMode()}


def html_preview(params):
    """A preview job whose image is not an image: the service must refuse to serve it."""
    return {"mime": "image/png", "width": 1, "height": 1, "stream": "PreviewPNG"}, b"<html><script>x</script>"


def catalog_document(params):
    """The catalog's read job, misbehaving for documents whose name asks for it (slow,
    crash, bomb) and answering a record that is not one for the names below."""
    name = os.path.basename(str(params.get("path", "")))
    if "badtype" in name:
        record, image = real.catalog_document(params)
        record["configurations"] = "not a list"
        return record, image
    if "oversize" in name:
        record, image = real.catalog_document(params)
        record["properties"] = [
            {"name": "x" * 5000, "type": "text", "text": "", "value": "", "expression": None, "linked": False}
        ]
        return record, image
    if "toomany" in name:
        record, image = real.catalog_document(params)
        record["views"] = [["s", "v", None, None]] * 10_001
        return record, image
    if "badimage" in name:
        record, _image = real.catalog_document(params)
        return record, b"<html><script>x</script>"
    return _by_name(params, real.catalog_document)


def priority(params):
    """This worker's scheduling priority: its Windows priority class, or its nice value."""
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.GetPriorityClass.argtypes = (ctypes.c_void_p,)
        k32.GetPriorityClass.restype = ctypes.c_uint32
        return {"class": k32.GetPriorityClass(k32.GetCurrentProcess()), "nice": None}
    return {"class": None, "nice": os.nice(0)}
