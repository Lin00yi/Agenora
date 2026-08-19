"""Create the full current schema under Alembic control.

Fresh production databases begin here, before the historical conditional
revisions. Older personal deployments were already created by the former
application-startup bootstrap and should be verified before being stamped at
their existing revision.
"""

from typing import Sequence, Union

from alembic import op

from src.auth import models as _auth_models  # noqa: F401
from src.conversations import models as _conv_models  # noqa: F401
from src.kb import models as _kb_models  # noqa: F401
from src.observability import models as _obs_models  # noqa: F401
from src.settings_user import models as _settings_user_models  # noqa: F401
from src.storage.database import Base

revision: str = "0000_schema_bootstrap"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create a fresh schema and all model-declared indexes once."""
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # This is an initial-schema bridge, not a safe destructive downgrade.
    pass
