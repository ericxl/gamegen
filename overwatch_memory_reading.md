# Overwatch Memory Scanner — Entity & Team Detection

## Approach

Overwatch uses **teams** (`Team 1`, `Team 2`), not an `is_enemy` flag.
To determine enemies: `is_enemy = entity.team != local_player.team`

## Two-Phase Usage

### Phase 1: Initial Scan (once per Overwatch launch, ~10-30s)

Finds the memory regions containing entity/team data. Run once, cache the addresses.

```powershell
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

public class OwScan {
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern IntPtr OpenProcess(int access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool ReadProcessMemory(IntPtr h, IntPtr addr, byte[] buf, int size, out int read);
    [DllImport("kernel32.dll")]
    public static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern int VirtualQueryEx(IntPtr h, IntPtr addr, out MBI mbi, int len);
    [StructLayout(LayoutKind.Sequential)]
    public struct MBI {
        public IntPtr BaseAddress, AllocationBase;
        public uint AllocationProtect;
        public IntPtr RegionSize;
        public uint State, Protect, Type;
    }

    // Returns base addresses of regions that matched, so we can re-read them instantly later
    public static long[] FindRegions(int pid, string[] terms, int maxHits = 80) {
        var addrs = new System.Collections.Generic.List<long>();
        IntPtr h = OpenProcess(0x0410, false, pid);
        if (h == IntPtr.Zero) { Console.WriteLine("FAIL: cant open process"); return addrs.ToArray(); }
        IntPtr addr = IntPtr.Zero; MBI mbi; int count = 0; int found = 0;
        while (count < 200000) {
            if (VirtualQueryEx(h, addr, out mbi, Marshal.SizeOf(typeof(MBI))) == 0) break;
            long sz = (long)mbi.RegionSize;
            if (mbi.State == 0x1000 && sz > 0 && sz < 5000000) {
                byte[] buf = new byte[(int)sz]; int rd;
                if (ReadProcessMemory(h, mbi.BaseAddress, buf, buf.Length, out rd) && rd > 0) {
                    string txt = Encoding.ASCII.GetString(buf, 0, rd);
                    foreach (string term in terms) {
                        int si = 0;
                        while (si < txt.Length) {
                            int idx = txt.IndexOf(term, si, StringComparison.OrdinalIgnoreCase);
                            if (idx < 0) break;
                            int s = Math.Max(0, idx - 50); int l = Math.Min(250, txt.Length - s);
                            var sb = new StringBuilder();
                            foreach (char c in txt.Substring(s, l))
                                sb.Append(c >= 32 && c < 127 ? c : '.');
                            Console.WriteLine("[" + term + "] @0x" +
                                ((long)mbi.BaseAddress).ToString("X") + "+" + idx + ": " + sb);
                            if (!addrs.Contains((long)mbi.BaseAddress))
                                addrs.Add((long)mbi.BaseAddress);
                            found++;
                            if (found >= maxHits) { CloseHandle(h); return addrs.ToArray(); }
                            si = idx + term.Length;
                        }
                    }
                }
            }
            addr = new IntPtr((long)mbi.BaseAddress + sz); count++;
        }
        Console.WriteLine("Done: " + count + " regions, " + found + " hits, " + addrs.Count + " unique regions");
        CloseHandle(h);
        return addrs.ToArray();
    }

    // Instant re-read of a known region
    public static string ReadRegion(int pid, long baseAddr, int size) {
        IntPtr h = OpenProcess(0x0410, false, pid);
        if (h == IntPtr.Zero) return "FAIL";
        byte[] buf = new byte[size]; int rd;
        ReadProcessMemory(h, new IntPtr(baseAddr), buf, size, out rd);
        CloseHandle(h);
        var sb = new StringBuilder();
        foreach (byte b in buf) { char c = (char)b; sb.Append(c >= 32 && c < 127 ? c : '.'); }
        return sb.ToString();
    }
}
'@

$owPid = (Get-Process Overwatch).Id
Write-Host "PID: $owPid"

# Phase 1: Full scan — find regions (slow, once per launch)
$regions = [OwScan]::FindRegions($owPid, @(
    'self to team',
    'Team 1', 'Team 2',
    'Standard Bot', 'Tank Bot', 'Sniper Bot', 'Friendly Bot', 'Dummy Bot'
))

# Save region addresses for Phase 2
Write-Host "`nCached regions for instant re-read:"
foreach ($r in $regions) { Write-Host ("  0x" + $r.ToString("X")) }
```

### Phase 2: Instant Re-Read (per game change, <1s)

Once Phase 1 has found the region addresses, re-read them directly — no scanning needed.

```powershell
# Re-read a cached region instantly (replace address from Phase 1 output)
$data = [OwScan]::ReadRegion($owPid, 0xADDRESS_FROM_PHASE1, 16384)

# Extract entity/team names
[regex]::Matches($data, '(Team [12]|Standard Bot|Tank Bot|Sniper Bot|Friendly Bot|Dummy Bot|self to team \d|move player to team \d|swap.+to team \d)') |
    ForEach-Object { $_.Value } | Sort-Object | Group-Object | Format-Table Count, Name
```

Region addresses are **stable within a session** (same PID). They only change on Overwatch restart → re-run Phase 1.

## Determining Enemies

From scan results:
- `self to team 2` → local player is on **Team 2**
- Entities/actions tagged `Team 1` → **enemies**
- Entities/actions tagged `Team 2` → **allies**

## Gotchas

- **`$pid` is reserved** in PowerShell — use `$owPid`
- **Capitalized names** (`Standard Bot` not `bot`) — lowercase matches noise
- **~7GB process** — Phase 1 takes 10-30s, Phase 2 is instant
- **Addresses stable within session**, change on restart (ASLR)
- **`Enemy` as search term** matches hero tooltips, not entities — use team-based detection
