from pydantic import Field

from .common import Base


class CompanyProfile(Base):
    company_id: str
    name: str
    inn: str | None = None
    okved: list[str] = Field(default_factory=list)
    industry: str | None = None
    region: str | None = None
    revenue: float | None = None
    employees: int | None = None
    products: list[str] = Field(default_factory=list)
    key_partners: list[str] = Field(default_factory=list)
    links: list["CompanyLink"] = Field(default_factory=list)
    completeness: float = Field(ge=0, le=1, description="Доля заполненных признаков")
    missing_fields: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class CompanyLink(Base):
    target_company_id: str | None = None
    target_name: str
    relation_type: str
    strength: float = Field(ge=0, le=1)
