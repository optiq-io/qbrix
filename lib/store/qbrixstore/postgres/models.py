from datetime import datetime, time, timezone
from uuid import uuid4
from typing import List, Optional
from sqlalchemy import String, Boolean, Float, Integer, ForeignKey, JSON, DateTime, Time
from sqlalchemy import Text
from sqlalchemy import Index, UniqueConstraint
from sqlalchemy import text
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
    changes: Mapped[list["Change"]] = relationship(
        "Change", back_populates="tenant", cascade="all, delete-orphan"
    )
    metrics: Mapped[list["Metric"]] = relationship(
        "Metric", back_populates="tenant", cascade="all, delete-orphan"
    )
    loops: Mapped[list["Loop"]] = relationship(
        "Loop", back_populates="tenant", cascade="all, delete-orphan"
    )
    connections: Mapped[list["Connection"]] = relationship(
        "Connection", back_populates="tenant", cascade="all, delete-orphan"
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


class Change(Base):
    """one write by one actor: what it touched, before and after, and what the
    target had learned at that moment."""

    __tablename__ = "changes"
    __table_args__ = (
        # an object's history, newest first
        Index(
            "ix_changes_tenant_id_target_created_at",
            "tenant_id",
            "target_type",
            "target_id",
            "created_at",
        ),
        # the workspace's changes, newest first
        Index("ix_changes_tenant_id_created_at", "tenant_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # no foreign key: history outlives the user who made it
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    connection_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    api_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    before: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    learning: Mapped[dict | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="applied")
    undoes_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("changes.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="changes")


class Metric(Base):
    """what a loop improves. its type and range are fixed; what it means and
    how long a decision waits for it are versioned."""

    __tablename__ = "metrics"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_metric_tenant_name"),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    score_lo: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_hi: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="metrics")
    versions: Mapped[list["MetricVersion"]] = relationship(
        "MetricVersion",
        back_populates="metric",
        cascade="all, delete-orphan",
        order_by=lambda: [MetricVersion.major, MetricVersion.minor],
    )


class MetricVersion(Base):
    """one version of a metric. never changed in place: the newest is current,
    and a decision is sealed by the version it was opened under."""

    __tablename__ = "metric_versions"
    __table_args__ = (
        UniqueConstraint(
            "metric_id", "major", "minor", name="uq_metric_version_number"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    metric_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("metrics.id", ondelete="CASCADE"), nullable=False
    )
    major: Mapped[int] = mapped_column(Integer, nullable=False)
    minor: Mapped[int] = mapped_column(Integer, nullable=False)
    semantic: Mapped[str] = mapped_column(Text, nullable=False)
    window_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    metric: Mapped["Metric"] = relationship("Metric", back_populates="versions")


class Loop(Base):
    """a place in the product where qbrix decides on every request. the key is
    what code calls; it locks when the loop is launched. the current cycle is
    the highest-numbered one. live_since is when it last went live, at launch
    or resume."""

    __tablename__ = "loops"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_loop_tenant_key"),)

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metric_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("metrics.id"), nullable=False, index=True
    )
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    paused_from: Mapped[str | None] = mapped_column(String(16), nullable=True)
    live_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fallback_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="loops")
    metric: Mapped["Metric"] = relationship("Metric")
    options: Mapped[list["LoopOption"]] = relationship(
        "LoopOption",
        back_populates="loop",
        cascade="all, delete-orphan",
        order_by=lambda: LoopOption.position,
    )
    cycles: Mapped[list["Cycle"]] = relationship(
        "Cycle",
        back_populates="loop",
        cascade="all, delete-orphan",
        order_by=lambda: Cycle.number,
    )


class LoopOption(Base):
    """one thing a loop can serve, with the config the app renders it from."""

    __tablename__ = "loop_options"
    __table_args__ = (UniqueConstraint("loop_id", "key", name="uq_loop_option_key"),)

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    loop_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("loops.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    loop: Mapped["Loop"] = relationship("Loop", back_populates="options")


class Cycle(Base):
    """a version of a loop's options, engine and learning. its id is the id
    the learning path serves and trains it under."""

    __tablename__ = "cycles"
    __table_args__ = (UniqueConstraint("loop_id", "number", name="uq_cycle_number"),)

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    loop_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("loops.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    metric_version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("metric_versions.id"), nullable=False
    )
    options: Mapped[list] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    loop: Mapped["Loop"] = relationship("Loop", back_populates="cycles")
    metric_version: Mapped["MetricVersion"] = relationship("MetricVersion")


class Pin(Base):
    """a loop or metric a person keeps in their sidebar. ref is the target's id,
    in the table kind names, so a deleted target leaves a row nothing lists."""

    __tablename__ = "pins"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "ref", name="uq_pin_user_kind_ref"),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ref: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class OAuthClient(Base):
    """a client that registered itself (dynamic client registration). a client
    identified by a metadata document url is never stored."""

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: uuid4().hex
    )
    client_metadata: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Connection(Base):
    """a client acting for one person. client_identity is what makes two
    sign-ins the same client: the metadata document url, or for a registered
    client its software_id, else its name. client_id is the registration it
    last signed in with, which its refresh tokens are bound to."""

    __tablename__ = "connections"
    __table_args__ = (
        Index(
            "uq_connections_user_client_active",
            "user_id",
            "client_identity",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_identity: Mapped[str] = mapped_column(String(512), nullable=False)
    client_id: Mapped[str] = mapped_column(String(512), nullable=False)
    client_name: Mapped[str] = mapped_column(String(128), nullable=False)
    client_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="connections")
    user: Mapped["User"] = relationship("User")
    tokens: Mapped[list["ConnectionToken"]] = relationship(
        "ConnectionToken",
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ConnectionToken(Base):
    """an access or refresh token of a connection, stored as its sha-256 only.
    used_at marks a refresh token already exchanged; presenting it again
    revokes the connection."""

    __tablename__ = "connection_tokens"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: uuid4().hex
    )
    connection_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    resource: Mapped[str] = mapped_column(String(512), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    connection: Mapped["Connection"] = relationship(
        "Connection", back_populates="tokens"
    )
