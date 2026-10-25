"""Minimal ctypes wrapper around the ngspice shared library.

It loads ngspice (the copy that ships with KiCad works), sources a netlist,
runs it in the foreground and returns every vector of every plot as numpy
arrays. No GUI and no external Python packages beyond numpy.

Set NGSPICE_LIBRARY_PATH to the full path of ngspice.dll / libngspice.so if
the library is not found automatically.
"""
import ctypes
import ctypes.util
import glob
import os
import sys
from ctypes import (CFUNCTYPE, POINTER, Structure, c_bool, c_char_p, c_double,
                    c_int, c_short, c_void_p)

import numpy as np


class _NgComplex(Structure):
    _fields_ = [("cx_real", c_double), ("cx_imag", c_double)]


class _VectorInfo(Structure):
    _fields_ = [("v_name", c_char_p),
                ("v_type", c_int),
                ("v_flags", c_short),
                ("v_realdata", POINTER(c_double)),
                ("v_compdata", POINTER(_NgComplex)),
                ("v_length", c_int)]


_SendChar = CFUNCTYPE(c_int, c_char_p, c_int, c_void_p)
_SendStat = CFUNCTYPE(c_int, c_char_p, c_int, c_void_p)
_ControlledExit = CFUNCTYPE(c_int, c_int, c_bool, c_bool, c_int, c_void_p)
_SendData = CFUNCTYPE(c_int, c_void_p, c_int, c_int, c_void_p)
_SendInitData = CFUNCTYPE(c_int, c_void_p, c_int, c_void_p)
_BGThreadRunning = CFUNCTYPE(c_int, c_bool, c_int, c_void_p)


def _candidates():
    env = os.environ.get("NGSPICE_LIBRARY_PATH")
    if env:
        yield env
    if sys.platform.startswith("win"):
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramW6432", r"C:\Program Files"),
                 os.environ.get("LOCALAPPDATA", "")]
        for root in roots:
            if not root:
                continue
            for path in sorted(glob.glob(os.path.join(root, "KiCad", "*", "bin", "ngspice.dll")),
                               reverse=True):
                yield path
        yield "ngspice.dll"
    elif sys.platform == "darwin":
        yield "/Applications/KiCad/KiCad.app/Contents/Frameworks/libngspice.dylib"
        yield "libngspice.dylib"
    else:
        yield "libngspice.so.0"
        yield "libngspice.so"
    found = ctypes.util.find_library("ngspice")
    if found:
        yield found


def _load_library():
    errors = []
    for path in _candidates():
        try:
            if os.path.isabs(path) and os.path.exists(path) and sys.platform.startswith("win"):
                os.add_dll_directory(os.path.dirname(path))
            return ctypes.CDLL(path), path
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    raise RuntimeError("Could not load the ngspice shared library. Set NGSPICE_LIBRARY_PATH.\n"
                       + "\n".join(errors))


class NgSpice:
    """Single ngspice instance. ngspice keeps global state, so use one object."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.lib, self.path = _load_library()
        self.log = []
        self._cb_char = _SendChar(self._on_char)
        self._cb_stat = _SendStat(lambda s, i, p: 0)
        self._cb_exit = _ControlledExit(self._on_exit)
        self.lib.ngSpice_Init.argtypes = [_SendChar, _SendStat, _ControlledExit,
                                          c_void_p, c_void_p, c_void_p, c_void_p]
        self.lib.ngSpice_Init(self._cb_char, self._cb_stat, self._cb_exit,
                              None, None, None, None)
        self.lib.ngSpice_Command.argtypes = [c_char_p]
        self.lib.ngSpice_Command.restype = c_int
        self.lib.ngGet_Vec_Info.argtypes = [c_char_p]
        self.lib.ngGet_Vec_Info.restype = POINTER(_VectorInfo)
        self.lib.ngSpice_CurPlot.restype = c_char_p
        self.lib.ngSpice_AllPlots.restype = POINTER(c_char_p)
        self.lib.ngSpice_AllVecs.argtypes = [c_char_p]
        self.lib.ngSpice_AllVecs.restype = POINTER(c_char_p)

    def _on_char(self, text, ident, user):
        self.log.append(text.decode(errors="replace"))
        return 0

    def _on_exit(self, status, unload, quit_, ident, user):
        self.log.append(f"ngspice exit request {status}")
        return 0

    def cmd(self, command):
        self.lib.ngSpice_Command(command.encode())

    def errors(self):
        bad = ("error", "singular", "timestep too small", "aborted", "no such")
        return [l for l in self.log if any(b in l.lower() for b in bad)
                and "warning" not in l.lower()]

    def _read_vectors(self, plot):
        out = {}
        names = self.lib.ngSpice_AllVecs(plot.encode())
        i = 0
        while names[i]:
            name = names[i].decode()
            i += 1
            info = self.lib.ngGet_Vec_Info(f"{plot}.{name}".encode())
            if not info:
                continue
            vi = info.contents
            n = vi.v_length
            if vi.v_realdata:
                arr = np.ctypeslib.as_array(vi.v_realdata, shape=(n,)).copy()
            elif vi.v_compdata:
                raw = np.ctypeslib.as_array(
                    ctypes.cast(vi.v_compdata, POINTER(c_double)), shape=(2 * n,)).copy()
                arr = raw[0::2] + 1j * raw[1::2]
            else:
                continue
            out[name.lower()] = arr
        return out

    def run_file(self, netlist_path):
        """Source a netlist that holds its analysis lines, run it, return
        {plot_name: {vector: ndarray}} for the plots this run created."""
        self.log.clear()
        self.cmd("destroy all")
        self.cmd("remcirc")
        path = os.path.abspath(netlist_path).replace("\\", "/")
        self.cmd(f"source {path}")
        before = self._plots()
        self.cmd("run")
        after = self._plots()
        new = [p for p in after if p not in before and p != "const"]
        if not new:
            raise RuntimeError(f"ngspice produced no data for {netlist_path}:\n"
                               + "".join(self.log[-40:]))
        text = "".join(self.log).lower()
        # a failed operating point makes AC and DC results meaningless, and a
        # transient that falls back to a pseudo transient may start wrong
        if ("source stepping failed" in text or "aborted" in text
                or "timestep too small" in text or "cannot recover" in text):
            raise RuntimeError(f"ngspice did not converge for {netlist_path}:\n"
                               + "".join(self.log[-20:]))
        result = {p: self._read_vectors(p) for p in new}
        return result

    def _plots(self):
        plots = self.lib.ngSpice_AllPlots()
        out = []
        i = 0
        while plots[i]:
            out.append(plots[i].decode())
            i += 1
        return out


def run(netlist_path):
    """Run one netlist and return the vectors of the newest plot, plus all plots."""
    ng = NgSpice()
    plots = ng.run_file(netlist_path)
    # the newest plot is the first one ngspice lists after a run
    newest = list(plots.keys())[0]
    return plots[newest], plots
