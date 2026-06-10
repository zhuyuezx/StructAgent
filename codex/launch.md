### Launch Command
```
python -m uvicorn core.api:app --port 8000
```

```
cd frontend 
npm run dev -- --host 127.0.0.1 --port 5173
```

```
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="D:\tmp\drawio-chrome-profile"
```

### Ablation
```
$OUT = "logs\ablation_live"

  foreach ($rep in 1..3) {
    foreach ($task in "source_target","rect3","rect5","rect6") {
      python tests\run_screenshot_ablation.py --task-id $task --condition sg_only --rep $rep --clear-canvas --out $OUT
      python tests\run_screenshot_ablation.py --task-id $task --condition screenshot_sg --rep $rep --clear-canvas --out $OUT
    }
  }
```
```
python tests\summarize_screenshot_ablation.py --input logs\ablation_live --agent planner
python tests\plot_screenshot_ablation.py --input logs\ablation_live --agent planner --output logs\ablation_live\textonly_ablation.svg

Get-Content logs\ablation_live\summary.md
```

### Debug

```
Invoke-RestMethod http://127.0.0.1:9222/json
Invoke-RestMethod http://127.0.0.1:8000/api/target/status
$body = @{ model = "Qwen3.5-4B"; messages = @(@{ role = "user"; content = "Say hi." }); max_tokens = 8; temperature = 0 } | ConvertTo-Json -Depth 5; Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/v1/chat/completions" -ContentType "application/json" -Body $body
```