import re

file = r"D:\L\Documents\BIT质押请求\bybit_staking\ui\main_window.py"
with open(file, "r", encoding="utf-8") as f:
    content = f.read()

old_marker = 'updater = os.path.join(exe_dir, "_updater.bat")'

if old_marker in content:
    start = content.find(old_marker)
    end_search_start = content.find("subprocess.Popen", start)
    end_paren = content.find(")", end_search_start)
    end_line = content.find("\n", end_paren)
    sleep_line = content.find("time.sleep(0.5)", end_line)
    sleep_end = content.find("\n", sleep_line)
    
    new_block = '''# PowerShell 替换脚本（比 cmd bat 更可靠处理中文路径和文件锁）
            ps_cmd = (
                f"$pidToKill = {os.getpid()}; "
                f"$old = '{old_exe}'; "
                f"$new = '{new_exe}'; "
                f"$exeDir = '{exe_dir}'; "
                "@("
                "    'Start-Sleep -Seconds 3',"
                "    'taskkill /f /im BybitStaking.exe 2>$null',"
                "    'taskkill /f /im BybitStaking_*.exe 2>$null',"
                "    \\\"taskkill /f /pid $pidToKill 2>$null\\\","
                "    'Start-Sleep -Seconds 2',"
                "    'if (Test-Path $old) { Remove-Item $old -Force -ErrorAction SilentlyContinue }',"
                "    'Start-Sleep -Seconds 1',"
                "    'Move-Item -Path $new -Destination $old -Force -ErrorAction SilentlyContinue',"
                "    'if (Test-Path $old) {',"
                "    '    Remove-Item (Join-Path $exeDir \\\"BybitStaking_new*.exe\\\") -Force -ErrorAction SilentlyContinue',"
                "    '    Start-Process $old',"
                "    '}',"
                "    'Remove-Item $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue'"
                ") -join \\\"
\\\""
            )
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                creationflags=0x00000008
            )
'''
    
    content = content[:start] + new_block + content[sleep_end+1:]
    
    with open(file, "w", encoding="utf-8") as f:
        f.write(content)
    print("Replaced successfully")
else:
    print("Old marker not found")
