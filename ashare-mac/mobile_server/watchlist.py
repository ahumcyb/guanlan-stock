"""Personal watchlist with durable, idempotent per-stock operations."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from .artifacts import CODE
from .queue import canonical_uuid


class WatchlistStore:
    def __init__(self,root,clock=time.time):
        self.root=Path(root).resolve()/'jobs';self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'watchlist.sqlite';self.clock=clock

    @contextmanager
    def connection(self):
        fd=os.open(self.path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o660);os.close(fd)
        connection=sqlite3.connect(str(self.path),timeout=10)
        try:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS favorites (code TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER, updated_at REAL);
                INSERT OR IGNORE INTO metadata VALUES (1,0,0);
            ''')
            yield connection
        finally:connection.close()

    @staticmethod
    def snapshot(connection):
        revision,updated=connection.execute('SELECT revision,updated_at FROM metadata WHERE id=1').fetchone()
        codes=[row[0] for row in connection.execute('SELECT code FROM favorites ORDER BY code')]
        return dict(schema_version=1,revision=revision,updated_at=updated,codes=codes)

    def public(self):
        with self.connection() as connection:return self.snapshot(connection)

    def apply(self,operation):
        if (not isinstance(operation,dict) or set(operation)!={'operation_id','ts_code','action'}
                or not canonical_uuid(operation.get('operation_id'))
                or not isinstance(operation.get('ts_code'),str) or not CODE.fullmatch(operation['ts_code'])
                or operation.get('action') not in ['add','remove']):raise ValueError('自选操作无效')
        code=operation['ts_code'];identity=operation['operation_id']
        payload=json.dumps([code,operation['action']],separators=(',',':'))
        with self.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            old=connection.execute('SELECT payload FROM operations WHERE id=?',(identity,)).fetchone()
            if old:
                if old[0]!=payload:raise ValueError('同一操作不能改变内容')
            else:
                if operation['action']=='add':
                    exists=connection.execute('SELECT 1 FROM favorites WHERE code=?',(code,)).fetchone()
                    if not exists and connection.execute('SELECT count(*) FROM favorites').fetchone()[0]>=1000:
                        raise ValueError('自选最多保存1000只')
                    changed=connection.execute('INSERT OR IGNORE INTO favorites VALUES (?)',(code,)).rowcount
                else:changed=connection.execute('DELETE FROM favorites WHERE code=?',(code,)).rowcount
                connection.execute('INSERT INTO operations VALUES (?,?)',(identity,payload))
                if changed:connection.execute('UPDATE metadata SET revision=revision+1,updated_at=? WHERE id=1',(self.clock(),))
            result=self.snapshot(connection);connection.commit();return result
