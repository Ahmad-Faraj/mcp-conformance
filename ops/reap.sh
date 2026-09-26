#!/bin/bash
# Reap containers orphaned by a probe timeout.
#
# run_batch kills the local "docker run" client when a step times out, but the
# container keeps running on the daemon. Each one holds up to 768m, so on a long
# census they accumulate until the host runs out of memory and starts killing
# probes that would otherwise have succeeded.
#
# The longest legitimate container life is the install budget (timeout + 120s)
# plus the probe timeout, comfortably under five minutes, so anything past ten
# is orphaned and its verdict is already recorded.
LOG=~/reap.log
while true; do
  NOW=$(date +%s); n=0
  for id in $(docker ps -q); do
    st=$(docker inspect -f "{{.State.StartedAt}}" "$id" 2>/dev/null) || continue
    s=$(date -d "$st" +%s 2>/dev/null) || continue
    if [ $((NOW - s)) -gt 600 ]; then
      docker kill "$id" >/dev/null 2>&1 && n=$((n + 1))
    fi
  done
  [ "$n" -gt 0 ] && echo "$(date -Is) reaped $n" >> $LOG
  sleep 120
done
