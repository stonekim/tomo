"""Local entry points without side effects at import time."""
import argparse
import json
import tempfile
from pathlib import Path
from jsonschema import Draft202012Validator
from tomo.contracts import SCHEMA
from .api import create_app
from .config import Settings
from .db import Database


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('migrate')
    serve = sub.add_parser('serve')
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8000)
    contracts = sub.add_parser('contracts')
    contracts.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.command == 'migrate':
        Database(Settings.from_env().database)
        print('Database migrated to version 2')
    elif args.command == 'serve':
        import uvicorn
        uvicorn.run(create_app(), host=args.host, port=args.port)
    else:
        Draft202012Validator.check_schema(SCHEMA)
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Settings(database=str(Path(directory) / 'contracts.sqlite3')))
            generated = json.dumps(app.openapi(), indent=2, sort_keys=True) + '\n'
        path = Path('docs/contracts/openapi.json')
        if args.check:
            if path.read_text() != generated:
                raise SystemExit('OpenAPI drift: run contracts and review diff')
            print('Contract v1 schema and OpenAPI match')
        else:
            path.write_text(generated)
            print(f'Generated {path}')


if __name__ == '__main__':
    main()
