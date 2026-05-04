"""
SPDX-License-Identifier: MIT
Copyright (C) 2026 John Birdwell
"""


from os import PathLike
import logging
import os
from datetime import timedelta
from os import environ
from pathlib import Path
import json
from sys import argv

from murmur2 import murmur2_fast
from hashlib import md5, sha1, sha512, sha256
import requests

from birdwell.utils import MemoryZip, FlexEncoder, subkey, stale, regrouper

from modpack_db import ModpackDB
from distribution_apis import ModrinthAPI, CurseAPI


log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
info = log.info

server_name = environ.get('SERVER_NAME', 'server').encode()
server_addr = environ.get('SERVER_ADDR', 'localhost').encode()

DEFAULT_PACKNAME = 'modpack'
DEFAULT_PACK_AUTHOR = 'jcbirdwell'

# server.dat file for packs is just hardcoded
RAW_SERVER_FILE = (
    b'\n\x00\x00\t\x00\x07servers\n\x00\x00\x00\x01\x08\x00\x04name\x00\x05'
    + server_name +
    b'\x08\x00\x02ip\x00\t'
    + server_addr +
    b'\x01\x00\x06hidden\x00\x00\x00'
)


alt = regrouper(r'^value.*')
sha_re = regrouper(r'^\[(\w{8})]-(.*)$')

# establish and ensure mod storage directory
MODS = Path(environ.get('MOD_ROOT', 'mod_storage')).absolute()
mod_path = MODS.joinpath
if not MODS.exists():
    log.info(f'generating missing mod root @ "{MODS!s}"')
    MODS.mkdir(parents=True, exist_ok=True)



class PackExportError(Exception):
    pass



db: ModpackDB = ModpackDB.from_env({'dbname': 'minecraft'})
modrinth = ModrinthAPI(environ['MODRINTH_API_KEY'])
curse = CurseAPI(environ['CURSE_API_KEY'])


core_re = regrouper(r'\D*?(\d[.\d]*\d)\D*?', 1)


def mod_version(s: str, mc_version=None):
    if mc_version:
        s = s.replace(mc_version, '')
    return core_re(s)


def project_match(curse_data, modrinth_data):
    if not curse_data or not modrinth_data:
        return False

    cl = curse_data['links']
    for mk, ck in [['source_url', 'sourceUrl'], ['issues_url', 'issuesUrl'], ['wiki_url', 'wikiUrl']]:
        if (mv := modrinth_data[mk]) and cl[ck] == mv:
            return True

    return False


def force_match(proj_with_curse, modrinth_pid):
    cpid = proj_with_curse['pid']
    db_modrinth = db.get_rinth_project(modrinth_pid)
    if db_modrinth:
        if cpid == db_modrinth['pid']:
            return
        # move the curse stuff to new pid
        db.project_merge_releases(cpid, db_modrinth['pid'])
        return db.update_project(db_modrinth['pid'], {
            'cs_project_raw': proj_with_curse['cs_project_raw'], 'cs_pid': proj_with_curse['cs_pid']})

    md = modrinth.project(modrinth_pid)
    # only update, no pid means no releases to move
    return db.update_project(cpid, {
        'mr_pid': modrinth_pid,
        'mr_project_raw': md,
        'project_env': modrinth.project_env(md)
    })


def fix_fail(failure, hit_index):
    return force_match(failure[0], failure[1][hit_index]['project_id'])


def curse_sha1(release_file: dict):
    return next((x['value'] for x in release_file['hashes'] if x['algo'] == 1), None)



def reattempt_modrinth_mesh(proj, with_hits=False):
    hits = []

    def finalize(pack=None):
        if with_hits:
            return pack, hits

        return pack

    cp = proj['cs_project_raw']
    if not cp:
        return finalize()

    mesh = None
    hash_mesh = False
    # mesh using latest file hashes
    if 'latestFiles' in cp:
        for file in cp['latestFiles']:
            s1 = curse_sha1(file)
            mesh = modrinth.match(s1)
            if mesh:
                print(f'SHA MESH for "{proj['project_name']}"')
                hash_mesh = True
                break

    # fallback to search based meshing
    if not mesh:
        hits = modrinth.search(cp['name'], limit=10)['hits']

        if not hits:
            return finalize()


        auths = {x['name'].lower() for x in cp['authors']}
        for i, h in enumerate(hits):
            a = h['author'].lower()
            if a in auths:
                print(f'auth match [{i}] {a} @> {auths}')
                mesh = h
                break

    # note: not using negation as all fallthrough returns an empty finalize
    if mesh:
        print('HITMESH', mesh)
        mesh_db = db.get_rinth_project(mesh['project_id'])
        if mesh_db:
            return finalize(
                mesh_db['pid']
                # hash based match doesn't need to check for a project match
                if hash_mesh or project_match(cp, mesh_db['mr_project_raw'])
                else None
            )


        mesh_mrp = modrinth.project(mesh['project_id'])
        if mesh_mrp:
            # hash based match doesn't need to check for a project match
            if hash_mesh or project_match(cp, mesh_mrp):
                # return data for combine
                return finalize({
                    'mr_project_raw': mesh_mrp,
                    'mr_pid': mesh['project_id'],
                    'project_env': modrinth.project_env(mesh_mrp)
                })

    # fallthrough returns None when no mesh
    return finalize()


def mod_remesh():
    targs = db.modrinth_missing()
    fixes = 0
    fails = []
    tot = len(targs)
    for i, x in enumerate(targs):
        print(f'[{i+1:03} / {tot}] :: {x['project_name']}')
        mesh, hits = reattempt_modrinth_mesh(x, with_hits=True)
        if isinstance(mesh, int):
            db.merge_projects(x['pid'], mesh, subkey(x, 'cs_pid', 'cs_project_raw'))
            fixes += 1
        elif mesh:
            db.update_project(x['pid'], mesh)
            fixes += 1
        else:
            fails.append([x, hits])

    print(f'fixed {fixes} / {tot}')
    return targs, fails


CURSE_HASH_ALGOS = {
    1: 'sha1',
    2: 'md5'
}

extract_file_version = regrouper(r'\w[-\s_][vV]?\.?(\d+.*)\..\w+$', 1)



def format_curse_release(cmf, rp=None):
    fh = {CURSE_HASH_ALGOS[v['algo']]: v['value'] for v in cmf['hashes']}
    fh['murmur2'] = cmf['fileFingerprint']

    if rp is None:
        rp = {
                 'cs_pid': cmf['modId'],
                 'cs_match_raw': cmf
             } | fh

    elif rp['sha1'] != fh['sha1']:
        raise ValueError('modrinth hash doesnt match selected file')

    # curse release(file) id ... curse doesn't have version ids
    rp['cs_rid'] = cmf['id']
    rp['cs_url'] = cmf['downloadUrl']
    rp['filename'] = cmf['fileName']
    # release type
    match cmf['releaseType']:
        case 1:
            rp['release_type'] = 'release'
        case 2:
            rp['release_type'] = 'beta'
        case 3:
            rp['release_type'] = 'alpha'

    # version parsing
    rp['mc_versions'] = []
    rp['loaders'] = []
    support = set()
    log.debug(cmf['gameVersions'])
    for v in cmf['sortableGameVersions']:
        match v['gameVersionTypeId']:
            # mc
            case 77784:
                rp['mc_versions'].append(v['gameVersion'])
            # server/client
            case 75208:
                support.add(v['gameVersionName'].lower())
            # loader
            case 68441:
                rp['loaders'].append(v['gameVersionName'].lower())
            case _:
                log.info(f'unknown game version {v}')

    rp['dependencies'] = []
    for dep in cmf['dependencies']:
        if dep['relationType'] != 3:
            continue
        rp['dependencies'].append(ensured_project(cs_pid=dep['modId'])['pid'])

    rp['release_version'] = extract_file_version(rp['filename'])
    rp['release_ts'] = cmf['fileDate']

    return rp


def modrinth_file(files_or_release: list | dict):
    files = files_or_release['files'] if isinstance(files_or_release, dict) else files_or_release
    if not files:
        return None
    return next((x for x in files if x['primary']), files[0])


def format_modrinth_release(mm, rp=None):
    # we only use the primary / first file
    mmf = modrinth_file(mm)
    if rp is None:
        rp = {
                 'mr_pid': mm['project_id'],
                 'mr_match_raw': mm,
             } | mmf['hashes']
    # otherwise ensure our "primary" selection actually matches
    elif mmf['hashes']['sha1'] != rp['sha1']:
        raise ValueError('modrinth hash doesnt match selected file')

    rp['loaders'] = mm['loaders']
    rp['dependencies'] = []

    for dep in mm['dependencies']:
        if dep['dependency_type'] != 'required':
            continue
        log.info('resolving required dependency')
        rp['dependencies'].append(ensured_project(mr_pid=dep['project_id'])['pid'])

    rp['mc_versions'] = mm['game_versions']
    rp['release_version'] = mm['version_number']
    rp['release_ts'] = mm['date_published']
    rp['release_type'] = mm['version_type']
    # modrinth has a separate "version" ? unsure how a specific version can have multiple files.. ?
    rp['mr_vid'] = mm['id']
    rp['mr_rid'] = mmf['id']
    rp['mr_url'] = mmf['url']
    rp['filename'] = mmf['filename']

    return rp


def ingest_mod(target: Path | tuple[str, bytes]):
    log.info('storing new mod')
    if isinstance(target, tuple):
        base_name, md = target
    else:
        base_name = target.name
        md = target.read_bytes()

    sha1_hex = sha1(md).hexdigest()
    fn = f'[{sha1_hex[:8]}]-{base_name}'
    fp = MODS.joinpath(fn)
    if not fp.exists():
        fp.write_bytes(md)


    db_release: dict | None = db.get_release_sha1(sha1_hex)
    if db_release:
        log.info('already in db')
        if not any(
                db_release[k] is None
                for k in ['file_path', 'file_size_bytes', 'sha1', 'murmur2', 'sha256', 'sha512', 'md5']
        ):
            return db_release


    mm2 = murmur2_fast(md)

    # release pack is the file
    rp: dict = {
        'file_path': fn,
        'file_size_bytes': len(md),
        'sha1': sha1_hex,
        'murmur2': mm2,
        'sha256': sha256(md).hexdigest(),
        'sha512': sha512(md).hexdigest(),
        'md5': md5(md).hexdigest(),
    }

    # db version was missing some file data, submit and return
    if db_release:
        log.info(f'updating file fields for "{fn}"')
        return db.update_project_file_fields(db_release['rid'], rp)

    mm = rp['mr_match_raw'] = modrinth.match(sha1_hex)
    mr_pid = mm['project_id'] if mm else None

    cms = rp['cs_match_raw'] = curse.matches(mm2)
    if cms and cms['exactMatches']:
        cmf = cms['exactMatches'][0]['file']
        cs_pid = cmf['modId']
    else:
        cmf = None
        cs_pid = None


    if not mm and not cmf:
        log.info('unable to find any matches')
        return
    elif not mm:
        log.info(f'unable to find modrinth match for "{fn}"')
        rp |= format_curse_release(cmf, rp)
        # rp['release_version'] = mod_version(fn, rp['mc_versions'][0])
        # project via curse

    else:
        rp |= format_modrinth_release(mm, rp)

        if cmf:
            rp['cs_rid'] = cmf['id']
            rp['cs_url'] = cmf['downloadUrl']

    proj = ensured_project(mr_pid=mr_pid, cs_pid=cs_pid)

    # perform a recheck on missing modrinth data
    if proj['mr_pid'] is None and proj['platform_exclusive'] is None:
        mesh = reattempt_modrinth_mesh(proj)
        # merging into existing, we are no longer fresh
        if isinstance(mesh, int):
            # only need update, no releases move since we haven't set yet (we were fresh)
            proj = db.update_project(mesh, subkey(proj, 'cs_pid', 'cs_project_raw'))

        elif mesh:
            proj = db.update_project(proj['pid'], mesh)

    rp['pid'] = proj['pid']
    return db.set_release(rp)


def ensured_project(mr_pid=None, cs_pid=None, mr_fp=None, cs_fp=None):
    # if fresh pulls were provided we use them to fill
    #  ids or compare if that was also given
    if mr_fp:
        if not mr_pid:
            mr_pid = mr_fp['id']
        else:
            # ensure they match, this also validates id is in the pull
            if mr_pid == mr_fp['id']:
                raise ValueError('pull project and provided pid do not match')

    if cs_fp:
        if not cs_pid:
            cs_pid = cs_fp['id']
        else:
            # ensure they match, this also validates id is in the pull
            if cs_pid != cs_fp['id']:
                raise ValueError('pull project and provided pid do not match')

    # ensure we have a target
    if mr_pid is None and cs_pid is None:
        raise ValueError('must have at least one project source')

    mr_dp = None
    cs_dp = None


    if mr_pid:
        mr_dp = db.get_rinth_project(mr_pid)
        if not mr_dp:
            if not mr_fp:
                mr_fp = modrinth.project(mr_pid)

            mr_dp = {
                'project_name': mr_fp['title'],
                'project_type': mr_fp['project_type'],
                'project_env': modrinth.project_env(mr_fp),
                'mr_pid': mr_pid,
                'mr_project_raw': mr_fp,
            }
        # when a pull is provided but we already have db data, perform update
        # this can be differentiated by the presence of our native pid on the mr_dp
        elif mr_fp:
            mr_dp |= {
                'project_name': mr_fp['title'],
                'project_type': mr_fp['project_type'],
                'project_env': modrinth.project_env(mr_fp),
                'mr_pid': mr_pid,
                'mr_project_raw': mr_fp,
            }


    if cs_pid:
        cs_dp = db.get_curse_project(cs_pid)

        if not cs_dp:
            if not cs_fp:
                cs_fp = curse.project(cs_pid)

            pt = curse.project_type(cs_fp)

            cs_dp = {
                'project_name': cs_fp['name'],
                'project_type': pt,
                # curse doesn't provide environment, but we know that
                #  if the mod is a texture/shader pack its client only
                'project_env': 'client_only' if pt != 'mod' else 'unknown',
                'cs_pid': cs_pid,
                'cs_project_raw': cs_fp
            }
        # already have db but pull was provided, forces update (see modrinth variant above for more details)
        elif cs_fp:
            pt = curse.project_type(cs_fp)
            cs_dp |= {
                'project_name': cs_fp['name'],
                'project_type': pt,
                'project_env': 'client_only' if pt != 'mod' else 'unknown', # see above
                'cs_pid': cs_pid,
                'cs_project_raw': cs_fp
            }


    # only database pulls
    if not cs_fp and not mr_fp:
        # we have entries for both
        if cs_dp and mr_dp:
            # same and synced -> we can return either
            if cs_dp['pid'] == mr_dp['pid']:
                return mr_dp # or cs_dp

            # different pids -> we need to sync db projects
            else:
                # update curse releases to point to modrinth's pid and merge curse data into modrinth project
                # -> return updated project entry
                return db.merge_projects(cs_dp['pid'], mr_dp['pid'], subkey(cs_dp, 'cs_pid', 'cs_project_raw'))

        # otherwise we just return the one we have since no fresh
        else:
            return cs_dp or mr_dp

    # both fresh, we combine and set
    elif cs_fp and mr_fp:
        # all options require a combined db_entry
        combined = mr_dp | subkey(cs_dp, 'cs_pid', 'cs_project_raw')
        # if we have pids on db variant our fresh_pull resulted in an update
        if 'pid' in mr_dp and 'pid' in cs_dp:
            # same pids, we can combine and update
            if mr_dp['pid'] == cs_dp['pid']:
                return db.update_project(mr_dp['pid'], combined)
            # otherwise we must merge
            return db.merge_projects(cs_dp['pid'], mr_dp['pid'], combined)
        elif 'pid' in mr_dp:
            # updating modrinth project
            return db.update_project(mr_dp['pid'], combined)
        elif 'pid' in cs_dp:
            # updating curse project
            return db.update_project(cs_dp['pid'], combined)

        # no pids is freshly entered project ( with our native project_id )
        return db.set_project(mr_dp | subkey(cs_dp, 'cs_pid', 'cs_project_raw'))

    # we have a single fresh entry
    elif cs_fp:
        # if we have the other, we update it and return that
        if mr_dp:
            if 'pid' in cs_dp and cs_dp['pid'] != mr_dp['pid']:
                # merge in this case also gets updates from itself, as this occurs when a forced pull was present
                return db.merge_projects(cs_dp['pid'], mr_dp['pid'], mr_dp | subkey(cs_dp, 'cs_pid', 'cs_project_raw'))

            # fallthrough update here ignores fresh (forced) changes to cs_dp as modrinth will always have more
            return db.update_project(mr_dp['pid'], subkey(cs_dp, 'cs_pid', 'cs_project_raw'))

        # otherwise we just enter the fresh (db variant) and return that
        return db.set_project(cs_dp)

    elif mr_fp:
        if cs_dp:  # cs_dp with no fresh means it came from db (and will have pid etc)
            if 'pid' in mr_dp:
                if cs_dp['pid'] != mr_dp['pid']:
                    # merge in this case also gets updates from itself, as this occurs when a forced pull was present
                    return db.merge_projects(cs_dp['pid'], mr_dp['pid'], mr_dp | subkey(cs_dp, 'cs_pid', 'cs_project_raw'))
                # we catch fallthrough here as the update may have better data ( modrinth as source )
                return db.update_project(mr_dp['pid'], mr_dp | subkey(cs_dp, 'cs_pid', 'cs_project_raw'))

            # since we now have a modrinth project, we can also update the project_env
            return db.update_project(cs_dp['pid'], subkey(mr_dp, 'mr_pid', 'mr_project_raw', 'project_env'))

        # otherwise we just set the new modrinth project
        return db.set_project(mr_dp)


    # all cases should have already returned
    raise Exception()


def download_ingest(file_name, link):
    data = requests.get(link).content
    return ingest_mod((file_name, data))



def latest_release(project_id, loader, mc_version, prefer_release=True):
    db_vers = db.releases(project_id, loader=loader, mc_version=mc_version)
    if not db_vers:
        return None
    if prefer_release:
        return next(
            (x for x in db_vers if x['release_type'] == 'release'),
            db_vers[0]
        )
    return db_vers[0]


def ensured_latest_release(proj, loader='neoforge', mc_version='1.21.1', force=False):
    if not force and not stale(proj['release_fetch_ts'], timedelta(days=1)):
        return latest_release(proj['pid'], loader=loader, mc_version=mc_version)


    if proj['mr_pid']:
        if fr_vers := modrinth.releases(proj['mr_pid'], loader=loader, mc_version=mc_version):
            for ver in fr_vers:
                db_ver = format_modrinth_release(ver)
                db_ver['pid'] = proj['pid']
                db.set_release(db_ver)


    if proj['cs_pid']:
        if fr_vers := curse.releases(proj['cs_pid'], loader=loader, mc_version=mc_version):
            for ver in fr_vers:
                db_ver = format_curse_release(ver)
                db_ver['pid'] = proj['pid']
                db.set_release(db_ver)


    proj['release_fetch_ts'] = db.bump_release_fetch(proj['pid'])

    return latest_release(proj['pid'], loader=loader, mc_version=mc_version)



def prepare_pack_contents(mod_dir: Path, mc_version='1.21.1', loader='neoforge', latest=False):
    pack = {}

    tot = len(os.listdir(mod_dir))
    for i, p in enumerate(mod_dir.iterdir()):
        if p.suffix not in {'.zip', '.jar'}:
            print(f'skipping non-mod "{p!s}"')
            continue
        print(f'[{i:03} / {tot}] :: {p!s}')
        m = ingest_mod(p)
        pack[m['pid']] = m

    log.info(f'ensuring latest [{latest}] and/or resolving dependencies')
    # find latest release
    for mod_pid in list(pack):
        mod: dict = pack[mod_pid]
        if latest:
            checked = ensured_latest_release(mod, loader=loader, mc_version=mc_version)
            if not checked:
                log.info('no alternate release found')
            elif checked['rid'] != mod['rid']:
                print(f'updated mod from "{mod['release_version']}" => "{checked['release_version']}"')
                mod = pack[mod_pid] = checked
        if mod['dependencies']:
            for dep in mod['dependencies']:
                if dep not in pack:
                    print(f'resolving dependency release for {mod['project_name']} with pid [{dep}]')
                    pack[dep] = ensured_latest_release(db.project(dep), loader=loader, mc_version=mc_version)

    log.info('ensuring all mods are downloaded')

    for k in pack:
        mod = pack[k]
        if mod['file_path'] is None or not mod_path(mod['file_path']).exists():
            # check if we have a matching has stored already
            ss = f'[{mod['sha1'][:8]}]-'
            fn = next((x for x in os.listdir(MODS) if x.startswith(ss)), None)
            if fn:
                print(f'found downloaded match, upgrading "{fn}"')
                md = mod_path(fn).read_bytes()

                pack[k] = db.update_project_file_fields(mod['rid'], {
                    'file_path': fn,
                    'file_size_bytes': len(md),
                    'murmur2': murmur2_fast(md),
                    'sha256': sha256(md).hexdigest(),
                    'sha512': sha512(md).hexdigest(),
                    'md5': md5(md).hexdigest(),
                })

            # otherwise we will be downloading the mod
            elif mod['mr_url']:
                print(f'downloading "{mod['filename']}" from modrinth @ {mod['mr_url']}')
                pack[k] = download_ingest(mod['filename'], mod['mr_url'])
            else:
                print(f'downloading "{mod['filename']}" from curse @ {mod['cs_url']}')
                pack[k] = download_ingest(mod['filename'], mod['cs_url'])

    return pack


def latest_neo(mc_version='1.21.1'):
    res = requests.get('https://maven.neoforged.net/api/maven/versions/releases/net%2Fneoforged%2Fneoforge').json()
    pre = f'{mc_version.split('.', 1)[-1]}.'
    options = [x for x in res['versions'] if x.startswith(pre) and ('-' not in x)]
    ver = max((int(x.removeprefix(pre)) for x in options))
    return f'{pre}{ver}'


def as_neo_link(version):
    return f'https://maven.neoforged.net/releases/net/neoforged/neoforge/{version}/neoforge-{version}-installer.jar'


def prepare_pack_export(pack_name: str, old_version: str, new_version: str):
    sep = {
        old_version: {},
        new_version: {}
    }

    pack = db.get_modpacks(names=[pack_name], versions=[old_version, new_version])
    for v in pack:
        sep[v['pack_version']][v['pid']] = v

    patch: dict = {
        'additions': [], 'removals': [], 'updates': [], 'unchanged': [],
        'old_version': {
            'version': old_version,
            'full_pack': sep[old_version]
        },
        'new_version': {
            'version': new_version,
            'full_pack': sep[new_version]
        }
    }

    old = patch['old_version']['full_pack']
    new = patch['new_version']['full_pack']
    oss = set(old)
    nss = set(new)
    for k in oss.intersection(nss):
        o = old[k]
        n = new[k]
        if o['rid'] == n['rid']:
            patch['unchanged'].append({
                'mod': n['project_name'],
                'version': [n['release_version']],
                'file': [n['file_path']],
                'release_id': [n['rid']]
            })
        else:
            patch['updates'].append({
                'mod': n['project_name'],
                'version': [o['release_version'], n['release_version']],
                'file': [o['file_path'], n['file_path']],
                'release_id': [o['rid'], n['rid']]
            })

    for k in oss.difference(nss):
        o = old[k]
        patch['removals'].append({
            'mod': o['project_name'],
            'version': [o['release_version']],
            'file': [o['file_path']],
            'release_id': [o['rid']]
        })

    for k in nss.difference(oss):
        n = new[k]
        patch['additions'].append({
            'mod': n['project_name'],
            'version': [n['release_version']],
            'file': [n['file_path']],
            'release_id': [n['rid']]
        })

    res = {
        'server': [],
        'client': []
    }

    dest_map = {
        'both':        ['server', 'client'],
        'server_only': ['server', 'client'],
        'client_only': ['client']
    }


    for item in new.values():
        for dest in dest_map[item['project_env']]:
            res[dest].append(item)

    mc_version = '1.21.1'
    neo_ver = latest_neo(mc_version)

    return {
        'pack_name': pack_name,
        'pack_version': new_version,
        'loader': {'name': 'neoforge', 'version': neo_ver, 'launcher': as_neo_link(neo_ver)},
        'mc_version': mc_version,
        'pack_author': DEFAULT_PACK_AUTHOR,
        'patch': patch,
        'targets': res
    }


def pack_export(pack: dict, dst: PathLike):

    out_root = Path(dst)
    if not out_root.exists():
        raise PackExportError('output destination root doesnt exist')
    elif not out_root.is_dir():
        raise PackExportError('output destination isnt a directory')

    info('output structure generation')
    version = pack['pack_version']
    # prepare version output location
    # map to trim padded version str for normalized directory 1.02.06 => 1/2/6
    # also guards against malformed version strings ... todo: beta version support ?
    major, minor, patch = map(lambda v: str(int(v)), version.split('.'))
    od = out_root.joinpath(major, minor, patch)

    if not od.exists():
        info(f'generating output directories @ "{od!s}"')
        od.mkdir(parents=True, exist_ok=True)

    pack_name = pack['pack_name']
    author = pack['pack_author']
    mc_version = pack['mc_version']
    ld = pack['loader']

    flame_base = {
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "minecraft":{
            "modLoaders":[{"id":f"{ld['name']}-{ld['version']}","primary": True}],
            "version": mc_version
        },
        "name":f"{pack_name}-{version}",
        "overrides":"overrides",
        "version": version,
        'author': author,
        'files': []
    }

    # init curse destinations
    links = []
    ff = flame_base['files']

    # these will be the folders present
    curse_dst = {'mod': [], 'texture': [], 'shader': []}
    prism_dst = {'mod': [], 'texture': [], 'shader': []}
    dst_map = {'mod': 'mods', 'texture': 'texturepacks', 'shader': 'shaderpacks'}
    info('mapping client packs')
    # iterate through modpack contents assigning client specific outputs,
    #  attempting to match native mod export when possible
    for item in pack['targets']['client']:
        dr = item['project_type']
        fp = mod_path(item['file_path'])

        # prism just gets everything
        prism_dst[dr].append(fp)

        # curse only gets the file if it doesnt have a link
        if not item['cs_pid'] or not item['cs_rid']:
            curse_dst[dr].append(fp)
            continue

        # we include linkable mods in curse manifest instead
        ff.append({
            "fileID": int(item['cs_rid']),
            "projectID": int(item['cs_pid']),
            "required": True
        })
        txt = f'{item['project_name']} (by {item['cs_project_raw']['authors'][0]['name']})'
        links.append(f'<li><a href="https://www.curseforge.com/projects/{item['cs_pid']}">{txt}</a></li>')

    info('exporting curse variant')
    # write the curse version of modpack
    # note: im not actually sure about the native handling of changes
    #  for curse releases, this structure and content is modeled after
    #  the prism client's curse variant export but ~automated~
    with MemoryZip(od, 'curse') as mz:
        mz.write('overrides/servers.dat', RAW_SERVER_FILE)
        mz.write('modlist.html', f'<ul>\n{'\n'.join(links)}\n</ul>')
        mz.write('manifest.json', json.dumps(flame_base, indent=2))
        for k, stuff in curse_dst.items():
            if not stuff:
                continue
            for p in stuff:
                mz.write(f'overrides/{dst_map[k]}/{p.name}', p.read_bytes())

    # generate metadata file content for prism variant of pack
    prism_cfg = '\n'.join([
        f'[General]',
        f'ExportAuthor={author}',
        f'ExportName={pack_name}-{version}',
        f'ExportOptionalFiles=true',
        f'ExportSummary=',
        f'ExportVersion={version}',
    ])

    prism_comps = {
        "components": [
            {
                "cachedName": "LWJGL 3",
                "cachedVersion": "3.3.3",
                "cachedVolatile": True,
                "dependencyOnly": True,
                "uid": "org.lwjgl3",
                "version": "3.3.3"
            },
            {
                "cachedName": "Minecraft",
                "cachedRequires": [
                    {
                        "suggests": "3.3.3",
                        "uid": "org.lwjgl3"
                    }
                ],
                "cachedVersion": mc_version,
                "important": True,
                "uid": "net.minecraft",
                "version": mc_version
            },
            {
                "cachedName": "NeoForge",
                "cachedRequires": [
                    {
                        "equals": mc_version,
                        "uid": "net.minecraft"
                    }
                ],
                "cachedVersion": ld['version'],
                "uid": "net.neoforged",
                "version": ld['version']
            }
        ],
        "formatVersion": 1
    }

    info('exporting prism variant')
    # export zip of file
    with MemoryZip(od, 'prism') as mz:
        mz.write('minecraft/servers.dat', RAW_SERVER_FILE)
        mz.write('instance.cfg', prism_cfg)
        mz.write('mmc-pack.json', json.dumps(prism_comps, indent=2))
        for k, stuff in prism_dst.items():
            if not stuff:
                continue
            for p in stuff:
                mz.write(f'minecraft/{dst_map[k]}/{p.name}', p.read_bytes())

    info('exporting server variant')
    with MemoryZip(od, 'server') as mz:
        mz.write('modpack_manifest.json', json.dumps(pack, default=FlexEncoder().default))
        for item in pack['targets']['server']:
            ip = mod_path(item['file_path'])
            mz.write(f'mods/{ip.name}', ip.read_bytes())


def transform_packs(
        src: PathLike,
        dst: PathLike,
        version: str,
        pack_name: str = DEFAULT_PACKNAME,
        author: str = DEFAULT_PACK_AUTHOR,
        mc_version: str = '1.21.1',
        neo_version: str = '21.1.216'
):
    """
    export the modpack contents and metadata to all supported clients

    Parameters
    ----------
    src : modpack as a folder containing metadata and overwrite folders (mods/shaderpacks/texturepacks)
    dst : pack version root dir (version subdirectories will be generated here)
    version : version string in MAJOR.MINOR.PATCH format, numerical only not beta/alpha/etc
    pack_name : pack name
    author : pack creator
    mc_version : minecraft version of pack
    neo_version : version of neoforge being used

    """
    info('presence checks')
    # ensure source
    sp = Path(src)
    if not sp.exists():
        raise FileNotFoundError('source dir')

    # ensure we have metadata
    # todo: curse api access for mod lookups
    mf = sp.joinpath('modpack_metadata.json')
    if not mf.exists():
        raise FileNotFoundError('metadata')

    meta = json.loads(mf.read_text())

    out_root = Path(dst)
    if not out_root.exists():
        raise PackExportError('output destination root doesnt exist')
    elif not out_root.is_dir():
        raise PackExportError('output destination isnt a directory')

    info('output structure generation')
    # prepare version output location
    # map to trim padded version str for normalized directory 1.02.06 => 1/2/6
    # also guards against malformed version strings ... todo: beta version support ?
    major, minor, patch = map(lambda v: str(int(v)), version.split('.'))
    od = out_root.joinpath(major, minor, patch)

    if not od.exists():
        od.mkdir(parents=True, exist_ok=True)

    # todo: revision comparison / pack change generation between versions

    # initialize curse manifest
    flame_base = {
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "minecraft":{
            "modLoaders":[{"id":f"neoforge-{neo_version}","primary": True}],
            "version": mc_version
        },
        "name":f"{pack_name}-{version}",
        "overrides":"overrides",
        "version": version,
        'author': author,
        'files': []
    }
    dl_map = {
        'mods': {},
        'shaderpacks': {},
        'texturepacks': {}
    }


    projects = {}
    prism_zip = {'mods': [], 'texturepacks': [], 'shaderpacks': []}

    info('metadata remap')
    # quick and dirty metadata remapping for lookup
    # todo: api access or sqlite for sanity
    for mod in meta['mods']:
        dl = mod['downloaded'].rsplit('/', 1)[-1]
        mm = next((x for x in mod['files'] if x['fileName'] == dl), None)
        if not mm:
            print(f'missing mod meta for "{dl}"', mod)
            continue

        pj = mod['project']
        pid = pj['id']
        projects[pid] = pj

        dl_map['mods'][dl] = { "fileID": mm['id'], "projectID": pid, "required": True }

    # init curse destinations
    links = []
    ff = flame_base['files']

    # these will be the folders present
    overrides = {'mods': [], 'texturepacks': [], 'shaderpacks': []}

    info('pack parsing iteration')
    # iterate through modpack contents assigning client specific outputs,
    #  attempting to match native mod export when possible
    for dr in overrides:
        # split based on which part of the pack we are operating on
        dm = dl_map[dr]
        for file_path in sp.joinpath(dr).iterdir():
            # all files are added to prism zip
            prism_zip[dr].append(file_path)

            # curse pack only overrides when mod cant be downloaded
            linked = dm.get(file_path.name)
            if linked and (pj := projects.get(linked['projectID'])):
                ff.append(linked)
                txt = f'{pj['name']} (by {pj['author']['name']})'
                links.append(f'<li><a href="https://www.curseforge.com/projects/{pj['id']}">{txt}</a></li>')
                continue

            # missed files are added to overrides
            overrides[dr].append(file_path)

    info('exporting curse variant')
    # write the curse version of modpack
    # note: im not actually sure about the native handling of changes
    #  for curse releases, this structure and content is modeled after
    #  the prism client's curse variant export but ~automated~
    with MemoryZip(od, 'curse') as mz:
        mz.write('overrides/servers.dat', RAW_SERVER_FILE)
        mz.write('modlist.html', f'<ul>\n{'\n'.join(links)}\n</ul>')
        mz.write('manifest.json', json.dumps(flame_base, indent=2))
        for op in overrides:
            stuff = overrides[op]
            if not stuff:
                continue
            for p in stuff:
                mz.write(f'overrides/{op}/{p.name}', p.read_bytes())

    # generate metadata file content for prism variant of pack

    prism_cfg = '\n'.join([
        f'[General]',
        f'ExportAuthor={author}',
        f'ExportName={pack_name}-{version}',
        f'ExportOptionalFiles=true',
        f'ExportSummary=',
        f'ExportVersion={version}',
    ])

    prism_comps = {
        "components": [
            {
                "cachedName": "LWJGL 3",
                "cachedVersion": "3.3.3",
                "cachedVolatile": True,
                "dependencyOnly": True,
                "uid": "org.lwjgl3",
                "version": "3.3.3"
            },
            {
                "cachedName": "Minecraft",
                "cachedRequires": [
                    {
                        "suggests": "3.3.3",
                        "uid": "org.lwjgl3"
                    }
                ],
                "cachedVersion": mc_version,
                "important": True,
                "uid": "net.minecraft",
                "version": mc_version
            },
            {
                "cachedName": "NeoForge",
                "cachedRequires": [
                    {
                        "equals": mc_version,
                        "uid": "net.minecraft"
                    }
                ],
                "cachedVersion": neo_version,
                "uid": "net.neoforged",
                "version": neo_version
            }
        ],
        "formatVersion": 1
    }

    info('exporting prism variant')
    # export zip of file
    with MemoryZip(od, 'prism') as mz:
        mz.write('minecraft/servers.dat', RAW_SERVER_FILE)
        mz.write('instance.cfg', prism_cfg)
        mz.write('mmc-pack.json', json.dumps(prism_comps, indent=2))
        for op in prism_zip:
            stuff = prism_zip[op]
            if not stuff:
                continue
            for mod_path in stuff:
                mz.write(f'minecraft/{op}/{mod_path.name}', mod_path.read_bytes())

    # todo: modrinth, raw, and metadata only


def pack_gen(src, cur_version, target_version, name=DEFAULT_PACKNAME):
    p3 = prepare_pack_contents(Path(src), latest=True)
    db.set_modpack(name, target_version, [x['rid'] for x in p3.values()])
    prep = prepare_pack_export(name, cur_version, target_version)
    pack_export(prep, 'final_pack')





if __name__ == '__main__':
    pack_gen(*argv[1:])