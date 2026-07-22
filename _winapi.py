# 用 Windows API 直接提取 mstsc.exe 的第一个图标组为 .ico
import ctypes, ctypes.wintypes
import struct, os

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

# 加载 mstsc.exe 作为数据文件
LOAD_LIBRARY_AS_DATAFILE = 2
LOAD_LIBRARY_AS_IMAGE_RESOURCE = 0x20
hmod = kernel32.LoadLibraryExW(r"C:\Windows\System32\mstsc.exe", None, LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_IMAGE_RESOURCE)
if not hmod:
    print("LoadLibraryEx failed")
    exit()

# FindResource + LoadResource + LockResource for RT_GROUP_ICON
# EnumResourceNames to find the first icon group
RT_GROUP_ICON = 14
first_name = []

@ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_long)
def enum_callback(hmod, rtype, name, lparam):
    if rtype == RT_GROUP_ICON:
        first_name.append(name)
        return False  # stop after first
    return True

kernel32.EnumResourceNamesW(hmod, RT_GROUP_ICON, enum_callback, 0)

if not first_name:
    print("No RT_GROUP_ICON found")
    exit()

name = first_name[0]
print(f"Found icon group: {name}")

# Load the resource
hrsrc = kernel32.FindResourceW(hmod, name, RT_GROUP_ICON)
if not hrsrc:
    print("FindResource failed")
    exit()

hglobal = kernel32.LoadResource(hmod, hrsrc)
size = kernel32.SizeofResource(hmod, hrsrc)
ptr = kernel32.LockResource(hglobal)

# Read the icon group data
data = ctypes.string_at(ptr, size)

# Parse the group - it has GRPICONDIRENTRY which is slightly different from ICO format
# We need to convert GRPICONDIR to ICO format
count = struct.unpack_from("<H", data, 4)[0]
print(f"Icon count: {count}")

# Build ICO header
ico_data = bytearray()
ico_data += struct.pack("<HHH", 0, 1, count)  # ICO header

# Image data offset starts after the directory
img_offset = 6 + count * 16
img_entries = []
img_raw_data = []

for i in range(count):
    off = 6 + i * 14  # GRPICONDIRENTRY is 14 bytes
    bWidth, bHeight, bColors, bReserved, wPlanes, wBitCount, dwBytesInRes, nID = struct.unpack_from("<BBBBHHIH", data, off)
    
    # ICO directory entry is 16 bytes
    wWidth = bWidth if bWidth != 0 else 256
    wHeight = bHeight if bHeight != 0 else 256
    
    entry = struct.pack("<BBBBHHII", wWidth if wWidth < 256 else 0, wHeight if wHeight < 256 else 0, bColors, bReserved, wPlanes, wBitCount, dwBytesInRes, img_offset)
    img_entries.append(entry)
    
    # Load the actual image resource
    img_hrsrc = kernel32.FindResourceW(hmod, ctypes.c_void_p(nID), ctypes.c_int(3))  # RT_ICON = 3
    if img_hrsrc:
        img_hglobal = kernel32.LoadResource(hmod, img_hrsrc)
        img_size = kernel32.SizeofResource(hmod, img_hrsrc)
        img_ptr = kernel32.LockResource(img_hglobal)
        img_data = ctypes.string_at(img_ptr, img_size)
        img_raw_data.append(img_data)
        img_offset += img_size
    else:
        print(f"Failed to load image {nID}")

ico_data += b"".join(img_entries)
for d in img_raw_data:
    ico_data += d

out_path = r"D:\L\Documents\BIT质押请求\mstsc.ico"
with open(out_path, "wb") as f:
    f.write(ico_data)

print(f"Saved: {len(ico_data)} bytes, {count} icons")

kernel32.FreeLibrary(hmod)
