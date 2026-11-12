"""Explicit server-only configuration; never reads credential files."""
import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    database: str = './data/tomo.sqlite3'
    session_hours: int = 24
    allowed_origins: tuple[str, ...] = ()
    model_mode: str = 'disabled'
    model_endpoint: str = ''
    model_name: str = ''
    model_api_key: str = ''
    model_timeout: float = 20
    model_attempts: int = 2
    model_max_output_tokens: int = 1200
    model_daily_calls: int = 200
    model_user_daily_calls: int = 20
    model_concurrency: int = 2
    model_cost_field: str = 'cost'
    model_currency_field: str = 'currency'

    def __post_init__(self):
        if not 1 <= self.session_hours <= 168:
            raise ValueError('Session lifetime must be 1–168 hours')
        if self.model_mode not in ('disabled', 'mock', 'real'):
            raise ValueError('Invalid model mode')
        if not 1 <= self.model_attempts <= 3 or not 0 < self.model_timeout <= 120:
            raise ValueError('Invalid model retry/timeout bounds')
        if not 1 <= self.model_max_output_tokens <= 4096 or not 1 <= self.model_daily_calls <= 10000 or not 1 <= self.model_user_daily_calls <= self.model_daily_calls or not 1 <= self.model_concurrency <= 8:
            raise ValueError('Invalid provider runtime limits')
        for field in (self.model_cost_field, self.model_currency_field):
            if len(field) > 80 or (field and not field.replace('_','').isalnum()):
                raise ValueError('Invalid reported usage field mapping')
        for origin in self.allowed_origins:
            url = urlsplit(origin)
            if url.scheme not in ('http', 'https') or not url.netloc or url.path or url.query or url.fragment or url.username:
                raise ValueError('Origins must be explicit scheme://host[:port] values')
        if self.model_mode == 'real':
            url = urlsplit(self.model_endpoint)
            if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError('Real provider requires a fixed HTTPS endpoint without credentials/query')
            if not self.model_name or not self.model_api_key:
                raise ValueError('Real provider requires model name and server API key')

    @classmethod
    def from_env(cls):
        return cls(
            database=os.environ.get('TOMO_DATABASE', './data/tomo.sqlite3'),
            session_hours=int(os.environ.get('TOMO_SESSION_HOURS', '24')),
            allowed_origins=tuple(x.strip() for x in os.environ.get('TOMO_ALLOWED_ORIGINS', '').split(',') if x.strip()),
            model_mode=os.environ.get('TOMO_MODEL_MODE', 'disabled'),
            model_endpoint=os.environ.get('TOMO_MODEL_ENDPOINT', ''),
            model_name=os.environ.get('TOMO_MODEL_NAME', ''),
            model_api_key=os.environ.get('TOMO_MODEL_API_KEY', ''),
            model_timeout=float(os.environ.get('TOMO_MODEL_TIMEOUT', '20')),
            model_attempts=int(os.environ.get('TOMO_MODEL_ATTEMPTS', '2')),
            model_max_output_tokens=int(os.environ.get('TOMO_MODEL_MAX_OUTPUT_TOKENS', '1200')),
            model_daily_calls=int(os.environ.get('TOMO_MODEL_DAILY_CALLS', '200')),
            model_user_daily_calls=int(os.environ.get('TOMO_MODEL_USER_DAILY_CALLS', '20')),
            model_concurrency=int(os.environ.get('TOMO_MODEL_CONCURRENCY', '2')),
            model_cost_field=os.environ.get('TOMO_MODEL_COST_FIELD','cost'),
            model_currency_field=os.environ.get('TOMO_MODEL_CURRENCY_FIELD','currency'),
        )
