# Re-running the census on a rented host

The first census truncated every logged frame at 2,000 characters, lost 17 servers to
harness defects, and recorded no image digests. Those are fixed. This run repeats the
same population, with the same pinned package versions, and produces transcripts the
released numbers can be regenerated from.

Budget from the recorded durations: 130,462 seconds of container time, so about 5
hours of wall clock at 8 workers. On an 8 vCPU on-demand instance that is roughly $3.

## 1. Instance

- 8 vCPU, 32 GB memory (m7i.2xlarge or equivalent). Spot is fine; the run resumes.
- 100 GB gp3 disk. Images and installs fill a small disk quickly.
- Public subnet with a public IP. A NAT gateway would cost more per hour than the
  instance, and package downloads are inbound traffic, which is free.
- Set a billing alarm before launching.

## 2. Setup

```bash
git clone https://github.com/Ahmad-Faraj/mcp-conformance.git
cd mcp-conformance
bash ops/bootstrap.sh
newgrp docker
```

The frame file is not in the repository. Copy `data/frame_latest.jsonl` from the
release, or from your machine:

```bash
scp data/release/frame_latest.jsonl ubuntu@<host>:mcp-conformance/data/
```

## 3. Smoke test first

```bash
bash ops/run_census.sh smoke
```

Twenty servers, about a minute. Before going further, confirm in the output rows:

- `harness_commit` is a real commit, not `unknown`
- `image_digests` holds a digest for each base image
- `request_timeout_s` and `max_frame_chars` are present, with `max_frame_chars: 0`
- no row carries `batch_error`
- the recorded `tools/list` reply parses as JSON when read back

## 4. Full run

Start it inside tmux. A browser terminal closes when the tab does, and the run dies
with it.

```bash
sudo apt-get install -y tmux
tmux new -s census
WORKERS=8 bash ops/run_census.sh full
```

Detach with Ctrl+B then D. Reattach later with `tmux attach -t census`.

### On a small instance

A free-plan account may only offer 2 vCPU types such as m7i-flex.large. The run still
works: use `WORKERS=3`, expect 12 to 18 hours instead of 5, and leave it overnight.
Flex instance types throttle toward a CPU baseline under sustained load, so more
workers buy little. Cost stays near a dollar.

Expect about 1,300 servers per hour. Watch for:

- free disk above 20 GB (`df -h .`). If it falls, `docker system prune -af`.
- the row count rising steadily. A stall beyond ten minutes means a container is
  ignoring its timeout.
- memory pressure. Eight containers at 768 MB is about 6 GB; drop to 6 workers if the
  host swaps.

If the run dies, rerun the same command with `--skip-done` added to the python line in
`ops/run_census.sh`, and it continues where it stopped.

## 5. Test-retest

```bash
RETEST_N=400 bash ops/run_census.sh retest
```

A seeded random subsample, probed a second time. Agreement between the two runs is the
reliability figure the paper currently lacks. Keep both result directories.

## 6. Afterwards

```bash
tar -czf runs.tar.gz data/runs
```

Copy that down, terminate the instance, and check the bill the next day. Then, on your
machine:

- regenerate the release with `driver/make_release.py`
- rerun `make_numbers.py`, `make_tables.py` and `make_figures.py`
- compare the new handshake rate against the July figure. A gap is a result about
  ecosystem change over two months, not a fault in the harness, provided the package
  versions still resolve.
