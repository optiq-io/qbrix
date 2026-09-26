from datetime import datetime, time, timezone
from uuid import uuid4
from typing import List, Optional
from sqlalchemy import String, Boolean, Float, Integer, ForeignKey, JSON, DateTime, Time
from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    plan_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    pools: Mapped[list["Pool"]] = relationship(
        "Pool", back_populates="tenant", cascade="all, delete-orphan"
    )
    experiments: Mapped[list["Experiment"]] = relationship(
        "Experiment", back_populates="tenant", cascade="all, delete-orphan"
    )
    users: Mapped[list["User"]] = relationship(
        "User", back_populates="tenant", cascade="all, delete-orphan"
    )
    stripe_customer: Mapped["StripeCustomer | None"] = relationship(
        "StripeCustomer",
        back_populates="tenant",
        uselist=False,
        cascade="all, delete-orphan",
    )
    subscription: Mapped["Subscription | None"] = relationship(
        "Subscription",
        back_populates="tenant",
        uselist=False,
        cascade="all, delete-orphan",
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice", back_populates="tenant", cascade="all, delete-orphan"
    )
    invites: Mapped[list["Invite"]] = relationship(
        "Invite", back_populates="tenant", cascade="all, delete-orphan"
    )


class Pool(Base):
    __tablename__ = "pools"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_pool_tenant_name"),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="pools")
    arms: Mapped[list["Arm"]] = relationship(
        "Arm", back_populates="pool", cascade="all, delete-orphan"
    )
    experiments: Mapped[list["Experiment"]] = relationship(
        "Experiment", back_populates="pool"
    )


class Arm(Base):
    __tablename__ = "arms"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    pool_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("pools.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    pool: Mapped["Pool"] = relationship("Pool", back_populates="arms")


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_experiment_tenant_name"),
        # serves count_active on the plan-limit check; tenant_id alone is already
        # covered by the leading column of uq_experiment_tenant_name.
        Index("ix_experiments_tenant_id_enabled", "tenant_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    pool_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("pools.id"), nullable=False, index=True
    )
    policy: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    meta_experiment_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("experiments.id"),
        nullable=True,
        default=None,
        index=True,
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="experiments")
    pool: Mapped["Pool"] = relationship("Pool", back_populates="experiments")
    feature_gate: Mapped["FeatureGate"] = relationship(
        "FeatureGate",
        back_populates="experiment",
        uselist=False,
        cascade="all, delete-orphan",
    )
    meta_experiment: Mapped[Optional["Experiment"]] = relationship(
        "Experiment",
        remote_side="Experiment.id",
        back_populates="learner_experiments",
    )
    learner_experiments: Mapped[List["Experiment"]] = relationship(
        "Experiment",
        back_populates="meta_experiment",
        cascade="all, delete-orphan",
    )


class FeatureGate(Base):
    __tablename__ = "feature_gates"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    experiment_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("experiments.id"), nullable=False, unique=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rollout_percentage: Mapped[float] = mapped_column(Float, default=100.0)
    default_arm_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("arms.id"), nullable=True, index=True
    )
    schedule_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    schedule_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    active_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    rules: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    experiment: Mapped["Experiment"] = relationship(
        "Experiment", back_populates="feature_gate"
    )
    default_arm: Mapped["Arm | None"] = relationship(
        "Arm", foreign_keys=[default_arm_id]
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="users")
    api_keys: Mapped[list["APIKey"]] = relationship(
        "APIKey", back_populates="user", cascade="all, delete-orphan"
    )


class APIKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        # serves list_by_user and the tenant-wide count join; user_id alone is
        # covered by the leading column.
        Index("ix_api_keys_user_id_is_active", "user_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, default="Default API Key"
    )
    rate_limit_per_minute: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1000
    )
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", back_populates="api_keys")


class Invite(Base):
    __tablename__ = "invites"
    __table_args__ = (
        # equality columns first, range last: serves the pending-invite count on
        # every seat check and the per-email pending lookup. tenant_id alone is
        # covered by the leading column.
        Index(
            "ix_invites_tenant_id_status_expires_at",
            "tenant_id",
            "status",
            "expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    invited_by: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="invites")
    inviter: Mapped["User"] = relationship("User", foreign_keys=[invited_by])


class StripeCustomer(Base):
    __tablename__ = "stripe_customers"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), nullable=False, unique=True
    )
    stripe_customer_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="stripe_customer")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), nullable=False, unique=True
    )
    stripe_subscription_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    current_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    current_period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    canceled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="subscription")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), nullable=False, index=True
    )
    stripe_invoice_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    stripe_subscription_id: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_due: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_paid: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="usd")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    invoice_pdf: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="invoices")
