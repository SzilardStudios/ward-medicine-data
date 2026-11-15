import sys, os, json, zipfile, gzip, sqlite3
import xml.etree.ElementTree as ET
raw, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
import glob, re
S=re.search(r'f_vmp2_(\d+)\.xml', ' '.join(os.listdir(raw))).group(1)
def rows(fn, tag):
    for ev, el in ET.iterparse(f'{raw}/{fn}'):
        if el.tag == tag:
            yield {c.tag:(c.text or '') for c in el}
            el.clear()
lk={}
root=ET.parse(f'{raw}/f_lookup2_{S}.xml').getroot()
for grp in root:
    if grp.tag in ('FORM','ROUTE'):
        lk[grp.tag]={i.find('CD').text:i.find('DESC').text for i in grp}
vtm={r['VTMID']:r['NM'] for r in rows(f'f_vtm2_{S}.xml','VTM') if not r.get('INVALID')}
vmp={}; vmp_inv=0
for r in rows(f'f_vmp2_{S}.xml','VMP'):
    if r.get('INVALID')=='1': vmp_inv+=1; continue
    vmp[r['VPID']]={'n':r['NM'],'t':r.get('VTMID','')}
form={}; route={}
for r in rows(f'f_vmp2_{S}.xml','DFORM'): form.setdefault(r['VPID'],[]).append(lk['FORM'].get(r['FORMCD'],r['FORMCD']))
for r in rows(f'f_vmp2_{S}.xml','DROUTE'): route.setdefault(r['VPID'],[]).append(lk['ROUTE'].get(r['ROUTECD'],r['ROUTECD']))
brands={}; amp_inv=0; amp_same=0
amp2vmp={}
for r in rows(f'f_amp2_{S}.xml','AMP'):
    if r.get('INVALID')=='1': amp_inv+=1; continue
    v=vmp.get(r['VPID'])
    if not v: continue
    amp2vmp[r['APID']]=r['VPID']
    if r['NM'].strip().lower()==v['n'].strip().lower(): amp_same+=1; continue
    brands.setdefault((r['NM'],r['VPID']),r['APID'])
ampp2amp={r['APPID']:r['APID'] for r in rows(f'f_ampp2_{S}.xml','AMPP')}
gt={}
z=zipfile.ZipFile(glob.glob(f'{raw}/week*-GTIN.zip')[0])
with z.open([n for n in z.namelist() if n.endswith('.xml')][0]) as f:
    for ev, el in ET.iterparse(f):
        if el.tag=='AMPP':
            pid=el.findtext('AMPPID'); ap=ampp2amp.get(pid); vp=amp2vmp.get(ap)
            if vp:
                for g in el.findall('GTINDATA'):
                    if g.find('ENDDT') is None: gt[g.findtext('GTIN').lstrip('0')]=vp
            el.clear()
print('VTM',len(vtm),'VMP valid',len(vmp),'VMP invalid',vmp_inv)
print('AMP invalid',amp_inv,'AMP same-name-as-VMP',amp_same,'branded AMP entries',len(brands))
print('active GTINs mapped to VMP',len(gt))
db=f'{out}/index.sqlite'
if os.path.exists(db): os.remove(db)
c=sqlite3.connect(db)
c.executescript('create table vtm(id text primary key,name text);create table vmp(id text primary key,name text,vtm text,forms text,routes text);create table brand(name text,vmp text);create table gtin(gtin text primary key,vmp text);')
c.executemany('insert into vtm values(?,?)',vtm.items())
c.executemany('insert into vmp values(?,?,?,?,?)',[(k,v['n'],v['t'],';'.join(sorted(set(form.get(k,[])))),';'.join(sorted(set(route.get(k,[]))))) for k,v in vmp.items()])
c.executemany('insert into brand values(?,?)',[(n,v) for (n,v) in brands])
c.executemany('insert into gtin values(?,?)',gt.items())
c.commit(); c.execute('vacuum'); c.close()
sz=os.path.getsize(db); print('sqlite bytes',sz)
with open(db,'rb') as f, gzip.open(db+'.gz','wb') as g: g.write(f.read())
print('gzip bytes',os.path.getsize(db+'.gz'))
# names-only text (no GTIN) for search-list sizing
names=sorted({v['n'] for v in vmp.values()}|{n for n,_ in brands}|set(vtm.values()))
open(out+'/names.txt','w').write('\n'.join(names)); print('unique names',len(names),'bytes',os.path.getsize(out+'/names.txt'))
