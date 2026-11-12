import hashlib
import hmac
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from tomo.contracts import validate
from .errors import PlatformError


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'{salt}:{digest}'


class Auth:
    def __init__(self, db, hours=24, clock=time.time):
        self.db, self.hours, self.clock = db, hours, clock
        self.dummy_hash = password_hash('dummy-password-never-used')

    def register(self, credentials):
        validate('Credentials', credentials)
        encoded = password_hash(credentials['password'])
        user_id = str(uuid.uuid4())
        try:
            with self.db.transaction() as conn:
                conn.execute('INSERT INTO users VALUES(?,?,?)', (user_id, credentials['username'], encoded))
        except sqlite3.IntegrityError:
            raise PlatformError(409, 'USERNAME_TAKEN', 'Username unavailable') from None
        return self.login(credentials)

    def login(self, credentials):
        validate('Credentials', credentials)
        now = self.clock()
        failure = False
        with self.db.transaction() as conn:
            limit = conn.execute('SELECT * FROM login_limits WHERE username=?', (credentials['username'],)).fetchone()
            if limit and now - limit['since'] < 300 and limit['attempts'] >= 10:
                raise PlatformError(429, 'LOGIN_THROTTLED', 'Try again later')
            user = conn.execute('SELECT * FROM users WHERE username=?', (credentials['username'],)).fetchone()
            stored = user['password_hash'] if user else self.dummy_hash
            candidate = password_hash(credentials['password'], stored.split(':')[0])
            if not hmac.compare_digest(candidate, stored) or not user:
                since = limit['since'] if limit and now - limit['since'] < 300 else now
                attempts = limit['attempts'] + 1 if limit and since == limit['since'] else 1
                conn.execute('INSERT OR REPLACE INTO login_limits VALUES(?,?,?)', (credentials['username'], attempts, since))
                failure = True
            else:
                conn.execute('DELETE FROM login_limits WHERE username=?', (credentials['username'],))
                token = secrets.token_urlsafe(32)
                expires = now + self.hours * 3600
                conn.execute('INSERT INTO sessions VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user['id'], expires))
        if failure:
            raise PlatformError(401, 'INVALID_CREDENTIALS', 'Invalid username or password')
        return {'user_id': user['id'], 'token': token, 'expires_at': datetime.fromtimestamp(expires, timezone.utc).isoformat()}

    def authenticate(self, token):
        with self.db.transaction() as conn:
            session = conn.execute('SELECT * FROM sessions WHERE token_hash=? AND expires>?', (hashlib.sha256(token.encode()).hexdigest(), self.clock())).fetchone()
        if not session:
            raise PlatformError(401, 'UNAUTHENTICATED', 'A valid bearer session is required')
        return session['user_id']

    def logout(self, token):
        with self.db.transaction() as conn:
            conn.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
