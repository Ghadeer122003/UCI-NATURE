# scripts/pipeline/make_manifest.py
# creates manifest.csv from local downloaded images in data/staging/
# optionally creates batch manifests in data/outputs/batches/

import argparse
import csv
import hashlib
from datetime import datetime


STAGING = Path("data/staging")
OUT = Path("data/outputs/manifest.csv")
BATCH_DIR = Path("data/outputs/batches")

CACHE = Path("data/outputs/cache/processed_file_ids.txt")
NEW_OUT = Path("data/outputs/manifest_new.csv")


LOCAL_ID_PREFIX = "local:"


def split_local_name(local_file_name: str):
    if "__" in local_file_name:
        file_id, original_name = local_file_name.split("__", 1)
        return file_id, original_name
    return "", local_file_name


def derive_local_file_id(relative_path: Path) -> str:
    """Stable synthetic id for images that did not come from Drive.

    Drive downloads are named "<file_id>__<original_name>", so they carry an
    id already. Files added any other way (SD-card upload, manual copy) keep
    their original camera filename, which used to leave file_id empty. Those
    rows were then dropped by the new-only filter, so the images never got
    processed.
    """
    key = relative_path.as_posix()
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return f"{LOCAL_ID_PREFIX}{digest}"


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def append_manifest_file_ids_to_cache(manifest_path: Path, cache_path: Path) -> dict:
    manifest_path = Path(manifest_path)
    cache_path = Path(cache_path)

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    existing = set()
    if cache_path.exists():
        with cache_path.open("r", encoding="utf-8") as f:
            existing = {line.strip() for line in f if line.strip()}

    ids_to_add = []
    with manifest_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fid = (row.get("file_id") or "").strip()
            if fid and fid not in existing:
                existing.add(fid)
                ids_to_add.append(fid)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("a", encoding="utf-8") as f:
        for fid in ids_to_add:
            f.write(fid + "\n")

    return {
        "manifest_path": str(manifest_path),
        "cache_path": str(cache_path),
        "ids_appended": len(ids_to_add),
    }


def build_manifest(
    staging: Path = STAGING,
    out: Path = OUT,
    batch_size: int = 0,
    batch_dir: Path = BATCH_DIR,
    cache_path: Path = CACHE,
    new_out: Path = NEW_OUT,
    write_new_only: bool = False,
    update_cache: bool = False,
) -> dict:
    staging = Path(staging)
    out = Path(out)
    batch_dir = Path(batch_dir)
    cache_path = Path(cache_path)
    new_out = Path(new_out)

    if not staging.exists():
        raise FileNotFoundError(f"{staging} not found. Run download_drive.py first.")

    image_extensions = {".jpg", ".jpeg", ".png"}

    rows = []
    for p in sorted(staging.rglob("*")):
        if not p.is_file():
            continue
        if p.name.startswith(".") or p.name.startswith("._"):
            continue
        if p.suffix.lower() not in image_extensions:
            continue

        file_id, original_name = split_local_name(p.name)

        if not file_id:
            # Not a Drive download; mint a deterministic id so the file is not
            # treated as unidentifiable and silently skipped downstream.
            try:
                relative_to_staging = p.relative_to(staging)
            except ValueError:
                relative_to_staging = Path(p.name)
            file_id = derive_local_file_id(relative_to_staging)

        try:
            local_path = str(p.relative_to(Path.cwd()))
        except ValueError:
            local_path = str(p)

        stat = p.stat()
        rows.append(
            {
                "file_id": file_id,
                "file_name": original_name,
                "local_file_name": p.name,
                "local_path": local_path,
                "size_bytes": stat.st_size,
                "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )

    fieldnames = [
        "file_id",
        "file_name",
        "local_file_name",
        "local_path",
        "size_bytes",
        "modified_time",
    ]

    write_csv(out, rows, fieldnames)
    print(f"wrote {len(rows)} rows -> {out}")

    result = {
        "manifest_path": str(out),
        "rows_written": len(rows),
        "batch_count": 0,
        "new_manifest_path": None,
        "new_rows_written": None,
    }

    if batch_size and batch_size > 0:
        batch_dir.mkdir(parents=True, exist_ok=True)
        total = len(rows)
        batch_count = (total + batch_size - 1) // batch_size
        result["batch_count"] = batch_count

        for i in range(batch_count):
            start = i * batch_size
            end = min(start + batch_size, total)
            batch_rows = rows[start:end]
            batch_path = batch_dir / f"batch_{i + 1:04d}.csv"
            write_csv(batch_path, batch_rows, fieldnames)
            print(f"  batch {i + 1:04d}: {len(batch_rows)} rows -> {batch_path}")

    if write_new_only:
        processed = set()
        if cache_path.exists():
            with open(cache_path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s:
                        processed.add(s)

        new_rows = []
        skipped_already_processed = 0
        missing_id = []
        for r in rows:
            fid = (r.get("file_id") or "").strip()
            if not fid:
                # Should be unreachable now that every row gets an id, but keep
                # it loud instead of dropping images on the floor silently.
                missing_id.append(r.get("local_path") or r.get("local_file_name") or "")
                continue
            if fid in processed:
                skipped_already_processed += 1
                continue
            new_rows.append(r)

        write_csv(new_out, new_rows, fieldnames)
        print(f"cache: {cache_path} ({len(processed)} ids)")
        print(f"wrote {len(new_rows)} rows -> {new_out}")
        print(f"skipped {skipped_already_processed} rows (already processed)")
        if missing_id:
            print(f"WARNING: {len(missing_id)} rows had no file_id and were NOT processed")
            for path_value in missing_id[:10]:
                print(f"  no file_id: {path_value}")

        result["new_manifest_path"] = str(new_out)
        result["new_rows_written"] = len(new_rows)
        result["skipped_already_processed"] = skipped_already_processed
        result["missing_file_id"] = len(missing_id)

        if update_cache:
            cache_result = append_manifest_file_ids_to_cache(new_out, cache_path)
            print(f"updated cache: appended {cache_result['ids_appended']} ids -> {cache_path}")

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", default=str(STAGING))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--batch_size", type=int, default=0, help="0 = no batch manifests")
    parser.add_argument("--batch_dir", default=str(BATCH_DIR))
    parser.add_argument("--cache", default=str(CACHE), help="file with processed file_ids (one per line)")
    parser.add_argument("--new_out", default=str(NEW_OUT), help="where to write manifest of only new/unprocessed ids")
    parser.add_argument("--write_new_only", action="store_true", help="also write a filtered manifest containing only new/unprocessed file_ids")
    parser.add_argument("--update_cache", action="store_true", help="append new_out file_ids to cache (run only AFTER a successful pipeline run)")
    args = parser.parse_args()

    build_manifest(
        staging=Path(args.staging),
        out=Path(args.out),
        batch_size=args.batch_size,
        batch_dir=Path(args.batch_dir),
        cache_path=Path(args.cache),
        new_out=Path(args.new_out),
        write_new_only=args.write_new_only,
        update_cache=args.update_cache,
    )


if __name__ == "__main__":
    main()