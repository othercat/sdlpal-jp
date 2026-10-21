"""Stage a small resource batch and roll back handled publication failures.

This is not a crash-safe or concurrent-writer transaction. All outputs must
share a directory; only files registered by this batch may be changed.
"""
import json
import os
import shutil
import stat
import tempfile
import warnings
from pathlib import Path


class ResourceTransaction:
    def __init__(self, directory, overwrite=True):
        self.directory = Path(directory).resolve(strict=True)
        self.overwrite = overwrite
        self.outputs = {}
        self.keep_recovery = False
        self.committed = False
        self.staging = None

    def __enter__(self):
        return self

    def stage(self, name):
        if Path(name).name != name or name in ("", ".", ".."):
            raise ValueError("Resource output must be a file name.")
        if self.committed:
            raise RuntimeError("Resource batch already committed.")
        if self.staging is None:
            self.staging = Path(tempfile.mkdtemp(prefix=".sdlpal-prepare-", dir=self.directory))
        if name not in self.outputs:
            self.outputs[name] = self.staging / ("new-%d" % len(self.outputs))
        return str(self.outputs[name])

    @staticmethod
    def _regular(path):
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("Resource is not a regular file: %s" % path)

    def commit(self):
        if self.committed:
            raise RuntimeError("Resource batch already committed.")
        backups = {}
        # Check and back up the entire batch before publishing its first file.
        for index, (name, staged) in enumerate(self.outputs.items()):
            self._regular(staged)
            target = self.directory / name
            backup = None
            if os.path.lexists(target):
                self._regular(target)
                if not self.overwrite:
                    raise FileExistsError("Resource appeared during preparation: %s" % target)
                backup = self.staging / ("old-%d" % index)
                shutil.copy2(target, backup)
            backups[name] = backup

        attempted = []
        try:
            for name, staged in self.outputs.items():
                # Register intent first: an interrupt can arrive just after
                # os.replace succeeds, before control returns to Python.
                attempted.append(name)
                os.replace(staged, self.directory / name)
            self.committed = True
        except BaseException as failure:
            published = [name for name in attempted if not os.path.lexists(self.outputs[name])]
            recovery_errors = []
            for name in reversed(published):
                try:
                    if backups[name] is None:
                        (self.directory / name).unlink()
                    else:
                        os.replace(backups[name], self.directory / name)
                except BaseException as error:
                    recovery_errors.append({"name": name, "error": str(error)})
            if recovery_errors:
                self.keep_recovery = True
                recovery = {
                    "directory": str(self.directory), "failure": str(failure),
                    "rollback_errors": recovery_errors,
                    "backups": {name: str(path) if path else None for name, path in backups.items()},
                    "published": published,
                }
                # Do not discard originals even if writing the diagnostic fails.
                try:
                    (self.staging / "recovery.json").write_text(
                        json.dumps(recovery, ensure_ascii=False, indent=2), encoding="utf-8")
                except OSError:
                    pass
                raise RuntimeError("Resource rollback incomplete; keep recovery files at %s: %s" %
                                   (self.staging, recovery_errors)) from failure
            raise
    def __exit__(self, exc_type, exc, tb):
        if self.staging is not None and not self.keep_recovery:
            try:
                shutil.rmtree(self.staging)
            except OSError as error:
                # A leftover temporary directory is not a publication failure.
                warnings.warn("Temporary resource files remain at %s: %s (committed=%s)" %
                              (self.staging, error, self.committed), RuntimeWarning)
        return False
