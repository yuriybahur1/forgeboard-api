"""Initial immutable PostgreSQL schema snapshot."""

from alembic import op

revision = "20260823_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("""
    CREATE TABLE users (id uuid PRIMARY KEY, email varchar(320) NOT NULL, password_hash text NOT NULL,
      display_name varchar(120) NOT NULL, email_verified_at timestamptz, is_active boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL);
    CREATE UNIQUE INDEX uq_users_email_normalized ON users (lower(email));
    CREATE TABLE organizations (id uuid PRIMARY KEY, name varchar(120) NOT NULL, slug varchar(63) NOT NULL,
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      CONSTRAINT uq_organizations_slug UNIQUE (slug), CONSTRAINT ck_organizations_slug_format CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'));
    CREATE TABLE memberships (organization_id uuid REFERENCES organizations(id) ON DELETE CASCADE,
      user_id uuid REFERENCES users(id) ON DELETE CASCADE, role varchar(16) NOT NULL,
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, PRIMARY KEY (organization_id,user_id),
      CONSTRAINT ck_memberships_valid_role CHECK (role IN ('owner','admin','member','viewer')));
    CREATE INDEX ix_memberships_user_org ON memberships (user_id,organization_id);
    CREATE TABLE invitations (id uuid PRIMARY KEY, organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
      invited_email varchar(320) NOT NULL, role varchar(16) NOT NULL, token_hash varchar(64) NOT NULL,
      inviter_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, expires_at timestamptz NOT NULL,
      accepted_at timestamptz, revoked_at timestamptz, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      CONSTRAINT uq_invitations_token_hash UNIQUE(token_hash));
    CREATE INDEX ix_invitations_org_pending ON invitations (organization_id,expires_at) WHERE accepted_at IS NULL AND revoked_at IS NULL;
    CREATE TABLE projects (id uuid PRIMARY KEY, organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
      name varchar(120) NOT NULL, key varchar(10) NOT NULL, description text NOT NULL DEFAULT '', archived boolean NOT NULL DEFAULT false,
      next_issue_number integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      CONSTRAINT uq_projects_organization_id_key UNIQUE (organization_id,key), CONSTRAINT ck_projects_key_format CHECK (key ~ '^[A-Z][A-Z0-9]{1,9}$'));
    CREATE TABLE issues (id uuid PRIMARY KEY, organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
      project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE, number integer NOT NULL, title varchar(240) NOT NULL,
      description text NOT NULL DEFAULT '', status varchar(20) NOT NULL DEFAULT 'backlog', priority varchar(20) NOT NULL DEFAULT 'no_priority',
      reporter_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, assignee_id uuid REFERENCES users(id) ON DELETE SET NULL,
      due_date date, version integer NOT NULL DEFAULT 1, archived_at timestamptz, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      CONSTRAINT uq_issues_project_id_number UNIQUE(project_id,number));
    CREATE INDEX ix_issues_org_created_id ON issues (organization_id,created_at DESC,id);
    CREATE INDEX ix_issues_project_status ON issues (project_id,status);
    CREATE INDEX ix_issues_assignee ON issues (organization_id,assignee_id);
    CREATE INDEX ix_issues_search_trgm ON issues USING gin ((title || ' ' || description) gin_trgm_ops);
    CREATE TABLE labels (id uuid PRIMARY KEY, organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
      name varchar(50) NOT NULL, color varchar(7) NOT NULL, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      CONSTRAINT uq_labels_organization_id_name UNIQUE(organization_id,name), CONSTRAINT ck_labels_color_hex CHECK (color ~ '^#[0-9A-Fa-f]{6}$'));
    CREATE TABLE issue_labels (issue_id uuid REFERENCES issues(id) ON DELETE CASCADE, label_id uuid REFERENCES labels(id) ON DELETE CASCADE,
      PRIMARY KEY(issue_id,label_id));
    CREATE TABLE comments (id uuid PRIMARY KEY, organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
      issue_id uuid NOT NULL REFERENCES issues(id) ON DELETE CASCADE, author_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      body text NOT NULL, edited_at timestamptz, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL);
    CREATE INDEX ix_comments_issue_created_id ON comments (issue_id,created_at,id);
    CREATE TABLE notifications (id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      organization_id uuid REFERENCES organizations(id) ON DELETE CASCADE, kind varchar(50) NOT NULL, payload jsonb NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(), read_at timestamptz);
    CREATE INDEX ix_notifications_user_unread ON notifications (user_id,created_at) WHERE read_at IS NULL;
    CREATE TABLE audit_events (id uuid PRIMARY KEY, actor_id uuid REFERENCES users(id) ON DELETE SET NULL,
      organization_id uuid REFERENCES organizations(id) ON DELETE CASCADE, action varchar(100) NOT NULL, entity_type varchar(50) NOT NULL,
      entity_id uuid, metadata jsonb NOT NULL, request_id varchar(128), created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ix_audit_org_created_id ON audit_events (organization_id,created_at DESC,id);
    CREATE TABLE auth_sessions (id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      family_id uuid NOT NULL, refresh_token_hash varchar(64) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz NOT NULL, rotated_at timestamptz, revoked_at timestamptz, user_agent varchar(300), ip_address varchar(64),
      CONSTRAINT uq_auth_sessions_refresh_token_hash UNIQUE(refresh_token_hash));
    CREATE INDEX ix_auth_sessions_user_active ON auth_sessions (user_id) WHERE revoked_at IS NULL;
    CREATE TABLE one_time_tokens (id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      purpose varchar(30) NOT NULL, token_hash varchar(64) NOT NULL, expires_at timestamptz NOT NULL,
      used_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_one_time_tokens_token_hash UNIQUE(token_hash));
    CREATE TABLE outbox_events (id uuid PRIMARY KEY, topic varchar(100) NOT NULL, payload jsonb NOT NULL,
      occurred_at timestamptz NOT NULL DEFAULT now(), available_at timestamptz NOT NULL DEFAULT now(), attempts integer NOT NULL DEFAULT 0,
      locked_at timestamptz, locked_by varchar(100), processed_at timestamptz, failed_at timestamptz, last_error text);
    CREATE INDEX ix_outbox_dispatch ON outbox_events (available_at,occurred_at) WHERE processed_at IS NULL AND failed_at IS NULL;
    """)


def downgrade() -> None:
    for table in (
        "outbox_events",
        "one_time_tokens",
        "auth_sessions",
        "audit_events",
        "notifications",
        "comments",
        "issue_labels",
        "labels",
        "issues",
        "projects",
        "invitations",
        "memberships",
        "organizations",
        "users",
    ):
        op.drop_table(table)
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
