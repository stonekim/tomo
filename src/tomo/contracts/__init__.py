"""Frozen shared JSON contracts."""
import json
from importlib.resources import files
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

SCHEMA = json.loads(files(__package__).joinpath('v1.json').read_text())

def validate(name, value):
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ValidationError('Only finite JSON values are allowed') from exc
    schema = {"$ref": f"#/$defs/{name}", "$defs": SCHEMA["$defs"]}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
