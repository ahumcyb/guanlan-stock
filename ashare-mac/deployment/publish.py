"""Root-operated, checksum-verified atomic activation. No network credentials."""
import argparse
import fcntl
import grp
import json
import os
import shutil
import pwd
from pathlib import Path
if __package__:
    from engine.snapshot_protocol import FILE_NAMES,REVISION,validate_manifest,sha256_file,retain_snapshots
else:
    from snapshot_protocol import FILE_NAMES,REVISION,validate_manifest,sha256_file,retain_snapshots


def verify(directory,revision):
    if directory.is_symlink() or directory.resolve()!=directory or set(p.name for p in directory.iterdir())!={'raw','manifest.json'}:
        raise ValueError('Unexpected release layout')
    raw=directory/'raw';manifest=directory/'manifest.json'
    if (raw.is_symlink() or not raw.is_dir() or raw.resolve()!=raw
            or manifest.is_symlink() or not manifest.is_file() or manifest.resolve()!=manifest
            or manifest.stat().st_size>65536):raise ValueError('Unsafe release layout')
    value=validate_manifest(json.loads((directory/'manifest.json').read_text()))
    if value['revision']!=revision:raise ValueError('Revision mismatch')
    if set(p.name for p in (directory/'raw').iterdir())!=set(FILE_NAMES):raise ValueError('Unexpected data files')
    for entry in value['files']:
        file=directory/'raw'/entry['name']
        if file.resolve()!=file or file.stat().st_size!=entry['bytes'] or sha256_file(file)!=entry['sha256']:
            raise ValueError('Snapshot checksum mismatch')
    return value


def publish(root,revision):
    if not REVISION.fullmatch(revision):raise ValueError('Invalid revision')
    root=root.resolve(); stage=root/'staging'/revision; target=root/'releases'/revision
    with (root/'.publish.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if stage.exists():
            value=verify(stage,revision)
            gid=grp.getgrnam('guanlan-data').gr_gid
            owner=os.geteuid()
            if owner==0:
                try:owner=pwd.getpwnam('guanlan-worker').pw_uid
                except KeyError:pass
            for directory in [stage,stage/'raw']:
                os.chown(directory,owner,gid,follow_symlinks=False);os.chmod(directory,0o750,follow_symlinks=False)
            for file in [stage/'manifest.json',*(stage/'raw').iterdir()]:
                os.chown(file,owner,gid,follow_symlinks=False);os.chmod(file,0o640,follow_symlinks=False)
            if target.exists():
                previous=verify(target,revision)
                if previous['files']!=value['files']:raise ValueError('Existing immutable version differs')
                shutil.rmtree(stage)
            else:os.rename(stage,target)
        else:value=verify(target,revision)
        previous=(root/'current').resolve().name if (root/'current').is_symlink() else None
        link=root/('.current-'+os.urandom(6).hex())
        try:
            link.symlink_to(Path('releases')/revision);os.replace(link,root/'current')
        finally:
            if link.is_symlink():link.unlink()
        retain_snapshots(root/'releases',revision,previous if previous!=revision else None)
        print(json.dumps({'revision':revision,'as_of':value['as_of'],'validation':'ok',
                         'rows':{f['name']:f['rows'] for f in value['files']}},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--revision',required=True)
    a=p.parse_args();publish(a.root,a.revision)
