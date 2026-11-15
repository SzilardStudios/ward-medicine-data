"""Make the update package for hosting: pack file + manifest.json.
usage: python3 -I make_pack.py <dir with dmd-data.json + gtin.json> <out site dir> <version e.g. 2026-W45> <released YYYY-MM-DD> <source text>"""
import json, sys, os, zlib
src, out, ver, rel, source = sys.argv[1:6]
d = json.load(open(f'{src}/dmd-data.json')); g = json.load(open(f'{src}/gtin.json'))
os.makedirs(out, exist_ok=True)
name = f'dmd-pack-{ver}.json'
raw = json.dumps({'p': d['p'], 'b': d['b'], 'gtin': g}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
open(f'{out}/{name}', 'wb').write(raw)
m = {'format': 1, 'version': ver, 'released': rel, 'source': source, 'file': name, 'bytes': len(raw),
     'crc32': format(zlib.crc32(raw) & 0xffffffff, '08x'), 'products': len(d['p']), 'brands': len(d['b']), 'gtins': len(g)}
json.dump(m, open(f'{out}/manifest.json', 'w'), indent=2)
print(m)
