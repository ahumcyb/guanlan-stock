"""One fixed research pipeline, used by both Mac and fallback server processes."""
import argparse
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from engine.snapshot_protocol import validate_manifest
from engine.close_proof import valid_date,verify_package_close
from .artifacts import STRATEGIES,publish,atomic_json


def build(root,overlay,work,action,expected_as_of=None):
    if expected_as_of is not None and (action!='refresh' or not valid_date(expected_as_of)):
        raise ValueError('Invalid expected closing date')
    root=root.resolve();work=work.resolve();work.mkdir(parents=True,exist_ok=True)
    if expected_as_of:
        overlay=work/'closing-overlay'
        overlay.mkdir(exist_ok=True)
    source=validate_manifest(json.loads((root/'manifest.json').read_text()))
    def run(module,*arguments):
        subprocess.run([sys.executable,'-u','-m',module,*map(str,arguments)],check=True)
    if action=='refresh':
        extra=['--through',expected_as_of,'--force-latest'] if expected_as_of else []
        run('engine.update','--data-root',root,'--overlay',overlay,*extra)
    elif action!='recompute':raise ValueError('Unknown action')
    proof=None
    if expected_as_of:
        updated=json.loads((overlay/'last_update.json').read_text())
        proof=updated.get('close_attestation')
        if updated.get('forced_latest_date')!=expected_as_of or not isinstance(proof,dict) or proof.get('date')!=expected_as_of:
            raise ValueError('Target closing day was not freshly verified; old data cannot be published as today')
    package_options=['--closing-date',expected_as_of] if expected_as_of else []
    run('engine.package_data','--data-root',root,'--overlay',overlay,'--output',work/'packages',*package_options)
    revision=json.loads((work/'packages/latest.json').read_text())['revision'];market=work/'packages'/revision
    if expected_as_of:verify_package_close(market,expected_as_of,proof)
    empty=work/'report-overlay';empty.mkdir(exist_ok=True)
    if (overlay/'last_update.json').is_file():atomic_json(empty/'last_update.json',json.loads((overlay/'last_update.json').read_text()))
    outputs=work/'reports'
    for strategy in STRATEGIES:
        run('engine.cli','--data-root',market,'--overlay',empty,'--output',outputs/strategy,'--strategy',strategy)
    manifests=publish(outputs,work/'mobile',revision)
    if expected_as_of and any(m['as_of']!=expected_as_of for m in manifests.values()):
        raise ValueError('Closing strategy dates differ')
    generation=manifests['leaders']['generation'];research=work/'mobile/releases'/generation
    bundle=work/'bundle.zip';temporary=work/'.bundle.zip'
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=4) as archive:
        metadata={'schema_version':1,'input_revision':source['revision'],'data_revision':revision,'generation':generation}
        if expected_as_of:metadata.update(expected_as_of=expected_as_of,close_attestation=proof)
        archive.writestr('bundle.json',json.dumps(metadata))
        for prefix,folder in [('market',market),('research',research)]:
            for path in sorted(folder.rglob('*')):
                if path.is_file() and not path.is_symlink():archive.write(path,prefix+'/'+path.relative_to(folder).as_posix())
    if temporary.stat().st_size>256*1024*1024:raise ValueError('Mobile bundle exceeds transfer limit')
    os.replace(temporary,bundle)
    print(f'{len(STRATEGIES)} 套盘后策略已生成，待上传结果包 {bundle.stat().st_size/1024/1024:.1f} MiB',flush=True)
    return bundle


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True);p.add_argument('--overlay',type=Path,required=True)
    p.add_argument('--work',type=Path,required=True);p.add_argument('--action',choices=['refresh','recompute'],required=True)
    p.add_argument('--expected-as-of')
    a=p.parse_args()
    try:build(a.data_root,a.overlay,a.work,a.action,a.expected_as_of)
    except Exception:
        print('本次计算未完成，服务器原有结果已保留',flush=True);raise SystemExit(1)
