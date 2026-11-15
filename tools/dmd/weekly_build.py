"""Weekly medicine data build for Ward Drug Lookup.

Fetches the newest NHS dm+d release from NHS TRUD, builds the data pack the app downloads,
checks it the same way the app does, and writes pack + manifest.json.

usage:
  python weekly_build.py --data-dir ward-medicine-data            (live: needs env TRUD_API_KEY)
  python weekly_build.py --data-dir out --dry-run                 (build into a folder, never overwrites the live manifest)
  python weekly_build.py --data-dir out --from-dir <folder>       (test: use archives already on disk, no network)

Exit code 0 = nothing wrong (published, or already up to date). Anything else = a problem, nothing published.
The TRUD key is read only from the environment and is never printed.
"""
import argparse, glob, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, tempfile, urllib.request, urllib.error, zipfile, zlib
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS = [s for s in os.environ.get('TRUD_ITEMS', '24,25').split(',') if s.strip()]  # dm+d, dm+d bonus
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
KEY = os.environ.get('TRUD_API_KEY', '').strip()


def say(*a):
    print(*a, flush=True)


def clean(text):
    """Never let the key reach a log."""
    text = str(text)
    return text.replace(KEY, '***') if KEY else text


def die(msg):
    say('PROBLEM:', clean(msg))
    sys.exit(1)


def http_get(url, timeout=120):
    req = urllib.request.Request(url, headers={'User-Agent': 'ward-drug-lookup-data-build'})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        die(f'TRUD answered with an error (HTTP {e.code}) for a request. Check the API key and that the account is subscribed to the item.')
    except Exception as e:
        die(f'Could not reach TRUD: {type(e).__name__}')


def latest_release(item):
    url = f'https://isd.digital.nhs.uk/trud/api/v1/keys/{KEY}/items/{item}/releases?latest'
    data = json.load(http_get(url))
    rels = data.get('releases') or []
    if not rels:
        die(f'TRUD item {item} returned no release.')
    return rels[0]


def download(rel, dest):
    with http_get(rel['archiveFileUrl'], timeout=600) as r, open(dest, 'wb') as f:
        shutil.copyfileobj(r, f, 1 << 20)
    size = os.path.getsize(dest)
    want = rel.get('archiveFileSizeBytes')
    if want and size != int(want):
        die(f'{rel.get("archiveFileName")}: download is {size} bytes, TRUD says {want}.')
    expect = rel.get('archiveFileSha256') or ''
    if not expect and rel.get('checksumFileUrl'):
        try:
            m = re.search(r'\b[0-9a-fA-F]{64}\b', http_get(rel['checksumFileUrl']).read().decode('utf-8', 'ignore'))
            expect = m.group(0) if m else ''
        except SystemExit:
            raise
    if expect:
        h = hashlib.sha256()
        with open(dest, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        if h.hexdigest().lower() != expect.lower():
            die(f'{rel.get("archiveFileName")}: checksum does not match TRUD.')
        say('  checksum ok')
    else:
        say('  (no checksum offered by TRUD, size check only)')


def unpack_all(archives, work):
    """Extract each archive, then any inner GTIN / BNF zips, into one folder."""
    for a in archives:
        with zipfile.ZipFile(a) as z:
            z.extractall(work)
    for inner in glob.glob(os.path.join(work, '**', '*.zip'), recursive=True):
        n = os.path.basename(inner).upper()
        if 'GTIN' in n:
            continue  # build_index2.py reads this one as a zip
        if 'BNF' in n:
            with zipfile.ZipFile(inner) as z:
                z.extractall(os.path.join(os.path.dirname(inner), 'bnf_unzipped'))


def find_one(work, pattern, what):
    hits = glob.glob(os.path.join(work, '**', pattern), recursive=True)
    if not hits:
        listing = sorted(os.path.relpath(p, work) for p in glob.glob(os.path.join(work, '**', '*'), recursive=True))[:60]
        die(f'Could not find {what} ({pattern}) in the downloads. Contents: {listing}')
    return hits[0]


def release_info(arch_names):
    """Release number and date from names like nhsbsa_dmd_11.1.0_20261109000001.zip"""
    for n in arch_names:
        m = re.search(r'dmd_(\d+\.\d+\.\d+)_(\d{4})(\d{2})(\d{2})', n)
        if m and 'bonus' not in n.lower():
            return m.group(1), f'{m.group(2)}-{m.group(3)}-{m.group(4)}'
    return None, None


def run(*args):
    r = subprocess.run([sys.executable, '-I', *args], capture_output=True, text=True)
    if r.returncode != 0:
        die(f'{os.path.basename(args[0])} failed: {r.stderr[-600:]}')
    return r.stdout


def check_pack(raw_bytes, m, prev):
    """Same checks as the app (src/update.ts)."""
    if len(raw_bytes) != m['bytes'] or format(zlib.crc32(raw_bytes) & 0xffffffff, '08x') != m['crc32']:
        die('Pack does not match its own manifest.')
    d = json.loads(raw_bytes)
    if not isinstance(d.get('p'), list) or not isinstance(d.get('b'), list) or not isinstance(d.get('gtin'), dict):
        die('The pack has the wrong layout.')
    floor = max(5000, int(prev['products'] * 0.9) if prev else 0)
    if len(d['p']) < floor:
        die(f'The pack has too few products ({len(d["p"])}, needs at least {floor}).')
    for x in d['p']:
        if not (isinstance(x, list) and len(x) == 4 and isinstance(x[0], str) and isinstance(x[1], str) and isinstance(x[2], str) and isinstance(x[3], int)):
            die('A product entry is damaged.')
    n = len(d['p'])
    for x in d['b']:
        if not (isinstance(x, list) and isinstance(x[0], str) and isinstance(x[1], int) and 0 <= x[1] < n):
            die('A brand entry is damaged.')
    for k, v in d['gtin'].items():
        if not (isinstance(v, int) and 0 <= v < n):
            die('A barcode entry is damaged.')
    return len(d['p']), len(d['b']), len(d['gtin'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', required=True)
    ap.add_argument('--dry-run', action='store_true', help='build and check, write only into --data-dir')
    ap.add_argument('--from-dir', help='folder of ready archives (*.zip) instead of downloading')
    ap.add_argument('--keep', type=int, default=4, help='how many old pack files to keep')
    a = ap.parse_args()

    data_dir = os.path.abspath(a.data_dir)
    os.makedirs(data_dir, exist_ok=True)
    prev = None
    mp = os.path.join(data_dir, 'manifest.json')
    if os.path.exists(mp):
        prev = json.load(open(mp))

    with tempfile.TemporaryDirectory() as tmp:
        arch = []
        if a.from_dir:
            arch = sorted(glob.glob(os.path.join(a.from_dir, '*.zip')))
            if not arch:
                die('No zip files in --from-dir.')
            say('Using archives from', a.from_dir)
        else:
            if not KEY:
                die('TRUD_API_KEY is not set.')
            rels = []
            for item in ITEMS:
                rel = latest_release(item.strip())
                say(f'TRUD item {item}: {rel.get("archiveFileName")} (release date {rel.get("releaseDate")})')
                rels.append(rel)
            # nothing new on TRUD: stop before downloading anything
            if prev and not a.dry_run and str(rels[0].get('releaseDate', '')) and str(rels[0]['releaseDate']) <= prev['released']:
                say(f'Already up to date ({prev["version"]}, released {prev["released"]}). Nothing to do.')
                return
            for rel in rels:
                dest = os.path.join(tmp, rel['archiveFileName'])
                download(rel, dest)
                arch.append(dest)

        ver_no, released = release_info([os.path.basename(p) for p in arch])
        if not released:
            die('Could not read the release number and date from the archive names: ' + ', '.join(os.path.basename(p) for p in arch))
        iso = date.fromisoformat(released).isocalendar()
        version = f'{iso[0]}-W{iso[1]:02d}'
        d = date.fromisoformat(released)
        source = f'NHS dm+d release {ver_no}, {d.day} {MONTHS[d.month - 1]} {d.year}'
        say('Release', ver_no, released, '->', version)

        if prev and not a.dry_run and (prev['released'] > released or (prev['released'] == released and prev['version'] >= version)):
            say(f'Already up to date ({prev["version"]}). Nothing to do.')
            return

        work = os.path.join(tmp, 'work')
        os.makedirs(work)
        unpack_all(arch, work)
        raw = os.path.dirname(find_one(work, 'f_vmp2_*.xml', 'the dm+d VMP file'))
        if not glob.glob(os.path.join(raw, 'week*-GTIN.zip')):
            gz = find_one(work, 'week*-GTIN.zip', 'the GTIN file')
            shutil.copy(gz, raw)
        bnfxml = find_one(work, 'f_bnf1_*.xml', 'the BNF mapping file')

        idx = os.path.join(tmp, 'idx')
        say(run(os.path.join(HERE, 'build_index2.py'), raw, idx).strip().splitlines()[-1])
        say(run(os.path.join(HERE, 'filter_index.py'), os.path.join(idx, 'index.sqlite'), bnfxml, os.path.join(idx, 'drug_index.sqlite')).strip().replace('\n', ' | '))
        app = os.path.join(tmp, 'app')
        say(run(os.path.join(HERE, 'make_app_dmd.py'), os.path.join(idx, 'drug_index.sqlite'), app).strip())
        out = os.path.join(tmp, 'site')
        run(os.path.join(HERE, 'make_pack.py'), app, out, version, released, source)

        m = json.load(open(os.path.join(out, 'manifest.json')))
        raw_bytes = open(os.path.join(out, m['file']), 'rb').read()
        prods, brands, gtins = check_pack(raw_bytes, m, prev if not a.dry_run else None)
        say(f'Checks passed: {prods} products, {brands} brands, {gtins} barcodes, {m["bytes"]} bytes, crc32 {m["crc32"]}')

        if prev and prev.get('file') == m['file'] and prev.get('crc32') == m['crc32']:
            say('Identical to the pack already published.')
        # pack first, manifest last, so the app never sees a manifest that points at a missing file
        shutil.copy(os.path.join(out, m['file']), os.path.join(data_dir, m['file']))
        shutil.copy(os.path.join(out, 'manifest.json'), mp)
        old = sorted(glob.glob(os.path.join(data_dir, 'dmd-pack-*.json')), reverse=True)
        for p in old[a.keep:]:
            os.remove(p)
        say('Published to', a.data_dir if not a.dry_run else a.data_dir + ' (dry run)')


if __name__ == '__main__':
    main()
