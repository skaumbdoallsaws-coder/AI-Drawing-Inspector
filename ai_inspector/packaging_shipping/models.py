"""Closed, SI-unit contracts shared by manual editing and Sage."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

Scalar = Annotated[float, Field(ge=0, le=10000, allow_inf_nan=False, strict=True)]
Length = Annotated[float, Field(gt=0, le=5, allow_inf_nan=False, strict=True)]
Dimensions = tuple[Length, Length, Length]
Position = tuple[Scalar, Scalar, Scalar]
Identity = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")]
Text = Annotated[str, Field(min_length=1, max_length=160)]
Orientation = Annotated[int, Field(ge=0, le=5, strict=True)]
Fraction = Annotated[float, Field(ge=0, le=1, strict=True)]
Color = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


class Appearance(Closed):
    color: Color = "#9BA1A6"
    roughness: Fraction = 0.55
    metalness: Fraction = 0.0
    opacity: Annotated[float, Field(gt=0, le=1, strict=True)] = 1.0


class MaterialDensity(Closed):
    name: Text
    density_kg_m3: Annotated[float, Field(gt=0, le=25000, strict=True)]
    evidence: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def documented(self):
        if not self.evidence.strip():
            raise ValueError("Record the source of the physical density.")
        return self


class MassCalculation(Closed):
    volume_m3: Annotated[float, Field(gt=0, le=125, strict=True)]
    material: MaterialDensity
    exclusions: Annotated[str, Field(max_length=500)] = ""


class Product(Closed):
    name: Text
    dimensions_m: Dimensions
    mass_kg: Annotated[float, Field(gt=0, le=1000, strict=True)] | None = None
    mass_basis: Literal["unknown", "user_measured", "cad", "estimate"] = "unknown"
    mass_evidence: Annotated[str, Field(max_length=500)] = ""
    source_id: Identity | None = None
    source_revision: Annotated[str, Field(max_length=128)] = ""
    mass_calculation: MassCalculation | None = None
    appearance: Appearance | None = None

    @model_validator(mode="after")
    def evidence(self):
        if (self.mass_kg is None) != (self.mass_basis == "unknown"):
            raise ValueError("Mass and its provenance must be supplied together.")
        if self.mass_kg is not None and not self.mass_evidence.strip():
            raise ValueError("Record the source of the mass, including estimates.")
        if self.mass_calculation is not None:
            calculated = self.mass_calculation.volume_m3 * self.mass_calculation.material.density_kg_m3
            if self.mass_basis != "estimate" or self.mass_kg is None or abs(self.mass_kg - calculated) > max(1e-9, calculated * 1e-8):
                raise ValueError("Density-based mass must match the documented calculation and remain an estimate.")
        return self


class BoardBlank(Closed):
    dimensions_m: tuple[Length, Length]
    quantity: Annotated[int, Field(ge=1, le=20, strict=True)] = 1
    mass_per_area_kg_m2: Annotated[float, Field(gt=0, le=25, strict=True)]
    evidence: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def documented(self):
        if not self.evidence.strip():
            raise ValueError("Record the board basis weight and the full blank, including flaps and overlaps.")
        return self


class Carton(Closed):
    name: Text
    inner_m: Dimensions
    outer_m: Dimensions
    tare_kg: Annotated[float, Field(ge=0, le=100, strict=True)] | None = None
    tare_evidence: Annotated[str, Field(max_length=500)] = ""
    cost_usd: Annotated[float, Field(ge=0, le=10000, strict=True)] | None = None
    max_payload_kg: Annotated[float, Field(gt=0, le=1000, strict=True)] | None = None
    supplier: Annotated[str, Field(max_length=160)] = ""
    sku: Annotated[str, Field(max_length=160)] = ""
    source_url: Annotated[str, Field(max_length=500)] = ""
    board_blank: BoardBlank | None = None
    appearance: Appearance | None = None

    @model_validator(mode="after")
    def dimensions(self):
        if self.source_url:
            try:
                url = urlsplit(self.source_url)
                if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or any(ord(c) < 33 for c in self.source_url):
                    raise ValueError()
            except ValueError:
                raise ValueError("Supplier source must be a public HTTP(S) URL without credentials.") from None
        if any(o <= i for i, o in zip(self.inner_m, self.outer_m)):
            raise ValueError("External dimensions must exceed internal dimensions on every axis.")
        if self.tare_kg is not None and not self.tare_evidence.strip():
            raise ValueError("Record the source of the empty-carton weight.")
        if self.board_blank:
            b = self.board_blank
            calculated = b.dimensions_m[0] * b.dimensions_m[1] * b.quantity * b.mass_per_area_kg_m2
            if self.tare_kg is None or abs(self.tare_kg - calculated) > max(1e-9, calculated * 1e-8):
                raise ValueError("Carton tare must match the full-blank area calculation.")
        return self


class Placement(Closed):
    id: Identity
    position_m: Position
    orientation: Orientation = 0


class Pocket(Closed):
    id: Identity
    shape: Literal["rectangular", "cylindrical"] = "rectangular"
    dimensions_m: Dimensions
    position_m: Position

    @model_validator(mode="after")
    def circular(self):
        if self.shape == "cylindrical" and abs(self.dimensions_m[0] - self.dimensions_m[2]) > 1e-9:
            raise ValueError("A vertical cylindrical pocket needs equal X and Z diameters.")
        return self


class Insert(Closed):
    id: Identity
    name: Text
    dimensions_m: Dimensions
    position_m: Position
    material: Text = "Foam"
    density_kg_m3: Annotated[float, Field(gt=0, le=25000, strict=True)]
    material_evidence: Annotated[str, Field(min_length=1, max_length=500)]
    cost_usd: Annotated[float, Field(ge=0, le=10000, strict=True)] | None = None
    pockets: Annotated[list[Pocket], Field(max_length=16)] = Field(default_factory=list)
    minimum_wall_m: Annotated[float, Field(ge=0.001, le=0.2, strict=True)] = 0.005
    minimum_floor_m: Annotated[float, Field(ge=0, le=0.2, strict=True)] = 0.005
    appearance: Appearance | None = None

    @model_validator(mode="after")
    def evidence(self):
        if not self.material_evidence.strip():
            raise ValueError("Record the source of the insert material density.")
        if len({p.id for p in self.pockets}) != len(self.pockets):
            raise ValueError("Pocket IDs must be unique within an insert.")
        return self


class SurfaceGraphic(Closed):
    id: Identity
    target: Literal["carton", "insert"] = "carton"
    target_id: Identity | None = None
    face: Literal["x-", "x+", "y-", "y+", "z-", "z+"] = "y+"
    kind: Literal["text", "image"] = "text"
    text: Annotated[str, Field(max_length=500)] = ""
    image_id: Identity | None = None
    color: Color = "#17191C"
    u: Fraction = 0.5
    v: Fraction = 0.5
    width_fraction: Annotated[float, Field(gt=0, le=1, strict=True)] = 0.7
    height_fraction: Annotated[float, Field(gt=0, le=1, strict=True)] = 0.3
    rotation_degrees: Literal[0, 90, 180, 270] = 0

    @model_validator(mode="after")
    def content(self):
        if (self.target == "insert") != (self.target_id is not None):
            raise ValueError("Select an insert ID only for an insert graphic.")
        if self.kind == "text" and (not self.text.strip() or self.image_id is not None):
            raise ValueError("Text graphics require lettering and no image ID.")
        if self.kind == "image" and (not self.image_id or self.text):
            raise ValueError("Image graphics require a scoped imported image and no text.")
        if (self.u - self.width_fraction / 2 < -1e-9 or self.u + self.width_fraction / 2 > 1 + 1e-9
                or self.v - self.height_fraction / 2 < -1e-9 or self.v + self.height_fraction / 2 > 1 + 1e-9):
            raise ValueError("Keep the graphic's proportional fit region within its target face.")
        return self


class Package(Closed):
    id: Identity
    carton: Carton
    placements: Annotated[list[Placement], Field(max_length=48)] = Field(default_factory=list)
    inserts: Annotated[list[Insert], Field(max_length=32)] = Field(default_factory=list)
    allowance_kg: Annotated[float, Field(ge=0, le=20, strict=True)] | None = None
    allowance_evidence: Annotated[str, Field(max_length=500)] = ""
    graphics: Annotated[list[SurfaceGraphic], Field(max_length=16)] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique(self):
        ids = [x.id for x in self.placements] + [x.id for x in self.inserts]
        if len(ids) != len(set(ids)):
            raise ValueError("Component IDs must be unique within a package.")
        if len({g.id for g in self.graphics}) != len(self.graphics):
            raise ValueError("Graphic IDs must be unique within a package.")
        if any(g.target == "insert" and g.target_id not in {i.id for i in self.inserts} for g in self.graphics):
            raise ValueError("An insert graphic must refer to an existing insert in this carton.")
        if self.allowance_kg is not None and not self.allowance_evidence.strip():
            raise ValueError("Record what the packing allowance includes, even when zero.")
        return self


class CushionRequirement(Closed):
    """Minimum insert material between every product envelope and each carton wall.

    Measured along each axis from the product face to the wall; any valid insert counts
    as material. This is a geometric requirement, not a cushioning-performance rating.
    `material` is the foam a proposal uses when it rebuilds the lining.
    """
    floor_m: Annotated[float, Field(ge=0, le=0.2, strict=True)] = 0.0
    top_m: Annotated[float, Field(ge=0, le=0.2, strict=True)] = 0.0
    sides_m: Annotated[float, Field(ge=0, le=0.2, strict=True)] = 0.0
    material: MaterialDensity
    evidence: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def meaningful(self):
        if not self.evidence.strip():
            raise ValueError("Record why these cushioning thicknesses are required.")
        if max(self.floor_m, self.top_m, self.sides_m) <= 0:
            raise ValueError("Set at least one cushioning thickness, or remove the requirement.")
        return self


class AllowanceRule(Closed):
    """Packing allowance a proposal assigns to every package it builds."""
    allowance_kg: Annotated[float, Field(ge=0, le=20, strict=True)]
    evidence: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def documented(self):
        if not self.evidence.strip():
            raise ValueError("Record what the per-package allowance includes, even when zero.")
        return self


FaceName = Literal["x_min", "x_max", "y_min", "y_max", "z_min", "z_max"]
FaceOffset = Annotated[float, Field(ge=0, le=5, allow_inf_nan=False, strict=True)]


class FaceArea(Closed):
    """Rectangle on a product face, in metres from the face's low corner.

    u_m and v_m run along the face's two other product axes in X, Y, Z order:
    Y and Z for an X face, X and Z for a Y face, X and Y for a Z face.
    """
    u_m: tuple[FaceOffset, FaceOffset]
    v_m: tuple[FaceOffset, FaceOffset]

    @model_validator(mode="after")
    def ordered(self):
        if self.u_m[0] >= self.u_m[1] or self.v_m[0] >= self.v_m[1]:
            raise ValueError("Each no-contact area range needs a start below its end.")
        return self


class NoContactRegion(Closed):
    """A product face, or a rectangle on it, that nothing may touch.

    Faces use the product's own axes, before any packing orientation. No packing material,
    carton wall or other product may lie within air_gap_m of the region, measured straight
    out from the face. A geometric clearance requirement, not a protective-performance rating.
    """
    id: Identity
    name: Text
    face: FaceName
    area: FaceArea | None = None
    air_gap_m: Annotated[float, Field(ge=0.001, le=0.2, strict=True)]
    evidence: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def documented(self):
        if not self.evidence.strip():
            raise ValueError("Record why this region must not be touched.")
        return self


class Constraints(Closed):
    clearance_m: Annotated[float, Field(ge=0, le=0.2, strict=True)] = 0.02
    gap_m: Annotated[float, Field(ge=0, le=0.2, strict=True)] = 0.01
    allowed_orientations: Annotated[list[Orientation], Field(min_length=1, max_length=6)] = Field(default_factory=lambda: [0])
    contents: Literal["unconfirmed", "ordinary_nonhazardous", "special_handling"] = "unconfirmed"
    cushion: CushionRequirement | None = None
    package_allowance: AllowanceRule | None = None
    no_contact: Annotated[list[NoContactRegion], Field(max_length=12)] = Field(default_factory=list)

    @model_validator(mode="after")
    def distinct_regions(self):
        if len({r.id for r in self.no_contact}) != len(self.no_contact):
            raise ValueError("No-contact region IDs must be unique.")
        return self

    @model_serializer(mode="wrap")
    def compact(self, handler) -> dict:
        """Unset optional protections are left out, so a design that never used them keeps the
        hash, and with it the saved quotes, it had before these fields existed."""
        data = handler(self)
        for key in ("cushion", "package_allowance"):
            if data.get(key) is None:
                data.pop(key, None)
        if not data.get("no_contact"):
            data.pop("no_contact", None)
        return data


class Design(Closed):
    name: Text = "Untitled package"
    product: Product | None = None
    quantity: Annotated[int, Field(ge=1, le=48, strict=True)] = 1
    constraints: Constraints = Field(default_factory=Constraints)
    packages: Annotated[list[Package], Field(max_length=10)] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique(self):
        ids = [p.id for p in self.packages]
        if len(ids) != len(set(ids)):
            raise ValueError("Package IDs must be unique.")
        instances = [p.id for box in self.packages for p in box.placements]
        if len(instances) != len(set(instances)):
            raise ValueError("Product instance IDs must be unique across packages.")
        return self


class Edit(Closed):
    expected_revision: Annotated[int, Field(ge=0, strict=True)]
    request_id: Identity
    design: Design


class RevisionCommand(Closed):
    expected_revision: Annotated[int, Field(ge=0, strict=True)]
    request_id: Identity


class PackingRequest(Closed):
    expected_revision: Annotated[int, Field(ge=0, strict=True)]
    cartons: Annotated[list[Carton], Field(min_length=1, max_length=6)]
    max_packages: Annotated[int, Field(ge=1, le=6, strict=True)] = 3


class DensityRequest(Closed):
    source_revision: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    material: MaterialDensity
    exclusions: Annotated[str, Field(max_length=500)] = ""


class BaselineSelect(Closed):
    baseline: Annotated[str, Field(pattern=r"^(current|alt_[a-f0-9]{32})$")]


class EvidenceReview(Closed):
    """The user's review of one public-source evidence record; it never edits a design."""
    status: Literal["unreviewed", "accepted", "rejected"]


class AlternativeSave(Closed):
    expected_revision: Annotated[int, Field(ge=0, strict=True)]
    request_id: Identity
    name: Text
    design: Design | None = None


class Address(Closed):
    name: Annotated[str, Field(max_length=100)] = ""
    street1: Annotated[str, Field(min_length=1, max_length=150)]
    street2: Annotated[str, Field(max_length=150)] = ""
    city: Annotated[str, Field(min_length=1, max_length=100)]
    state: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    zip: Annotated[str, Field(pattern=r"^\d{5}(-\d{4})?$")]
    country: Literal["US"] = "US"
    residential: Annotated[bool, Field(strict=True)]


CarrierAccountId = Annotated[str, Field(pattern=r"^ca_[A-Za-z0-9_]{1,64}$")]
ProviderName = Annotated[str, Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._&/+-]*$")]


class ServiceFilter(Closed):
    """Exact carrier and service names as the provider returns them."""
    carrier: ProviderName
    service: ProviderName


class QuoteOptions(Closed):
    """Documented EasyPost shipment options that affect rating; omitted when left at default."""
    delivery_confirmation: Literal["NO_SIGNATURE", "SIGNATURE", "ADULT_SIGNATURE"] | None = None
    saturday_delivery: Annotated[bool, Field(strict=True)] = False

    def provider_options(self):
        options = {}
        if self.delivery_confirmation is not None:
            options["delivery_confirmation"] = self.delivery_confirmation
        if self.saturday_delivery:
            options["saturday_delivery"] = True
        return options


class QuoteScenario(Closed):
    """Everything that defines a rated scenario, independent of revision and refresh."""
    origin: Address
    destinations: Annotated[list[Address], Field(min_length=1, max_length=3)]
    # Future-date rating is refused until the provider documents that rates honor it.
    ship_date: date | None = None
    carrier_accounts: Annotated[list[CarrierAccountId], Field(max_length=10)] = Field(default_factory=list)
    services: Annotated[list[ServiceFilter], Field(max_length=20)] = Field(default_factory=list)
    options: QuoteOptions = Field(default_factory=QuoteOptions)

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.carrier_accounts)) != len(self.carrier_accounts):
            raise ValueError("List each carrier account once.")
        if len({(s.carrier, s.service) for s in self.services}) != len(self.services):
            raise ValueError("List each carrier service once.")
        return self

    def scenario(self):
        """Everything that defines the rated scenario, independent of revision and refresh."""
        return {"origin": self.origin.model_dump(mode="json"),
                "destinations": [d.model_dump(mode="json") for d in self.destinations],
                "ship_date": None if self.ship_date is None else self.ship_date.isoformat(),
                "carrier_accounts": sorted(self.carrier_accounts),
                "services": sorted([s.carrier, s.service] for s in self.services),
                "options": self.options.provider_options()}


class QuoteRequest(QuoteScenario):
    expected_revision: Annotated[int, Field(ge=0, strict=True)]
    # False reuses a saved quote for the identical scenario; True explicitly requests new rates.
    refresh: Annotated[bool, Field(strict=True)] = False


class ScenarioAuthorization(QuoteScenario):
    """Session addresses the user lets Sage quote by scenario ID, within a shipment budget and time limit.

    Kept in server memory only; Sage sees the ID and city-level labels, never street addresses.
    """
    sage_shipments: Annotated[int, Field(ge=1, le=12, strict=True)]
    minutes: Annotated[int, Field(ge=5, le=240, strict=True)] = 60
