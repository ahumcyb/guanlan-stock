"""One fixed research pipeline, used by both Mac and fallback server processes."""
import argparse
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from engine.snapshot_protocol import validate_manifest
from .artifacts import publish,atomic_json


def build(root,overlay,work,action):
    root=root.resolve();work=work.resolve();work.mkdir(parents=True,exist_ok=True)
    source=validate_manifest(json.loads((root/'manifest.json').read_text()))
    def run(module,*arguments):
        subprocess.run([sys.executable,'-u','-m',module,*map(str,arguments)],check=True)
    if action=='refresh':run('engine.update','--data-root',root,'--overlay',overlay)
    elif action!='recompute':raise ValueError('Unknown action')
    run('engine.package_data','--data-root',root,'--overlay',overlay,'--output',work/'packages')
    revision=json.loads((work/'packages/latest.json').read_text())['revision'];market=work/'packages'/revision
    empty=work/'report-overlay';empty.mkdir(exist_ok=True)
    if (overlay/'last_update.json').is_file():atomic_json(empty/'last_update.json',json.loads((overlay/'last_update.json').read_text()))
    outputs=work/'reports'
    for strategy in ['leaders','pullback']:
        run('engine.cli','--data-root',market,'--overlay',empty,'--output',outputs/strategy,'--strategy',strategy)
    manifests=publish(outputs,work/'mobile',revision)
    generation=manifests['leaders']['generation'];research=work/'mobile/releases'/generation
    bundle=work/'bundle.zip';temporary=work/'.bundle.zip'
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=4) as archive:
        archive.writestr('bundle.json',json.dumps({'schema_version':1,'input_revision':source['revision'],'data_revision':revision,'generation':generation}))
        for prefix,folder in [('market',market),('research',research)]:
            for path in sorted(folder.rglob('*')):
                if path.is_file() and not path.is_symlink():archive.write(path,prefix+'/'+path.relative_to(folder).as_posix())
    if temporary.stat().st_size>256*1024*1024:raise ValueError('Mobile bundle exceeds transfer limit')
    os.replace(temporary,bundle)
    print(f'两套策略已生成，待上传结果包 {bundle.stat().st_size/1024/1024:.1f} MiB',flush=True)
    return bundle


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True);p.add_argument('--overlay',type=Path,required=True)
    p.add_argument('--work',type=Path,required=True);p.add_argument('--action',choices=['refresh','recompute'],required=True)
    a=p.parse_args()
    try:build(a.data_root,a.overlay,a.work,a.action)
    except Exception:
        print('本次计算未完成，服务器原有结果已保留',flush=True);raise SystemExit(1)
