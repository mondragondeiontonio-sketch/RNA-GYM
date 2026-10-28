"""Version keys for raw file bytes, never experimental observation identities."""
import re


def artifact_uid(asset_id, source_sha256):
    if (not isinstance(asset_id, str) or not asset_id or '@' in asset_id or
            not isinstance(source_sha256, str) or
            re.fullmatch(r'[0-9a-f]{64}', source_sha256) is None):
        raise ValueError('HASH_BOUND_ARTIFACT_ID_REQUIRED')
    return asset_id + '@sha256:' + source_sha256
