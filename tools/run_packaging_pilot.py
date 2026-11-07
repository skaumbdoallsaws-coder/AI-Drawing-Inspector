"""Run only the isolated packaging workspace; never loads desktop layouts or .env."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def create_app(storage=None, rating=None, library_root=None):
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import RedirectResponse
    from ai_inspector.facility_layout.authorization import local_facility_principal
    from ai_inspector.packaging_shipping.api import create_router
    from ai_inspector.packaging_shipping.service import PackagingService
    from ai_inspector.packaging_shipping.credentials import EasyPostCredentialStore, carrier_owner
    app = FastAPI(title="InspectorPro Packaging Pilot")
    service = PackagingService(storage or ROOT / ".runtime" / "packaging-pilot")
    stores = {}
    def account(principal):
        identity = carrier_owner(principal)
        if identity not in stores:
            stores[identity] = EasyPostCredentialStore(service.root / "carrier-credentials", identity, enabled=True)
        return stores[identity]
    app.include_router(create_router(service, principal_resolver=lambda request: local_facility_principal(site_id="packaging-pilot"), static_root=ROOT / "static", rating=rating, credential_factory=None if rating else account, library_root=library_root))
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.get("/")
    def home():
        return RedirectResponse("/packaging")
    return app


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8179)
    parser.add_argument("--storage", type=Path, default=ROOT / ".runtime" / "packaging-pilot")
    parser.add_argument("--library", type=Path, default=None, help="Inspection library folder to offer (read-only)")
    args = parser.parse_args()
    uvicorn.run(create_app(args.storage, library_root=args.library), host="127.0.0.1", port=args.port, access_log=False)
