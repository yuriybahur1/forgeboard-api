"""Enforce issue workflow values in PostgreSQL."""

from alembic import op

revision = "20260823_0002"
down_revision = "20260823_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "valid_status",
        "issues",
        "status IN ('backlog','todo','in_progress','done','canceled')",
    )
    op.create_check_constraint(
        "valid_priority",
        "issues",
        "priority IN ('no_priority','low','medium','high','urgent')",
    )
    op.create_check_constraint("positive_version", "issues", "version >= 1")


def downgrade() -> None:
    op.drop_constraint("positive_version", "issues", type_="check")
    op.drop_constraint("valid_priority", "issues", type_="check")
    op.drop_constraint("valid_status", "issues", type_="check")
