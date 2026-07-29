-- MathTutor Launcher — 双击启动，自动打开浏览器
--
-- 部署说明：把生成的 MathTutor.app 拖到 /Applications 即可。
-- 首次使用前请先运行 scripts/setup.sh 并编辑好 .env。
--
-- 编译命令：
--   osacompile -o MathTutor.app scripts/MathTutor.applescript

set projectDir to POSIX path of (path to home folder) & "DeepTutor"
set backendUrl to "http://localhost:8002"
set frontendUrl to "http://localhost:3782"
set logFile to "/tmp/mathtutor.log"

-- 检查项目目录
try
	do shell script "test -d " & quoted form of projectDir & " && echo ok"
on error
	display dialog "找不到 DeepTutor 文件夹。" & return & return & ¬
		"请确认项目安装在：~" & "DeepTutor" & return & ¬
		"如位置不同，请联系 xj。" ¬
		with title "MathTutor" buttons {"确定"} default button 1 ¬
		with icon stop
	return
end try

-- 检查 .env 是否已配置
try
	do shell script "test -f " & quoted form of (projectDir & ".env") & " && grep -q 'sk-' " & quoted form of (projectDir & ".env") & " && echo ok"
on error
	display dialog "未找到有效的 .env 文件。" & return & return & ¬
		"请先运行：bash ~/DeepTutor/scripts/setup.sh" & return & ¬
		"然后编辑 ~/DeepTutor/.env 填入 API Key。" ¬
		with title "MathTutor — 未初始化" buttons {"确定"} default button 1 ¬
		with icon caution
	return
end try

-- 检查是否已在运行
try
	do shell script "curl -s -o /dev/null -w '%{http_code}' " & backendUrl & " | grep -q 200 && echo running"
	display dialog "MathTutor 已在运行！" & return & return & ¬
		"浏览器打开 " & frontendUrl & " 即可使用。" ¬
		with title "MathTutor" buttons {"打开浏览器", "不去了"} default button 1 ¬
		with icon note
	if button returned of result = "打开浏览器" then
		open location frontendUrl
	end if
	return
on error
	-- 未运行，继续启动
end try

-- 显示启动进度
set progressMsg to "正在启动 MathTutor ..."
set progress total steps to -1
set progress description to progressMsg
set progress additional description to "后端 + 前端，约需 15-30 秒"

-- 启动后端和前端（后台运行）
try
	do shell script "cd " & quoted form of projectDir & ¬
		" && source .venv/bin/activate && nohup python scripts/start_web.py > " & ¬
		logFile & " 2>&1 &"
on error errMsg
	display dialog "启动失败：" & errMsg ¬
		with title "MathTutor — 启动错误" buttons {"确定"} default button 1 ¬
		with icon stop
	return
end try

-- 等待启动完成
set maxWait to 30
repeat with i from 1 to maxWait
	delay 1
	try
		do shell script "curl -s -o /dev/null -w '%{http_code}' " & ¬
			backendUrl & " | grep -q 200 && echo ready"

		-- 启动成功！
		set progress total steps to 1
		set progress completed steps to 1

		open location frontendUrl
		return
	on error
		-- 继续等待
	end try
end repeat

-- 超时
display dialog "启动超时（已等待 " & maxWait & " 秒）。" & return & return & ¬
	"请手动在终端运行：bash ~/DeepTutor/scripts/start.sh" & return & ¬
	"如有问题请联系 xj。" ¬
	with title "MathTutor — 启动超时" buttons {"确定"} default button 1 ¬
	with icon stop
