"""Versioned, transactional SQLite migrations; no destructive startup operations."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS = [
    (1, [
        'CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)',
        'CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL)',
        'CREATE TABLE login_limits(username TEXT PRIMARY KEY, attempts INTEGER NOT NULL, since REAL NOT NULL)',
        '''CREATE TABLE saves(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), domain TEXT NOT NULL CHECK(domain IN ('game','plan')), title TEXT NOT NULL, initial_state TEXT NOT NULL, created_at TEXT NOT NULL)''',
        '''CREATE TABLE branches(id TEXT PRIMARY KEY, save_id TEXT NOT NULL REFERENCES saves(id), parent_id TEXT REFERENCES branches(id), fork_sequence INTEGER NOT NULL, revision INTEGER NOT NULL, initial_state TEXT NOT NULL)''',
        '''CREATE TABLE events(branch_id TEXT NOT NULL REFERENCES branches(id), sequence INTEGER NOT NULL, id TEXT NOT NULL, origin_branch_id TEXT NOT NULL REFERENCES branches(id), type TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, causes TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(branch_id,sequence), UNIQUE(branch_id,id))''',
        '''CREATE TABLE plan_versions(id TEXT PRIMARY KEY, save_id TEXT NOT NULL REFERENCES saves(id), revision INTEGER NOT NULL, previous_id TEXT REFERENCES plan_versions(id), kind TEXT NOT NULL CHECK(kind IN ('judgment','update','outcome')), content TEXT NOT NULL, based_on TEXT REFERENCES plan_versions(id), created_at TEXT NOT NULL, UNIQUE(save_id,revision))''',
        '''CREATE TABLE idempotency(owner_id TEXT NOT NULL REFERENCES users(id), key TEXT NOT NULL, fingerprint TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(owner_id,key))''',
    ]),
    (2, [
        '''CREATE TABLE model_audit(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), save_id TEXT NOT NULL REFERENCES saves(id), purpose TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('real','mock')), model TEXT NOT NULL, attempt INTEGER NOT NULL, status TEXT NOT NULL, usage TEXT NOT NULL, created_at TEXT NOT NULL)''',
        'CREATE INDEX saves_owner ON saves(owner_id)',
        'CREATE INDEX audit_owner_save ON model_audit(owner_id,save_id)',
    ]),
]


class Database:
    def __init__(self, path):
        if path == ':memory:':
            raise ValueError('Use a file database; connections are per transaction')
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=10000')
        return conn

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self):
        conn = self.connect()
        try:
            conn.execute('PRAGMA journal_mode=WAL')
        finally:
            conn.close()
        with self.transaction() as conn:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            if version > MIGRATIONS[-1][0]:
                raise RuntimeError('Database is newer than this service; restore matching code')
            for number, statements in MIGRATIONS:
                if number > version:
                    for statement in statements:
                        conn.execute(statement)
                    conn.execute(f'PRAGMA user_version={number}')
