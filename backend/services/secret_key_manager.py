"""Secret key manager for Nebulus Gantry.

Generates, persists, loads, and rotates cryptographically secure secret
keys used for session signing.  Keys are stored on disk with restrictive
file permissions and are never logged or exposed via API responses.

Typical usage::

    from pathlib import Path
    from backend.services.secret_key_manager import get_secret_key, rotate_secret_key

    data_dir = Path("data")
    key = get_secret_key(data_dir)       # load or create
    new_key = rotate_secret_key(data_dir) # force rotation
"""

from __future__ import annotations

import logging
import os
import secrets
import stat
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_KEY_FILENAME = ".secret_key"
_KEY_BYTES = 32  # 32 bytes → 64-char hex string


def _key_path(data_dir: Path) -> Path:
    """Return the resolved path to the secret key file.

    Args:
        data_dir: Directory where application data is stored.

    Returns:
        Full path to the ``.secret_key`` file.
    """
    return data_dir / _KEY_FILENAME


def _generate_key() -> str:
    """Generate a cryptographically secure secret key.

    Returns:
        A 64-character hex-encoded string (32 random bytes).
    """
    return secrets.token_hex(_KEY_BYTES)


def _storage_error(key_file: Path, err: OSError) -> RuntimeError:
    return RuntimeError(
        f"Cannot create the secret key file in {key_file.parent} ({type(err).__name__}). "
        "Set SECRET_KEY in the environment, or make GANTRY_DATA_DIR writable."
    )


def _write_temp(key_file: Path, key: str) -> str:
    """Write *key* to a 0600 temp file next to *key_file*; return its path."""
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(key_file.parent), prefix=".secret_key_tmp_")
    except OSError as e:
        raise _storage_error(key_file, e) from e
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        os.write(fd, key.encode("utf-8"))
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        _unlink_quietly(tmp_path)
        raise
    os.close(fd)
    return tmp_path


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _write_key(key_file: Path, key: str) -> None:
    """Atomically write (or overwrite) *key* to *key_file* with 0600 permissions."""
    tmp_path = _write_temp(key_file, key)
    try:
        os.replace(tmp_path, str(key_file))
    except BaseException:
        _unlink_quietly(tmp_path)
        raise


def _create_key_exclusive(key_file: Path, key: str) -> str | None:
    """Create *key_file* only if it doesn't exist (atomic ``link``).

    Returns *key* if this process created the file, or ``None`` if another
    process won the race (the caller then re-reads the file). The file is
    complete and 0600 before it becomes visible, so a reader never sees a
    partial key.
    """
    tmp_path = _write_temp(key_file, key)
    try:
        os.link(tmp_path, str(key_file))
        return key
    except FileExistsError:
        return None
    except OSError:
        # Filesystem without hard links (EPERM/EOPNOTSUPP/EXDEV/EMLINK...):
        # fall back to an exclusive create of the key file itself.
        return _create_key_excl_open(key_file, key)
    finally:
        _unlink_quietly(tmp_path)


def _create_key_excl_open(key_file: Path, key: str) -> str | None:
    """O_CREAT|O_EXCL fallback; 0600 from creation. ``None`` if the file exists."""
    try:
        fd = os.open(str(key_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return None
    except OSError as e:
        raise _storage_error(key_file, e) from e
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)  # 0o600 regardless of umask
        os.write(fd, key.encode("utf-8"))
        os.fsync(fd)
    except OSError as e:
        os.close(fd)
        _unlink_quietly(str(key_file))
        raise _storage_error(key_file, e) from e
    os.close(fd)
    return key


def _fd_closed(fd: int) -> bool:
    """Check whether a file descriptor is already closed.

    Args:
        fd: File descriptor integer.

    Returns:
        ``True`` if *fd* is closed, ``False`` otherwise.
    """
    try:
        os.fstat(fd)
        return False
    except OSError:
        return True


def _read_key(key_file: Path) -> str | None:
    """Read an existing key from disk.

    Args:
        key_file: Path to the secret key file.

    Returns:
        The key string if the file exists and is non-empty, else ``None``.
    """
    if not key_file.exists():
        return None
    mode = stat.S_IMODE(key_file.stat().st_mode)
    if mode & 0o077:
        logger.warning("Secret key file %s has mode %o; it should be 0600 (chmod 600).",
                       key_file, mode)
    content = key_file.read_text(encoding="utf-8").strip()
    return content if content else None


def get_secret_key(data_dir: Path) -> str:
    """Return the current secret key, generating one if absent.

    On first call (or if the file was deleted) a new key is generated
    and persisted.  Subsequent calls return the persisted key.

    Args:
        data_dir: Directory where application data is stored.

    Returns:
        A 64-character hex-encoded secret key.
    """
    key_file = _key_path(data_dir)
    existing = _read_key(key_file)
    if existing is not None:
        return existing

    key = _generate_key()
    created = _create_key_exclusive(key_file, key)
    if created is not None:
        return created
    # The file exists: another worker created it first (it is always complete,
    # because it only appears via link), so everyone uses that key.
    # With the O_EXCL fallback the winner's file is briefly empty, so wait a moment.
    for _ in range(50):
        existing = _read_key(key_file)
        if existing is not None:
            return existing
        time.sleep(0.01)
    # Still empty (e.g. a manual truncation, not a race): replace it.
    _write_key(key_file, key)
    return key


def rotate_secret_key(data_dir: Path) -> str:
    """Generate a new secret key and overwrite the persisted copy.

    **Warning:** Rotating the key invalidates all existing sessions
    signed with the previous key.

    Args:
        data_dir: Directory where application data is stored.

    Returns:
        The newly generated 64-character hex-encoded secret key.
    """
    key = _generate_key()
    _write_key(_key_path(data_dir), key)
    return key
