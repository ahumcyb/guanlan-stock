"""Download an immutable snapshot over an authenticated, read-only SSH channel."""
import argparse
import fcntl
import ipaddress
import json
import os
import selectors
import signal
import time
import shutil
import subprocess
import tempfile
from pathlib import Path
import pyarrow.parquet as pq

from .data import atomic_json
from .snapshot_protocol import validate_manifest,sha256_file,retain_snapshots


class SshTransport:
    def __init__(self,config):
        ipaddress.ip_address(config['host'])
        if config['user']!='guanlan-data':raise ValueError('必须使用只读行情账户')
        identity=Path(config['identity_file']).expanduser().resolve()
        if not identity.is_file() or identity.stat().st_mode & 0o077:
            raise ValueError('找不到只读 SSH 私钥，或私钥权限不是 600')
        self.prefix=['/usr/bin/ssh','-F','/dev/null','-T','-o','BatchMode=yes',
            '-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes',
            '-o','ClearAllForwardings=yes','-o','ConnectTimeout=12',
            '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3',
            '-i',str(identity),f'{config["user"]}@{config["host"]}']

    def _run(self,command,output=None,limit=65536):
        try:
            process=subprocess.Popen(self.prefix+[command],stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        except OSError:raise ValueError('无法启动 SSH 客户端') from None
        selector=selectors.DefaultSelector();result=bytearray();received=0;deadline=time.monotonic()+300
        for stream in (process.stdout,process.stderr):
            os.set_blocking(stream.fileno(),False);selector.register(stream,selectors.EVENT_READ)
        try:
            while selector.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0:raise ValueError('服务器数据传输超时，旧缓存已保留')
                for key,_ in selector.select(min(.5,remaining)):
                    stdout=key.fileobj is process.stdout
                    chunk=os.read(key.fileobj.fileno(),min(65536,limit-received+1) if stdout else 65536)
                    if not chunk:selector.unregister(key.fileobj);continue
                    if stdout:
                        received+=len(chunk)
                        if received>limit:raise ValueError('服务器返回数据超过声明大小，已终止传输')
                        if output is None:result.extend(chunk)
                        else:output.write(chunk)
                    # Drain and discard stderr so a peer cannot fill memory or block.
            if process.wait(timeout=max(.1,deadline-time.monotonic()))!=0:
                raise ValueError('SSH 数据访问失败，请检查网络、只读密钥和主机密钥')
            return bytes(result)
        finally:
            selector.close()
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
            process.stdout.close();process.stderr.close()

    def manifest(self):
        data=self._run('manifest')
        if len(data)>65536:raise ValueError('服务器数据清单过大')
        return validate_manifest(json.loads(data))

    def file(self,revision,name,destination,expected_bytes):
        with destination.open('wb') as output:self._run(f'file {revision} {name}',output,limit=expected_bytes)


def verify_files(directory,manifest):
    for entry in manifest['files']:
        path=directory/'raw'/entry['name']
        if (not path.is_file() or path.is_symlink() or path.stat().st_size!=entry['bytes']
                or sha256_file(path)!=entry['sha256']):
            raise ValueError(f'{entry["name"]} 文件完整性校验失败')
        if pq.read_metadata(path).num_rows!=entry['rows']:
            raise ValueError(f'{entry["name"]} 行数校验失败')


def sync(config,cache,transport=None):
    cache=cache.resolve();cache.mkdir(parents=True,exist_ok=True)
    with (cache/'.sync.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('已有服务器同步正在运行') from None
        transport=transport or SshTransport(config)
        print('连接服务器，读取已发布数据版本…',flush=True)
        manifest=validate_manifest(transport.manifest())
        revision=manifest['revision'];releases=cache/'releases';releases.mkdir(exist_ok=True)
        destination=releases/revision
        if destination.exists():
            local=validate_manifest(json.loads((destination/'manifest.json').read_text()))
            if local['files']!=manifest['files']:raise ValueError('本地版本清单与服务器不一致')
            verify_files(destination,manifest)
        else:
            stage=Path(tempfile.mkdtemp(prefix='.staging-',dir=cache));(stage/'raw').mkdir()
            try:
                for i,entry in enumerate(manifest['files']):
                    print(f'同步 {i+1}/5 · {entry["name"]} · {entry["bytes"]/1024/1024:.1f} MiB',flush=True)
                    transport.file(revision,entry['name'],stage/'raw'/entry['name'],entry['bytes'])
                verify_files(stage,manifest)
                atomic_json(stage/'manifest.json',manifest)
                os.rename(stage,destination)
            finally:
                if stage.exists():shutil.rmtree(stage)
        previous=(cache/'current').resolve().name if (cache/'current').is_symlink() else None
        temporary=cache/('.current-'+os.urandom(6).hex())
        try:
            temporary.symlink_to(Path('releases')/revision)
            os.replace(temporary,cache/'current')
        finally:
            if temporary.is_symlink():temporary.unlink()
        retain_snapshots(releases,revision,previous if previous!=revision else None)
        print(f'服务器同步完成 · {manifest["as_of"]} · 五张表校验通过',flush=True)
        return destination


if __name__=='__main__':
    def cancel(_signal,_frame):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,cancel)
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--cache',type=Path,required=True)
    a=p.parse_args()
    try:sync(json.loads(a.config.read_text()),a.cache)
    except KeyboardInterrupt:
        print('服务器同步已取消，旧缓存已保留',flush=True);raise SystemExit(130)
    except Exception as e:
        print(str(e) if isinstance(e,ValueError) else f'服务器同步失败（{type(e).__name__}），旧缓存已保留',flush=True)
        raise SystemExit(1)
