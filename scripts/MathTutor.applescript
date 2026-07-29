-- MathTutor Launcher — 双击启动，自动打开浏览器
--
-- 自动检测项目位置：优先 .app 所在目录，其次 ~/DeepTutor
--
-- 编译命令：
--   osacompile -o MathTutor.app scripts/MathTutor.applescript

-- 候选路径
set candidates to {}
-- 1) .app 自身所在目录
tell application "System Events"
	set appParentDir to POSIX path of (container of (path to me))
end tell
set end of candidates to appParentDir
-- 2) 标准学生安装位置
set end of candidates to (POSIX path of (path to home folder) & "DeepTutor/")

-- 检测哪个候选目录是真实项目根目录
set projectDir to ""
repeat with candidate in candidates
	try
		-- 项目根目录的特征：有 .env 或 .env.student 或 scripts/start.sh
		do shell script "test -f " & quoted form of (candidate & "/scripts/start.sh") & " && echo found"
		set projectDir to candidate
		exit repeat
	on error
		try
			do shell script "test -f " & quoted form of (candidate & "/.env.student") & " && echo found"
			set projectDir to candidate
			exit repeat
		on error
			try
				do shell script "test -d " & quoted form of (candidate & "/.venv") & " && echo found"
				set projectDir to candidate
				exit repeat
			end try
		end try
	end try
end repeat

set backendUrl to "http://localhost:8002"
set frontendUrl to "http://localhost:3782"
set logFile to "/tmp/mathtutor.log"

-- 找不到项目
if projectDir is "" then
	set triedPaths to ""
	repeat with c in candidates
		set triedPaths to triedPaths & return & "  • " & c
	end repeat
	display dialog "找不到 MathTutor 项目文件夹。已尝试：" & triedPaths & return & return & ¬
		"默认安装位置：~/DeepTutor" & return & ¬
		"如有问题请联系 xj。" with title "MathTutor" buttons {"确定"} default button 1 with icon stop
	return
end if

-- 检查 .env 是否存在
try
	do shell script "test -f " & quoted form of (projectDir & "/.env") & " && echo ok"
on error
	display dialog "项目未初始化。请先运行：" & return & ¬
		"bash " & projectDir & "/scripts/setup.sh" with title "MathTutor — 未初始化" ¬
		buttons {"打开终端", "确定"} default button 2 with icon caution
	if button returned of result = "打开终端" then
		tell application "Terminal"
			activate
			do script "cd " & quoted form of projectDir & " && bash scripts/setup.sh"
		end tell
	end if
	return
end try

-- 检查是否已在运行
try
	do shell script "curl -s -o /dev/null -w '%{http_code}' " & backendUrl & " | grep -q 200 && echo running"
	display dialog "MathTutor 已在运行！" & return & return & ¬
		"浏览器打开 " & frontendUrl & " 即可使用。" with title "MathTutor" ¬
		buttons {"打开浏览器", "不去了"} default button 1 with icon note
	if button returned of result = "打开浏览器" then
		open location frontendUrl
	end if
	return
on error
	-- 未运行，继续启动
end try

-- 显示启动进度
set progress description to "正在启动 MathTutor ..."
set progress additional description to "后端 + 前端，约需 15-30 秒"
set progress total steps to -1

-- 启动后端和前端
try
	do shell script "cd " & quoted form of projectDir & ¬
		" && source .venv/bin/activate && nohup python scripts/start_web.py > " & ¬
		logFile & " 2>&1 &"
on error errMsg
	display dialog "启动失败：" & errMsg with title "MathTutor — 启动错误" ¬
		buttons {"确定"} default button 1 with icon stop
	return
end try

-- 等待启动完成
repeat 30 times
	delay 1
	try
		do shell script "curl -s -o /dev/null -w '%{http_code}' " & ¬
			backendUrl & " | grep -q 200 && echo ready"
		set progress total steps to 1
		set progress completed steps to 1
		open location frontendUrl
		return
	on error
		-- 继续等待
	end try
end repeat

-- 超时
display dialog "启动超时（已等待 30 秒）。" & return & return & ¬
	"请手动在终端运行：bash " & projectDir & "/scripts/start.sh" & return & ¬
	"如有问题请联系 xj。" with title "MathTutor — 启动超时" ¬
	buttons {"确定"} default button 1 with icon stop
