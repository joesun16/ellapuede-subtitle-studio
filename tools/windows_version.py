"""Version metadata displayed in Windows executable properties."""
import _bootstrap  # noqa: F401  puts src/ on sys.path
from version import VERSION

def resource():
    numeric=tuple(int(v) for v in VERSION.split('.'))+(0,)
    return f'''VSVersionInfo(ffi=FixedFileInfo(filevers={numeric!r},prodvers={numeric!r},mask=0x3f,flags=0x0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('CompanyName','EllaPuede'),StringStruct('FileDescription','EllaPuede Subtitle Extractor'),StringStruct('FileVersion','{VERSION}'),StringStruct('InternalName','EllaPuede'),StringStruct('ProductName','EllaPuede Subtitle Extractor'),StringStruct('ProductVersion','{VERSION}')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])'''
