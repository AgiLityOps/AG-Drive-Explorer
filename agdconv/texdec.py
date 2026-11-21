"""Decoder for IonCore .tex textures (LZ4-compressed PVRTC 4/2 bpp or RGBA8) and PVR v3 files. Mip 0 only."""
import struct, lz4.block, texture2ddecoder, numpy as np
MAGIC = b'\x01\x11\xdd\xee'
def _dec(data, w, h):
    bpp = len(data) * 8 // (w * h)
    if bpp == 4: raw = texture2ddecoder.decode_pvrtc(data, w, h, False)
    elif bpp == 2: raw = texture2ddecoder.decode_pvrtc(data, w, h, True)
    elif bpp == 32: return np.frombuffer(data, np.uint8).reshape(h, w, 4).copy()
    else: raise ValueError('unsupported texture bpp %s' % bpp)
    return np.frombuffer(raw, np.uint8).reshape(h, w, 4)[:, :, [2, 1, 0, 3]].copy()   # BGRA -> RGBA
def read(d):
    """Returns dict(kind='2d'|'cube', w, h, faces=[HxWx4 uint8]). Rows are as stored in the file (bottom-up, OpenGL)."""
    if d[:4] == b'PVR\x03':
        ver, fl, pf_lo, pf_hi, cs, ct, h, w, dep, ns, nf, nm, ml = struct.unpack_from('<13I', d, 0)
        if pf_hi != 0 or pf_lo not in (0, 1, 2, 3): raise ValueError('unsupported PVR pixel format')
        bpp = 2 if pf_lo in (0, 1) else 4
        fsz = w * h * bpp // 8; p = 52 + ml
        faces = [_dec(d[p + f * fsz:p + (f + 1) * fsz], w, h) for f in range(nf)]
        return dict(kind='cube' if nf == 6 else '2d', w=w, h=h, faces=faces)
    if d[:4] != MAGIC: raise ValueError('not an IonCore texture')
    flags, typ, mips, w, h = struct.unpack_from('<IHHHH', d, 4)
    off = 0x20; chunks = []; nfaces = 6 if typ == 5 else 1
    while len(chunks) < nfaces and off + 4 <= len(d):
        cs = struct.unpack_from('<I', d, off)[0]; blob = d[off + 4:off + 4 + cs]
        try: u = lz4.block.decompress(blob, uncompressed_size=64 << 20)
        except Exception: u = blob
        chunks.append(u); off += 4 + cs
    return dict(kind='cube' if typ == 5 else '2d', w=w, h=h, faces=[_dec(c, w, h) for c in chunks])
