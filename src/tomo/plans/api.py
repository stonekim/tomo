from fastapi import APIRouter, Body, Depends, Request
from tomo.platform.api import current_user, create_app
from tomo.platform.rules import RuleRegistry
from .rules import validate_plan
from .service import PlanService, CreateInput, VersionInput, OutcomeInput


def create_router(clock=None):
    router = APIRouter(prefix='/api/v1/plans', tags=['Real plans'])

    def service(request):
        return PlanService(request.app.state.store, request.app.state.models, clock)

    @router.get('')
    def list_plans(request: Request, owner=Depends(current_user)):
        return service(request).list(owner)

    @router.post('', status_code=201)
    def create_plan(request: Request, body: CreateInput, owner=Depends(current_user)):
        return service(request).create(owner, body)

    @router.get('/{save_id}')
    def get_plan(save_id: str, request: Request, owner=Depends(current_user)):
        return service(request).detail(owner, save_id)

    @router.post('/{save_id}/versions', status_code=201)
    def update_plan(save_id: str, request: Request, body: VersionInput, owner=Depends(current_user)):
        return service(request).update(owner, save_id, body)

    @router.post('/{save_id}/outcomes', status_code=201)
    def record_outcome(save_id: str, request: Request, body: OutcomeInput, owner=Depends(current_user)):
        return service(request).outcome(owner, save_id, body)

    @router.get('/{save_id}/review')
    def review(save_id: str, request: Request, owner=Depends(current_user)):
        return service(request).detail(owner, save_id)['review']

    @router.post('/{save_id}/suggestions')
    def suggestions(save_id: str, request: Request, owner=Depends(current_user)):
        return service(request).suggest(owner, save_id)

    return router


def create_plan_app(settings=None, *, clock=None):
    """Standalone plan app; integration registers validate_plan on its combined registry."""
    rules = RuleRegistry()
    rules.register('plan', validate_plan)
    return create_app(settings, rule_registry=rules, domain_routers=[create_router(clock)])
