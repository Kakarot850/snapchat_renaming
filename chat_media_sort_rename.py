import argparse
import os
import re
from datetime import datetime
from pathlib import Path
import json

# ==========================================
# Defaults & Constants
# ==========================================
DEFAULT_MEDIA_DIR = Path("chat_media")
DEFAULT_SNAP_HISTORY = Path("json/snap_history.json")

ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp",
    ".mp4", ".mov", ".m4a", ".mp3",
}

TIME_TOLERANCE_SECONDS = 2   # +/- 2 seconds window
TZ_OFFSET_SECONDS = 19800    # 5 hours 30 mins (IST / UTC+05:30)


# ==========================================
# Helpers
# ==========================================
def normalize_to_epoch_seconds(val):
    if val is None:
        return None
    try:
        val = float(val)
        if val > 1e14:      # 16 digits: Microseconds
            return val / 1_000_000
        elif val > 1e11:    # 13 digits: Milliseconds
            return val / 1_000
        else:               # 10 digits: Seconds
            return val
    except (ValueError, TypeError):
        return None


def load_snap_events(history_path: Path):
    with open(history_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    events = []

    def walk_nodes(node, current_parent_key="unknown"):
        if isinstance(node, dict):
            epoch_sec = None
            for key in ["Created(microseconds)", "Created(ms)", "timestamp", "Epoch"]:
                if key in node:
                    epoch_sec = normalize_to_epoch_seconds(node[key])
                    break

            if epoch_sec is None:
                date_str = node.get("Created") or node.get("Date")
                if date_str:
                    clean_str = re.sub(r"\s+UTC.*$", "", str(date_str).strip())
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                        try:
                            dt = datetime.strptime(clean_str, fmt)
                            epoch_sec = dt.timestamp()
                            break
                        except ValueError:
                            pass

            if epoch_sec is not None:
                media_type = node.get("Media Type") or node.get("Type") or "SNAP"
                events.append({
                    "parent_key": current_parent_key,
                    "media_type": media_type,
                    "epoch_seconds": epoch_sec
                })

            for key, val in node.items():
                walk_nodes(val, current_parent_key=key)

        elif isinstance(node, list):
            for item in node:
                walk_nodes(item, current_parent_key=current_parent_key)

    walk_nodes(data)
    events.sort(key=lambda x: x["epoch_seconds"])
    return events


# ==========================================
# Main Processing Pipeline
# ==========================================
def process_snapchat_data(
    media_dir=DEFAULT_MEDIA_DIR,
    snap_history_path=DEFAULT_SNAP_HISTORY,
    dry_run: bool = False,
    **kwargs
):
    """
    Process, match, and organize Snapchat chat media.

    Optional **kwargs:
      time_tolerance (int/float): Match tolerance in seconds (default: 2)
      tz_offset (int/float): Timezone offset in seconds (default: 19800)
    """
    media_dir = Path(media_dir)
    snap_history_path = Path(snap_history_path)
    tolerance = kwargs.get("time_tolerance", TIME_TOLERANCE_SECONDS)
    tz_offset = kwargs.get("tz_offset", TZ_OFFSET_SECONDS)

    if not media_dir.exists():
        raise FileNotFoundError(f"Media directory not found: {media_dir}")
    if not snap_history_path.exists():
        raise FileNotFoundError(f"Snap history file not found: {snap_history_path}")

    # ------------------------------------------
    # Step 1: Scan Media Files
    # ------------------------------------------
    print(f"Scanning media in '{media_dir}'...")
    media_records = []

    for file_path in sorted(media_dir.iterdir()):
        if not file_path.is_file() or file_path.name.startswith("."):
            continue

        ext = file_path.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            continue

        stat = file_path.stat()
        ctime_epoch = getattr(stat, "st_birthtime", stat.st_ctime)
        creation_datetime_str = datetime.fromtimestamp(ctime_epoch).strftime("%Y-%m-%d %H:%M:%S")

        record = {
            "file_path": file_path,
            "filename": file_path.name,
            "extension": ext,
            "creation_datetime": creation_datetime_str,
            "epoch_timestamp": ctime_epoch,
        }
        media_records.append(record)

    print(f"Discovered {len(media_records)} media files.")

    # ------------------------------------------
    # Step 2: Load Snap History & Match Records
    # ------------------------------------------
    snap_events = load_snap_events(snap_history_path)
    print(f"Loaded {len(snap_events)} events from '{snap_history_path.name}'.")
    print(f"Matching timestamps (Tolerance: +/-{tolerance}s, TZ Offset: {tz_offset}s)...")

    used_event_indices = set()
    matched_count = 0

    for item in media_records:
        file_epoch = normalize_to_epoch_seconds(item["epoch_timestamp"])
        if file_epoch is None:
            continue

        best_match = None
        best_match_idx = None
        min_diff = float("inf")

        for idx, event in enumerate(snap_events):
            if idx in used_event_indices:
                continue

            event_epoch = event["epoch_seconds"]
            raw_diff = abs(file_epoch - event_epoch)
            tz_diff = abs(raw_diff - tz_offset)
            diff = min(raw_diff, tz_diff)

            if diff <= tolerance and diff < min_diff:
                min_diff = diff
                best_match = event
                best_match_idx = idx

        if best_match:
            used_event_indices.add(best_match_idx)
            item["parent_key_name"] = best_match["parent_key"]
            matched_count += 1
        else:
            item["parent_key_name"] = None

    print(f"Matching finished: {matched_count}/{len(media_records)} items matched.\n")

    # ------------------------------------------
    # Step 3: Sort into User / YYYY / YYYY-MM
    # ------------------------------------------
    mode_label = "DRY RUN MODE (No changes applied)" if dry_run else "LIVE MODE (Moving into folders)"
    print(f"=== {mode_label} ===")
    print(f"{'STATUS':<8} | {'ORIGINAL NAME':<35} | {'CREATION DATE':<20} | {'NEW PATH & NAME'}")
    print("-" * 130)

    used_names_per_folder = {}
    processed_count = 0
    missing_count = 0

    for item in media_records:
        source_path = item["file_path"]
        original_filename = item["filename"]
        ext = item["extension"]
        raw_creation_dt = item["creation_datetime"]

        if not source_path.exists():
            print(f"{'MISSING':<8} | {original_filename:<35} | {raw_creation_dt:<20} | [File not found]")
            missing_count += 1
            continue

        date_part, time_part = raw_creation_dt.split(" ")
        year_str = date_part.split("-")[0]
        year_month_str = f"{year_str}-{date_part.split('-')[1]}"
        formatted_timestamp = f"{date_part}_{time_part.replace(':', '-')}"

        parent_key = item.get("parent_key_name")
        folder_user = re.sub(r"[^\w\-]", "_", parent_key) if parent_key and parent_key != "unknown" else "unmatched"

        target_dir = media_dir / folder_user / year_str / year_month_str

        base_name = f"snapchat_{formatted_timestamp}"
        folder_tracker = used_names_per_folder.setdefault(str(target_dir), {})
        count = folder_tracker.get(base_name, 0) + 1
        folder_tracker[base_name] = count

        new_filename = f"{base_name}{ext}" if count == 1 else f"{base_name}_{count}{ext}"
        target_path = target_dir / new_filename

        relative_display_path = target_path.relative_to(media_dir)

        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
            source_path.rename(target_path)
            status = "MOVED"
        else:
            status = "PREVIEW"

        print(f"{status:<8} | {original_filename:<35} | {raw_creation_dt:<20} | {relative_display_path}")
        processed_count += 1

    print("-" * 130)
    if dry_run:
        print(f"Dry run complete. Verified {processed_count} files ready to organize. (Missing: {missing_count})")
        print("Run without '--dry-run' to execute moves.")
    else:
        print(f"Organization complete. Successfully moved and renamed {processed_count} files.")


# ==========================================
# CLI Argument Parser
# ==========================================
def parse_cli_args():
    parser = argparse.ArgumentParser(description="Rename & organize Snapchat chat media into YYYY/YYYY-MM folders.")
    parser.add_argument("--media-dir", default=DEFAULT_MEDIA_DIR, help="Path to chat_media directory.")
    parser.add_argument("--snap-history", default=DEFAULT_SNAP_HISTORY, help="Path to snap_history.json.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simulate the sorting without moving files (default: False)."
    )
    parser.add_argument("--time-tolerance", type=float, default=TIME_TOLERANCE_SECONDS, help="Timestamp match window in seconds.")
    parser.add_argument("--tz-offset", type=float, default=TZ_OFFSET_SECONDS, help="Timezone offset shift in seconds.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_cli_args()
    process_snapchat_data(
        media_dir=args.media_dir,
        snap_history_path=args.snap_history,
        dry_run=args.dry_run or False,
        time_tolerance=args.time_tolerance,
        tz_offset=args.tz_offset,
    )