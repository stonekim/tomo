"""Frozen shared JSON contracts."""
import json
from importlib.resources import files
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA = json.loads(files(__package__).joinpath('v1.json').read_text())

def validate(name, value):
    schema = {"$ref": f"#/$defs/{name}", "$defs": SCHEMA["$defs"]}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
