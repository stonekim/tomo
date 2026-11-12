"""Server-side model adapters. Persist usage on every bounded attempt."""
import time
import threading
import math
import re
from dataclasses import dataclass
import httpx
from .errors import PlatformError


UNKNOWN_USAGE = dict.fromkeys(('input_tokens', 'output_tokens', 'cached_input_tokens', 'cost', 'currency'))


@dataclass(frozen=True)
class ModelResult:
    text: str
    usage: dict


class ProviderFailure(Exception):
    def __init__(self, status, retryable, usage=None):
        self.status, self.retryable = status, retryable
        self.usage = usage or UNKNOWN_USAGE.copy()
        super().__init__(status)


def usage_from_response(body, cost_field='cost', currency_field='currency'):
    usage = body.get('usage')
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get('prompt_tokens_details')
    details = details if isinstance(details, dict) else {}

    def count(value):
        return value if type(value) is int and value >= 0 else None

    # Only explicitly reported, finite amounts and currency codes are preserved.
    cost = usage.get(cost_field) if cost_field else None
    currency = usage.get(currency_field) if currency_field else None
    cost = cost if type(cost) in (int,float) and math.isfinite(cost) and cost >= 0 else None
    currency = currency if isinstance(currency,str) and re.fullmatch('[A-Z]{3}',currency) else None
    # Token usage must never be inferred from text length.
    return {'input_tokens': count(usage.get('prompt_tokens')),
            'output_tokens': count(usage.get('completion_tokens')),
            'cached_input_tokens': count(details.get('cached_tokens')),
            'cost': cost, 'currency': currency}


def structured_json(text):
    """Accept raw JSON or one exact JSON fence; never scrape JSON from prose."""
    import json
    text=text.strip()
    fenced=re.fullmatch(r'```(?:json)?\s*(.*?)\s*```',text,flags=re.S|re.I)
    if fenced:text=fenced.group(1)
    value=json.loads(text)
    json.dumps(value,allow_nan=False)
    return value


class MockAdapter:
    mode, name = 'mock', 'deterministic-mock-v1'

    def complete(self, messages):
        return ModelResult('Mock response: no real model was called.', UNKNOWN_USAGE.copy())


class HttpAdapter:
    mode = 'real'

    def __init__(self, settings, transport=None):
        self.settings, self.name, self.transport = settings, settings.model_name, transport

    def complete(self, messages):
        try:
            with httpx.Client(timeout=self.settings.model_timeout, transport=self.transport, follow_redirects=False, trust_env=False) as client:
                with client.stream('POST', self.settings.model_endpoint,
                                   headers={'Authorization': f'Bearer {self.settings.model_api_key}'},
                                   json={'model': self.name, 'messages': messages, 'stream': False, 'max_tokens': self.settings.model_max_output_tokens}) as response:
                    status = response.status_code
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 2_000_000:
                            raise ProviderFailure('invalid_response', False)
            import json
            try:
                body = json.loads(data)
            except (ValueError, UnicodeError):
                raise ProviderFailure('rate_limited' if status == 429 else 'provider_error' if status != 200 else 'invalid_response', status == 429 or status >= 500) from None
            if not isinstance(body, dict):
                raise ProviderFailure('invalid_response', False)
            usage = usage_from_response(body, self.settings.model_cost_field, self.settings.model_currency_field)
            if status == 429:
                raise ProviderFailure('rate_limited', True, usage)
            if status >= 500:
                raise ProviderFailure('provider_error', True, usage)
            if status != 200:
                raise ProviderFailure('provider_error', False, usage)
            try:
                text = body['choices'][0]['message']['content']
                if not isinstance(text, str):
                    raise TypeError
            except (KeyError, IndexError, TypeError):
                raise ProviderFailure('invalid_response', False, usage) from None
            return ModelResult(text, usage)
        except httpx.TimeoutException:
            raise ProviderFailure('timeout', True) from None
        except httpx.TransportError:
            raise ProviderFailure('transport', True) from None


class ModelService:
    def __init__(self, store, adapter=None, attempts=2, sleeper=time.sleep, *, limits=(200, 20), concurrency=2):
        self.store, self.adapter, self.attempts, self.sleeper = store, adapter, attempts, sleeper
        self.limits = limits
        self.semaphore = threading.BoundedSemaphore(concurrency)
        if not 1 <= attempts <= 3:
            raise ValueError('Model attempts must be 1–3')

    def generate(self, owner, save_id, purpose, messages):
        self.store.assert_owner(owner, save_id)
        if not self.semaphore.acquire(blocking=False):
            raise PlatformError(429, 'MODEL_BUSY', 'Model concurrency limit reached; retry later')
        try:
            return self._generate(owner, save_id, purpose, messages)
        finally:
            self.semaphore.release()

    def _generate(self, owner, save_id, purpose, messages):
        self.store.assert_owner(owner, save_id)
        if not self.adapter:
            raise PlatformError(503, 'MODEL_DISABLED', 'No model provider configured')
        if not isinstance(purpose, str) or not 1 <= len(purpose) <= 200:
            raise PlatformError(422, 'INVALID_MODEL_REQUEST', 'Purpose required')
        if not isinstance(messages, list) or not messages or len(messages) > 100:
            raise PlatformError(422, 'INVALID_MODEL_REQUEST', 'Messages required')
        total = 0
        for message in messages:
            if not isinstance(message, dict) or set(message) != {'role', 'content'} or message['role'] not in ('system', 'user', 'assistant') or not isinstance(message['content'], str):
                raise PlatformError(422, 'INVALID_MODEL_REQUEST', 'Invalid message')
            total += len(message['content'])
        if total > 32_000:
            raise PlatformError(422, 'INVALID_MODEL_REQUEST', 'Model context too large')
        for attempt in range(1, self.attempts + 1):
            audit_id = self.store.begin_audit(owner, save_id, purpose, self.adapter.mode, self.adapter.name, attempt, limits=self.limits)
            try:
                result = self.adapter.complete(messages)
            except ProviderFailure as failure:
                self.store.finish_audit(owner, audit_id, failure.status, failure.usage)
                if failure.retryable and attempt < self.attempts:
                    self.sleeper(0.1 * 2 ** (attempt - 1))
                    continue
                raise PlatformError(503, 'MODEL_UNAVAILABLE', 'Model call failed; see usage audit') from None
            self.store.finish_audit(owner, audit_id, 'ok', result.usage)
            return result
