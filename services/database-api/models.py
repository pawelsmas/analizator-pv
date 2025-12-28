"""
Database API - SQLAlchemy Models
"""

from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean,
    DateTime, Numeric, ForeignKey, JSON, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

Base = declarative_base()


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    nip = Column(String(20))
    address = Column(Text)
    contact_email = Column(String(255))
    contact_phone = Column(String(50))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    projects = relationship("Project", back_populates="company", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"))
    name = Column(String(255), nullable=False)
    description = Column(Text)
    location_name = Column(String(255))
    latitude = Column(Numeric(10, 7))
    longitude = Column(Numeric(10, 7))
    analysis_mode = Column(String(50), default="pv_bess")
    status = Column(String(50), default="draft")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="projects")
    profiles = relationship("EnergyProfile", back_populates="project", cascade="all, delete-orphan")
    analyses = relationship("AnalysisResult", back_populates="project", cascade="all, delete-orphan")


class EnergyProfile(Base):
    __tablename__ = "energy_profiles"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    profile_type = Column(String(50), nullable=False)  # consumption, pv_generation, net_load
    time_resolution = Column(String(20), nullable=False, default="hourly")
    year = Column(Integer, nullable=False)
    source = Column(String(100))
    filename = Column(String(255))
    total_kwh = Column(Numeric(15, 3))
    peak_kw = Column(Numeric(12, 3))
    data_points = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("Project", back_populates="profiles")
    data = relationship("ProfileData", back_populates="profile", cascade="all, delete-orphan")


class ProfileData(Base):
    __tablename__ = "profile_data"

    id = Column(BigInteger, primary_key=True)
    profile_id = Column(Integer, ForeignKey("energy_profiles.id", ondelete="CASCADE"))
    timestamp = Column(DateTime(timezone=True), nullable=False)
    value_kw = Column(Numeric(12, 4), nullable=False)

    __table_args__ = (
        UniqueConstraint('profile_id', 'timestamp', name='uq_profile_timestamp'),
    )

    # Relationships
    profile = relationship("EnergyProfile", back_populates="data")


class PriceScenario(Base):
    __tablename__ = "price_scenarios"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    scenario_type = Column(String(50), nullable=False)  # historical, forecast, custom
    source = Column(String(100))
    year = Column(Integer)
    currency = Column(String(10), default="PLN")
    unit = Column(String(20), default="PLN/MWh")
    avg_price = Column(Numeric(10, 2))
    min_price = Column(Numeric(10, 2))
    max_price = Column(Numeric(10, 2))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    data = relationship("PriceData", back_populates="scenario", cascade="all, delete-orphan")
    analyses = relationship("AnalysisResult", back_populates="price_scenario")


class PriceData(Base):
    __tablename__ = "price_data"

    id = Column(BigInteger, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("price_scenarios.id", ondelete="CASCADE"))
    timestamp = Column(DateTime(timezone=True), nullable=False)
    price_pln_mwh = Column(Numeric(10, 4), nullable=False)

    __table_args__ = (
        UniqueConstraint('scenario_id', 'timestamp', name='uq_scenario_timestamp'),
    )

    # Relationships
    scenario = relationship("PriceScenario", back_populates="data")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    price_scenario_id = Column(Integer, ForeignKey("price_scenarios.id", ondelete="SET NULL"), nullable=True)
    analysis_type = Column(String(50), nullable=False)
    input_params = Column(JSONB, nullable=False)
    results = Column(JSONB, nullable=False)
    status = Column(String(50), default="completed")
    compute_time_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("Project", back_populates="analyses")
    price_scenario = relationship("PriceScenario", back_populates="analyses")


class AnalysisMode(Base):
    __tablename__ = "analysis_modes"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    name_pl = Column(String(100), nullable=False)
    name_en = Column(String(100), nullable=False)
    description_pl = Column(Text)
    icon = Column(String(50))
    requires_pv = Column(Boolean, default=False)
    requires_bess = Column(Boolean, default=False)
    requires_load = Column(Boolean, default=True)
    requires_prices = Column(Boolean, default=False)
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
