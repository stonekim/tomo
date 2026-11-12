import copy
from .errors import PlatformError


class RuleRegistry:
    def __init__(self):
        self.validators = {}

    def register(self, domain, validator):
        if domain not in ('game', 'plan') or domain in self.validators:
            raise ValueError('Invalid or duplicate domain registration')
        self.validators[domain] = validator

    def check(self, domain, old_state, proposed_state, event):
        validator = self.validators.get(domain)
        if validator is None:
            raise PlatformError(503, 'DOMAIN_UNAVAILABLE', 'Domain rules are not installed')
        validator(copy.deepcopy(old_state), copy.deepcopy(proposed_state), copy.deepcopy(event))
