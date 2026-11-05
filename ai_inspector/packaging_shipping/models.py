"""Closed, SI-unit contracts shared by manual editing and Sage."""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Scalar = Annotated[float, Field(ge=0, le=10000, allow_inf_nan=False, strict=True)]
Length = Annotated[float, Field(gt=0, le=5, allow_inf_nan=False, strict=True)]
Dimensions = tuple[Length, Length, Length]
Position = tuple[Scalar, Scalar, Scalar]
Identity = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")]
Text = Annotated[str, Field(min_length=1, max_length=160)]
Orientation = Annotated[int, Field(ge=0, le=5, strict=True)]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


class Product(Closed):
    name: Text
    dimensions_m: Dimensions
    mass_kg: Annotated[float, Field(gt=0, le=1000, strict=True)] | None = None
    mass_basis: Literal["unknown", "user_measured", "cad", "estimate"] = "unknown"
    mass_evidence: Annotated[str, Field(max_length=500)] = ""
    source_id: Identity | None = None
    source_revision: Annotated[str, Field(max_length=128)] = ""

    @model_validator(mode="after")
    def evidence(self):
        if (self.mass_kg is None) != (self.mass_basis == "unknown"):
            raise ValueError("Mass and its provenance must be supplied together.")
        if self.mass_kg is not None and not self.mass_evidence.strip():
            raise ValueError("Record the source of the mass, including estimates.")
        return self


class Carton(Closed):
    name: Text
    inner_m: Dimensions
    outer_m: Dimensions
    tare_kg: Annotated[float, Field(ge=0, le=100, strict=True)] | None = None
    tare_evidence: Annotated[str, Field(max_length=500)] = ""
    cost_usd: Annotated[float, Field(ge=0, le=10000, strict=True)] | None = None
    max_payload_kg: Annotated[float, Field(gt=0, le=1000, strict=True)] | None = None

    @model_validator(mode="after")
    def dimensions(self):
        if any(o <= i for i, o in zip(self.inner_m, self.outer_m)):
            raise ValueError("External dimensions must exceed internal dimensions on every axis.")
        if self.tare_kg is not None and not self.tare_evidence.strip():
            raise ValueError("Record the source of the empty-carton weight.")
        return self


class Placement(Closed):
    id: Identity
    position_m: Position
    orientation: Orientation = 0


class Insert(Closed):
    id: Identity
    name: Text
    dimensions_m: Dimensions
    position_m: Position
    material: Text = "Foam"
    density_kg_m3: Annotated[float, Field(gt=0, le=25000, strict=True)]
    material_evidence: Annotated[str, Field(min_length=1, max_length=500)]
    cost_usd: Annotated[float, Field(ge=0, le=10000, strict=True)] | None = None

    @model_validator(mode="after")
    def evidence(self):
        if not self.material_evidence.strip():
            raise ValueError("Record the source of the insert material density.")
        return self


class Package(Closed):
    id: Identity
    carton: Carton
    placements: Annotated[list[Placement], Field(max_length=48)] = Field(default_factory=list)
    inserts: Annotated[list[Insert], Field(max_length=32)] = Field(default_factory=list)
    allowance_kg: Annotated[float, Field(ge=0, le=20, strict=True)] | None = None
    allowance_evidence: Annotated[str, Field(max_length=500)] = ""

    @model_validator(mode="after")
    def unique(self):
        ids = [x.id for x in self.placements] + [x.id for x in self.inserts]
        if len(ids) != len(set(ids)):
            raise ValueError("Component IDs must be unique within a package.")
        if self.allowance_kg is not None and not self.allowance_evidence.strip():
            raise ValueError("Record what the packing allowance includes, even when zero.")
        return self


class Constraints(Closed):
    clearance_m: Annotated[float, Field(ge=0, le=0.2, strict=True)] = 0.02
    gap_m: Annotated[float, Field(ge=0, le=0.2, strict=True)] = 0.01
    allowed_orientations: Annotated[list[Orientation], Field(min_length=1, max_length=6)] = Field(default_factory=lambda: [0])
    contents: Literal["unconfirmed", "ordinary_nonhazardous", "special_handling"] = "unconfirmed"


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


class Address(Closed):
    name: Annotated[str, Field(max_length=100)] = ""
    street1: Annotated[str, Field(min_length=1, max_length=150)]
    street2: Annotated[str, Field(max_length=150)] = ""
    city: Annotated[str, Field(min_length=1, max_length=100)]
    state: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    zip: Annotated[str, Field(pattern=r"^\d{5}(-\d{4})?$")]
    country: Literal["US"] = "US"
    residential: Annotated[bool, Field(strict=True)]


class QuoteRequest(Closed):
    expected_revision: Annotated[int, Field(ge=0, strict=True)]
    origin: Address
    destinations: Annotated[list[Address], Field(min_length=1, max_length=3)]
