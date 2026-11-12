"""Owner-scoped persistence. Every mutation validates before its atomic commit."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from tomo.contracts import validate
from .errors import PlatformError, missing
from .rules import RuleRegistry


def uid():
    return str(uuid.uuid4())


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Store:
    def __init__(self, db, rules=None):
        self.db, self.rules = db, rules or RuleRegistry()

    def _save(self, conn, owner, save_id, domain=None):
        row = conn.execute('SELECT * FROM saves WHERE id=? AND owner_id=?', (save_id, owner)).fetchone()
        if not row:
            raise missing()
        if domain and row['domain'] != domain:
            raise PlatformError(422, 'WRONG_DOMAIN', 'Operation does not belong to this save domain')
        return row

    def assert_owner(self, owner, save_id):
        with self.db.transaction() as conn:
            return dict(self._save(conn, owner, save_id))

    def _save_view(self, conn, row):
        branch = conn.execute('SELECT id FROM branches WHERE save_id=? AND parent_id IS NULL', (row['id'],)).fetchone()
        return {key: row[key] for key in ('id', 'domain', 'title', 'created_at')} | {'schema_version': 1, 'initial_state': json.loads(row['initial_state']), 'initial_branch_id': branch['id'] if branch else None}

    def create_save(self, owner, proposal):
        validate('SaveCreate', proposal)
        self.rules.check(proposal['domain'], None, proposal['state'], {'type': 'initialize'})
        with self.db.transaction() as conn:
            save_id = uid()
            conn.execute('INSERT INTO saves VALUES(?,?,?,?,?,?)', (save_id, owner, proposal['domain'], proposal['title'], encode(proposal['state']), timestamp()))
            if proposal['domain'] == 'game':
                conn.execute('INSERT INTO branches VALUES(?,?,?,?,?,?)', (uid(), save_id, None, 0, 0, encode(proposal['state'])))
            return self._save_view(conn, self._save(conn, owner, save_id))

    def list_saves(self, owner):
        with self.db.transaction() as conn:
            return [self._save_view(conn, row) for row in conn.execute('SELECT * FROM saves WHERE owner_id=? ORDER BY created_at,id', (owner,)).fetchall()]

    def get_save(self, owner, save_id):
        with self.db.transaction() as conn:
            return self._save_view(conn, self._save(conn, owner, save_id))

    def _branch(self, conn, owner, save_id, branch_id):
        self._save(conn, owner, save_id, 'game')
        row = conn.execute('SELECT * FROM branches WHERE id=? AND save_id=?', (branch_id, save_id)).fetchone()
        if not row:
            raise missing()
        return row

    def _event_view(self, row):
        return {key: row[key] for key in ('id', 'sequence', 'origin_branch_id', 'type', 'created_at')} | {key: json.loads(row[key]) for key in ('payload', 'state', 'causes')}

    def _branch_view(self, conn, row):
        events = [self._event_view(e) for e in conn.execute('SELECT * FROM events WHERE branch_id=? ORDER BY sequence', (row['id'],)).fetchall()]
        return {key: row[key] for key in ('id', 'save_id', 'parent_id', 'fork_sequence', 'revision')} | {'events': events, 'state': events[-1]['state'] if events else json.loads(row['initial_state'])}

    def get_branch(self, owner, save_id, branch_id):
        with self.db.transaction() as conn:
            return self._branch_view(conn, self._branch(conn, owner, save_id, branch_id))

    def list_branches(self, owner, save_id):
        with self.db.transaction() as conn:
            self._save(conn, owner, save_id, 'game')
            return [self._branch_view(conn, row) for row in conn.execute('SELECT * FROM branches WHERE save_id=? ORDER BY rowid', (save_id,)).fetchall()]

    def _replay(self, conn, owner, key, route, proposal):
        fingerprint = hashlib.sha256(encode([route, proposal]).encode()).hexdigest()
        row = conn.execute('SELECT * FROM idempotency WHERE owner_id=? AND key=?', (owner, key)).fetchone()
        if row and row['fingerprint'] != fingerprint:
            raise PlatformError(409, 'IDEMPOTENCY_CONFLICT', 'Key was used for a different request')
        return fingerprint, json.loads(row['response']) if row else None

    def _remember(self, conn, owner, key, fingerprint, response):
        conn.execute('INSERT INTO idempotency VALUES(?,?,?,?)', (owner, key, fingerprint, encode(response)))
        return response

    def append_event(self, owner, save_id, branch_id, proposal):
        validate('EventProposal', proposal)
        with self.db.transaction() as conn:
            branch = self._branch(conn, owner, save_id, branch_id)
            fingerprint, replay = self._replay(conn, owner, proposal['idempotency_key'], ['event', save_id, branch_id], proposal)
            if replay is not None:
                return replay
            if branch['revision'] != proposal['expected_revision']:
                raise PlatformError(409, 'REVISION_CONFLICT', 'Reload current branch before retrying')
            current = self._branch_view(conn, branch)
            known = {event['id'] for event in current['events']}
            if not set(proposal['causes']) <= known:
                raise PlatformError(422, 'INVALID_CAUSE', 'Causes must reference existing events in this branch')
            self.rules.check('game', current['state'], proposal['state'], proposal)
            sequence = branch['revision'] + 1
            conn.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)', (branch_id, sequence, uid(), branch_id, proposal['type'], encode(proposal['payload']), encode(proposal['state']), encode(proposal['causes']), timestamp()))
            conn.execute('UPDATE branches SET revision=? WHERE id=?', (sequence, branch_id))
            response = self._branch_view(conn, self._branch(conn, owner, save_id, branch_id))
            return self._remember(conn, owner, proposal['idempotency_key'], fingerprint, response)

    def fork(self, owner, save_id, branch_id, proposal):
        validate('Fork', proposal)
        with self.db.transaction() as conn:
            parent = self._branch(conn, owner, save_id, branch_id)
            fingerprint, replay = self._replay(conn, owner, proposal['idempotency_key'], ['fork', save_id, branch_id], proposal)
            if replay is not None:
                return replay
            at = proposal['at_sequence']
            if at > parent['revision']:
                raise PlatformError(422, 'INVALID_FORK', 'Fork must reference an existing sequence')
            child = uid()
            conn.execute('INSERT INTO branches VALUES(?,?,?,?,?,?)', (child, save_id, branch_id, at, at, parent['initial_state']))
            conn.execute('''INSERT INTO events SELECT ?,sequence,id,origin_branch_id,type,payload,state,causes,created_at FROM events WHERE branch_id=? AND sequence<=?''', (child, branch_id, at))
            response = self._branch_view(conn, self._branch(conn, owner, save_id, child))
            return self._remember(conn, owner, proposal['idempotency_key'], fingerprint, response)

    def _version_view(self, row):
        return {key: row[key] for key in ('id', 'save_id', 'revision', 'previous_id', 'kind', 'based_on', 'created_at')} | {'content': json.loads(row['content'])}

    def list_versions(self, owner, save_id):
        with self.db.transaction() as conn:
            self._save(conn, owner, save_id, 'plan')
            return [self._version_view(row) for row in conn.execute('SELECT * FROM plan_versions WHERE save_id=? ORDER BY revision', (save_id,)).fetchall()]

    def append_version(self, owner, save_id, proposal):
        validate('VersionProposal', proposal)
        with self.db.transaction() as conn:
            save = self._save(conn, owner, save_id, 'plan')
            fingerprint, replay = self._replay(conn, owner, proposal['idempotency_key'], ['version', save_id], proposal)
            if replay is not None:
                return replay
            last = conn.execute('SELECT * FROM plan_versions WHERE save_id=? ORDER BY revision DESC LIMIT 1', (save_id,)).fetchone()
            revision = last['revision'] if last else 0
            if revision != proposal['expected_revision']:
                raise PlatformError(409, 'REVISION_CONFLICT', 'Reload current plan before retrying')
            if proposal['kind'] == 'outcome':
                judgment = conn.execute("SELECT * FROM plan_versions WHERE id=? AND save_id=? AND kind='judgment'", (proposal['based_on'], save_id)).fetchone()
                if not judgment:
                    raise PlatformError(422, 'INVALID_JUDGMENT_REFERENCE', 'Outcome must reference a judgment in this plan')
            elif proposal['based_on'] is not None:
                raise PlatformError(422, 'INVALID_JUDGMENT_REFERENCE', 'Only outcomes may specify based_on')
            if not last and proposal['kind'] != 'judgment':
                raise PlatformError(422, 'JUDGMENT_REQUIRED', 'First version must be a judgment')
            previous = json.loads(last['content']) if last else json.loads(save['initial_state'])
            self.rules.check('plan', previous, proposal['content'], proposal)
            version_id = uid()
            conn.execute('INSERT INTO plan_versions VALUES(?,?,?,?,?,?,?,?)', (version_id, save_id, revision + 1, last['id'] if last else None, proposal['kind'], encode(proposal['content']), proposal['based_on'], timestamp()))
            response = self._version_view(conn.execute('SELECT * FROM plan_versions WHERE id=?', (version_id,)).fetchone())
            return self._remember(conn, owner, proposal['idempotency_key'], fingerprint, response)

    def begin_audit(self, owner, save_id, purpose, mode, model, attempt):
        audit_id = uid()
        usage = dict.fromkeys(('input_tokens', 'output_tokens', 'cached_input_tokens', 'cost', 'currency'))
        with self.db.transaction() as conn:
            self._save(conn, owner, save_id)
            conn.execute('INSERT INTO model_audit VALUES(?,?,?,?,?,?,?,?,?,?)', (audit_id, owner, save_id, purpose, mode, model, attempt, 'pending', encode(usage), timestamp()))
        return audit_id

    def finish_audit(self, owner, audit_id, status, usage):
        validate('Usage', usage)
        with self.db.transaction() as conn:
            conn.execute('UPDATE model_audit SET status=?,usage=? WHERE id=? AND owner_id=?', (status, encode(usage), audit_id, owner))

    def list_audit(self, owner, save_id):
        with self.db.transaction() as conn:
            self._save(conn, owner, save_id)
            return [{key: row[key] for key in ('id', 'save_id', 'purpose', 'mode', 'model', 'attempt', 'status', 'created_at')} | {'usage': json.loads(row['usage'])} for row in conn.execute('SELECT * FROM model_audit WHERE owner_id=? AND save_id=? ORDER BY rowid', (owner, save_id)).fetchall()]
