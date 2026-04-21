# Overwatch Replay Data Path — Investigation Findings

Investigation date: 2026-04-30
Replay code used: `7Q7AG2`
Overwatch build: 149004 (D:\Overwatch\_retail_\Overwatch.exe, PID 6096 during capture)

## TL;DR

- **Replay data never touches disk.** `WriteFile` count during a 120-second window covering import + ~90 s of playback was **0**.
- **Replay data arrives over HTTPS from Google Cloud CDN** (`yi-in-f207.1e100.net`, `*.bc.googleusercontent.com`).
- **It is a streaming pull, not a one-shot download.** Pattern: 322-byte request out, ~600 KB response in, every ~30 s.
- **Network stack is WinHTTP + schannel** (Windows native TLS).
- **Almost everything is statically linked into `Overwatch.exe`** — there is no `replay.dll` to target. The reverse-engineering target is the main exe.

## Method

Process Monitor (Sysinternals, installed via winget) ran for 120 s while the live OW client was used to import replay code `7Q7AG2` and let it play. Capture saved to `captures/replay_7Q7AG2_20260430_133407.pml` (249 MB), converted to CSV, filtered to `Process Name = Overwatch.exe` (69,140 events).

## Operation distribution (Overwatch.exe events)

| Count  | Operation                |
| -----: | ------------------------ |
| 24,305 | ReadFile                 |
| 10,417 | RegOpenKey               |
| 9,835  | RegQueryKey              |
| 9,084  | RegCloseKey              |
| 1,323  | QueryStandardInformationFile |
| 1,238  | CreateFileMapping        |
| **1,220**  | **TCP Receive**       |
| 765    | CreateFile               |
| **121**    | **TCP Send**          |
| 23     | UDP Send                 |
| **11**     | **TCP Connect**       |
| **9**      | **TCP Disconnect**    |
| **0**      | **WriteFile**         |

`WriteFile = 0` is the load-bearing fact: replay data is held entirely in memory.

## Network endpoints

| Bytes RX | Endpoint | Role |
| -------- | -------- | ---- |
| 2.31 MB  | `yi-in-f207.1e100.net:443` (port 51578) | **Main replay data stream** |
| 698 KB   | `yi-in-f207.1e100.net:443` (port 51581) | Parallel data stream |
| 650 KB   | `yi-in-f207.1e100.net:443` (port 51589) | Parallel data stream |
| ~5 KB ×6 | `*.bc.googleusercontent.com:443` (89.91.201.35) | Metadata / signed-URL responses |
| 2.5 KB   | `24.105.60.12:3724` | Battle.net auth |
| 1.4 KB   | `146.75.94.137:443` | Misc HTTPS |
| 0.1 KB   | `168.89.125.34:1119` | Battle.net API |

`1e100.net` is Google's reverse-DNS name for Google Cloud frontend hosts. Blizzard fronts replay delivery on Google Cloud.

## Streaming pattern (port 51578, the primary connection)

Bytes received per second (cumulative on the right):

```
13:34:26 PM   +    2,726 bytes   cum=     2,726   <- first response after request
13:34:27 PM   +   63,304          cum=    66,030
13:34:28 PM   +  166,880          cum=   232,910   <- initial burst (~232 KB)
13:34:31 PM   +   13,158          cum=   246,068
13:34:37 PM   +  216,748          cum=   462,816   <- second chunk
13:35:05 PM   +  661,292          cum= 1,124,108   <- ~30 s later, ~600 KB
13:35:35 PM   +  612,292          cum= 1,736,400   <- ~30 s later, ~600 KB
13:36:05 PM   +  626,971          cum= 2,363,371   <- ~30 s later, ~600 KB
```

Send pattern on the same connection:

```
13:34:26  Length: 193   <- initial GET (HTTP/2 request headers)
13:34:27  Length:  93
13:34:27  Length: 271
13:34:27  Length: 322
13:34:31  Length: 271
13:34:37  Length: 322
13:35:05  Length: 322
13:35:35  Length: 322
13:36:05  Length: 322
```

Interpretation: one initial request, then periodic 322-byte sends every ~30 s that pull the next chunk. Likely HTTP/2 streamed responses or a polling protocol over a persistent TLS session. Each chunk corresponds to a tick window of replay data.

Throughput: roughly **3–4 MB per minute of replay**, extrapolating to ~30–50 MB for a full match across the parallel connections.

## Loaded modules (relevant)

Of 144 modules in Overwatch.exe's address space, only four are Blizzard-owned:

```
Overwatch.exe         72 MB    main exe — replay logic lives here
Overwatch_loader.dll  9.6 MB   loader
bink2w64.dll          0.4 MB   RAD Bink (cutscene video codec)
vivoxsdk.dll          12.4 MB  Vivox (voice chat)
```

Network-relevant Windows modules loaded:

```
WINHTTP.dll, schannel.DLL, WS2_32.dll, mswsock.dll
ncrypt.dll, ncryptsslp.dll, secur32.dll
CRYPT32.dll, bcrypt.dll, bcryptPrimitives.dll
DNSAPI.dll, IPHLPAPI.DLL, webio.dll
```

Confirms: WinHTTP for HTTP, schannel for TLS, no bundled OpenSSL/BoringSSL.

## On-disk artifacts checked and ruled out

| Path | Result |
| ---- | ------ |
| `%LOCALAPPDATA%\Blizzard Entertainment\Overwatch\148522,148915,149004\Hotfix\` | Hotfix payloads only (~1–3 MB total). Not replay data. |
| `%LOCALAPPDATA%\Blizzard Entertainment\Overwatch\76080844\Highlights\` | Out of scope per project (separate feature). |
| `%LOCALAPPDATA%\Blizzard Entertainment\Overwatch\76080844\Store\` | Cosmetics. Not replay data. |
| `%LOCALAPPDATA%\Blizzard Entertainment\Overwatch\ShopImages\` | Store images. Not replay data. |
| `%USERPROFILE%\Documents\Overwatch\` | Settings, screenshots, error logs. Last replay-ish folder (`videos\`) untouched since 2018. |
| Any path under D:\Overwatch\ | No new files written during the session. |

## Implications for the pipeline

What remains viable for getting the raw replay bytes:

1. **TLS-MitM the CDN connections.** The Google CDN traffic is almost certainly not client-pinned (Blizzard would have to pin Google's intermediate CA, which they cannot control). The Battle.net auth traffic on 3724/1119 is more likely pinned, but is small and probably only brokers signed CDN URLs — not load-bearing for getting the replay bytes themselves. Tools: portable mitmproxy, Burp, or Fiddler.
2. **Wireshark + ETW TLS keylog.** Capture encrypted pcap with Wireshark, extract schannel TLS session keys via Windows event tracing, decrypt offline. No CA install, no proxy reconfig.
3. **WinHTTP API hook.** Inject into Overwatch.exe and hook `WinHttpReadData` / `WinHttpReceiveResponse` / `WinHttpQueryHeaders` for cleartext post-decryption. No network changes, but DLL injection into a Blizzard-anti-cheat process (Warden) is the highest-risk option.
4. **Memory scan post-decryption.** Extend the scaffolding in `overwatch_memory_reading.md` to find the decrypted replay buffer. Read-only; same risk profile as the existing memory work.

What is dead:

- Filesystem cache monitoring (`WriteFile = 0`).
- Single-shot CDN file download (no monolithic file — it's chunked streaming).

## Reproducing the trace

```powershell
$procmon = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Microsoft.Sysinternals.ProcessMonitor_Microsoft.Winget.Source_8wekyb3d8bbwe\Procmon64.exe"
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$pml = "C:\depot\ow\captures\replay_<CODE>_$ts.pml"
Start-Process -FilePath $procmon -ArgumentList @('/AcceptEula','/Quiet','/Minimized','/Runtime','120','/Backingfile',"`"$pml`"") -WindowStyle Minimized
# import the replay code in OW, let it play, capture auto-stops at 120 s

# convert to CSV after capture
& $procmon /OpenLog $pml /SaveAs ($pml -replace '\.pml$','.csv') /Quiet
```

To filter the CSV to OW-only events:

```bash
head -1 capture.csv > ow.csv && grep ',"Overwatch\.exe",' capture.csv >> ow.csv
```

## Open questions

- Do all replay codes route through the same `1e100.net` host, or is there geographic / load-balanced variation? (One sample so far.)
- Is the streaming protocol HTTP/2 with server-initiated pushes, or HTTP/1.1 long-poll? The 322-byte sends every 30 s look like client-initiated polls but could be HTTP/2 control frames. Confirm via TLS-MitM.
- What does the Battle.net auth handshake (3724/1119) actually return — a one-shot signed URL, a session token used per chunk, or something else?
- Does the replay finish (terminal chunk) or does the connection idle? The capture ended mid-replay so this is not yet known.
- For full-match capture, total bytes? Extrapolation (~30–50 MB) is unverified.
