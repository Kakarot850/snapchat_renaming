# Snapchat Media Organizer & Renamer (`final.py`)

A Python script designed to organize, timestamp-match, and rename Snapchat media exports (`chat_media` and `memories`) into clean, chronological folder hierarchies.

---

## ⚠️ Critical Warning: Moving Files (Cut vs. Copy)

> **Always CUT and PASTE (Move) your media files — DO NOT COPY and PASTE.**
>
> On Windows and macOS, copy-pasting a file creates a new filesystem entry and updates its creation timestamp (`st_birthtime` / `st_ctime`) to the current moment.
> To preserve the original creation date and time of your photos and videos, you must **cut and paste (`Ctrl + X` / `Cmd + X`)** the files into the working folder.

---

## 1. Prerequisites & Installation

The script requires standard Python 3.8+ and does not depend on external tools like `exiftool`.

Install the necessary dependencies using `pip`:

```bash
pip install pytz tzlocal
```

_(Standard libraries used: `argparse`, `os`, `re`, `datetime`, `pathlib`, `json`)._

---

## 2. Directory Structure Setup

Place `org2.py` in your project root and arrange your input files:

```text
snapchat_project/
├── org2.py
├── json/
│   └── snap_history.json      # Extracted from your Snapchat data export
├── chat_media/                # Place cut-and-pasted chat media here
│   ├── sample1.jpg
│   └── sample2.mp4
└── memories/                  # Place cut-and-pasted memories here
    ├── snap1.jpg
    └── snap2.mp4
```

---

## 3. Step-by-Step Usage

Run the script from your terminal:

```bash
python org2.py
```

The script will guide you through an interactive setup:

### Step 1: Select Processing Mode

- **`1) chat_media`**: Reads `snap_history.json`, matches file timestamps against chat events (accounting for timezone offsets and tolerance windows), and organizes media by user/conversation.
- **`2) memories`**: Skips all JSON lookups completely. Renames and sorts media directly based on the file creation timestamps.

### Step 2: Confirm Folder Paths

Press **`Enter`** to accept the default values, or enter custom paths:

- **chat_media mode:**
    - Media Directory `[default: 'chat_media']`
    - History File `[default: 'json/snap_history.json']`
- **memories mode:**
    - Media Directory `[default: 'memories']`

### Step 3: Subfolder Sorting

Choose whether to sort files into subfolders:

- **`y` (Default):** Organizes files into structured subfolders.
- **`n`:** Renames files in place inside the root media directory.

### Step 4: Choose Folder Structure Type (if subfolders are enabled)

Select your preferred hierarchy:

1. `YYYY / YYYY-MM /` _(e.g., `2024 / 2024-05 /`)_ **[Default]**
2. `YYYY / MM /` _(e.g., `2024 / 05 /`)_
3. `YYYY /` _(e.g., `2024 /`)_
4. `YYYY-MM /` _(e.g., `2024-05 /`)_

_(Note: In `chat_media` mode, the matched sender/recipient folder name is automatically prepended before this date structure)._

### Step 5: Dry Run Confirmation

- **`y` (Default):** **Safe Preview Mode.** Inspects files, displays a comparison table in the console, and confirms matches without altering, moving, or renaming anything on disk.
- **`n`:** **Live Mode.** Applies the renames and moves the files into their target destinations.

---

## 4. Renaming Format

All files are renamed chronologically using their resolved timestamp:

```text
snapchat_YYYY-MM-DD_HH-MM-SS.ext
```

If multiple files share the exact same second within the same folder, a counter is appended to avoid collisions:

```text
snapchat_2024-05-14_15-30-00.jpg
snapchat_2024-05-14_15-30-00_2.jpg
```

---

## 5. Supported File Formats

- **Images:** `.jpg`, `.jpeg`, `.png`, `.webp`
- **Videos & Audio:** `.mp4`, `.mov`, `.m4a`, `.mp3`
