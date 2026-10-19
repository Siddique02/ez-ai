"""add matches and estimates

Revision ID: caacee657823
Revises: a961e665a5ed
Create Date: 2026-09-25 23:39:58.450921

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'caacee657823'
down_revision: Union[str, Sequence[str], None] = 'a961e665a5ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
