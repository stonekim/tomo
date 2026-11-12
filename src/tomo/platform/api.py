from fastapi import Body, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jsonschema import ValidationError
from starlette.exceptions import HTTPException
from tomo.contracts import SCHEMA
from .auth import Auth
from .config import Settings
from .db import Database
from .errors import PlatformError
from .models import HttpAdapter, MockAdapter, ModelService
from .store import Store

bearer = HTTPBearer(auto_error=False)


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials or credentials.scheme.lower() != 'bearer':
        raise PlatformError(401, 'UNAUTHENTICATED', 'A valid bearer session is required')
    return request.app.state.auth.authenticate(credentials.credentials)


def create_app(settings=None, *, rule_registry=None, domain_routers=()):
    settings = settings or Settings.from_env()
    app = FastAPI(title='Tomo shared foundation', version='1.0.0', docs_url='/docs', redoc_url=None)
    db = Database(settings.database)
    app.state.auth = Auth(db, settings.session_hours)
    app.state.store = Store(db, rule_registry)
    adapter = MockAdapter() if settings.model_mode == 'mock' else HttpAdapter(settings) if settings.model_mode == 'real' else None
    app.state.models = ModelService(app.state.store, adapter, settings.model_attempts)
    if settings.allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_credentials=False,
                           allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type'])

    def error(status, code, message):
        return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message}})

    @app.exception_handler(PlatformError)
    async def platform_error(request, exc):
        return error(exc.status, exc.code, exc.message)

    @app.exception_handler(ValidationError)
    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Never echo input, which could contain passwords or private prompt context.
        return error(422, 'INVALID_REQUEST', 'Request does not satisfy contract v1')

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(exc.status_code, 'HTTP_ERROR', 'Request cannot be served')

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return error(500, 'INTERNAL_ERROR', 'Internal service error')

    @app.middleware('http')
    async def boundaries(request, call_next):
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > 262_144:
                return error(413, 'REQUEST_TOO_LARGE', 'Request limit is 256 KiB')
            chunks.append(chunk)
        request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/healthz', operation_id='health')
    def health():
        with db.transaction() as conn:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
        return {'status': 'ok', 'contract_version': 1, 'database_version': version}

    @app.post('/api/v1/auth/register', status_code=201, operation_id='register')
    def register(body: dict = Body(...)):
        return app.state.auth.register(body)

    @app.post('/api/v1/auth/login', operation_id='login')
    def login(body: dict = Body(...)):
        return app.state.auth.login(body)

    @app.post('/api/v1/auth/logout', status_code=204, operation_id='logout')
    def logout(owner=Depends(current_user), credentials=Depends(bearer)):
        app.state.auth.logout(credentials.credentials)
        return Response(status_code=204)

    @app.get('/api/v1/me', operation_id='me')
    def me(owner=Depends(current_user)):
        return {'user_id': owner}

    @app.post('/api/v1/saves', status_code=201, operation_id='create_save')
    def create_save(body: dict = Body(...), owner=Depends(current_user)):
        return app.state.store.create_save(owner, body)

    @app.get('/api/v1/saves', operation_id='list_saves')
    def list_saves(owner=Depends(current_user)):
        return app.state.store.list_saves(owner)

    @app.get('/api/v1/saves/{save_id}', operation_id='get_save')
    def get_save(save_id: str, owner=Depends(current_user)):
        return app.state.store.get_save(owner, save_id)

    @app.get('/api/v1/saves/{save_id}/branches', operation_id='list_branches')
    def list_branches(save_id: str, owner=Depends(current_user)):
        return app.state.store.list_branches(owner, save_id)

    @app.get('/api/v1/saves/{save_id}/branches/{branch_id}', operation_id='get_branch')
    def get_branch(save_id: str, branch_id: str, owner=Depends(current_user)):
        return app.state.store.get_branch(owner, save_id, branch_id)

    @app.post('/api/v1/saves/{save_id}/branches/{branch_id}/events', operation_id='append_event')
    def append_event(save_id: str, branch_id: str, body: dict = Body(...), owner=Depends(current_user)):
        return app.state.store.append_event(owner, save_id, branch_id, body)

    @app.post('/api/v1/saves/{save_id}/branches/{branch_id}/forks', status_code=201, operation_id='fork')
    def fork(save_id: str, branch_id: str, body: dict = Body(...), owner=Depends(current_user)):
        return app.state.store.fork(owner, save_id, branch_id, body)

    @app.get('/api/v1/saves/{save_id}/versions', operation_id='list_versions')
    def list_versions(save_id: str, owner=Depends(current_user)):
        return app.state.store.list_versions(owner, save_id)

    @app.post('/api/v1/saves/{save_id}/versions', status_code=201, operation_id='append_version')
    def append_version(save_id: str, body: dict = Body(...), owner=Depends(current_user)):
        return app.state.store.append_version(owner, save_id, body)

    @app.get('/api/v1/saves/{save_id}/usage', operation_id='list_audit')
    def list_audit(save_id: str, owner=Depends(current_user)):
        return app.state.store.list_audit(owner, save_id)

    for router in domain_routers:
        app.include_router(router)

    contracts = {
        'register': ('Credentials', 'Session'), 'login': ('Credentials', 'Session'),
        'create_save': ('SaveCreate', 'Save'), 'get_save': (None, 'Save'), 'list_saves': (None, ['Save']),
        'get_branch': (None, 'Branch'), 'list_branches': (None, ['Branch']),
        'append_event': ('EventProposal', 'Branch'), 'fork': ('Fork', 'Branch'),
        'append_version': ('VersionProposal', 'PlanVersion'), 'list_versions': (None, ['PlanVersion']),
        'list_audit': (None, ['Audit']),
    }

    def contract_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        import json
        document = get_openapi(title=app.title, version=app.version, routes=app.routes)
        definitions = json.loads(json.dumps(SCHEMA['$defs']).replace('#/$defs/', '#/components/schemas/'))
        document.setdefault('components', {}).setdefault('schemas', {}).update(definitions)
        for path in document['paths'].values():
            for operation in path.values():
                if not isinstance(operation, dict) or 'operationId' not in operation:
                    continue
                pair = contracts.get(operation['operationId'])
                if pair:
                    request_name, response_name = pair
                    if request_name:
                        operation['requestBody'] = {'required': True, 'content': {'application/json': {'schema': {'$ref': f'#/components/schemas/{request_name}'}}}}
                    response_schema = {'type': 'array', 'items': {'$ref': f'#/components/schemas/{response_name[0]}'}} if isinstance(response_name, list) else {'$ref': f'#/components/schemas/{response_name}'}
                    status = '201' if operation['operationId'] in ('register', 'create_save', 'fork', 'append_version') else '200'
                    operation['responses'][status]['content'] = {'application/json': {'schema': response_schema}}
                for status in ('401', '404', '409', '413', '422', '429', '503'):
                    operation['responses'][status] = {'description': 'Shared error; see ADR-0002', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Error'}}}}
        app.openapi_schema = document
        return document

    app.openapi = contract_openapi
    return app
