"""Create chat_audit_logs table with RLS.

Revision ID: 0001
Revises:
Create Date: 2026-05-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create table
    op.create_table(
        'chat_audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_id', sa.String(36), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('doc_ids', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('latency_ms', sa.Integer(), nullable=False),
        sa.Column('tokens_in', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tokens_out', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_chat_audit_logs_tenant_id', 'chat_audit_logs', ['tenant_id'], unique=False)
    op.create_index('ix_chat_audit_logs_user_id', 'chat_audit_logs', ['user_id'], unique=False)
    op.create_index('ix_chat_audit_logs_session_id', 'chat_audit_logs', ['session_id'], unique=False)

    # Enable RLS
    op.execute('ALTER TABLE chat_audit_logs ENABLE ROW LEVEL SECURITY;')

    # Create RLS policies
    op.execute('''
        CREATE POLICY chat_audit_select ON chat_audit_logs FOR SELECT
          USING (tenant_id = current_setting('app.tenant_id')::uuid);
    ''')

    op.execute('''
        CREATE POLICY chat_audit_insert ON chat_audit_logs FOR INSERT
          WITH CHECK (true);
    ''')

    op.execute('''
        CREATE POLICY chat_audit_delete ON chat_audit_logs FOR DELETE
          USING (false);
    ''')


def downgrade() -> None:
    # Drop RLS policies
    op.execute('DROP POLICY IF EXISTS chat_audit_select ON chat_audit_logs;')
    op.execute('DROP POLICY IF EXISTS chat_audit_insert ON chat_audit_logs;')
    op.execute('DROP POLICY IF EXISTS chat_audit_delete ON chat_audit_logs;')

    # Drop table
    op.drop_table('chat_audit_logs')
