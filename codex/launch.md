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

### Debug

```
Invoke-RestMethod http://127.0.0.1:9222/json
Invoke-RestMethod http://127.0.0.1:8000/api/target/status
$body = @{ model = "Qwen3.5-4B"; messages = @(@{ role = "user"; content = "Say hi." }); max_tokens = 8; temperature = 0 } | ConvertTo-Json -Depth 5; Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/v1/chat/completions" -ContentType "application/json" -Body $body
```