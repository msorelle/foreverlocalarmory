# Forever Local Armory

A read-only browser for your WoW Forever Syndicator inventory. Search by item, ID, or character, or filter by storage location. Open an item to look up its WoW Forever catalog details in ForeverDB.

## Run it on Windows

Use Python 3.10 or later. From this directory in PowerShell, run:

```powershell
py -3 .\inventory_web.py --game-dir 'D:\Games\World of Warcraft\_forever_' --ownership '..\wowinvsync\ownership.json'
```

Adjust the game folder if needed. The command reuses the ownership file from the existing inventory sync project. For a standalone setup, create a local `ownership.json` and point `--ownership` to it. Each key is an account folder inside `WTF\Account`, and each value is a list of exact character keys from that account's `SYNDICATOR_DATA.Characters` table in `SavedVariables\Syndicator.lua`.

```json
{
  "ACCOUNT_FOLDER": ["Character Realm-PvE"]
}
```

The browser opens on this computer. Log out of WoW to save fresh Syndicator data, then click **Refresh saves**. Press Ctrl+C in PowerShell to stop the browser server.

## ForeverDB access

Request API access and create a key after approval. Enter the key at the hidden prompt or set the `FOREVERDB_API_KEY` environment variable before launching. Press Enter at the prompt or use `--offline` to browse without catalog requests. [ForeverDB developer docs](https://foreverdb.net/developers)

The app keeps the key on the local Python server and sends ForeverDB the catalog item ID when you open an item. Character names, account names, inventory counts, and save files stay on this computer. Item details describe the catalog entry. Equipped enchants and other character-specific modifications aren't part of that lookup.

The inventory page footer includes the attribution badge. [Data from ForeverDB.net](https://foreverdb.net)
