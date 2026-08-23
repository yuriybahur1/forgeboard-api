"""Initial schema."""

from alembic import op

from workstream.db.base import Base
from workstream.modules import models  # noqa: F401

revision = "20260823_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        table.create(bind, checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(bind, checkfirst=False)
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
