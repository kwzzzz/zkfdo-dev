#!/usr/bin/env python3
"""One-off: B6h-style request workspace cleanup for finished aq requests (approved by miiz 2026-10-26).

Same retained-evidence rule as n6_b6h_cleanup._v22_store_evidence_name. Unlike that helper, links
inside the workspace are removed as links (never followed). A manifest with counts and allocated
bytes is written before deletion and a completion record after.
"""
import json, os, stat, sys, hashlib
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from n6_b6h_cleanup import _v22_store_evidence_name  # noqa: E402


def scan(target: Path):
    keep, drop, links, dirs = [], [], [], []
    for base, dnames, fnames in os.walk(target, followlinks=False):
        b = Path(base)
        for d in dnames:
            p = b / d
            (links if p.is_symlink() else dirs).append(p)
        for f in fnames:
            p = b / f
            m = p.lstat()
            if stat.S_ISLNK(m.st_mode):
                links.append(p)
            elif stat.S_ISREG(m.st_mode):
                (keep if _v22_store_evidence_name(p.relative_to(target)) else drop).append((p, m.st_blocks * 512))
            else:
                raise SystemExit(f"special file: {p}")
    return keep, drop, links, dirs


def main() -> int:
    root, record, revision = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    record.mkdir(parents=True, exist_ok=True)
    for qo in sys.argv[4:]:
        target = root / revision / f"{int(qo):06d}"
        keep, drop, links, dirs = scan(target)
        h = hashlib.sha256("\n".join(sorted(str(p.relative_to(target)) for p, _ in keep)).encode()).hexdigest()
        info = {"revision": revision, "queue_order": int(qo), "target": str(target),
                "deleted_files": len(drop), "deleted_du_bytes": sum(s for _, s in drop),
                "deleted_links": len(links), "retained_files": len(keep),
                "retained_du_bytes": sum(s for _, s in keep), "retained_list_sha256": h,
                "recorded_at": datetime.now(timezone.utc).isoformat()}
        (record / f"{revision}-{int(qo):06d}-before.json").write_text(json.dumps(info, indent=1))
        for p in links:
            p.unlink()
        for p, _ in drop:
            p.unlink()
        for d in sorted(dirs, key=lambda x: len(x.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        info["deleted_at"] = datetime.now(timezone.utc).isoformat()
        (record / f"{revision}-{int(qo):06d}-deleted.json").write_text(json.dumps(info, indent=1))
        print(json.dumps({k: info[k] for k in ("queue_order", "deleted_files", "deleted_du_bytes", "retained_files")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
