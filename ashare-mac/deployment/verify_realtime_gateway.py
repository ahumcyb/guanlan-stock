"""Non-mutating HTTPS probes: malformed reports cannot own an execution lease."""
import argparse
import http.client
import json
from pathlib import Path
from mobile_server.mac_worker import WorkerClient


def verify(config):
    if config.stat().st_mode&0o077:raise ValueError('Connection file must be private')
    client=WorkerClient(json.loads(config.read_text()))
    medium=json.dumps({'lease':'0'*64,'report':{'invalid_diagnostic_probe':'x'*8192}}).encode()
    cases=[('/v1/worker/realtime/publish',medium,409),
           ('/v1/worker/realtime/renew',medium,413),
           ('/v1/worker/realtime/publish',b'x'*(256*1024+1),413)]
    results=[]
    for path,body,expected in cases:
        connection=http.client.HTTPSConnection('106.14.125.189',context=client.context,timeout=20)
        try:
            connection.request('POST',path,body=body,headers={'Authorization':'Bearer '+client.token,'Content-Type':'application/json'})
            response=connection.getresponse();response.read(8192)
            results.append(dict(path=path,bytes=len(body),status=response.status,expected=expected))
            if response.status!=expected:raise ValueError('Gateway boundary mismatch: '+json.dumps(results[-1]))
        finally:connection.close()
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(verify(args.config)))
