import sys, os, sqlite3, gzip
import xml.etree.ElementTree as ET
src, bnfxml, out = sys.argv[1:4]
bnf={}
for ev,el in ET.iterparse(bnfxml):
    if el.tag=='VMP': bnf[el.findtext('VPID')]=(el.findtext('BNF') or '',el.findtext('ATC') or ''); el.clear()
def keep(v):
    b,a=bnf.get(v,('',''))
    if b: return b[:2] in {f'{i:02d}' for i in range(1,16)}
    return bool(a)   # no BNF code but has an ATC drug code
s=sqlite3.connect(src)
if os.path.exists(out): os.remove(out)
o=sqlite3.connect(out)
o.executescript('create table vmp(id text primary key,name text,vtm text,forms text,routes text,bnf text,atc text);create table brand(name text,vmp text);create table gtin(gtin text primary key,vmp text);create table vtm(id text primary key,name text);')
vm=[r for r in s.execute('select id,name,vtm,forms,routes from vmp') if keep(r[0])]
ids={r[0] for r in vm}
o.executemany('insert into vmp values(?,?,?,?,?,?,?)',[r+bnf.get(r[0],('',''))for r in vm])
o.executemany('insert into brand values(?,?)',[r for r in s.execute('select name,vmp from brand') if r[1] in ids])
o.executemany('insert into gtin values(?,?)',[r for r in s.execute('select gtin,vmp from gtin') if r[1] in ids])
o.executemany('insert into vtm values(?,?)',s.execute('select id,name from vtm').fetchall())
o.execute('create index ix_b on brand(name)');o.execute('create index ix_v on vmp(name)')
o.commit()
for t in ('vmp','brand','gtin','vtm'): print(t,o.execute(f'select count(*) from {t}').fetchone()[0])
o.execute('vacuum');o.close()
print('bytes',os.path.getsize(out))
with open(out,'rb') as f,gzip.open(out+'.gz','wb') as g:g.write(f.read())
print('gz',os.path.getsize(out+'.gz'))
