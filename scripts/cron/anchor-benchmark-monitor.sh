#!/bin/bash
# anchor benchmark monitor (v29.8 P1-5)
# 监控 anchor server 健康 + 路由质量 + benchmark 状态
# 输出 /tmp/anchor-benchmark-monitor-{ts}.log
LOG="/tmp/anchor-benchmark-monitor-$(date +%Y%m%d-%H%M%S).log"
echo "=== anchor benchmark monitor (v29.8 P1-5) ===" > "$LOG"
echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
echo "" >> "$LOG"

# 1. anchor server 健康
echo "--- anchor server health ---" >> "$LOG"
HEALTH=$(curl -s --max-time 5 http://127.0.0.1:8088/readyz 2>&1)
echo "$HEALTH" >> "$LOG"
if echo "$HEALTH" | grep -q '"ready": true'; then
  echo "Status: HEALTHY" >> "$LOG"
else
  echo "Status: UNHEALTHY" >> "$LOG"
fi
echo "" >> "$LOG"

# 2. anchor 路由状态 (v1/models)
echo "--- anchor routing (v1/models) ---" >> "$LOG"
MODELS=$(curl -s --max-time 5 http://127.0.0.1:8088/v1/models 2>&1)
echo "$MODELS" | head -5 >> "$LOG"
WORKERS=$(echo "$MODELS" | grep -oE '"worker_pool":\[[^]]*\]' | head -1)
echo "Worker pool: $WORKERS" >> "$LOG"
echo "" >> "$LOG"

# 3. benchmark 脚本存在性
echo "--- benchmark scripts ---" >> "$LOG"
for f in bandit_replay_eval.py build_quality_table.py eval_pareto_curve.py run_live_pareto_curve.py; do
  if [ -f "/Users/henry/anchor/scripts/$f" ]; then
    echo "  [OK] $f" >> "$LOG"
  else
    echo "  [MISSING] $f" >> "$LOG"
  fi
done
echo "" >> "$LOG"

# 4. 最近 benchmark 结果
echo "--- recent benchmark artifacts ---" >> "$LOG"
ls -t /Users/henry/anchor/evals/*.json 2>/dev/null | head -5 >> "$LOG"
BENCH_COUNT=$(ls /Users/henry/anchor/evals/*.json 2>/dev/null | wc -l | tr -d ' ')
echo "Benchmark artifacts: $BENCH_COUNT" >> "$LOG"
echo "" >> "$LOG"

# 5. anchor 进程状态
echo "--- anchor process ---" >> "$LOG"
pgrep -fl "anchor" 2>/dev/null | head -5 >> "$LOG"
PROC_COUNT=$(pgrep -f "anchor" 2>/dev/null | wc -l | tr -d ' ')
echo "Anchor processes: $PROC_COUNT" >> "$LOG"

echo "" >> "$LOG"
echo "Log: $LOG"
