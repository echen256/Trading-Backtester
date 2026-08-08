# VaM saved-content activity report

Generated from file metadata in `/Users/ericchen/Downloads/VAM/Saves` on 2026-07-13.

## How to read this

- **Scene saves** are the last-modified times of VaM scene JSON files. They are the strongest local evidence of a save action.
- **In market hours** means the timestamp falls within regular U.S. equity-market hours: 8:30 AM–3:00 PM Central, on a normal market day. A timestamp can show a save occurred; it cannot prove the full length of a session.
- A range is an **inferred observed window** from the first to last save on that date. It may contain multiple sessions, and time outside the range is unknown.
- All times below are Central time, based on the Mac filesystem timestamps.
- `Saves/Person` itself has no user files. VaM's actual saved character appearances are in `Custom/Atom/Person/Appearance`; those records are included below.

## Summary

- Scene-save records: **26**
- Dates with scene saves: **12**
- Dates with at least one save during regular market hours: **4**
  - 2026-05-27, 2026-06-26, 2026-07-06, and 2026-07-13
- Character-appearance preset records: **22** across **10** dates
- Character-appearance preset dates with a save during regular market hours: **2**
  - 2026-05-27 and 2026-07-13
- 2026-05-25 had saves at market-hour clock times but was Memorial Day, when U.S. equity markets were closed.
- Two plugin-state files were saved on 2026-05-25; they are included separately below.

## Full scene-save log

| Date | Observed window | Scene saves (last modified) | Regular-market overlap |
|---|---:|---|---|
| Sun, May 24 | 8:15 PM–11:34 PM | 8:15:02 PM; 10:54:58 PM; 11:27:14 PM; 11:34:06 PM | No — weekend |
| Mon, May 25 | 9:21 AM–11:12 AM | 9:21:43 AM; 9:43:58 AM; 10:31:49 AM; 11:12:53 AM | No — Memorial Day market holiday |
| Tue, May 26 | 8:11 PM–9:51 PM | 8:11:30 PM; 8:46:26 PM; 9:51:43 PM | No |
| Wed, May 27 | 8:27 AM–9:10 AM | 8:27:43 AM; **9:10:02 AM** | **Yes — observed window crosses the 8:30 AM open; one save at 9:10 AM** |
| Fri, May 29 | 10:50 PM | 10:50:26 PM | No |
| Fri, Jun 5 | 6:02 PM–8:12 PM | 6:02:56 PM; 7:50:51 PM; 8:12:13 PM | No |
| Mon, Jun 8 | 6:35 PM | 6:35:47 PM | No |
| Wed, Jun 10 | 7:28 AM | 7:28:04 AM | No — before open |
| Thu, Jun 25 | 6:35 PM | 6:35:36 PM | No |
| Fri, Jun 26 | 8:49 AM | **8:49:48 AM** | **Yes — save during market hours** |
| Mon, Jul 6 | 8:58 AM | **8:58:06 AM** | **Yes — save during market hours** |
| Fri, Jul 10 | 7:30 AM–8:07 AM | 7:30:48 AM; 7:32:06 AM; 8:07:45 AM | No — before open |
| Mon, Jul 13 | 12:02 PM | **12:02:34 PM** | **Yes — save during market hours** |

## Character-appearance preset save log

These are `.vap` files under `Custom/Atom/Person/Appearance`; matching `.jpg` preview files were written within seconds of each entry and are not repeated here.

| Date | Appearance preset saves (last modified) | Regular-market overlap |
|---|---|---|
| Sun, May 24 | `Preset_taylor` — 10:30:39 PM; `Preset_taylor s` — 10:46:47 PM; `Preset_lana` — 10:54:06 PM; `Preset_hyuna` — 11:21:52 PM | No — weekend |
| Mon, May 25 | `Preset_taylor s2` — 9:48:27 AM; `Preset_taylor s2 fit` — 10:25:26 AM; `Preset_charleen` — 11:06:09 PM | No — Memorial Day market holiday |
| Tue, May 26 | `Preset_charleen long hair` — 7:51:35 PM; `Preset_nikita` — 8:33:59 PM; `Preset_anya 1` — 9:46:25 PM | No |
| Wed, May 27 | `Preset_rr` — **9:04:47 AM** | **Yes — saved during market hours** |
| Fri, May 29 | `Preset_rio` — 10:17:17 PM; `Preset_artoria` — 10:19:40 PM; `Preset_clubbing` — 10:57:48 PM; `Preset_katarina` — 11:05:59 PM | No |
| Wed, Jun 10 | `Preset_Akemi 2` — 7:46:20 AM | No — before open |
| Wed, Jun 17 | `Preset_tifa` — 10:28:16 PM; `Preset_Akemi 3` — 10:31:06 PM | No |
| Thu, Jun 25 | `Preset_haruka` — 6:31:03 PM | No |
| Sun, Jun 28 | `Preset_nikita succubus` — 10:59:00 PM | No — weekend |
| Mon, Jul 13 | `Preset_elaf6` — **9:57:50 AM**; `Preset_nicola` — **10:00:28 AM** | **Yes — both saved during market hours** |

## Plugin-state saves

These are application/plugin settings rather than scene or character presets.

| Date and time | File | Market overlap |
|---|---|---|
| Mon, May 25, 8:49:52 AM | `Saves/PluginData/PluginIdea/Common/tmp` | No — Memorial Day market holiday |
| Mon, May 25, 10:42:54 AM | `Saves/PluginData/Chokaphi/Decal_Maker_2_Settings.json` | No — Memorial Day market holiday |

## Additional July 13 evidence

Outside the explicit save record, VaM cache/configuration files were written from **10:42 AM through 1:04 PM** on Jul 13. This is consistent with VaM being actively used through part of the trading session, but it is not a precise session-duration record.

## Best-available inferred activity log

This is the closest available substitute for an opening/launch log. It uses writes in VaM's runtime-only locations—`Cache`, `Saves`, `AddonPackagesUserPrefs`, `Custom/PluginData`, and the main `prefs.json`—and excludes package archives, downloaded assets, and Finder metadata. A window means there was observed runtime activity between the endpoints; it does **not** prove one continuous session or an exact application opening time.

| Date | First–last runtime write | Evidence | Trading-hours overlap |
|---|---|---|---|
| Sun, May 24 | 6:41 PM–11:34 PM | Cache, saves, add-on preferences | No — weekend |
| Mon, May 25 | 8:43 AM–11:06 PM | Cache, saves, add-on preferences | No — Memorial Day market holiday |
| Tue, May 26 | 7:44 PM–9:54 PM | Cache, saves, add-on preferences | No |
| Wed, May 27 | 8:06 AM–5:43 PM | Cache, saves, add-on preferences | **Yes — observed writes span market hours** |
| Fri, May 29 | 10:03 PM–11:15 PM | Cache, saves, add-on preferences | No |
| Tue, Jun 2 | 8:18 AM–9:05 PM | Cache | **Yes — observed writes span market hours** |
| Fri, Jun 5 | 8:21 AM–8:12 PM | Cache, saves, add-on preferences | **Yes — observed writes span market hours** |
| Sat, Jun 6 | 7:49 AM–8:10 AM | Cache, add-on preferences | No — weekend |
| Mon, Jun 8 | 5:51 PM–7:27 PM | Cache, saves, add-on preferences | No |
| Wed, Jun 10 | 7:21 AM–7:46 AM | Cache, saves, add-on preferences | No — before open |
| Sun, Jun 14 | 10:01 PM | Cache | No — weekend |
| Wed, Jun 17 | 10:21 PM–10:31 PM | Cache | No |
| Thu, Jun 25 | 7:24 AM–11:08 PM | Cache, saves, add-on preferences | **Yes — observed writes span market hours** |
| Fri, Jun 26 | 8:25 AM–8:49 AM | Cache, saves | **Yes — observed writes after the 8:30 AM open** |
| Sun, Jun 28 | 10:37 PM–11:03 PM | Cache | No — weekend |
| Tue, Jun 30 | 10:01 AM–10:10 AM | Cache | **Yes — observed writes during market hours** |
| Mon, Jul 6 | 8:58 AM–8:59 AM | Saves | **Yes — save during market hours** |
| Tue, Jul 7 | 9:41 PM–10:01 PM | Cache | No |
| Wed, Jul 8 | 10:37 PM–10:51 PM | Cache, add-on preferences | No |
| Fri, Jul 10 | 6:45 AM–9:30 AM | Cache, saves, add-on preferences | **Yes — observed writes continue past the 8:30 AM open** |
| Mon, Jul 13 | 9:57 AM–1:04 PM | Cache, saves, add-on preferences, plugin state, main preferences | **Yes — observed writes during market hours** |

## Limits

This report does not count launches, folder opens, unsaved use, or time spent in the application. Files can also be modified when an existing scene is re-saved, copied, or installed. It should therefore be treated as a conservative activity log rather than a complete usage history.
