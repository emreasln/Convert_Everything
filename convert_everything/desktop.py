"""Windows: put a converted file's icon exactly where the original sat on the desktop.

Explorer drops a new desktop file into the next free slot, often far away from the
original. We ask the desktop's own view (IFolderView) where the old icon was and move
the new icon there. Best effort: if anything fails, Explorer's placement is kept.
"""
import ctypes
import time
from ctypes import POINTER, byref, c_int, c_long, c_uint, c_ulong, c_void_p, c_wchar_p, wintypes
from pathlib import Path


class GUID(ctypes.Structure):
    _fields_ = [("d1", c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


class VARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("reserved", ctypes.c_ushort * 3), ("value", c_void_p * 2)]


def _guid(text):
    g = GUID()
    ctypes.oledll.ole32.CLSIDFromString(text, byref(g))
    return g


def _call(obj, index, argtypes, *args):
    """Call method number `index` of a COM object's vtable."""
    vtable = ctypes.cast(obj, POINTER(c_void_p))[0]
    fn = ctypes.cast(vtable, POINTER(c_void_p))[index]
    return ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(fn)(obj, *args)


def _query(obj, index, iid, *leading):
    """Call a method whose last arguments are (REFIID, void**) and return the new object."""
    out = c_void_p()
    _call(obj, index, [POINTER(GUID)] * (len(leading) + 1) + [POINTER(c_void_p)],
          *[byref(g) for g in leading], byref(_guid(iid)), byref(out))
    if not out.value:
        raise OSError("interface not available")
    return out


def _desktop_dirs():
    dirs = []
    for csidl in (0x10, 0x19):  # CSIDL_DESKTOPDIRECTORY, CSIDL_COMMON_DESKTOPDIRECTORY
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:
            dirs.append(Path(buf.value).resolve())
    return dirs


def _desktop_view():
    """Returns (IFolderView, IShellFolder) of the desktop."""
    ctypes.windll.ole32.CoInitialize(None)
    windows = c_void_p()
    ctypes.oledll.ole32.CoCreateInstance(byref(_guid("{9BA05972-F6A8-11CF-A442-00A0C90A8F39}")), None, 0x17,
                                         byref(_guid("{85CB6900-4D95-11CF-960C-0080C7F4EE85}")), byref(windows))
    loc, empty, hwnd, disp = VARIANT(vt=3), VARIANT(), c_long(), c_void_p()  # VT_I4 CSIDL_DESKTOP
    _call(windows, 15, [POINTER(VARIANT), POINTER(VARIANT), c_int, POINTER(c_long), c_int, POINTER(c_void_p)],
          byref(loc), byref(empty), 8, byref(hwnd), 1, byref(disp))  # FindWindowSW(SWC_DESKTOP, SWFO_NEEDDISPATCH)
    if not disp.value:
        raise OSError("desktop window not found")
    provider = _query(disp, 0, "{6D5140C1-7436-11CE-8034-00AA006009FA}")
    browser = _query(provider, 3, "{000214E2-0000-0000-C000-000000000046}",
                     _guid("{4C96BE40-915C-11CF-99D3-00AA004AE837}"))  # SID_STopLevelBrowser
    view = c_void_p()
    _call(browser, 15, [POINTER(c_void_p)], byref(view))  # QueryActiveShellView
    folder_view = _query(view, 0, "{CDE725B0-CCC9-4519-917E-325D72FAB4CE}")
    folder = _query(folder_view, 5, "{000214E6-0000-0000-C000-000000000046}")  # GetFolder
    return folder_view, folder


def _item(folder, name):
    pidl = c_void_p()
    _call(folder, 3, [c_void_p, c_void_p, c_wchar_p, POINTER(c_ulong), POINTER(c_void_p), POINTER(c_ulong)],
          None, None, name, None, byref(pidl), None)  # ParseDisplayName
    return pidl


def icon_position(path):
    """Where the file's icon sits on the desktop, or None if it isn't on the desktop."""
    path = Path(path)
    try:
        if path.parent.resolve() not in _desktop_dirs():
            return None
        folder_view, folder = _desktop_view()
        point = wintypes.POINT()
        _call(folder_view, 11, [c_void_p, POINTER(wintypes.POINT)], _item(folder, path.name), byref(point))
        return point.x, point.y
    except OSError:
        return None


def move_icon(path, position, removed=None):
    """Move a desktop file's icon to `position` (from icon_position). Pass the file
    that just left that spot as `removed`, so the desktop knows the spot is free."""
    if removed:
        ctypes.windll.shell32.SHChangeNotify(0x4, 0x1005, str(removed), None)  # SHCNE_DELETE, SHCNF_PATHW | SHCNF_FLUSH
    ctypes.windll.shell32.SHChangeNotify(0x2, 0x1005, str(path), None)  # SHCNE_CREATE
    try:
        folder_view, folder = _desktop_view()
    except OSError:
        return
    for _ in range(50):  # wait until the view shows the new file, or it would place it again afterwards
        try:
            item = _item(folder, Path(path).name)
            _call(folder_view, 11, [c_void_p, POINTER(wintypes.POINT)], item, byref(wintypes.POINT()))
            break
        except OSError:
            time.sleep(0.1)
    else:
        return
    for _ in range(10):  # until the old icon is really gone, the spot counts as taken
        _call(folder_view, 16, [c_uint, c_void_p, POINTER(wintypes.POINT), c_ulong],
              1, (c_void_p * 1)(item), byref(wintypes.POINT(*position)), 0x80)  # SelectAndPositionItems(SVSI_POSITIONITEM)
        time.sleep(0.2)
        point = wintypes.POINT()
        _call(folder_view, 11, [c_void_p, POINTER(wintypes.POINT)], item, byref(point))
        if (point.x, point.y) == tuple(position):
            return
