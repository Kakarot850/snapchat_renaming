import argparse
import os
import re
from datetime import datetime
from pathlib import Path
import json

# ==========================================
# Defaults & Constants
# ==========================================
DEFAULT_CHAT_DIR = Path("chat_media")
DEFAULT_MEMORIES_DIR = Path("memories")
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


def get_relative_subfolder(date_part: str, structure_type: str) -> Path:
    """Builds subfolder path based on the selected structure style."""
    parts = date_part.split("-")
    year = parts[0]
    month = parts[1]
    year_month = f"{year}-{month}"

    if structure_type == "1":       # YYYY/YYYY-MM/
        return Path(year) / year_month
    elif structure_type == "2":     # YYYY/MM/
        return Path(year) / month
    elif structure_type == "3":     # YYYY/
        return Path(year)
    elif structure_type == "4":     # YYYY-MM/
        return Path(year_month)
    else:                           # Default fallback: YYYY/YYYY-MM/
        return Path(year) / year_month


# ==========================================
# Main Processing Pipeline
# ==========================================
def process_snapchat_data(
    mode: str,
    media_dir: Path,
    snap_history_path: Path = DEFAULT_SNAP_HISTORY,
    use_subfolders: bool = True,
    structure_type: str = "1",
    dry_run: bool = True,
    **kwargs
):
    media_dir = Path(media_dir)
    tolerance = kwargs.get("time_tolerance", TIME_TOLERANCE_SECONDS)
    tz_offset = kwargs.get("tz_offset", TZ_OFFSET_SECONDS)

    if not media_dir.exists():
        raise FileNotFoundError(f"Media directory not found: {media_dir}")

    # ------------------------------------------
    # Step 1: Scan Media Files
    # ------------------------------------------
    print(f"\n[{mode.upper()} MODE] Scanning media in '{media_dir}'...")
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
            "parent_key_name": None,
        }
        media_records.append(record)

    print(f"Discovered {len(media_records)} media files.")

    # ------------------------------------------
    # Step 2: Match Records (chat_media only)
    # ------------------------------------------
    if mode == "chat_media":
        snap_history_path = Path(snap_history_path)
        if not snap_history_path.exists():
            raise FileNotFoundError(f"Snap history file not found: {snap_history_path}")

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

        print(f"Matching finished: {matched_count}/{len(media_records)} items matched.\n")
    else:
        print("Skipping JSON lookup for memories (direct rename & sort mode).\n")

    # ------------------------------------------
    # Step 3: Sort & Rename Files
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
        formatted_timestamp = f"{date_part}_{time_part.replace(':', '-')}"

        # Determine target folder path
        if use_subfolders:
            subfolder_path = get_relative_subfolder(date_part, structure_type)
            if mode == "chat_media":
                parent_key = item.get("parent_key_name")
                folder_user = re.sub(r"[^\w\-]", "_", parent_key) if parent_key and parent_key != "unknown" else "unmatched"
                target_dir = media_dir / folder_user / subfolder_path
            else:
                target_dir = media_dir / subfolder_path
        else:
            if mode == "chat_media":
                parent_key = item.get("parent_key_name")
                folder_user = re.sub(r"[^\w\-]", "_", parent_key) if parent_key and parent_key != "unknown" else "unmatched"
                target_dir = media_dir / folder_user
            else:
                target_dir = media_dir

        base_name = f"snapchat_{formatted_timestamp}"
        folder_tracker = used_names_per_folder.setdefault(str(target_dir), {})
        count = folder_tracker.get(base_name, 0) + 1
        folder_tracker[base_name] = count

        new_filename = f"{base_name}{ext}" if count == 1 else f"{base_name}_{count}{ext}"
        target_path = target_dir / new_filename

        try:
            relative_display_path = target_path.relative_to(media_dir)
        except ValueError:
            relative_display_path = target_path

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
        print("Set dry run to 'False' / 'N' to execute actual moves.")
    else:
        print(f"Organization complete. Successfully moved and renamed {processed_count} files.")


# ==========================================
# Interactive Prompt & Main Entry
# ==========================================
def main():
    print("=" * 60)
    print("      SNAPCHAT MEDIA ORGANIZER & RENAMER")
    print("=" * 60)

    # 1. Mode Selection
    print("\nSelect Processing Mode:")
    print("  1) chat_media (Match with snap_history.json & sort by user)")
    print("  2) memories   (Rename and sort directly, no JSON lookup)")
    mode_input = input("Enter choice (1 or 2) [default: 1]: ").strip()
    mode = "memories" if mode_input == "2" else "chat_media"

    # 2. Directory Paths with Defaults
    if mode == "chat_media":
        chat_prompt = input(f"\nEnter chat_media folder path [default: '{DEFAULT_CHAT_DIR}']: ").strip()
        media_dir = Path(chat_prompt) if chat_prompt else DEFAULT_CHAT_DIR

        history_prompt = input(f"Enter snap_history.json path [default: '{DEFAULT_SNAP_HISTORY}']: ").strip()
        snap_history_path = Path(history_prompt) if history_prompt else DEFAULT_SNAP_HISTORY
    else:
        mem_prompt = input(f"\nEnter memories folder path [default: '{DEFAULT_MEMORIES_DIR}']: ").strip()
        media_dir = Path(mem_prompt) if mem_prompt else DEFAULT_MEMORIES_DIR
        snap_history_path = DEFAULT_SNAP_HISTORY

    # 3. Subfolder Sorting Toggle
    print("\nDo you want to organize files into subfolders?")
    print("  y) Yes, sort into structured subfolders")
    print("  n) No, keep all renamed files in the root folder")
    sub_choice = input("Enter choice (y/n) [default: y]: ").strip().lower()
    use_subfolders = sub_choice != "n"

    # 4. Folder Structure Options
    structure_type = "1"
    if use_subfolders:
        print("\nChoose Folder Structure Type:")
        print("  1) YYYY / YYYY-MM /       (e.g., 2024 / 2024-05 /)")
        print("  2) YYYY / MM /            (e.g., 2024 / 05 /)")
        print("  3) YYYY /                 (e.g., 2024 /)")
        print("  4) YYYY-MM /              (e.g., 2024-05 /)")
        st_choice = input("Select structure (1-4) [default: 1]: ").strip()
        if st_choice in {"1", "2", "3", "4"}:
            structure_type = st_choice

    # 5. Dry Run Toggle (Default: True)
    print("\nRun in Dry Run mode (preview changes without moving/renaming)?")
    print("  y) Yes (Preview only, safe)")
    print("  n) No  (Live mode, apply changes to files)")
    dry_choice = input("Enter choice (y/n) [default: y]: ").strip().lower()
    dry_run = dry_choice != "n"

    # Run pipeline
    process_snapchat_data(
        mode=mode,
        media_dir=media_dir,
        snap_history_path=snap_history_path,
        use_subfolders=use_subfolders,
        structure_type=structure_type,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    main()