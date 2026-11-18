"""add is_superadmin and scopes to admin model

Revision ID: b7f1c2d8a943
Revises: 143318583395
Create Date: 2026-11-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b7f1c2d8a943'
down_revision: Union[str, None] = '143318583395'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Снимок набора на момент миграции. Намеренно продублирован из
# auth/scopes.py: миграция не должна зависеть от кода приложения,
# который завтра изменится.
LEGACY_ADMIN_SCOPES = (
    'accounts:read',
    'threads:read',
    'threads:write',
    'messages:read',
    'messages:write',
)


def upgrade() -> None:
    op.add_column(
        'admins',
        sa.Column('is_superadmin',
                  sa.Boolean(),
                  nullable=False,
                  server_default=sa.false()),
    )
    op.add_column(
        'admins',
        sa.Column('scopes',
                  postgresql.ARRAY(sa.String()),
                  nullable=False,
                  server_default='{}'),
    )

    # Главный админ (id = 1) раньше определялся как `admin_id == 1`
    # прямо в коде — переносим это в данные.
    op.execute('UPDATE admins SET is_superadmin = true WHERE id = 1')

    # Остальным выдаём ровно то, что они могли делать до введения прав.
    scopes_literal = ', '.join(f"'{scope}'" for scope in LEGACY_ADMIN_SCOPES)
    op.execute(
        f'UPDATE admins '
        f'SET scopes = ARRAY[{scopes_literal}]::varchar[] '
        f'WHERE is_superadmin = false'
    )


def downgrade() -> None:
    op.drop_column('admins', 'scopes')
    op.drop_column('admins', 'is_superadmin')
