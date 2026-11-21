"""IonCore container formats: STG1 static geometry, .aga animation, IPK2 script archive."""
import struct, numpy as np, lz4.block

def parse_stg(d):
    if d[:4] != b'STG1': raise ValueError('not an STG1 file')
    n = struct.unpack_from('<I', d, 4)[0]; off = 8; meshes = []
    for mi in range(n):
        nparts, nv, ni, stride, x = struct.unpack_from('<5I', d, off)
        mat = d[off + 20:off + 148].split(b'\0')[0].decode('latin1')
        p = off + 148; parts = []
        for _ in range(nparts):
            nch, vbb, nidx = struct.unpack_from('<3I', d, p)
            vb = p + 12 + nch * 32; ib = vb + vbb; end = ib + nidx * 2
            V = np.frombuffer(d, dtype=np.uint8, count=vbb, offset=vb).reshape(-1, stride)
            I = np.frombuffer(d, dtype='<u2', count=nidx, offset=ib)
            parts.append(dict(V=V, I=I)); p = end
        meshes.append(dict(mat=mat, stride=stride, parts=parts)); off = p
    return meshes

def parse_aga(d):
    """u32 magic, u32 version, u16 nrec; records: u32 namelen, name\\0, u8 flag, u16 nframes, frames of 4x4 f32
    (row-vector matrices; the PathFinder record has 5 extra bytes per frame)."""
    n = struct.unpack_from('<H', d, 8)[0]; p = 10; recs = []
    for i in range(n):
        L = struct.unpack_from('<I', d, p)[0]; name = d[p + 4:p + 4 + L].rstrip(b'\0').decode('latin1'); p += 4 + L
        cnt = struct.unpack_from('<H', d, p + 1)[0]; p += 3
        stride = 64
        if i == n - 1: stride = (len(d) - p) // max(cnt, 1)
        else:
            for s in (64, 69, 68):
                q = p + cnt * s
                if q + 4 <= len(d):
                    L2 = struct.unpack_from('<I', d, q)[0]
                    if 0 < L2 < 200 and q + 4 + L2 <= len(d) and d[q + 4 + L2 - 1] == 0 and d[q + 4:q + 5].isalpha():
                        stride = s; break
        M = np.array([np.frombuffer(d, '<f4', 16, p + k * stride) for k in range(cnt)]).reshape(cnt, 4, 4)
        recs.append(dict(index=i, name=name, frames=M)); p += cnt * stride
    return recs

def parse_ipk(d):
    """IPK2: u32 count; entries: name\\0, u32 entry_len, u32 lz4_len, u8, u32 raw_len, u32 0, LZ4 block."""
    if d[:4] != b'IPK2': raise ValueError('not an IPK2 archive')
    n = struct.unpack_from('<I', d, 4)[0]; p = 8; out = {}
    for _ in range(n):
        e = d.index(b'\0', p); name = d[p:e].decode('latin1'); p = e + 1
        a, b = struct.unpack_from('<2I', d, p); usize = struct.unpack_from('<I', d, p + 9)[0]
        out[name] = lz4.block.decompress(d[p + 17:p + 17 + b], uncompressed_size=usize); p = p + 4 + a
    return out
