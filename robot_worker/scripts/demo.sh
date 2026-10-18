#!/bin/zsh
# Run one robot shuffle for the demo and print the camera's verdict.
#   scripts/demo.sh swap_lr          (row must be: black, white, purple; slot 4 empty)
#   scripts/demo.sh swap_lr back     (puts purple, white, black back to the start)
#   scripts/demo.sh swap_lm / swap_lm back
sid=${1:-swap_lr}
case "$sid:$2" in
  swap_lr:) start='["black","white","purple"]';;
  swap_lr:back) start='["purple","white","black"]';;
  swap_lm:) start='["black","white","purple"]';;
  swap_lm:back) start='["white","black","purple"]';;
  *) echo "use: swap_lr | swap_lr back | swap_lm | swap_lm back"; exit 1;;
esac
J=demo-$sid-$(date +%H%M%S)
curl -s -m 30 -X POST localhost:8001/jobs -H 'Content-Type: application/json' \
  -d "{\"jobId\":\"$J\",\"actionId\":\"shuffle\",\"objectId\":\"$sid\",\"start\":$start}" >/dev/null || { echo "worker not running"; exit 1; }
echo "Robot running $sid ... (Ctrl+C here does NOT stop the arm: use the e-stop or: curl -X POST localhost:8001/stop)"
while true; do
  r=$(curl -s -m 10 localhost:8001/jobs/$J)
  st=$(echo "$r" | python3 -c "import sys,json;print(json.loads(sys.stdin.read(),strict=False)['status'])")
  [ "$st" = running ] || [ "$st" = queued ] || break
  sleep 2
done
echo "$r" | python3 -c "
import sys,json;d=json.loads(sys.stdin.read(),strict=False);c=d.get('check') or {}
print('RESULT:', d['status'].upper(), d.get('errorCode') or '')
if c.get('expected'): print('  expected', c['expected'], ' camera saw', c.get('observed'))
if d.get('error'): print('  ', d['error'])"
