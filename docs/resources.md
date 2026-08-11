# Resource sizing for a small VPS

## Target machine

The reference target is AlmaLinux 9 x86_64 with:

- 2 virtual CPU cores
- 1 GiB RAM
- 20 GiB disk

This is sufficient for a personal Mihomo VLESS + REALITY endpoint and usually
for a small number of users. CPU model, host contention, network route, and the
provider's traffic allowance are more likely to limit throughput than disk.

## Expected footprint

Approximate figures, not guarantees:

| Component | Typical footprint |
| --- | ---: |
| Mihomo at startup with this small config | 20–80 MiB RAM |
| Mihomo under ordinary personal traffic | 60–200 MiB RAM |
| Minimal AlmaLinux 9 userspace and services | 200–450 MiB RAM |
| Installed compressed/download artifacts | temporary only |
| Installed Mihomo binary | tens of MiB |
| Complete minimal operating system | usually several GiB |

Memory grows with active TCP/UDP connections, buffers, rule data, and traffic
patterns. This server has one listener, one user, static rejection rules, no
server rule-provider downloads, no dashboard, and no database, so its static
footprint is small.

Idle CPU use should be close to zero. Active CPU scales with traffic and
cryptographic work. Two shared vCPUs are appropriate for normal browsing,
streaming, and personal API traffic, but no fixed high-throughput figure can be
promised. Do not assume gigabit throughput on an inexpensive shared VPS.

## Included systemd limits

The example unit applies:

```ini
MemoryHigh=384M
MemoryMax=640M
TasksMax=512
LimitNOFILE=65536
```

`MemoryHigh` applies pressure before the hard limit. `MemoryMax` prevents a
leak or extreme connection spike from consuming the entire 1 GiB host. systemd
restarts Mihomo after an abnormal failure. If legitimate traffic reaches these
limits, measure the workload before raising them; upgrading the VPS may be
safer than leaving no RAM for SSH and the operating system.

Inspect actual usage:

```sh
systemctl show mihomo-server \
  -p MemoryCurrent -p MemoryPeak -p MemoryHigh -p MemoryMax \
  -p TasksCurrent -p TasksMax
systemd-cgtop --depth=2
journalctl -u mihomo-server --since today | grep -iE 'memory|oom|killed'
```

## Swap

A 512 MiB or 1 GiB swap file is a reasonable emergency buffer when the VPS has
no swap. Swap protects administrative access during short memory spikes; it is
not a substitute for adequate RAM and may hurt proxy latency when actively
used.

Check first:

```sh
swapon --show
free -h
df -h /
```

To create a 1 GiB file when the provider and filesystem support it:

```sh
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
grep -qF '/swapfile none swap defaults 0 0' /etc/fstab || \
  echo '/swapfile none swap defaults 0 0' | sudo tee -a /etc/fstab
```

Verify after reboot. Do not create duplicate `/etc/fstab` entries, and follow
the provider's guidance if swap files are prohibited.

## Disk and logs

Twenty GiB is ample if logs are bounded. Mihomo writes to journald rather than
standalone files in this project. Check journal usage:

```sh
journalctl --disk-usage
grep -R 'SystemMaxUse\|RuntimeMaxUse' \
  /etc/systemd/journald.conf /etc/systemd/journald.conf.d 2>/dev/null
```

A host-wide journald limit can be added in
`/etc/systemd/journald.conf.d/size.conf`, for example:

```ini
[Journal]
SystemMaxUse=200M
RuntimeMaxUse=100M
MaxRetentionSec=14day
```

Then restart journald. These are host-wide limits, so account for other
services before changing them.

## Capacity warning signs

Upgrade or reduce load when any of these is sustained:

- swap is continuously active;
- `MemoryCurrent` repeatedly approaches `MemoryMax`;
- OOM or systemd memory-limit kills occur;
- both vCPUs remain saturated during expected traffic;
- packet loss or latency rises only while the proxy is busy;
- the provider reports bandwidth throttling or exhausted transfer quota.
