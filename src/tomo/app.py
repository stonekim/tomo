"""Composed product factory: one identity/store, distinct validated domains, same-origin UI."""
from pathlib import Path
import os
from fastapi.staticfiles import StaticFiles
from tomo.limits import RequestSizeLimit
from tomo.platform.api import create_app
from tomo.platform.config import Settings
from tomo.platform.rules import RuleRegistry
from tomo.game import router as game_router, register_game_rules
from tomo.plans import create_router, validate_plan


def create_product_app(settings=None):
    registry = RuleRegistry()
    register_game_rules(registry)
    registry.register('plan', validate_plan)
    app = create_app(settings or Settings.from_env(), rule_registry=registry,
                     domain_routers=[game_router, create_router()])

    @app.middleware('http')
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    maximum=int(os.environ.get('TOMO_MAX_REQUEST_BYTES','524288'))
    if not 16384 <= maximum <= 2000000:
        raise ValueError('TOMO_MAX_REQUEST_BYTES must be between 16384 and 2000000')
    app.add_middleware(RequestSizeLimit, maximum=maximum)
    web = Path(os.environ.get('TOMO_WEB_ROOT', str(Path(__file__).resolve().parents[2] / 'web')))
    app.mount('/', StaticFiles(directory=web, html=True), name='product-web')
    return app
