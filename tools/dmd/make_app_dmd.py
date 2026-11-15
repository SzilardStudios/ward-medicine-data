"""Build app dmd-data.json + gtin.json from a drug_index.sqlite (output of build_index.py).
usage: python3 -I make_app_dmd.py <drug_index.sqlite> <out_dir>"""
import sqlite3, json, sys, os
src, out = sys.argv[1:3]
c = sqlite3.connect(src)
rows = [r for r in c.execute('select id,name,forms,routes,bnf from vmp') if not r[1].startswith('Generic ')]
rows.sort(key=lambda r: r[1])
idx = {r[0]: i for i, r in enumerate(rows)}
P = [[r[1], r[2], r[3], int(r[4][:2]) if r[4][:2].isdigit() else 0] for r in rows]
brands = [(n, idx[v]) for n, v in c.execute('select name,vmp from brand') if v in idx]
brands.sort(key=lambda b: (b[0], b[1]))
G = {g: idx[v] for g, v in c.execute('select gtin,vmp from gtin') if v in idx}
os.makedirs(out, exist_ok=True)
json.dump({'p': P, 'b': [[n, i] for n, i in brands]}, open(f'{out}/dmd-data.json', 'w'), ensure_ascii=False, separators=(',', ':'))
json.dump(G, open(f'{out}/gtin.json', 'w'), separators=(',', ':'))
print('products', len(P), 'brand entries', len(brands), 'gtins', len(G))
