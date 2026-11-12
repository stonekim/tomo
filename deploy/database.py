"""Consistent SQLite backup and explicit offline restore; never overwrites a backup."""
import argparse,sqlite3,os,uuid
from pathlib import Path
from datetime import datetime,timezone


def validate(path):
    with sqlite3.connect('file:'+str(path.resolve())+'?mode=ro',uri=True) as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Database integrity check failed')


def backup(source,target):
    if not source.is_file():raise RuntimeError('Source database is missing')
    if target.exists():raise RuntimeError('Refusing to overwrite a backup')
    target.parent.mkdir(parents=True,exist_ok=True)
    # Open exclusively before SQLite sees it; private even during the backup.
    fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    try:
        with sqlite3.connect('file:'+str(source.resolve())+'?mode=ro',uri=True) as src,sqlite3.connect(target) as dest:src.backup(dest)
        validate(target)
    except BaseException:
        # Preserve the failed artifact for diagnosis rather than pretending it is usable.
        target.rename(target.with_name(target.name+'.failed-'+uuid.uuid4().hex))
        raise


def restore(source,target,confirmed=False):
    if not confirmed:raise RuntimeError('Stop the service and explicitly confirm it before restore')
    for suffix in ('-wal','-shm','-journal'):
        if Path(str(target)+suffix).exists():raise RuntimeError('SQLite sidecars exist; confirm shutdown/checkpoint before restoring')
    validate(source);target.parent.mkdir(parents=True,exist_ok=True)
    candidate=target.with_name(target.name+'.restore-'+uuid.uuid4().hex)
    backup(source,candidate)
    old=None
    if target.exists():
        old=target.with_name(target.name+'.before-restore-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);target.rename(old)
    try:os.replace(candidate,target)
    except BaseException:
        if old is not None:os.replace(old,target)
        raise
    return old


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['backup','restore']);p.add_argument('source',type=Path);p.add_argument('target',type=Path);p.add_argument('--confirm-service-stopped',action='store_true');a=p.parse_args()
    if a.command=='backup':backup(a.source,a.target)
    else:restore(a.source,a.target,a.confirm_service_stopped)
    print('SQLite '+a.command+' verified; previous target preserved on restore')

if __name__=='__main__':main()
