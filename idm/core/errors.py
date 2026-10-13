class SegmentDownloadError(Exception):
    """A segment failed after exhausting its retry budget."""


class UnrecoverableDownloadError(Exception):
    """The download cannot proceed at all (bad URL, 404, disk full, etc.)."""


class DuplicateDownloadError(Exception):
    """Refused to queue a second active download for the same URL or
    destination file. Beyond being confusing, two DownloadTasks writing to
    the same destination_path concurrently would corrupt each other's
    output -- both preallocate and seek/write into the same file handle
    independently. `existing` is the record already occupying that slot."""

    def __init__(self, existing):
        super().__init__(f"already queued: {existing.url} -> {existing.destination_path}")
        self.existing = existing
